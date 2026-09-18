from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_DOTENV_PATH, override=True)

from .api import register_api
from .config import AppConfig, build_allowed_origins
from . import extensions
from .extensions import configure_database, db
from .utils.logging_config import configure_daily_logging


def _apply_overrides(overrides: dict | None) -> None:
    """Apply test or local configuration overrides."""

    if not overrides:
        return
    for key, value in overrides.items():
        setattr(AppConfig, key, value)


def _init_database() -> None:
    """Import models, create tables, and seed minimal RBAC defaults."""

    from . import models  # noqa: F401

    db.create_all()
    # 必须排在其余自愈之前：这一步含 containers.image → runtime_image 的改名，
    # 改名未完成时任何 select(Container) 都会枚举到不存在的列而报 no such column。
    _ensure_container_image_schema()
    _strip_legacy_snapshot_image_key()
    _ensure_container_lifecycle_schema()
    _ensure_deleted_container_schema()
    _ensure_image_template_schema()
    _ensure_container_failure_schema()
    _ensure_gpu_columns()
    _ensure_cleanup_deferral_schema()
    _ensure_machine_endpoint_schema()
    _ensure_freeze_state_schema()
    _ensure_machine_image_schema()
    try:
        from .services.rbac_service import seed_rbac_defaults

        seed_rbac_defaults()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("rbac seed skipped: %s", e)
    try:
        from .services.image_tasks import seed_image_defaults

        seed_image_defaults()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("image seed skipped: %s", e)
    try:
        from .services.settings_tasks import seed_system_settings_defaults

        seed_system_settings_defaults()
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("system settings seed skipped: %s", e)


def _ensure_image_template_schema() -> None:
    """补齐开发期旧 images 表缺失的镜像模板列。

    create_all 只创建新表，不会修改旧表；镜像模板在开发期经历过字段拆分，
    旧 SQLite 库会缺 base_image/dockerfile_body 等列，导致列表接口 500。
    """

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("images"):
        return

    existing = {column["name"] for column in inspector.get_columns("images")}
    required_sqlite = {
        "base_image": "ALTER TABLE images ADD COLUMN base_image VARCHAR(255) NOT NULL DEFAULT 'ubuntu:24.04'",
        "dockerfile_body": "ALTER TABLE images ADD COLUMN dockerfile_body TEXT NOT NULL DEFAULT ''",
        "status": "ALTER TABLE images ADD COLUMN status VARCHAR(8) NOT NULL DEFAULT 'draft'",
        "created_by_user_id": "ALTER TABLE images ADD COLUMN created_by_user_id INTEGER NULL",
        "created_at": "ALTER TABLE images ADD COLUMN created_at DATETIME NULL",
        "updated_at": "ALTER TABLE images ADD COLUMN updated_at DATETIME NULL",
    }
    required_mysql = {
        "base_image": "ALTER TABLE images ADD COLUMN base_image VARCHAR(255) NOT NULL DEFAULT 'ubuntu:24.04'",
        "dockerfile_body": "ALTER TABLE images ADD COLUMN dockerfile_body TEXT NOT NULL",
        "status": "ALTER TABLE images ADD COLUMN status ENUM('draft', 'ready', 'disabled') NOT NULL DEFAULT 'draft'",
        "created_by_user_id": "ALTER TABLE images ADD COLUMN created_by_user_id INT NULL",
        "created_at": "ALTER TABLE images ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "ALTER TABLE images ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }
    required = required_sqlite if current_engine.dialect.name == "sqlite" else required_mysql

    missing = [name for name in required if name not in existing]

    # 模板名唯一性移交应用层（2026-09 决策）：模板的移除是停用而非删除，停用行会继续
    # 占用名字，唯一约束会让该名字永久不可复用。模型已去掉 unique，但旧库上的唯一性
    # 是**独立索引**（create_all 对 unique=True + index=True 生成 ix_images_name），
    # 因此可以直接删掉重建为非唯一索引，无需重建表。幂等：只在它仍唯一时才动。
    index_rows = {idx["name"]: idx for idx in inspector.get_indexes("images") if idx.get("name")}
    name_index = index_rows.get("ix_images_name")
    if name_index is not None and name_index.get("unique"):
        # DROP INDEX 语法两方言不同：SQLite 不带表名，MySQL 必须写 `DROP INDEX 名 ON 表`。
        # 曾误用 SQLite 单方言形式，MySQL 上 1064 启动即崩（2026-09-15 实测）。
        drop_ddl = (
            "DROP INDEX ix_images_name"
            if current_engine.dialect.name == "sqlite"
            else "DROP INDEX ix_images_name ON images"
        )
        with current_engine.begin() as conn:
            conn.execute(text(drop_ddl))
            conn.execute(text("CREATE INDEX ix_images_name ON images(name)"))
        logging.getLogger(__name__).warning(
            "images.name unique index dropped: uniqueness now enforced in application layer"
        )

    if not missing:
        return

    with current_engine.begin() as conn:
        for name in missing:
            conn.execute(text(required[name]))
    logging.getLogger(__name__).warning("image schema upgraded: added columns %s", ", ".join(missing))


