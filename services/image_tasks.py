"""镜像模板服务。

镜像第一阶段只管理 Ctrl 侧长期保存的基础镜像与用户业务 Dockerfile
片段；最终 Dockerfile 由构建器临时生成。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.exc import IntegrityError

from ..constant import ImageStatus, OperationType
from ..extensions import session_scope
from ..repositories import image_repo, userimage_repo
from . import settings_tasks
from .operation_log_tasks import log_failure, log_success


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _coerce_status(value: str | ImageStatus | None) -> ImageStatus | None:
    if value is None:
        return None
    if isinstance(value, ImageStatus):
        return value
    try:
        return ImageStatus(str(value))
    except ValueError as exc:
        err = ValueError(f"invalid image status: {value}")
        setattr(err, "error_reason", "invalid_status")
        raise err from exc


def _serialize(image, *, include_content: bool = False) -> dict:
    """镜像概要序列化。大字段只在详情接口返回。

    include_content 仅详情用；列表不带内容，避免大字段进分页响应。
    """
    result = {
        "image_id": image.id,
        "name": image.name,
        "description": image.description,
        "base_image": image.base_image,
        # 归一后再出参：NULL 与 "" 在库里都可能存在，读侧一律折成 None（= 平台默认）
        "entrypoint": (image.entrypoint or "").strip() or None,
        "status": _status_value(image.status),
        "created_by_user_id": image.created_by_user_id,
        "created_at": image.created_at.isoformat() if image.created_at else None,
        "updated_at": image.updated_at.isoformat() if image.updated_at else None,
    }
    if include_content:
        result["dockerfile_body"] = image.dockerfile_body
    return result


def _dispatched_tag_if_fresh(machine_id: int, image_id: int) -> str | None:
    """该 (机器, 模板) 已派发过的制品标签——**仅当它相对模板当前版本没过时**才返回。

    过时判据 = `machine_image.created_at <= images.updated_at`（**严格大于才算新鲜**）。
    写点在改写时刷新 `created_at`，所以那一行记的是"最近一次派发的时刻"；它若严格晚于
    模板的最后一次修改，就说明这个制品正是当前模板版本产出的——此时
    `format_image_build_tag` 由同一对输入算出的值必然是它，提前返回因此**不会**造成
    "旧标签配新内容"。

    为什么是严格大于：DATETIME 列在 MySQL 上截断到秒。若派发与模板修改落在同一秒，
    `created_at == updated_at` 无法区分先后，判"新鲜"就可能把一个**早于**本次修改的
    标签当成当前值——那正是要杜绝的组合。判"过时"只会退回推导链路（结果恒正确），
    代价仅是少一次提前返回。

    过时、无行、表不可用：一律返回 None，交给正常推导链路。失败只 warning 不阻断——
    这条预检查是加速项，它的可用性不该影响创建容器或展示。
    """

    import logging

    from ..repositories import machine_image_repo

    logger = logging.getLogger(__name__)
    try:
        with session_scope(commit=False) as session:
            row = machine_image_repo.get_by_machine_image(
                int(machine_id), int(image_id), session=session
            )
            if row is None:
                return None
            image = image_repo.get_by_id(int(image_id), session=session)
            if image is None or row.created_at is None or image.updated_at is None:
                return None
            if row.created_at <= image.updated_at:
                return None
            return row.image_tag
    except Exception as e:  # pragma: no cover
        logger.warning("machine_image pre-check failed: machine=%s image=%s: %s", machine_id, image_id, e)
        return None


def format_image_build_tag(
    image_id: int | None,
    version_at: datetime | None,
    machine_id: int | None = None,
) -> str | None:
    """由「归属标识 + 版本戳」推导 Docker tag；两者缺一就推不出来，返回 None。

    这是**唯一**的标签构造实现：创建/恢复时填 Node 的 `config.image` 与 `image_build.image_tag`
    用它，展示出口也用它。公式只有一份，两边不可能漂。

    刻意**不**用 now() 兜底：那会编出一个从未出现过的标签。标签是 Node 侧的缓存键，
    编一个假的比返回空坏得多——展示会指着一个没跑过的制品，构建会去命中一个不存在的东西。
    推不出来就是推不出来，由调用方各自决定是拒绝还是留空。

    `machine_id` 给定时先做一次**预检查**（见 `_dispatched_tag_if_fresh`）：该 (机器, 模板)
    已派发过且没过时，就直接返回那个标签，不再推导。按契约它与推导值相等——两者的输入
    是同一对（归属标识 + 模板当前版本戳），预检查只是省掉一次推导。

    ⚠ **配方是"该容器自己那份"的调用点不要传 machine_id**：预检查返回的是机器级的当前
    标签，与容器自己的旧配方拼在一起就成了"新标签配旧内容"，与"旧标签配新内容"同样
    破坏 Node 的标签缓存（见 services/container_module/restore.py 的快照分支）。
    """
    if machine_id is not None and image_id is not None:
        fresh = _dispatched_tag_if_fresh(int(machine_id), int(image_id))
        if fresh is not None:
            return fresh
    if image_id is None or version_at is None:
        return None
    version_time = version_at
    if version_time.tzinfo is not None:
        version_time = version_time.astimezone(timezone.utc).replace(tzinfo=None)
    version_time = version_time.replace(microsecond=0)
    stamp = version_time.strftime("%Y%m%dT%H%M%SZ")
    return f"fuxi/image-{int(image_id)}:{stamp}"


# 容器里跑什么的**平台默认**：保持容器存活，等你 SSH 进来。
# 它是 Ctrl 的策略，因此只写在这里一处——Node 不持有它、也不做任何回落。
PLATFORM_DEFAULT_ENTRYPOINT = "tail -f /dev/null"


def render_final_dockerfile(
    *,
    base_image: str,
    platform_injection: str,
    dockerfile_body: str | None = None,
    entrypoint: str | None = None,
) -> str:
    """拼出最终 Dockerfile 文本。

    四段，顺序是硬约束：FROM → 平台注入 → 用户业务片段 → **ENTRYPOINT**。

    ENTRYPOINT 排在最后有两个作用，都靠 Docker 自己的规则生效，不需要运行期做任何事：

    1. **后写的 ENTRYPOINT 覆盖先写的** —— 用户在业务片段里自己写了 ENTRYPOINT 也不生效，
       平台那行说了算（构建时会有一条 MultipleInstructionsDisallowed 警告，无害）。
    2. **shell 形式比 exec 形式更能挡住外面的干扰**（四种组合都实测过）：

       | 干扰源 | shell 形式 | exec 形式 |
       |---|---|---|
       | 镜像里残留的 CMD | **被忽略** | 被追加成参数 |
       | `docker run` 传的命令 | 成为 shell 的 `$0/$1`，**脚本本身不变** | 追加成真参数 |

       注意第 2 行不是"什么都不发生"：`/proc/1/cmdline` 里看得见那些参数，但它们落在
       positional 参数上，而这行命令不引用 `$1/$@`——所以**实际执行的仍然是这一行**。

    所以"容器跑什么"在**构建期**就锁死了。这正是把启动命令放进 Dockerfile 而不是走
    运行期参数的原因：运行期要覆盖镜像入口得额外置空 Entrypoint 字段，而那条路一旦漏掉
    就会被镜像入口吃掉命令（2026-09 实测复现过）。

    另注（既有行为，与本决策无关）：容器 PID 1 被内核特例对待——**没装 handler 的信号一律
    忽略**，所以 `docker stop` 会走满 Node 的 `stop_container(timeout=10)` 才 SIGKILL。
    改动前 PID 1 是 tail 时同样是 10.3s（实测），不是本次引入的。

    留空即平台默认（`PLATFORM_DEFAULT_ENTRYPOINT`）。默认值在这里兜底意味着**渲染出来的
    Dockerfile 必定带 ENTRYPOINT**，"镜像自描述"这条永远成立。
    """

    parts: list[str] = [f"FROM {base_image}".strip()]
    injection = (platform_injection or "").strip()
    if injection:
        parts.append(injection)
    body = (dockerfile_body or "").strip()
    if body:
        parts.append(body)
    # shell 形式（不写方括号）是刻意的：见 docstring 第 2 条，它是唯一能挡住运行期传参的形态。
    parts.append(f"ENTRYPOINT {(entrypoint or '').strip() or PLATFORM_DEFAULT_ENTRYPOINT}")
    return "\n\n".join(parts).rstrip() + "\n"


@dataclass(frozen=True)
class DockerfileParts:
    """一份 Dockerfile 的四段输入——渲染**之前**的形态。

    字段名与 `render_final_dockerfile` 的形参、以及 images / containers 表的列名逐一对应，
    刻意不另起名：同一件事在库里、在这个类里、在渲染函数里都叫同一个名字。

    **四个字段，但容器行只落库其中三个**（`base_image` / `dockerfile_body` / `entrypoint`）；
    `platform_injection` 每次渲染现取系统设置，因此从容器读回来的那份里，这个字段
    装的是**当下**的注入，不是当年的（见 models/containers.py）。

    `entrypoint` 是**构建段**而不是运行期参数（2026-09 决策）：它渲染成 Dockerfile 的最后
    一行，因此决定了镜像内容，也参与"这份配方能否精确还原"。
    """

    base_image: str
    platform_injection: str
    dockerfile_body: str | None = None
    entrypoint: str | None = None

    def render(self) -> str:
        """渲染成最终 Dockerfile 文本（就是发给 Node 的那份）。"""
        return render_final_dockerfile(
            base_image=self.base_image,
            platform_injection=self.platform_injection,
            dockerfile_body=self.dockerfile_body,
            entrypoint=self.entrypoint,
        )


@dataclass(frozen=True)
class ImageBuild:
    """一次构建的全部留痕。

    payload 是发给 Node 的构建段（只含 Node 真正读的两个键）；其余字段是 Ctrl
    侧要落的账，**不进 payload**——它们是 Node 不读的死键，塞进去只会让人误以为
    Node 依赖它们（2026-09 曾因此清理过一次）。
    """

    payload: dict
    image_id: int
    # 本次构建所依据的**模板版本时刻**：取派发时读到的 images.updated_at，**不是 now()**。
    # 用当前时间会让「容器落后于模板」的比较退化为墙钟对版本戳，在两者之间的窗口内
    # 编辑模板将造成静默误判。
    version_at: datetime
    # 本次构建实际使用的配方（三段输入，而非渲染结果），要落成容器的留痕。
    # `dockerfile_parts.render()` 就是 payload 里那份 dockerfile_text。
    dockerfile_parts: DockerfileParts


def resolve_image_build(image_id: int, machine_id: int | None = None) -> ImageBuild | None:
    """按 image_id 解析出一次构建的全部留痕。

    payload 只回 Node 真正读的两个键（ImageBuildConfig 的 dockerfile_text / image_tag）。
    曾经还带 image_id 与 base_image：前者 Ctrl 自己就知道、Node 丢弃，后者已经作为
    `FROM ...` 写在 dockerfile_text 首行了 —— 都是没人读的冗余。

    取模板走 `image_repo.get_by_id` 原语，**不受停用过滤影响**：恢复链路要用已停用
    模板的内容判定分支，管理路径也要能取到停用行。

    `machine_id` 透传给 `format_image_build_tag` 的新鲜度预检查（见该函数）。调用方只
    取 `dockerfile_parts` 时可以不给——那时标签根本不被使用，给了只会多一次查询。
    """

    with session_scope(commit=False) as session:
        image = image_repo.get_by_id(image_id, session=session)
        if image is None:
            return None
        parts = DockerfileParts(
            base_image=image.base_image,
            platform_injection=settings_tasks.get_image_platform_injection_content() or "",
            dockerfile_body=image.dockerfile_body,
            # NULL 与 "" 都折成 None——渲染时再兜平台默认，调用方只见两态
            entrypoint=(image.entrypoint or "").strip() or None,
        )
        image_tag = format_image_build_tag(image.id, image.updated_at, machine_id)
        if image_tag is None:  # pragma: no cover - images.updated_at 是 NOT NULL，构造上不可达
            raise ValueError(f"image {image.id} has no version timestamp to derive a tag from")
        return ImageBuild(
            payload={
                "image_tag": image_tag,
                "dockerfile_text": parts.render(),
            },
            image_id=image.id,
            version_at=image.updated_at,
            dockerfile_parts=parts,
        )


class ImageUsability(str, Enum):
    """创建容器时对镜像模板的可用性判定结果。

    用字符串枚举而不是 `bool | None`：加入「已停用」之后三态不够用了——被拒绝时若只能
    报 `image_not_found`（误导：模板明明在）或 `image_access_denied`（更误导：与权限无关），
    调用方和用户都无从判断到底为什么建不了。
    """

    OK = "ok"
    NOT_FOUND = "not_found"
    DENIED = "denied"
    DISABLED = "disabled"


def Can_use_image_for_container(user_id: int | None, image_id: int) -> ImageUsability:
    """创建容器时的镜像可用性判断，口径与镜像列表可见性一致。

    停用优先于权限判定：一个已停用的模板对任何人都不可用，包括管理员——因此先看状态，
    再看可见性，避免把"停用"报成"无权"。

    注意取模板走 `get_by_id` 原语（**不过滤停用**）——过滤了就分辨不出 NOT_FOUND 与
    DISABLED 的差别，只能笼统报"不存在"。
    """

    visible_ids, include_public = _visible_scope(user_id)
    with session_scope(commit=False) as session:
        image = image_repo.get_by_id(image_id, session=session)
        if image is None:
            return ImageUsability.NOT_FOUND
        if image.status != ImageStatus.READY:
            # 草稿与停用一律不可用于新建容器：草稿是尚未定稿的模板。
            return ImageUsability.DISABLED
        if visible_ids is None and not include_public:
            return ImageUsability.OK
        if visible_ids and image.id in visible_ids:
            return ImageUsability.OK
        if include_public and image.created_by_user_id is None:
            return ImageUsability.OK
        return ImageUsability.DENIED


def _visible_scope(viewer_user_id: int | None) -> tuple[set[int] | None, bool]:
    """返回 (visible_image_ids, include_public)。

    - 资源通配者：不过滤（None, False）
    - 普通用户：已授权 user_images 集合 + 系统内置镜像全员可见（created_by IS NULL）
    """
    if viewer_user_id is None:
        return set(), False
    from .rbac_service import _has_resource_manage_direct

    if _has_resource_manage_direct(viewer_user_id, "image"):
        return None, False
    with session_scope(commit=False) as session:
        return set(userimage_repo.list_image_ids_by_user(viewer_user_id, session=session)), True


def _resource_scope(viewer_user_id: int | None) -> tuple[set[int], bool]:
    """只返回当前用户持有 user_images 资源绑定的镜像集合。"""

    if viewer_user_id is None:
        return set(), False
    with session_scope(commit=False) as session:
        return set(userimage_repo.list_image_ids_by_user(viewer_user_id, session=session)), False


def Create_image(
    *,
    name: str,
    base_image: str,
    dockerfile_body: str = "",
    description: str | None = None,
    status: str | ImageStatus | None = None,
    entrypoint: str | None = None,
    operator_user_id: int | None = None,
) -> int:
    """创建镜像模板，并把创建者绑定到 user-i。

    2026-09 决策：创建即带状态——status 缺省为草稿，显式传 ready/disabled 一步到位
    （此前恒 DRAFT，新建后必须二次编辑才能置可用）。
    """

    try:
        status_enum = _coerce_status(status)
        with session_scope() as session:
            # 名字唯一性由应用层承担（DB 已无唯一约束）：只在**未停用**的模板之间查重。
            # 停用的模板继续占着名字，但不该阻止同名新建——那会让一个被撤下的模板
            # 永久霸占一个名字。
            if image_repo.find_active_by_name(name, session=session) is not None:
                raise ValueError(f"image name already in use: {name}")
            image = image_repo.create_image(
                name=name,
                description=description,
                base_image=base_image,
                dockerfile_body=dockerfile_body,
                # 空串/纯空白一律归一成 NULL——"空即默认"只该有一种空值形态
                entrypoint=(entrypoint or "").strip() or None,
                status=status_enum or ImageStatus.DRAFT,
                created_by_user_id=operator_user_id,
                session=session,
            )
            if operator_user_id is not None:
                userimage_repo.grant_image(operator_user_id, image.id, session=session)
            image_id = image.id
    except Exception as exc:
        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.CREATE_IMAGE,
            target_type="image",
            target_id=0,
            detail={"name": name},
            error_reason=getattr(exc, "error_reason", None) or str(exc),
        )
        raise
    log_success(operator_user_id=operator_user_id,
        operation=OperationType.CREATE_IMAGE,
        target_type="image",
        target_id=image_id,
        detail={"name": name},
    )
    return image_id


def Update_image(
    *,
    image_id: int,
    operator_user_id: int | None = None,
    name: str | None = None,
    description: str | None = None,
    base_image: str | None = None,
    dockerfile_body: str | None = None,
    entrypoint: str | None = None,
    status: str | ImageStatus | None = None,
) -> bool:
    """更新镜像模板元数据或内容。"""

    image_name = name
    try:
        with session_scope(commit=False) as session:
            image = image_repo.get_by_id(image_id, session=session)
            if image is None:
                log_failure(operator_user_id=operator_user_id,
                    operation=OperationType.UPDATE_IMAGE,
                    target_type="image",
                    target_id=image_id,
                    detail={"name": None},
                    error_reason="image_not_found",
                )
                return False
            image_name = image.name

        fields = {
            "name": name,
            "description": description,
            "base_image": base_image,
            "status": _coerce_status(status),
        }
        if dockerfile_body is not None:
            fields["dockerfile_body"] = dockerfile_body
        if entrypoint is not None:
            # 传空串 = **清除**（回到平台默认）。None 仍是"不提供"，两者语义不同：
            # 前端要清空这一栏时发的就是空串，而省略该键表示这次不动它。
            fields["entrypoint"] = (entrypoint or "").strip() or None
        with session_scope() as session:
            # 改名也要过应用层查重（DB 已无唯一约束）：撞上**别的**活跃模板才拒绝，
            # 改成自己原来的名字不算冲突。
            if name is not None:
                clash = image_repo.find_active_by_name(name, session=session)
                if clash is not None and clash.id != int(image_id):
                    raise ValueError(f"image name already in use: {name}")
            ok = image_repo.update_image(image_id, session=session, **fields)
    except Exception as exc:
        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.UPDATE_IMAGE,
            target_type="image",
            target_id=image_id,
            detail={"name": image_name},
            error_reason=getattr(exc, "error_reason", None) or str(exc),
        )
        raise

    if not ok:
        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.UPDATE_IMAGE,
            target_type="image",
            target_id=image_id,
            detail={"name": image_name},
            error_reason="update_failed",
        )
        return False

    log_success(operator_user_id=operator_user_id,
        operation=OperationType.UPDATE_IMAGE,
        target_type="image",
        target_id=image_id,
        detail={"name": name or image_name},
    )
    return ok


def Delete_image(*, image_id: int, operator_user_id: int | None = None) -> bool:
    """移除模板——实际是**置为停用**，不做物理删除（design D2 第三版）。

    保留行而不是删掉，是为了让三件事同时成立：容器对模板的引用保持完整（"构建自哪个
    模板"这个事实不丢）、运行基底在模板撤下后仍可查、镜像标签仍可由归属标识推导。

    接口名与审计动作沿用 DELETE_IMAGE（对外语义就是"移除"），但**没有容器会被解绑**——
    归属标识的值永不改变。重新启用走 Update_image（status 在可更新白名单里）。
    """
    image_name = None
    try:
        with session_scope() as session:
            image = image_repo.get_by_id(image_id, session=session)
            if image is None:
                log_failure(operator_user_id=operator_user_id,
                    operation=OperationType.DELETE_IMAGE,
                    target_type="image",
                    target_id=image_id,
                    detail={"name": None},
                    error_reason="image_not_found",
                )
                return False
            image_name = image.name
            disabled = image_repo.disable_image(image_id, session=session)
            if disabled is None:
                log_failure(operator_user_id=operator_user_id,
                    operation=OperationType.DELETE_IMAGE,
                    target_type="image",
                    target_id=image_id,
                    detail={"name": image_name},
                    error_reason="delete_failed",
                )
                return False
    except Exception as exc:
        log_failure(operator_user_id=operator_user_id,
            operation=OperationType.DELETE_IMAGE,
            target_type="image",
            target_id=image_id,
            detail={"name": image_name},
            error_reason=getattr(exc, "error_reason", None) or str(exc),
        )
        raise

    log_success(operator_user_id=operator_user_id,
        operation=OperationType.DELETE_IMAGE,
        target_type="image",
        target_id=image_id,
        detail={"name": image_name, "disabled": True},
    )
    return True


def Get_image_detail(image_id: int) -> dict | None:
    with session_scope(commit=False) as session:
        image = image_repo.get_by_id(image_id, session=session)
        if image is None:
            return None
        return _serialize(image, include_content=True)


def List_image_bref_information(
    *,
    page_number: int = 1,
    page_size: int = 20,
    image_search: str | None = None,
    viewer_user_id: int | None = None,
    mine_only: bool = False,
) -> dict:
    page_number = max(1, int(page_number or 1))
    page_size = max(1, int(page_size or 20))
    visible_ids, include_public = _resource_scope(viewer_user_id) if mine_only else _visible_scope(viewer_user_id)
    with session_scope(commit=False) as session:
        total = image_repo.count_images(
            image_search=image_search,
            visible_image_ids=visible_ids,
            include_public=include_public,
            session=session,
        )
        images = image_repo.list_images(
            limit=page_size,
            offset=(page_number - 1) * page_size,
            image_search=image_search,
            visible_image_ids=visible_ids,
            include_public=include_public,
            session=session,
        )
        return {
            "images": [_serialize(image, include_content=False) for image in images],
            "total_page": math.ceil(total / page_size) if total else 0,
            "total_number": total,
        }


# ── 内置镜像 seed（幂等；create_app 建表后调用一次，与 RBAC seed 同模式） ──────

SEED_IMAGES: list[dict] = [
    {
        "name": "Ubuntu 24.04 · 基础",
        # 旧名收敛锚：内置模板改过名（22.04 → 24.04）时按它找回原来那行就地改，
        # 而不是新插一行。详见 seed_image_defaults。
        "legacy_names": ["Ubuntu 22.04 · 基础"],
        # 镜像构建契约（2026-08）：模板只表达业务环境；FROM 单独存，
        # 平台基础设施由构建注入保证，不在模板里预装。
        "description": "Ubuntu 24.04 通用环境模板（平台内置）。",
        "status": ImageStatus.READY,
        "base_image": "ubuntu:24.04",
        "dockerfile_body": "",
    },
]


def _find_legacy_seed_image(item: dict, *, session):
    """按 legacy_names 找回被改过名的内置模板行，限定 created_by_user_id IS NULL。

    限定系统行是有意的：用户自建的、恰好同名的模板不归平台管，不参与收敛。
    """
    for legacy_name in item.get("legacy_names") or []:
        image = image_repo.get_by_name(legacy_name, session=session)
        if image is not None and image.created_by_user_id is None:
            return image
    return None


def seed_image_defaults() -> None:
    """幂等 seed：写入内置镜像模板。

    - created_by_user_id 置空 → 系统镜像，全员可见（_visible_scope 的 include_public）
    - 同名已存在时跳过，不覆盖人工修改
    - 旧名收敛：内置模板改过名时，先按 legacy_names 找那条系统行就地改名 + 同步 FROM，
      找不到才插入新行。否则每改一次名就多出一个内置模板，用户可见可选的列表里会并排
      出现两个「基础」。

    所有权边界：created_by_user_id IS NULL 的系统模板归平台，随版本升级而变；
    要自定义请另建模板（自建行永不参与收敛）。
    """
    import logging

    for item in SEED_IMAGES:
        with session_scope() as session:
            # get_by_name 是**原语，不过滤停用** —— 这一点对本 seed 是必需的：
            # 内置模板若被停用，用"活跃行"去查会查不到，于是插进第二行同名模板，
            # 用户可见的列表里就并排出现两个「基础」。看见停用行才能正确跳过。
            if image_repo.get_by_name(item["name"], session=session) is not None:
                continue
            legacy = _find_legacy_seed_image(item, session=session)
            if legacy is not None:
                legacy_name, legacy_id, legacy_status = legacy.name, legacy.id, legacy.status
                image_repo.update_image(
                    legacy_id,
                    name=item["name"],
                    description=item["description"],
                    base_image=item["base_image"],
                    dockerfile_body=item["dockerfile_body"],
                    # **不覆盖状态**：管理员若已把它停用，平台升级不该悄悄把它启用回来。
                    # 新建的行才用 item 里的状态。
                    status=legacy_status,
                    session=session,
                )
                logging.getLogger(__name__).warning(
                    "builtin image template converged: %s -> %s (id=%s)",
                    legacy_name, item["name"], legacy_id,
                )
                continue
            image_repo.create_image(
                name=item["name"],
                description=item["description"],
                base_image=item["base_image"],
                dockerfile_body=item["dockerfile_body"],
                status=item["status"],
                created_by_user_id=None,
                session=session,
            )