def _ensure_container_failure_schema() -> None:
    """补齐开发期旧 containers 表缺失的失败诊断列。"""

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("containers"):
        return

    existing = {column["name"] for column in inspector.get_columns("containers")}
    required = {
        "failed_reason": "ALTER TABLE containers ADD COLUMN failed_reason VARCHAR(255) NULL",
        "failed_detail": "ALTER TABLE containers ADD COLUMN failed_detail TEXT NULL",
    }
    missing = [name for name in required if name not in existing]
    if not missing:
        return

    with current_engine.begin() as conn:
        for name in missing:
            conn.execute(text(required[name]))
    logging.getLogger(__name__).warning("container schema upgraded: added columns %s", ", ".join(missing))


def _ensure_container_lifecycle_schema() -> None:
    """Backfill soft-delete lifecycle columns for old containers tables."""

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("containers"):
        return

    logger = logging.getLogger(__name__)
    existing = {column["name"] for column in inspector.get_columns("containers")}
    required_sqlite = {
        "is_valid": "ALTER TABLE containers ADD COLUMN is_valid BOOLEAN NOT NULL DEFAULT 1",
        "deleted_at": "ALTER TABLE containers ADD COLUMN deleted_at DATETIME NULL",
        "deleted_trigger": "ALTER TABLE containers ADD COLUMN deleted_trigger VARCHAR(64) NULL",
        "deleted_reason": "ALTER TABLE containers ADD COLUMN deleted_reason VARCHAR(255) NULL",
        "deleted_by_user_id": "ALTER TABLE containers ADD COLUMN deleted_by_user_id INTEGER NULL",
    }
    required_mysql = {
        "is_valid": "ALTER TABLE containers ADD COLUMN is_valid BOOLEAN NOT NULL DEFAULT TRUE",
        "deleted_at": "ALTER TABLE containers ADD COLUMN deleted_at DATETIME NULL",
        "deleted_trigger": "ALTER TABLE containers ADD COLUMN deleted_trigger VARCHAR(64) NULL",
        "deleted_reason": "ALTER TABLE containers ADD COLUMN deleted_reason VARCHAR(255) NULL",
        "deleted_by_user_id": "ALTER TABLE containers ADD COLUMN deleted_by_user_id INTEGER NULL",
    }
    required = required_sqlite if current_engine.dialect.name == "sqlite" else required_mysql
    missing = [name for name in required if name not in existing]

    index_names = {index["name"] for index in inspector.get_indexes("containers") if index.get("name")}
    constraint_names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("containers")
        if constraint.get("name")
    }
    schema_names = index_names | constraint_names
    indexes_to_create = {
        "idx_containers_is_valid": "CREATE INDEX idx_containers_is_valid ON containers(is_valid)",
    }

    with current_engine.begin() as conn:
        for name in missing:
            conn.execute(text(required[name]))
        conn.execute(text("UPDATE containers SET is_valid = 1 WHERE is_valid IS NULL"))
        # active_name 已废弃：新代码不再写它。旧库上它可能还留着值，
        # 而残留的 (active_name, machine_id) 唯一索引会把「已删容器占着名字」变成硬阻塞。
        # 清空即让残留索引失效——新行不再写它（NULL），多个 NULL 在唯一索引下互不冲突。
        # 删列由 migrations/2026-09_drop_active_name.sql 处理（DDL 必须走在人工迁移里）。
        if "active_name" in existing:
            cleared = conn.execute(text("UPDATE containers SET active_name = NULL WHERE active_name IS NOT NULL"))
            if cleared.rowcount:
                logger.warning("active_name deprecated: cleared %s stale value(s)", cleared.rowcount)
        for name, ddl in indexes_to_create.items():
            if name in schema_names:
                continue
            try:
                conn.execute(text(ddl))
            except Exception as e:
                logger.warning("container lifecycle schema index %s create failed: %s", name, e)
    if missing:
        logger.warning("container lifecycle schema upgraded: added columns %s", ", ".join(missing))


def _ensure_machine_endpoint_schema() -> None:
    """补齐 machines.port（每台宿主机上 Node 的监听端口）。

    可空、无回填：旧行为 NULL 即「回落全局默认」，与改动前行为一致。
    """

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("machines"):
        return

    existing = {column["name"] for column in inspector.get_columns("machines")}
    if "port" in existing:
        return

    with current_engine.begin() as conn:
        conn.execute(text("ALTER TABLE machines ADD COLUMN port INTEGER NULL"))
    logging.getLogger(__name__).warning("machine schema upgraded: added columns port")


def _ensure_freeze_state_schema() -> None:
    """补齐 container_disk_freeze_state.deferral_seconds（冻结期内的不可用顺延）。

    与 ssh 到期清理、挂载保留期共用同一把尺子：期限按"业务正常时间"计，宕机/维护期
    不算数。旧行保持 NULL，读取侧 coalesce 兜底为 0。
    """

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("container_disk_freeze_state"):
        return

    existing = {column["name"] for column in inspector.get_columns("container_disk_freeze_state")}
    if "deferral_seconds" in existing:
        return

    with current_engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE container_disk_freeze_state ADD COLUMN deferral_seconds INTEGER NULL"
        ))
    logging.getLogger(__name__).warning("freeze state schema upgraded: added columns deferral_seconds")


def _ensure_deleted_container_schema() -> None:
    """Add deleted-owned mount state and cleanup linkage to existing databases."""

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("deleted_container_restore_snapshot"):
        return

    logger = logging.getLogger(__name__)
    deleted_columns = {
        column["name"]
        for column in inspector.get_columns("deleted_container_restore_snapshot")
    }
    cleanup_columns = (
        {
            column["name"]
            for column in inspector.get_columns("container_mount_cleanup")
        }
        if inspector.has_table("container_mount_cleanup")
        else set()
    )
    deleted_missing = "mount_cleaned" not in deleted_columns
    deferral_missing = "deferral_seconds" not in deleted_columns
    cleanup_missing = "deleted_id" not in cleanup_columns

    with current_engine.begin() as conn:
        if deleted_missing:
            conn.execute(text(
                "ALTER TABLE deleted_container_restore_snapshot "
                "ADD COLUMN mount_cleaned BOOLEAN NOT NULL DEFAULT 0"
            ))
        if deferral_missing:
            # 挂载保留期按"业务正常时间"计：宕机/维护期用户无法恢复，那段不算数。
            # 旧行保持 NULL，读取侧 coalesce 兜底为 0，不重写存量行。
            conn.execute(text(
                "ALTER TABLE deleted_container_restore_snapshot "
                "ADD COLUMN deferral_seconds INTEGER NULL"
            ))
        if cleanup_missing and inspector.has_table("container_mount_cleanup"):
            conn.execute(text(
                "ALTER TABLE container_mount_cleanup ADD COLUMN deleted_id INTEGER NULL"
            ))

        if deleted_missing:
            if "mount_path" in deleted_columns:
                conn.execute(text(
                    "UPDATE deleted_container_restore_snapshot "
                    "SET mount_cleaned = 1 WHERE mount_path IS NULL"
                ))
            if inspector.has_table("container_mount_cleanup"):
                conn.execute(text(
                    "UPDATE deleted_container_restore_snapshot "
                    "SET mount_cleaned = 1 "
                    "WHERE mount_cleanup_id IN ("
                    "  SELECT id FROM container_mount_cleanup "
                    "  WHERE cleaned_at IS NOT NULL"
                    ")"
                ))
        if cleanup_missing and inspector.has_table("container_mount_cleanup"):
            conn.execute(text(
                "UPDATE container_mount_cleanup "
                "SET deleted_id = ("
                "  SELECT id FROM deleted_container_restore_snapshot "
                "  WHERE mount_cleanup_id = container_mount_cleanup.id"
                ") "
                "WHERE deleted_id IS NULL"
            ))

    if deleted_missing:
        logger.warning("deleted container schema upgraded: added mount_cleaned")
    if cleanup_missing and inspector.has_table("container_mount_cleanup"):
        logger.warning("container mount cleanup schema upgraded: added deleted_id")


def _ensure_cleanup_deferral_schema() -> None:
    """补齐清理顺延（不可用窗口）相关的增量列。

    同一特性落在两张表上：machines 记窗口起点与采集心跳，ssh 记录表累计顺延秒数。
    create_all 只创建新表、不会修改旧表，因此这些列是当初上线时漏补的——
    旧 SQLite 库缺 machines.unavailable_since 会让机器列表与链路读面直接
    500（每轮 `no such column`），缺 deferral_seconds 会让清理倒计时读面 500。
    """

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    for table, required in (
        ("machines", {
            "unavailable_since": "ALTER TABLE machines ADD COLUMN unavailable_since DATETIME NULL",
            # 采集心跳：窗口起点的下界，供启动扫描兜底（旧库行保持 NULL，扫描会跳过）
            "last_seen_at": "ALTER TABLE machines ADD COLUMN last_seen_at DATETIME NULL",
        }),
        ("container_ssh_login_records", {
            # 旧行 NULL 由读取侧 coalesce 兜底为 0，这里不强制 DEFAULT，避免重写存量行
            "deferral_seconds": "ALTER TABLE container_ssh_login_records ADD COLUMN deferral_seconds INTEGER NULL",
        }),
    ):
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        missing = [name for name in required if name not in existing]
        if not missing:
            continue
        with current_engine.begin() as conn:
            for name in missing:
                conn.execute(text(required[name]))
        logging.getLogger(__name__).warning(
            "cleanup deferral schema upgraded: %s added columns %s", table, ", ".join(missing)
        )


def _ensure_gpu_columns() -> None:
    """补齐 GPU 三集合建模列（machines: gpu_list/gpu_allow_list；containers: gpu_chosen_list）。

    旧库补 JSON 列（SQLite 存 TEXT，MySQL 存 JSON）；新库由 create_all 直接建。
    """

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    for table, required in (
        ("machines", {
            "gpu_list": "ALTER TABLE machines ADD COLUMN gpu_list JSON NULL",
            "gpu_allow_list": "ALTER TABLE machines ADD COLUMN gpu_allow_list JSON NULL",
            "max_disk_size_gb": "ALTER TABLE machines ADD COLUMN max_disk_size_gb INTEGER NULL",
        }),
        ("containers", {
            "gpu_chosen_list": "ALTER TABLE containers ADD COLUMN gpu_chosen_list JSON NULL",
            "port_mappings": "ALTER TABLE containers ADD COLUMN port_mappings JSON NULL",
            # 容器创建时间（2026-09）：容器 id 在 SQLite 删除后可复用，created_at 提供
            # 新旧区分锚（op log 审计对照用）；老库 NULL 由下次创建/回填补齐。
            "created_at": "ALTER TABLE containers ADD COLUMN created_at DATETIME NULL",
        }),
    ):
        if not inspector.has_table(table):
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        missing = [name for name in required if name not in existing]
        if not missing:
            continue
        with current_engine.begin() as conn:
            for name in missing:
                conn.execute(text(required[name]))
        logging.getLogger(__name__).warning("gpu schema upgraded: %s added columns %s", table, ", ".join(missing))

    # 磁盘上限语义收敛回填：max_disk_size_gb 新列 NULL → 沿用原 disk_size_gb
    # （上限行为延续，管理员之后可调；幂等：只补 NULL）。
    if inspector.has_table("machines"):
        try:
            with current_engine.begin() as conn:
                conn.execute(text(
                    "UPDATE machines SET max_disk_size_gb = disk_size_gb "
                    "WHERE max_disk_size_gb IS NULL AND disk_size_gb IS NOT NULL"
                ))
        except Exception as e:  # pragma: no cover
            logging.getLogger(__name__).warning("max_disk_size_gb backfill failed: %s", e)

    _backfill_container_created_at(current_engine)


def _backfill_container_created_at(current_engine) -> None:
    """容器 created_at 存量回填（2026-09）：id 复用区分锚。

    反查来源 = op log 的 create_container 成功记录，取 MAX：id 复用 N 次有 N 条
    create 日志，现存容器 = 最近一次成功创建 → MAX 才是当前实体创建时刻。
    幂等：只补 NULL；无 create 日志的容器维持 NULL（getter 不过滤，兜底）。
    """

    import logging

    from sqlalchemy import inspect, text

    inspector = inspect(current_engine)
    if not (inspector.has_table("containers") and inspector.has_table("operation_logs")):
        return
    try:
        with current_engine.begin() as conn:
            conn.execute(text(
                "UPDATE containers SET created_at = ("
                "  SELECT MAX(created_at) FROM operation_logs"
                "  WHERE target_type = 'container' AND target_id = containers.id"
                "    AND operation = 'create_container' AND success = 1"
                ") WHERE created_at IS NULL"
            ))
    except Exception as e:  # pragma: no cover
        logging.getLogger(__name__).warning("container created_at backfill failed: %s", e)


def _ensure_container_image_schema() -> None:
    """容器镜像归属与构建留痕自愈（2026-09）。

    create_all 只建新表、不改旧表；旧库仍是单列 image。本函数幂等地补齐：
    改名 → 补列（image_id / last_build_at / 配方两项）→ 建索引 → 清悬挂 → 回填归属
    → 回填配方 → 退役 image_dockerfile → 退役 runtime_image。每一步都可在任意库上重复执行。

    必须在任何针对 containers 的 ORM 查询之前跑完：改名未完成时 select(Container)
    会枚举到 containers.runtime_image 而报 no such column。
    """

    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("containers"):
        return

    logger = logging.getLogger(__name__)
    existing = {column["name"] for column in inspector.get_columns("containers")}
    renamed = "image" in existing and "runtime_image" not in existing
    index_names = {index["name"] for index in inspector.get_indexes("containers") if index.get("name")}
    # 补列清单：INTEGER / DATETIME / VARCHAR / TEXT 两方言同形，故无需方言分支。
    required_columns = {
        "image_id": "ALTER TABLE containers ADD COLUMN image_id INTEGER NULL",
        "last_build_at": "ALTER TABLE containers ADD COLUMN last_build_at DATETIME NULL",
        "base_image": "ALTER TABLE containers ADD COLUMN base_image VARCHAR(255) NULL",
        "dockerfile_body": "ALTER TABLE containers ADD COLUMN dockerfile_body TEXT NULL",
    }
    missing = [name for name in required_columns if name not in existing]

    with current_engine.begin() as conn:
        # ① 旧单列改名：数据原地不动（需 SQLite >= 3.25 / MySQL 8.0）。
        #    这一步现在只为一个目的存在——让下面的回填有一个**确定的列名**可读（旧库叫
        #    `image`，后来叫 `runtime_image`）。该列在本次自愈的最后会被退役（⑧），
        #    因此不会留下任何过渡期状态；它的 NOT NULL 也随之消失。
        if renamed:
            conn.execute(text("ALTER TABLE containers RENAME COLUMN image TO runtime_image"))
        # ② 补列
        for name in missing:
            conn.execute(text(required_columns[name]))
        # ③ 索引：DDL 吞异常只 warning，与 _ensure_container_lifecycle_schema 同口径。
        if "ix_containers_image_id" not in index_names:
            try:
                conn.execute(text("CREATE INDEX ix_containers_image_id ON containers(image_id)"))
            except Exception as e:
                logger.warning("container image schema index create failed: %s", e)
        # ④ 清悬挂：外键只在新库里由 create_all 建出，旧库（SQLite 无法 ALTER 加外键）
        #    没有它。模板现在只停用不删除，因此新的悬挂值产生不了；这一步只清理
        #    历史遗留（旧行为下模板被物理删除留下的指向空行的值），并让新库能加上外键。
        if inspector.has_table("images"):
            dangling = conn.execute(text(
                "UPDATE containers SET image_id = NULL"
                " WHERE image_id IS NOT NULL AND image_id NOT IN (SELECT id FROM images)"
            ))
            if dangling.rowcount:
                logger.warning("container image_id cleared (legacy dangling): %s row(s)", dangling.rowcount)
    if renamed or missing:
        logger.warning("container image schema upgraded: renamed=%s added=%s", renamed, missing)

    # 顺序是硬约束：回填都要读旧列，所以退役必须排在最后一个回填之后。
    _backfill_container_image_id(current_engine)
    unconvertible = _backfill_container_dockerfile_parts(current_engine)
    if "image_dockerfile" in existing and unconvertible == 0:
        _retire_container_image_dockerfile(current_engine)
    _retire_runtime_image(current_engine)


def _retire_runtime_image(current_engine) -> None:
    """退役 containers.runtime_image（2026-09 二次决策）。

    它存的是"本次实跑制品的标签"——一个**派生值**（归属标识 + 版本戳一算就有）。标签改由
    `image_tasks.format_image_build_tag` 纯推导之后，它唯一的读点是展示回落，而那个回落在
    推导成功时永远轮不到；写点却还在每一行上抄一份，正是本变更一路在清理的"第二来源"。

    **这一步不只是清理，是必须做的**：旧库里这一列（由 `image` 改名而来）是 NOT NULL，
    新代码不再写它 —— 不删掉，新容器根本插不进去。

    排在所有回填之后：`_backfill_container_image_id` 正是从这一列反解归属与版本戳的。
    删列失败（SQLite < 3.35）只报 ERROR 不抛错，但那是**必须人工处理**的状态：调用方会
    因此插不进新行。所以日志写清怎么办，而不是只丢一句 warning。
    """

    import logging

    from sqlalchemy import inspect, text

    logger = logging.getLogger(__name__)
    inspector = inspect(current_engine)
    if not inspector.has_table("containers"):
        return
    columns = {column["name"] for column in inspector.get_columns("containers")}
    if "runtime_image" not in columns:
        return
    try:
        with current_engine.begin() as conn:
            conn.execute(text("ALTER TABLE containers DROP COLUMN runtime_image"))
    except Exception as e:
        logger.error(
            "containers.runtime_image drop FAILED (%s). 该列在旧库是 NOT NULL 而新代码不再写它——"
            "不删掉就插不进新容器行。请手工执行：ALTER TABLE containers DROP COLUMN runtime_image;",
            e,
        )
        return
    logger.warning("containers.runtime_image retired (tag is derived, not stored)")


def _backfill_container_dockerfile_parts(current_engine) -> int | None:
    """配方留痕的存量回填（2026-09 二次决策）：从旧的单列 image_dockerfile 转出。

    旧列存的是**渲染后**的整段文本，输入不可从文本里反解（渲染结果是纯文本，段边界没有
    标记，反解只会引入脆弱的启发式）。所以这里不做反解，做的是**验证性对齐**：

        取该容器 image_id 对应模板此刻的配方，渲染一份，与存量文本逐字节比对；
        相同 ⇒ 那就说明当初写进去的就是这一份，输入已知，写入。

    对不上就不写（模板改过、注入改过、或本来就是裸镜像容器）。这些行的配方无从重建，
    恢复会以 `data_not_recoverable` 拒绝——那是诚实的，比拿当前模板冒充它跑过的那份好。

    **返回值是"没能转出的行数"**，`None` 表示数不出来（读失败）。调用方只在拿到 0 时
    才退役旧列——还有行转不出来、或压根数不清，旧列就是它们配方的唯一留存，不能删。

    幂等：只补 base_image 为空的行；失败仅 warning。
    """

    import logging

    from sqlalchemy import inspect, text

    logger = logging.getLogger(__name__)
    inspector = inspect(current_engine)
    if not inspector.has_table("containers"):
        return 0
    columns = {column["name"] for column in inspector.get_columns("containers")}
    if "image_dockerfile" not in columns or "base_image" not in columns:
        return 0

    # 读与写分两次事务：中间要跑 ORM 查询（resolve_image_build 自带 session），
    # 和写事务挤在同一个连接上会在 SQLite 上演成锁等待。
    try:
        with current_engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, image_id, image_dockerfile FROM containers"
                " WHERE image_dockerfile IS NOT NULL AND base_image IS NULL"
            )).all()
    except Exception as e:  # pragma: no cover
        logger.warning("container dockerfile parts backfill read failed: %s", e)
        return None
    if not rows:
        return 0

    from .services.image_tasks import resolve_image_build

    by_template: dict[int, object] = {}
    updates = []
    for container_id, image_id, legacy_text in rows:
        if image_id is None:
            continue
        if image_id not in by_template:
            build = resolve_image_build(int(image_id))
            by_template[image_id] = build.dockerfile_parts if build is not None else None
        parts = by_template[image_id]
        if parts is None or parts.render() != legacy_text:
            continue
        updates.append({
            "container_id": container_id,
            "base_image": parts.base_image,
            "dockerfile_body": parts.dockerfile_body,
        })
    unconvertible = len(rows) - len(updates)
    if updates:
        try:
            with current_engine.begin() as conn:
                for values in updates:
                    conn.execute(
                        text(
                            "UPDATE containers SET base_image = :base_image,"
                            " dockerfile_body = :dockerfile_body WHERE id = :container_id"
                        ),
                        values,
                    )
        except Exception as e:  # pragma: no cover
            logger.warning("container dockerfile parts backfill write failed: %s", e)
            return None
    logger.warning(
        "container dockerfile parts backfilled: %s/%s row(s), %s left unconvertible",
        len(updates), len(rows), unconvertible,
    )
    return unconvertible


def _retire_container_image_dockerfile(current_engine) -> None:
    """退役 containers.image_dockerfile：一列渲染结果 → 两项输入（2026-09 二次决策）。

    渲染结果是**派生值**，落库就等于给同一个事实造了第二个来源——本变更要消灭的正是
    这个。它的两个消费者（展示出口、恢复的内容来源）现在都改读两项输入现场渲染。

    与 runtime_image 那个过渡残留不同，这里**直接删列**：该列是本次变更新引入的，
    从未随任何版本发布过，没有"旧库还在依赖它"这回事；而留着它会让派生值继续留在库里。
    调用方只在**所有存量行都转出成功**时才调到这里（还有转不出来的行，旧列就是它们配方
    的唯一留存）。删列失败（SQLite < 3.35）只 warning：列留着不参与任何业务。
    """

    import logging

    from sqlalchemy import text

    logger = logging.getLogger(__name__)
    try:
        with current_engine.begin() as conn:
            conn.execute(text("ALTER TABLE containers DROP COLUMN image_dockerfile"))
    except Exception as e:
        logger.warning("containers.image_dockerfile drop skipped: %s", e)


def _backfill_container_image_id(current_engine) -> None:
    """容器镜像留痕的存量回填（2026-09）：从 runtime_image 的 tag 反解归属与版本戳。

    tag 形如 `fuxi/image-<模板id>:<版本戳>`，一段字符串里编码了两个事实：

    - 模板 id → 回填 `image_id`（归属）
    - 版本戳 → 回填 `last_build_at`（本次构建所依据的模板版本时刻）

    只认这个形式；裸镜像 tag（如 ubuntu:24.04）无从推断归属，两项都保持 NULL —— 不猜。
    回填 `image_id` 前确认 images 行仍在，不制造悬挂值。幂等：只补 NULL；失败仅 warning。

    解析放在 Python 侧而非 SQL：MySQL 的 REGEXP 与 SQLite 无正则会把同一规则撕裂成
    两份方言实现。这是全仓库仅存的 tag 正则，只服务于这一次性迁移 ——
    新代码一律直接读 image_id，不再反解字符串。
    """

    import logging
    import re
    from datetime import datetime

    from sqlalchemy import inspect, text

    logger = logging.getLogger(__name__)
    inspector = inspect(current_engine)
    if not (inspector.has_table("containers") and inspector.has_table("images")):
        return
    # 该列退役之后这一步就无事可做 —— 早退，否则每次启动都会因为查了不存在的列而报一次
    # "backfill failed"，把一条正常状态伪装成故障。
    if "runtime_image" not in {c["name"] for c in inspector.get_columns("containers")}:
        return
    patched = 0
    stamped = 0
    try:
        with current_engine.begin() as conn:
            # 两类补口一起取：归属缺、或版本戳缺（存量两样都缺）。
            rows = conn.execute(text(
                "SELECT id, runtime_image, image_id, last_build_at FROM containers"
                " WHERE runtime_image IS NOT NULL"
                "   AND (image_id IS NULL OR last_build_at IS NULL)"
            )).all()
            if not rows:
                return
            known_ids = {row[0] for row in conn.execute(text("SELECT id FROM images")).all()}
            for container_id, runtime_image, current_image_id, current_stamp in rows:
                match = re.match(r"^fuxi/image-(\d+):(\d{8}T\d{6}Z)$", runtime_image or "")
                if not match:
                    continue
                image_id = int(match.group(1))
                # 版本戳与归属相互独立：模板行没了也只是不补归属，版本戳照补——
                # 它是"这个容器当初按哪个版本建的"这个事实，与模板是否还在无关。
                if current_stamp is None:
                    try:
                        stamp = datetime.strptime(match.group(2), "%Y%m%dT%H%M%SZ")
                    except ValueError:
                        stamp = None
                    if stamp is not None:
                        conn.execute(
                            text("UPDATE containers SET last_build_at = :stamp WHERE id = :container_id"),
                            {"stamp": stamp, "container_id": container_id},
                        )
                        stamped += 1
                if current_image_id is not None or image_id not in known_ids:
                    continue
                conn.execute(
                    text("UPDATE containers SET image_id = :image_id WHERE id = :container_id"),
                    {"image_id": image_id, "container_id": container_id},
                )
                patched += 1
    except Exception as e:  # pragma: no cover
        logger.warning("container image backfill failed: %s", e)
        return
    if patched or stamped:
        logger.warning(
            "container image backfilled: image_id=%s last_build_at=%s row(s)", patched, stamped
        )


def _strip_legacy_snapshot_image_key() -> None:
    """清掉已删容器快照 JSON 里的 `image` 键（2026-09 决策）。

    那个键存的是删除当刻的运行标签字符串。它有两个消费者，都已改掉：

    - 恢复路径曾拿它当"标签推导失败时的回落"——标签是**派生值**（归属标识 + 构建版本戳），
      两个输入都在容器行上，从 JSON 里再抄一份既多余又会让异常状态被静默掩盖；
    - 已删列表出参曾直接把它当展示值——同样改成了由容器行推导，与容器列表同一口径。

    消费者没了，留在数据里就是无意义保留（还是会被抄进每一份新快照的派生值）。
    就地删除，幂等：只剩这个键已不存在时不动那一行。

    与 `active_name` 的清空同款处理——数据层面的退役也走启动自愈，人工迁移不必重复一遍。
    """

    import json
    import logging

    from sqlalchemy import inspect, text

    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("deleted_container_restore_snapshot"):
        return

    logger = logging.getLogger(__name__)
    stripped = 0
    try:
        with current_engine.begin() as conn:
            rows = conn.execute(
                text("SELECT id, snapshot FROM deleted_container_restore_snapshot")
            ).all()
            for row_id, snapshot in rows:
                data = snapshot
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except (TypeError, ValueError):
                        continue
                if not isinstance(data, dict) or "image" not in data:
                    continue
                data.pop("image", None)
                conn.execute(
                    text("UPDATE deleted_container_restore_snapshot SET snapshot = :snapshot WHERE id = :row_id"),
                    {"snapshot": json.dumps(data, ensure_ascii=False), "row_id": row_id},
                )
                stripped += 1
    except Exception as e:  # pragma: no cover
        logger.warning("legacy snapshot image key cleanup failed: %s", e)
        return
    if stripped:
        logger.warning("legacy snapshot image key stripped: %s row(s)", stripped)


def _ensure_machine_image_schema() -> None:
    """machine_image 行身份自愈（2026-09）：从 (machine_id, image_tag) 收敛到
    (machine_id, image_id)。

    标签是**派生值**（归属标识 + 版本戳），不能承担身份——拿它做检索，格式一变即断。
    旧库上这张表的唯一键落在标签上，本函数幂等地：补 image_id 列 → 从既存标签反解回填
    → 清掉回填不出来的行 → 换唯一键。

    反解只服务这一次性迁移，理由同 `_backfill_container_image_id`：存量数据只有标签
    这一个载体，别无他途。新代码一律按 `(machine_id, image_id)` 检索，不再反解字符串。

    顺序是硬约束：换唯一键必须在回填**之后**，否则 (machine_id, image_id) 上有 NULL 重复
    的行会当场撞新约束。
    """

    import logging
    import re

    from sqlalchemy import inspect, text

    logger = logging.getLogger(__name__)
    current_engine = extensions.engine
    inspector = inspect(current_engine)
    if not inspector.has_table("machine_image"):
        return
    is_sqlite = current_engine.dialect.name == "sqlite"
    columns = {column["name"] for column in inspector.get_columns("machine_image")}
    index_names = {
        index["name"] for index in inspector.get_indexes("machine_image") if index.get("name")
    }

    with current_engine.begin() as conn:
        if "image_id" not in columns:
            conn.execute(text("ALTER TABLE machine_image ADD COLUMN image_id INTEGER NULL"))
        # 回填：只认 fuxi/image-<模板id>:… 这个形式；模板行不在了的也不留（会成悬挂值）。
        rows = conn.execute(text(
            "SELECT id, image_tag FROM machine_image WHERE image_id IS NULL"
        )).all()
        known_ids = (
            {row[0] for row in conn.execute(text("SELECT id FROM images")).all()}
            if inspector.has_table("images")
            else set()
        )
        patched = 0
        for row_id, image_tag in rows:
            match = re.match(r"^fuxi/image-(\d+):", image_tag or "")
            if not match or int(match.group(1)) not in known_ids:
                continue
            conn.execute(
                text("UPDATE machine_image SET image_id = :image_id WHERE id = :row_id"),
                {"image_id": int(match.group(1)), "row_id": row_id},
            )
            patched += 1

        # 回填不出来的行：身份无从确定，且在复合键语义下不会被任何检索命中。删掉。
        # （它们的存在只会让新唯一键建不上。）
        unresolvable = conn.execute(
            text("DELETE FROM machine_image WHERE image_id IS NULL")
        ).rowcount

        # 唯一键：旧名落在标签上，必须换。MySQL 是独立索引，可直接换；
        # SQLite 的 UNIQUE 是内联表约束，ALTER 删不掉（同 2026-09_container_soft_delete_strict_ids.sql
        # 的口径）——那边由"写点永不产生重复标签"兜住，不阻塞。
        if "uq_machine_image_tag" in index_names:
            conn.execute(text("DROP INDEX uq_machine_image_tag ON machine_image"))
        if "uq_machine_image_machine_id_image_id" not in index_names:
            try:
                conn.execute(text(
                    "CREATE UNIQUE INDEX uq_machine_image_machine_id_image_id"
                    " ON machine_image(machine_id, image_id)"
                ))
            except Exception as e:
                logger.warning("machine_image unique index create failed: %s", e)
        if not is_sqlite:
            # 回填 + 清理之后不该再有空值；MySQL 可收紧，SQLite 改不了列约束。
            try:
                conn.execute(text("ALTER TABLE machine_image MODIFY image_id INTEGER NOT NULL"))
            except Exception as e:
                logger.warning("machine_image image_id NOT NULL failed: %s", e)

    if patched or unresolvable:
        logger.warning(
            "machine_image composite key migrated: backfilled=%s removed=%s row(s)",
            patched, unresolvable,
        )


def _should_start_background_tasks() -> bool:
    """Return whether Ctrl background tasks should start."""

    return not getattr(AppConfig, "TESTING", False) and not getattr(AppConfig, "DISABLE_BACKGROUND_TASKS", False)


def _start_background_tasks() -> None:
    """Start Ctrl background tasks after their DB access is migrated.

    三个调度器各自按 settings 自门控（disk / mount 有 enabled 开关，未启用时
    start_* 返回 None 不启动）；任务只做纯 DB 扫描 + 到期集合的低频动作，
    不发起逐容器探测请求（mount 清理带机器可达 gate）。
    """

    from .schedulers.container_cleanup_task import start_container_cleanup_scheduler
    from .schedulers.container_disk_check_task import start_container_disk_check_scheduler
    from .schedulers.container_mount_cleanup_task import start_mount_cleanup_scheduler

    start_container_cleanup_scheduler()
    start_container_disk_check_scheduler()
    start_mount_cleanup_scheduler()


def create_app(config: str | None = None, overrides: dict | None = None) -> FastAPI:
    """Create the Ctrl FastAPI application."""

    _apply_overrides(overrides)
    configure_database(AppConfig.SQLALCHEMY_DATABASE_URI)
    configure_daily_logging(AppConfig)
    _init_database()
    # 内部运行时推送共享 token 预热（API 先于 WSS 子进程启动，保证两进程同一 token）
    try:
        import logging

        from .services.container_module.node_comms import _read_internal_token

        _read_internal_token()
    except Exception as e:  # pragma: no cover
        logging.getLogger(__name__).warning("internal token warmup failed: %s", e)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if _should_start_background_tasks():
            _start_background_tasks()
        yield

    app = FastAPI(title="FuxiYu CtrlKernel API", lifespan=lifespan)
    app.state.config = AppConfig
    app.state.db = db

    app.add_middleware(
        CORSMiddleware,
        allow_origins=build_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        reason = "invalid_payload"
        fields = {
            str(part)
            for error in errors
            for part in error.get("loc", ())
            if part not in ("body", "query", "path")
        }
        if any(error.get("type") == "json_invalid" for error in errors):
            reason = "invalid_json"
        elif request.url.path.endswith("/users/get_user_detail_information") and "user_id" in fields:
            reason = "missing_user_id"
        elif request.url.path.endswith("/request_register_code") and "email" in fields:
            reason = "missing_email"
        elif (
            request.url.path.endswith("/machines/add_machine_permission")
            or request.url.path.endswith("/machines/remove_machine_permission")
        ) and {"machine_id", "user_id"} & fields:
            reason = "missing_fields"
        return JSONResponse(
            status_code=400,
            content={
                "success": 0,
                "message": "invalid request payload",
                "error_reason": reason,
                "detail": errors,
            },
        )

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(_: Request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "success" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail, headers=exc.headers)
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": 0, "message": str(exc.detail), "error_reason": None},
            headers=exc.headers,
        )

    register_api(app)
    return app
