"""容器镜像归属与构建留痕的行为锁。

背景：容器的镜像归属此前是拿 image 列的 tag 字符串正则反解出来的，恢复链路还直接
拿 tag 回填、不重新构建 —— Node 上的 docker 制品一旦被 prune，恢复就永久失败。
改造后归属是 `image_id`（唯一身份来源），镜像标签改由「归属 + 构建版本戳」推导，
容器的 Dockerfile 快照只服务展示与精确还原。

本文件锁住七组性质：
1. 旧库自愈（改名 / 补列 / 回填归属与版本戳 / 清遗留悬挂 / 配方三段转换与旧列退役）与幂等；
2. 创建链路把归属与留痕落库，且 API 边界必填、客户端镜像名不采信；
3. 模板移除是**停用**而非删除：归属保留、管理路径仍可达、业务读点看不见；
4. 版本戳语义与落后判据（不看 created_at）；
5. 展示出口按落后判据分流，且模板停用后展示不为空；
6. 恢复的**三分支判定**（模板 READY+版本符合 / READY+新版本 / 非 READY 或归属为空）；
7. 配方留痕存的是**三段输入**而不是渲染结果（否则"注入变没变"无从判定）。
"""

from sqlalchemy import inspect, select, text

from ... import _ensure_container_image_schema, extensions
from ...api import container_api, deps
from ...models.containers import Container
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...repositories import containers_repo
from ...services import container_tasks
from ...services.container_module import information, utils
from ...services.image_tasks import DockerfileParts
from ...utils.Container import Container_info
from ..factories import create_container, create_container_graph, create_machine, create_user

TPL_TAG = "fuxi/image-1:20260825T090016Z"


def _container_info(name: str) -> Container_info:
    return Container_info(gpu_list=[], cpu_number=1, memory=1, shared_memory=0, name=name, image=TPL_TAG)


def _parts(base_image: str = "ubuntu:22.04", injection: str | None = None, body: str | None = None) -> DockerfileParts:
    """造一份配方。渲染结果是三段按空行拼接，因此 `_parts().render()` 恒带尾换行。

    `injection=None` 取**当下的系统设置**——与容器留痕的读取口径一致（注入不落库）。
    """
    if injection is None:
        from ...services import settings_tasks

        injection = settings_tasks.get_image_platform_injection_content() or ""
    return DockerfileParts(
        base_image=base_image, platform_injection=injection, dockerfile_body=body,
    )


def _set_recipe(container, parts: DockerfileParts) -> None:
    """把配方落到容器行上——只落模板侧两项，注入不落库（它永远取当下设置）。"""
    container.base_image = parts.base_image
    container.dockerfile_body = parts.dockerfile_body


def _recipe_of(container) -> DockerfileParts | None:
    """把容器行读回成配方（注入由当下设置补上）；没留痕返回 None。"""
    return utils.container_dockerfile_parts(container)


def _image_build_for(db_session, image_id: int, machine_id: int | None = None):
    """取一次构建留痕；`machine_id` 决定标签**从缓存拿**还是现造。"""
    from ...services.image_tasks import resolve_image_build

    return resolve_image_build(image_id, machine_id)


def _auth(monkeypatch, *, valid=True, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: valid)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)


def _to_legacy_shape(machine_id: int) -> None:
    """把 containers 换成旧形状：单列 image（NOT NULL）、无 image_id、**无外键**。

    用重建而非 ALTER 退回，有两个原因：SQLite 不允许 DROP 掉参与外键定义的列；
    而且重建出来的表本来就没有外键 —— 这正是旧库的真实状态，也是「清悬挂」那一步
    存在的唯一理由（新库有 FK 的 SET NULL 兜底，压根产生不了悬挂值）。
    """
    with extensions.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS containers"))
        conn.execute(text(
            "CREATE TABLE containers ("
            " id INTEGER PRIMARY KEY,"
            " name VARCHAR(120) NOT NULL,"
            " image VARCHAR(200) NOT NULL,"
            " machine_id INTEGER NOT NULL,"
            " container_status VARCHAR(20) NOT NULL,"
            " port INTEGER NOT NULL,"
            " memory_gb INTEGER NOT NULL,"
            " shared_gb INTEGER NOT NULL,"
            " gpu_number INTEGER NOT NULL,"
            " cpu_number INTEGER NOT NULL,"
            " is_valid BOOLEAN NOT NULL DEFAULT 1)"
        ))
        for name, image in (("legacy_tpl", TPL_TAG), ("legacy_bare", "ubuntu:24.04")):
            conn.execute(
                text(
                    "INSERT INTO containers (name, image, machine_id, container_status, port,"
                    " memory_gb, shared_gb, gpu_number, cpu_number, is_valid)"
                    " VALUES (:name, :image, :machine_id, 'online', 20001, 1, 0, 0, 1, 1)"
                ),
                {"name": name, "image": image, "machine_id": machine_id},
            )


def _image_id_by_name(name: str):
    with extensions.engine.begin() as conn:
        return conn.execute(
            text("SELECT image_id FROM containers WHERE name = :name"), {"name": name}
        ).scalar()


def _last_build_at_by_name(name: str):
    with extensions.engine.begin() as conn:
        return conn.execute(
            text("SELECT last_build_at FROM containers WHERE name = :name"), {"name": name}
        ).scalar()


def _add_legacy_dockerfile_column(values_by_name: dict[str, str]) -> None:
    """把已退役的 image_dockerfile 列加回 containers 表，并按容器名填值。

    模拟"三段输入上线之前"的库：那一列存的是渲染后的整段文本。
    """
    with extensions.engine.begin() as conn:
        conn.execute(text("ALTER TABLE containers ADD COLUMN image_dockerfile TEXT NULL"))
        for name, value in values_by_name.items():
            conn.execute(
                text("UPDATE containers SET image_dockerfile = :v WHERE name = :n"),
                {"v": value, "n": name},
            )


def _recipe_columns(container_id: int):
    with extensions.engine.connect() as conn:
        return tuple(conn.execute(
            text("SELECT base_image, dockerfile_body FROM containers WHERE id = :i"),
            {"i": container_id},
        ).one())


############################################################
# 旧库自愈：改名 / 加列 / 回填 / 清悬挂
############################################################

def test_legacy_image_column_is_read_then_retired(db_session):
    """旧库（单列 image）启动自愈：补 image_id、按 tag 回填，然后**把那一列也退役掉**。

    旧列在这条链路里只是回填的**输入**（读它反解归属与版本戳），读完就没有存在理由——
    它存的是派生值，而标签现在由 image_id + last_build_at 现算。它同时是旧库的 NOT NULL
    列，不删掉新容器插不进去。
    """
    machine = create_machine()
    _to_legacy_shape(machine.id)

    _ensure_container_image_schema()

    columns = {column["name"] for column in inspect(extensions.engine).get_columns("containers")}
    assert {"image_id", "last_build_at", "base_image", "dockerfile_body"} <= columns
    assert "image" not in columns and "runtime_image" not in columns
    assert "ix_containers_image_id" in {
        index["name"] for index in inspect(extensions.engine).get_indexes("containers")
    }
    # 模板产物 tag 认得出归属 → 回填；裸镜像 tag 无从推断 → 保持 NULL，不猜
    assert _image_id_by_name("legacy_tpl") == 1
    assert _image_id_by_name("legacy_bare") is None
    # 版本戳也从那一列反解出来了（标签里编码着构建时刻）
    assert _last_build_at_by_name("legacy_tpl") is not None
    assert _last_build_at_by_name("legacy_bare") is None


def test_ensure_container_image_schema_is_idempotent(db_session):
    """自愈可在任意库上重复执行：第二次不抛错、不改动已有归属。"""
    machine = create_machine()
    _to_legacy_shape(machine.id)

    _ensure_container_image_schema()
    _ensure_container_image_schema()

    assert _image_id_by_name("legacy_tpl") == 1
    assert _image_id_by_name("legacy_bare") is None


def test_ensure_container_image_schema_clears_dangling_image_id(db_session):
    """模板行已不存在时，指向它的 image_id 被清成 NULL 而不是留着悬挂。

    旧库没有外键（SQLite 无法 ALTER 加），模板在停机期间被删就会留下悬挂值，
    重建时无从解析 —— 启动自愈的「清悬挂」是唯一的补偿。清完不会被回填重新推回去：
    回填守着「images 行必须还在」这条线，不会凭 tag 造出指向空气的 id。
    """
    machine = create_machine()
    _to_legacy_shape(machine.id)
    _ensure_container_image_schema()
    assert _image_id_by_name("legacy_tpl") == 1
    # 停机期间模板被删：容器行还指着它
    with extensions.engine.begin() as conn:
        conn.execute(text("DELETE FROM images WHERE id = 1"))

    _ensure_container_image_schema()

    assert _image_id_by_name("legacy_tpl") is None
    # 只清归属：版本戳照留 —— "这个容器当初按哪个版本建的"是事实，与模板是否还在无关
    assert _last_build_at_by_name("legacy_tpl") is not None


############################################################
# 配方留痕：单列渲染结果 → 三段输入（2026-09 二次决策）
############################################################

def test_legacy_single_column_recipe_is_converted_and_retired(db_session):
    """旧的单列 image_dockerfile → 两项输入；转完把旧列**退役**。

    转换不是从文本反解段边界（渲染结果是纯文本，段边界没有标记，反解只会引入脆弱的
    启发式），而是**验证性对齐**：拿该容器 image_id 对应模板此刻的配方渲染一份，与存量
    文本逐字节比对，相同才写入——相同就证明当初写进去的就是这一份。

    旧列必须删：渲染结果是**派生值**（拼一下就有），留库就等于给同一个事实造第二个
    来源，而那正是本次改造要消灭的东西。
    """
    from ...services.image_tasks import resolve_image_build

    parts = resolve_image_build(1).dockerfile_parts
    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    _add_legacy_dockerfile_column({container.name: parts.render()})

    _ensure_container_image_schema()

    columns = {c["name"] for c in inspect(extensions.engine).get_columns("containers")}
    assert "image_dockerfile" not in columns, "转完就该退役"
    assert _recipe_columns(container.id) == (parts.base_image, parts.dockerfile_body)


def test_legacy_recipe_that_cannot_be_matched_keeps_the_old_column(db_session):
    """对不上的存量文本不写两项，且旧列**不退役**——它是那些行配方的唯一留存。

    模板改过、注入改过、裸镜像容器都会落到这一支。这些行的配方无从重建，恢复会以
    `data_not_recoverable` 拒绝——那是诚实的；拿当前模板冒充它跑过的那份要坏得多。
    """
    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    _add_legacy_dockerfile_column({container.name: "FROM ubuntu:22.04\nRUN echo hand-written\n"})

    _ensure_container_image_schema()

    columns = {c["name"] for c in inspect(extensions.engine).get_columns("containers")}
    assert "image_dockerfile" in columns, "还有行转不出来，旧列不能删"
    assert _recipe_columns(container.id) == (None, None), "对不上就不写，不猜"


############################################################
# 创建链路：image_id 必填 + 落库
############################################################

def test_create_container_api_requires_image_id(client, monkeypatch, db_session):
    """不传 image_id 直接 400，且不落到 service 门户（也不该发出 Node 请求）。

    这里刻意带上旧通路的 container.image：它**不能**替代 image_id —— 客户端自选镜像
    正是当年绕过平台注入（容器没 sshd）的那条路。
    """
    _auth(monkeypatch)
    called = []
    monkeypatch.setattr(
        container_api.container_service, "Create_container", lambda **kwargs: called.append(kwargs)
    )

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "container": {"NAME": "c", "image": "ubuntu:24.04"}},
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"
    assert called == []


def test_create_container_api_ignores_client_supplied_image(client, monkeypatch, db_session):
    """API 边界把 image_id 一路交给门户，且请求体里的镜像名一律不采信。"""
    _auth(monkeypatch)
    captured = []
    monkeypatch.setattr(
        container_api.container_service, "Create_container", lambda **kwargs: captured.append(kwargs) or True
    )

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "image_id": 1,
              "container": {"CPU_NUMBER": 1, "MEMORY": 1, "NAME": "c", "image": "evil:1.0"}},
    )

    assert resp.status_code == 200
    assert captured[0]["image_id"] == 1
    # wire 契约不变：进 Node config.image 的是平台解析出的 tag，不是客户端给的那个
    assert captured[0]["container"].image == captured[0]["image_build"]["image_tag"]
    assert "evil" not in captured[0]["container"].image


def test_create_container_api_rejects_unknown_image_id(client, monkeypatch, db_session):
    _auth(monkeypatch)

    resp = client.post(
        "/api/containers/create_container",
        json={"owner_user_id": 2, "machine_id": 1, "image_id": 999999, "container": {"NAME": "c"}},
    )

    assert resp.status_code == 404
    assert resp.json()["error_reason"] == "image_not_found"


def test_image_build_payload_carries_only_what_node_reads(db_session):
    """发给 Node 的构建段只带它真正读的两个键。

    曾经还带 image_id 与 base_image —— 前者 Node 丢弃、Ctrl 自己有，后者已经作为
    `FROM ...` 写在 dockerfile_text 首行。留着会让人误以为 base_image 是权威。
    """
    from ...services.image_tasks import resolve_image_build

    build = resolve_image_build(1)

    assert set(build.payload) == {"image_tag", "dockerfile_text"}
    assert build.payload["dockerfile_text"].splitlines()[0] == "FROM ubuntu:24.04"
    # 留痕与 payload 同源，且不进 payload（它们只落 Ctrl 的账）
    assert build.image_id == 1
    assert build.version_at is not None
    assert build.dockerfile_parts.render() == build.payload["dockerfile_text"]


############################################################
# 移除镜像模板：停用而非删除，归属与留痕都保留
############################################################

def test_delete_image_disables_and_keeps_binding(db_session):
    """移除模板 = 置停用。**没有容器会被解绑**——归属标识的值永不改变。

    保留行而非物理删除，是为了让"构建自哪个模板"这个事实不丢、运行基底在模板撤下后
    仍可查、镜像标签仍可推导。这三件事都靠"行还在"成立。
    """
    machine = create_machine()
    container = create_container(machine=machine, image_id=1)

    from ...services import image_tasks

    assert image_tasks.Delete_image(image_id=1) is True

    db_session.expire_all()
    kept = containers_repo.get_by_id(container.id, session=db_session)
    assert kept is not None
    assert kept.image_id == 1, "归属标识不该被解绑"

    # 模板行仍在，只是状态变了——因此运行基底仍可查
    from ...repositories import image_repo
    template = image_repo.get_by_id(1, session=db_session)
    assert template is not None
    assert template.status.value == "disabled"
    assert template.base_image == "ubuntu:24.04"


def test_disabled_template_still_readable_by_management_paths(db_session):
    """停用不是单向门：管理路径仍能取到它、改它、再启用它。

    这条守的是"过滤不能加在原语上"——`get_by_id` 若过滤了停用，`Update_image`
    会失明，停用就再也撤不回来。
    """
    from ...repositories import image_repo
    from ...services import image_tasks
    from ...constant import ImageStatus

    assert image_tasks.Delete_image(image_id=1) is True

    # 管理路径能取到
    template = image_repo.get_by_id(1, session=db_session)
    assert template is not None

    # 能改内容
    assert image_tasks.Update_image(image_id=1, description="停用后仍可编辑") is True
    db_session.expire_all()
    assert image_repo.get_by_id(1, session=db_session).description == "停用后仍可编辑"

    # 能重新启用
    assert image_tasks.Update_image(image_id=1, status=ImageStatus.READY) is True
    db_session.expire_all()
    assert image_repo.get_by_id(1, session=db_session).status == ImageStatus.READY


def test_disabled_template_hidden_from_business_reads(db_session):
    """业务读点看不见停用的模板：列表、计数、创建前判定。"""
    from ...repositories import image_repo
    from ...services import image_tasks

    assert image_tasks.Delete_image(image_id=1) is True

    listed = image_repo.list_images(session=db_session)
    assert 1 not in {img.id for img in listed}
    assert image_repo.count_images(session=db_session) == len(listed)
    assert (
        image_tasks.Can_use_image_for_container(None, 1)
        is image_tasks.ImageUsability.DISABLED
    )
    # 与"不存在"必须可区分——否则用户会去查一个明明存在的模板
    assert (
        image_tasks.Can_use_image_for_container(None, 999999)
        is image_tasks.ImageUsability.NOT_FOUND
    )


def test_disabled_template_frees_its_name(db_session):
    """停用的模板不再永久占用名字：唯一性只在未停用的模板之间判定。

    DB 的唯一约束已移除（停用行会继续占名，约束会让名字永久不可复用）；这条守的是
    应用层接管后的行为。
    """
    from ...repositories import image_repo
    from ...services import image_tasks

    name = image_repo.get_by_id(1, session=db_session).name
    assert image_tasks.Delete_image(image_id=1) is True

    # 同名新建应当成功（停用行不再参与查重）
    new_id = image_tasks.Create_image(
        name=name, base_image="ubuntu:24.04", dockerfile_body="", status="ready",
    )
    assert new_id != 1

    # 但两个**活跃**模板不能同名
    import pytest
    with pytest.raises(ValueError):
        image_tasks.Create_image(name=name, base_image="ubuntu:24.04", dockerfile_body="")


############################################################
# 读出侧：Dockerfile 走 image_id，不再反解 tag
############################################################

def test_image_dockerfile_renders_from_image_id(db_session):
    machine = create_machine()
    container = create_container(machine=machine, image_id=1)

    rendered = utils.container_image_dockerfile(container)

    assert rendered is not None and rendered.startswith("FROM ubuntu:24.04")


def test_image_dockerfile_falls_back_to_snapshot_without_binding(db_session):
    """无归属 → 展示容器自己的留痕（存量容器没有留痕时才是 None）。"""
    machine = create_machine()
    container = create_container(machine=machine, image_id=None)

    assert utils.container_image_dockerfile(container) is None

    _set_recipe(container, _parts(base_image="ubuntu:24.04", body="RUN echo snapshot"))
    assert utils.container_image_dockerfile(container) == (
        _parts(base_image="ubuntu:24.04", body="RUN echo snapshot").render()
    )


def test_common_fields_expose_ownership_and_template_name(db_session):
    """出参只有**归属标识 + 模板名**，不出标签（2026-09 决策）。

    标签是 Node 侧的缓存键与 docker 制品名，不是平台的管理粒度；前端要显示的是
    "这个容器用的是哪个模板"。名字由**服务端**解析——容器的可见性与模板的可见性是两套
    判据，用户可能看得见容器却看不见模板，让前端拿 image_id 自己去查会变成空白或报错。
    """
    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    db_session.commit()

    fields = information._build_container_common_fields(container, machine, [])

    assert fields["image_id"] == 1
    assert fields["image_name"] == "Ubuntu 24.04 · 基础"
    assert "container_image" not in fields, "标签不再对外"


def test_common_fields_tolerate_missing_template(db_session):
    """无归属（存量裸镜像容器）时两项都为空，不抛错、不编造。"""
    machine = create_machine()
    container = create_container(machine=machine, image_id=None)
    db_session.commit()

    fields = information._build_container_common_fields(container, machine, [])
    assert fields["image_id"] is None
    assert fields["image_name"] is None


############################################################
# 恢复链路：三分支判定（design D3）
############################################################

def _restore_target(image_id, snapshot_image=TPL_TAG, version_at=None, base=None):
    """造恢复上下文；`base=None` 表示该容器**没有配方留痕**（数据损坏态）。"""
    from datetime import datetime, timezone

    from ...services.container_module.restore import _RestoreTarget

    return _RestoreTarget(
        snapshot={"container_name": "c", "image": snapshot_image},
        container_id=1, machine_id=1, mount_path="/tmp/m",
        mount_cleanup_id=None, removed_at=datetime.now(timezone.utc),
        image_id=image_id, image_version_at=version_at,
        dockerfile_parts=None if base is None else _parts(base_image=base),
    )


def test_restore_uses_template_when_not_behind(db_session):
    """模板 READY 且容器不落后 → 正常拼装流程（无需快照、无需询问）。"""
    from ...services.container_module.restore import _resolve_restore_image
    from ...repositories import image_repo

    version_at = image_repo.get_by_id(1, session=db_session).updated_at
    resolved = _resolve_restore_image(_restore_target(1, version_at=version_at))

    assert resolved.mode == "template"
    assert resolved.needs_choice is False
    assert resolved.image_build["dockerfile_text"].startswith("FROM ubuntu:24.04")
    assert resolved.image_tag == resolved.image_build["image_tag"]
    assert resolved.image_id == 1


def test_restore_marks_choice_when_template_is_newer(db_session):
    """模板 READY 但容器落后 → 标记"这里存在二选一"；**默认仍取快照**。

    needs_choice 不是拒绝信号，也不表示"调用方没指定"——它描述的是**处境**（两份内容不同），
    专供预览接口决定要不要公布两份内容。
    """
    from datetime import datetime

    from ...services.container_module.restore import (
        _resolve_restore_image, CONTENT_SOURCE_SNAPSHOT,
    )

    old = datetime(2020, 1, 1)          # 远早于模板的 updated_at
    target = _restore_target(1, version_at=old, base="ubuntu:22.04")

    default = _resolve_restore_image(target)
    assert default.needs_choice is True, "有分歧就该标记"
    assert default.mode == "snapshot", "默认取快照，不按新"

    chosen = _resolve_restore_image(target, CONTENT_SOURCE_SNAPSHOT)
    assert chosen.needs_choice is True, "标记描述处境，不随传参改变"
    assert chosen.mode == "snapshot"
    assert chosen.image_build["dockerfile_text"] == _parts().render()
    # 快照路径的标签用**原标签**（内容没变，版本戳沿用），不能用模板的新标签
    assert chosen.image_tag == "fuxi/image-1:20200101T000000Z"

    latest = _resolve_restore_image(target, "template")
    assert latest.mode == "template"
    assert latest.image_tag == latest.image_build["image_tag"]


def test_restore_without_template_choice_when_not_behind(db_session):
    """版本符合 → 没有二选一（两份内容一致），不标记 → 预览不公布任何内容。"""
    from ...repositories import image_repo
    from ...services.container_module.restore import _resolve_restore_image

    version_at = image_repo.get_by_id(1, session=db_session).updated_at
    resolved = _resolve_restore_image(
        _restore_target(1, version_at=version_at, base="ubuntu:22.04")
    )

    assert resolved.needs_choice is False


def test_restore_uses_snapshot_when_template_not_ready(db_session):
    """模板非 READY（停用 / 草稿）→ 一律走快照，不把撤下或未定稿的内容端给用户选。"""
    from ...services import image_tasks
    from ...repositories import image_repo
    from ...services.container_module.restore import _resolve_restore_image

    version_at = image_repo.get_by_id(1, session=db_session).updated_at
    assert image_tasks.Delete_image(image_id=1) is True   # 置为停用

    resolved = _resolve_restore_image(
        _restore_target(1, version_at=version_at, base="ubuntu:22.04")
    )

    assert resolved.mode == "snapshot"
    assert resolved.needs_choice is False, "非 READY 不该问用户——直接取快照"
    assert resolved.image_build["dockerfile_text"] == _parts().render()


def test_restore_without_binding_uses_snapshot_without_tag_fallback(db_session):
    """归属为空 → 走快照分支；标签**只由归属+版本戳推导，没有回落**。

    这里刻意造一个"有留痕但无归属"的状态：内容发得出去（快照在），但标签推不出来。
    以前会回落到已删快照 JSON 里的 tag，现在没有了——那种状态由 `_build_restore_container`
    的非空校验拦下（见下一条测试）。
    """
    from ...services.container_module.restore import _resolve_restore_image

    built = _resolve_restore_image(_restore_target(None, base="ubuntu:22.04"))

    assert built.mode == "snapshot"
    assert built.image_build["dockerfile_text"] == _parts().render()
    assert built.image_tag is None, "无归属 → 推不出标签，且没有回落可退"


def test_restore_without_snapshot_raises_instead_of_degrading(db_session):
    """没有留痕 → **抛错**，不降级成"不发构建段、按标签直接跑"。

    容器恒有留痕（Create 与 Resurrect 都写），没有就是数据损坏。降级会让一个损坏状态
    **看起来像一次成功恢复**，并且把能否恢复交给"宿主机上还留着旧制品吗"去赌。
    """
    from ...services.container_module.exceptions import NodeServiceError
    from ...services.container_module.restore import _resolve_restore_image

    import pytest
    with pytest.raises(NodeServiceError) as excinfo:
        _resolve_restore_image(_restore_target(1, version_at=None))

    assert excinfo.value.reason == "data_not_recoverable"


def test_restore_rejects_when_tag_cannot_be_derived(db_session, monkeypatch, mock_node_send):
    """推不出运行标签时拒绝恢复，而不是退回某个旧载体里记的 tag。

    标签是**派生值**——由容器行上的「归属标识 + 构建版本戳」算出。这里曾经会回落到
    **已删容器快照 JSON** 的 `"image"` 键，那让一个多余载体参与了业务，还会掩盖
    "标签推不出来"这种异常状态。

    干净设计下这一步不可达：模板只停用不删除 ⇒ 归属永不置空；Create/Resurrect 都写版本戳。
    """
    from ...services.container_module.exceptions import NodeServiceError

    root, machine, container = create_container_graph()
    container.name = "no_tag"
    container.bind_mount_path = f"/home/{root.username}/containers/no_tag_data"
    container.image_id = None          # 干净设计下不该出现的状态
    container.last_build_at = None
    # 给一份留痕：否则会先撞上"没有配方可恢复"那条，测不到标签推导这一步
    _set_recipe(container, _parts())
    db_session.commit()
    mock_node_send({"success": 1})

    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot_id = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one().id

    import pytest
    with pytest.raises(NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot_id, operator_user_id=root.id)
    assert excinfo.value.reason == "invalid_payload"
    assert "derive image tag" in str(excinfo.value)


def test_no_restore_path_omits_the_build_segment(db_session):
    """**不存在不发构建段的恢复路径** —— 三条支路都发。

    这条是结构性保证，不是约定：`direct`（不发构建段、按标签直接跑）已删除，因为
    容器恒有留痕，那条路只会掩盖数据损坏，并把能否恢复交给"宿主机上还有旧制品吗"去赌。
    """
    from datetime import datetime

    from ...services.container_module.restore import _resolve_restore_image

    # 落后支（默认取快照）
    behind = _resolve_restore_image(
        _restore_target(1, version_at=datetime(2020, 1, 1), base="ubuntu:22.04")
    )
    # 模板支
    template = _resolve_restore_image(
        _restore_target(1, version_at=datetime(2020, 1, 1), base="ubuntu:22.04"),
        content_source="template",
    )
    # 版本符合支
    from ...repositories import image_repo
    fresh = _resolve_restore_image(
        _restore_target(
            1,
            version_at=image_repo.get_by_id(1, session=db_session).updated_at,
            base="ubuntu:22.04",
        )
    )

    for resolved in (behind, template, fresh):
        assert resolved.image_build is not None, "每条路都必须带构建段"
        assert resolved.image_build["dockerfile_text"]
        # 构建段的标签与声明的运行标签必须一致——否则同一个标签会指向不同内容，
        # 破坏 Node 侧按标签判定的构建缓存
        assert resolved.image_build["image_tag"] == resolved.image_tag


def test_resurrect_sends_image_build_and_keeps_image_id(db_session, monkeypatch, mock_node_send):
    """全链路：不落后的容器被删后恢复 → 发 image_build 重建，复活行归属与留痕都在。"""
    from ...repositories import image_repo

    root, machine, container = create_container_graph()
    container.name = "rebuild_me"
    container.bind_mount_path = f"/home/{root.username}/containers/rebuild_me_data"
    container.image_id = 1
    # 版本戳对齐当前模板 → 走"不落后"分支，无需调用方选择
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    db_session.commit()
    sent = mock_node_send({"success": 1})

    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot_id = db_session.scalars(
        select(DeletedContainerRestoreSnapshot)
    ).one().id

    container_tasks.resurrect_container(snapshot_id, operator_user_id=root.id)

    db_session.expire_all()
    create_call = next(item for item in sent if item["url"].endswith("/create_container"))
    image_build = create_call["payload"]["image_build"]
    assert image_build["dockerfile_text"].startswith("FROM ubuntu:24.04")
    # Node 侧 config.image 仍是 tag（wire 契约不变），且与构建出的 tag 同名
    assert create_call["payload"]["config"]["image"] == image_build["image_tag"]
    restored = containers_repo.get_by_id(container.id, session=db_session, include_invalid=True)
    assert restored.image_id == 1
    # 恢复必须刷新版本戳与配方——不刷新会让刚重建的容器被判定为落后，展示旧内容
    assert restored.last_build_at is not None
    assert _recipe_of(restored).render() == image_build["dockerfile_text"]


def _deleted_behind_container(db_session, mock_node_send, name):
    """造一个"模板已更新、容器落后"的已删容器，返回 (root, snapshot_id)。"""
    from datetime import datetime

    root, machine, container = create_container_graph()
    container.name = name
    container.bind_mount_path = f"/home/{root.username}/containers/{name}_data"
    container.image_id = 1
    container.last_build_at = datetime(2020, 1, 1)   # 远早于模板版本
    _set_recipe(container, _parts())
    db_session.commit()
    sent = mock_node_send({"success": 1})

    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot_id = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one().id
    return root, snapshot_id, sent


def test_resurrect_snapshot_choice_uses_the_container_recipe(db_session, monkeypatch, mock_node_send):
    """有二选一时选 `snapshot` → 用容器自己的留痕构建（它实际跑过的那份）。

    注意"默认"的语义变了：**有二选一时后端不自动恢复**，而是把两份内容交回调用方选
    （那是唯一内容会真正改变的场合）。所以这里必须显式传 `snapshot`。
    没有二选一的情形见 test_resurrect_api_returns_choice... 的反面：直接恢复、不问。
    """
    root, snapshot_id, sent = _deleted_behind_container(db_session, mock_node_send, "behind_me")

    container_tasks.resurrect_container(
        snapshot_id, operator_user_id=root.id, content_source="snapshot",
    )

    create_call = next(c for c in sent if c["url"].endswith("/create_container"))
    assert create_call["payload"]["image_build"]["dockerfile_text"] == _parts().render()


def test_resurrect_uses_template_only_when_explicitly_asked(db_session, monkeypatch, mock_node_send):
    """显式传 `template` 才用当前模板渲染 —— "按新"永不作为默认。"""
    root, snapshot_id, sent = _deleted_behind_container(db_session, mock_node_send, "want_new")

    container_tasks.resurrect_container(
        snapshot_id, operator_user_id=root.id, content_source="template",
    )

    create_call = next(c for c in sent if c["url"].endswith("/create_container"))
    assert create_call["payload"]["image_build"]["dockerfile_text"].startswith("FROM ubuntu:24.04")


############################################################
# 版本戳与落后判据（design D5）
############################################################

def test_version_stamp_is_the_tag_stamp_not_the_template_version(db_session):
    """版本戳是**这条标签自己的**版本戳，不是模板最后一次被改的时刻。

    来源见 `resolve_image_build_tag`：缓存命中时它是行里的 `created_at`，现造时是 `now()`。
    它落在容器行上，于是容器也能回答"我跑的是哪一版"。
    """
    from ...services.image_tasks import resolve_image_build
    from ...repositories import image_repo

    build = resolve_image_build(1)
    template = image_repo.get_by_id(1, session=db_session)

    assert build.payload["image_tag"].endswith(
        build.version_at.strftime("%Y%m%dT%H%M%SZ")
    )


def test_image_tag_is_never_fabricated(db_session):
    """推不出标签就返回 None，**绝不用 now() 编一个**。

    这里曾经是 `version_time = updated_at or datetime.now(timezone.utc)`。创建路径上永远
    触发不了（`images.updated_at` 是 NOT NULL），但展示路径上，裸镜像存量容器会因此显示
    一个**从未存在过的标签**——比显示空白坏得多：它指着一个没跑过的制品。

    标签是 Node 侧的缓存键，编造等于让缓存键说谎。所以这个兜底必须不存在。
    """
    from datetime import datetime

    from ...services.image_tasks import format_image_build_tag

    # 两个输入各缺一半都不能推，且都不能退化成"用今天编一个"
    assert format_image_build_tag(None, datetime(2026, 8, 25, 9, 0, 16)) is None
    assert format_image_build_tag(1, None) is None
    assert format_image_build_tag(None, None) is None

    today_stamp = datetime.utcnow().strftime("%Y%m%d")
    assert format_image_build_tag(1, None) != f"fuxi/image-1:{today_stamp}T000000Z"


def test_behind_judgement_ignores_created_at(db_session):
    """落后判据只看版本戳，**不看创建时间**。

    恢复不更新 created_at，用它判定会把一个刚按最新模板重建的容器误判为落后。
    """
    from datetime import datetime, timedelta

    from ...services.container_module.utils import is_version_behind
    from ...repositories import image_repo

    template_at = image_repo.get_by_id(1, session=db_session).updated_at

    assert is_version_behind(template_at, template_at) is False          # 版本符合
    assert is_version_behind(template_at - timedelta(days=1), template_at) is True   # 落后
    assert is_version_behind(template_at + timedelta(days=1), template_at) is False  # 更新
    # 没有留痕 → 无法证明是当前版本 → 按落后处理（展示快照更诚实）
    assert is_version_behind(None, template_at) is True
    # 模板版本未知 → 不判定为落后
    assert is_version_behind(template_at, None) is False


############################################################
# 展示出口的分流（design D8）
############################################################

def test_display_shows_snapshot_when_behind(db_session):
    """落后时展示容器自己的留痕——展示当前模板会撒谎。"""
    from datetime import datetime

    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    container.last_build_at = datetime(2020, 1, 1)     # 远早于模板版本
    _set_recipe(container, _parts(body="RUN echo old"))
    db_session.commit()

    shown = utils.container_image_dockerfile(container)

    assert shown == _parts(body="RUN echo old").render()
    assert "24.04" not in shown


def test_display_always_prefers_snapshot_regardless_of_freshness(db_session):
    """**有留痕就展示留痕**，与是否落后无关。

    这条守的是一个不做版本判据的理由：平台注入独立于模板版本。若"没落后就展示当前
    模板渲染"，注入变更而模板版本未变时，展示出口会给出新注入，而容器跑的是旧注入。
    """
    from ...repositories import image_repo

    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    # 版本戳对齐当前模板（判据会认为"不落后"），但留痕内容与模板不同
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    _set_recipe(container, _parts(body="RUN echo what-it-actually-runs"))
    db_session.commit()

    shown = utils.container_image_dockerfile(container)

    assert shown == _parts(body="RUN echo what-it-actually-runs").render()
    assert "24.04" not in shown, "有留痕时不该用当前模板渲染"


def test_display_falls_back_to_template_without_snapshot(db_session):
    """无留痕的存量容器回落为当前模板渲染——有损，但比空白好。"""
    from ...repositories import image_repo

    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    db_session.commit()

    assert container.base_image is None
    shown = utils.container_image_dockerfile(container)

    assert shown is not None and shown.startswith("FROM ubuntu:24.04")


def test_display_survives_template_being_disabled(db_session):
    """模板停用后，引用它的容器展示**不为空**——这是 D2 第三版的核心收益。

    停用的语义是"不能再用于新建"，不是"历史不可查"。展示出口若过滤了停用，
    停用一个模板就会让所有引用它的容器展示变空，等于自己取消了收益。
    """
    from ...services import image_tasks

    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    container.last_build_at = None           # 无版本戳
    _set_recipe(container, _parts(base_image="ubuntu:24.04"))
    db_session.commit()

    assert image_tasks.Delete_image(image_id=1) is True
    db_session.expire_all()

    assert utils.container_image_dockerfile(container) == _parts(base_image="ubuntu:24.04").render()
    # 运行基底（基础镜像）也仍可查——行还在
    from ...repositories import image_repo
    assert image_repo.get_by_id(1, session=db_session).base_image == "ubuntu:24.04"


############################################################
# 派发记录（machine_image）：纯观测、不在执行链上
############################################################

def test_machine_image_records_dispatch_and_dedupes(db_session, mock_node_send):
    from ...repositories import machine_image_repo, image_repo
    from datetime import datetime, timezone

    owner = create_user(username="owner_mi")
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    from ...repositories import machine_permission_repo
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    mock_node_send({"success": 1})

    build = _image_build_for(db_session, 1)
    for _ in range(2):
        container_tasks.Create_container(
            owner_user_id=owner.id, machine_id=machine.id,
            container=_container_info(f"mi_{_}"),
            image_build=build.payload, image_id=1,
            image_version_at=build.version_at, dockerfile_parts=build.dockerfile_parts,
        )

    rows = machine_image_repo.list_by_machine(machine.id, session=db_session)
    assert len(rows) == 1, "同一 (机器, 模板) 只该留一行"
    assert (rows[0].machine_id, rows[0].image_id) == (machine.id, 1)
    assert rows[0].image_tag == build.payload["image_tag"]


def test_machine_image_row_is_never_rewritten(db_session, mock_node_send):
    """一行一 (机器, 模板)，**重复派发不改写它**——tag 与 created_at 都不动。

    这一行就是"这台机器上那个制品"：就地改写等于悄悄换版本，而宿主机上那个制品还挂在
    旧标签下，成了没人记得的孤儿。要换代只有一条路：模板变更时整行删掉。
    """
    from ...repositories import machine_image_repo, machine_permission_repo

    owner = create_user(username="owner_mi_up")
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    mock_node_send({"success": 1})

    build = _image_build_for(db_session, 1)
    for i in range(2):
        container_tasks.Create_container(
            owner_user_id=owner.id, machine_id=machine.id,
            container=_container_info(f"mi_up_{i}"),
            image_build=build.payload, image_id=1,
            image_version_at=build.version_at, dockerfile_parts=build.dockerfile_parts,
        )

    rows = machine_image_repo.list_by_machine(machine.id, session=db_session)
    assert len(rows) == 1
    assert rows[0].image_tag == build.payload["image_tag"]
    assert rows[0].created_at == build.version_at, "版本戳也必须原样留着"


def test_template_update_clears_the_cache_and_forces_a_new_tag(db_session, mock_node_send):
    """**模板一变 → 缓存整行清掉 → 下次派发现造新标签**。这就是换代的全过程。

    断言方式刻意不依赖秒边界：先往行里种一条**独特**的标签，更新模板后它必须消失、
    派发必须现造一条别的——证明确实是"缓存没了、重新造"，而不是"恰好算出了同一个值"。
    """
    from ...repositories import image_repo, machine_image_repo, machine_permission_repo
    from ...services import image_tasks

    owner = create_user(username="owner_mi_inv")
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    mock_node_send({"success": 1})

    planted = "fuxi/image-1:29990101T000000Z"
    stamped = image_repo.get_by_id(1, session=db_session).updated_at + __import__("datetime").timedelta(seconds=5)
    machine_image_repo.record_dispatch(machine.id, 1, planted, stamped, session=db_session)
    db_session.commit()

    assert image_tasks.Update_image(image_id=1, description="改了个描述") is True
    db_session.expire_all()
    assert machine_image_repo.list_by_machine(machine.id, session=db_session) == [], \
        "模板一变，所有机器上的这一版记录都必须清掉（否则永不重建）"

    after = _image_build_for(db_session, 1, machine_id=machine.id)
    assert after.payload["image_tag"] != planted, "缓存已清，必须现造新标签（不能复用旧值）"
    assert after.payload["image_tag"].startswith("fuxi/image-1:")


def test_fabricated_stamp_has_second_precision_so_same_second_reuses_the_tag(db_session):
    """**已知边角**：标签的版本戳是秒精度，所以"模板变更"与"下次派发"落在同一秒时，
    现造出来的标签会与刚刚那一版**同名**。

    后果很窄但真实：那一秒里宿主机上若已存在同名制品，会被判成命中、跑旧内容，而 Ctrl
    显示的是新配方。要触发它必须"改模板"与"建容器"落在同一秒内。

    这里把行为钉住，是为了让它**可见**——将来若要收紧，做法是让现造的戳严格大于被删掉
    的那一版的戳，而那需要保留一点"上一版是什么时候"的记忆（当前设计刻意不留）。
    """
    from datetime import datetime

    from ...services.image_tasks import resolve_image_build_tag

    machine = create_machine()
    fixed = datetime(2026, 9, 19, 10, 0, 0, 123456)   # 秒精度会截到 10:00:00
    tag_a = resolve_image_build_tag.__globals__["format_image_build_tag"](1, fixed)
    tag_b = resolve_image_build_tag.__globals__["format_image_build_tag"](
        1, fixed.replace(microsecond=999999)
    )
    assert tag_a == tag_b, "同一秒内的两个时刻 → 同一个标签"


def test_cache_hit_reuses_the_stored_tag_verbatim(db_session):
    """**缓存命中 = 把行里的 tag 直接拿出来用**，不是拿行里的时间戳再算一遍。

    这里往行里种一条**与推导结果不同**的人工标签：若返回值是它，就证明确实是"读缓存"，
    而不是"重算恰好相等"。
    """
    from datetime import timedelta

    from ...repositories import image_repo, machine_image_repo
    from ...services.image_tasks import resolve_image_build_tag

    machine = create_machine()
    # 必须晚于模板的 updated_at，否则会被"陈旧行"那道闸门拦下
    stamped = image_repo.get_by_id(1, session=db_session).updated_at + timedelta(seconds=5)
    machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:29990101T000000Z", stamped, session=db_session
    )
    db_session.commit()

    tag, version_at = resolve_image_build_tag(1, machine.id)
    assert tag == "fuxi/image-1:29990101T000000Z", "命中就是读值，不现算"
    assert version_at == stamped


def test_stale_cache_row_is_not_reused(db_session):
    """行比模板旧（`created_at <= images.updated_at`）→ 判过时，改走现造。

    这是"删行"之外的第二道闸：删行没成功、或有人直连改库时，没有它就会永久复用陈旧的
    标签。判过时只会退回现造（结果恒正确），代价是一次多余的重建。
    """
    from datetime import datetime as _dt

    from ...extensions import session_scope
    from ...repositories import image_repo, machine_image_repo
    from ...services.image_tasks import resolve_image_build_tag

    machine = create_machine()
    machine_image_repo.record_dispatch(
        machine.id, 1, "fuxi/image-1:29990101T000000Z", _dt(2020, 1, 1), session=db_session
    )
    db_session.commit()

    tag, version_at = resolve_image_build_tag(1, machine.id)
    assert tag != "fuxi/image-1:29990101T000000Z", "过时行不得复用"
    assert version_at > _dt(2020, 1, 1)


def test_missing_row_and_missing_machine_fabricate_a_fresh_tag(db_session):
    """无行 → 现造；不给 machine_id（拿不到"机器上那一版"）→ 同样现造。"""
    from ...services.image_tasks import resolve_image_build_tag

    machine = create_machine()
    tag, version_at = resolve_image_build_tag(1, machine.id)
    assert tag.startswith("fuxi/image-1:")
    assert tag.endswith(version_at.strftime("%Y%m%dT%H%M%SZ"))

    tag2, _ = resolve_image_build_tag(1, None)
    assert tag2.startswith("fuxi/image-1:")


def test_machine_image_not_written_without_build_segment(db_session, mock_node_send):
    """没有构建段的通路不写派发记录——那次根本没有派发构建。"""
    from ...repositories import machine_image_repo, machine_permission_repo

    owner = create_user(username="owner_mi2")
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    mock_node_send({"success": 1})

    container_tasks.Create_container(
        owner_user_id=owner.id, machine_id=machine.id,
        container=_container_info("mi_direct"),
    )

    assert machine_image_repo.list_by_machine(machine.id, session=db_session) == []


def test_machine_image_is_observational_only(db_session, mock_node_send):
    """**有记录仍照常下发构建段**——这张表不在执行链上。

    守的是它唯一的危险用法：拿"记录已存在"去跳过构建。那会让它的假阳性
    （构建失败也留痕）从"显示不准"升级成"容器起不来"。
    """
    from ...repositories import machine_image_repo, machine_permission_repo

    owner = create_user(username="owner_mi3")
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    sent = mock_node_send({"success": 1})

    build = _image_build_for(db_session, 1)
    for i in range(2):
        container_tasks.Create_container(
            owner_user_id=owner.id, machine_id=machine.id,
            container=_container_info(f"mi_obs_{i}"),
            image_build=build.payload, image_id=1,
            image_version_at=build.version_at, dockerfile_parts=build.dockerfile_parts,
        )

    assert len(machine_image_repo.list_by_machine(machine.id, session=db_session)) == 1
    creates = [c for c in sent if c["url"].endswith("/create_container")]
    assert len(creates) == 2
    assert all("image_build" in c["payload"] for c in creates), "两次都必须下发构建段"


############################################################
# 标签解析的新鲜度预检查（machine_image 提前返回）
############################################################

def test_machine_image_repo_delete_is_scoped_to_template(db_session):
    """删除入口**有且只有一个**，且按模板清（不是按标签、不是按机器）。

    它是"模板变了 → 所有机器上那份制品都不再是这一版"的落地动作。按标签删会退化成
    "拿标签做检索"；按机器删会漏掉别的机器——两者都会留下永不重建的机器。
    """
    from ...repositories import machine_image_repo

    deletes = [n for n in dir(machine_image_repo) if n.startswith("delete") or n.startswith("remove")]
    assert deletes == ["delete_by_image"], deletes

    import inspect

    params = inspect.signature(machine_image_repo.delete_by_image).parameters
    assert list(params)[0] == "image_id"


############################################################
# 恢复预览：内容会变时先给用户看两份内容（design D14）
############################################################

def _deleted_container_behind(db_session, mock_node_send, name):
    """造一个"模板已更新、容器落后"的已删容器，返回 (root, snapshot_id)。"""
    from datetime import datetime

    from ...repositories import machine_permission_repo  # noqa: F401  (import 顺序无关)

    root, machine, container = create_container_graph()
    container.name = name
    container.bind_mount_path = f"/home/{root.username}/containers/{name}_data"
    container.image_id = 1
    container.last_build_at = datetime(2020, 1, 1)      # 远早于模板版本
    _set_recipe(container, _parts(body="RUN echo old"))
    db_session.commit()
    mock_node_send({"success": 1})

    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot_id = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one().id
    return root, snapshot_id


def _set_template_body(db_session, body: str, image_id: int = 1) -> None:
    """给模板填入业务片段——内置模板的 body 是空的，不填就没有"业务片段"这一段可比。"""
    from ...repositories import image_repo

    image_repo.update_image(image_id, dockerfile_body=body, session=db_session)
    db_session.commit()


def test_restore_returns_choice_when_behind(db_session, monkeypatch, mock_node_send):
    """落后时**不恢复**，把两份内容 + 分段差异交回来。

    公布面就在这里：不是靠一个独立查询接口，而是要真的发起恢复、且确实面临二选一时
    才会返回容器留痕。
    """
    _set_template_body(db_session, "RUN echo new\n")
    root, snapshot_id = _deleted_container_behind(db_session, mock_node_send, "preview_me")

    choice = container_tasks.resurrect_container(snapshot_id, operator_user_id=root.id)

    assert choice["requires_choice"] is True
    assert choice["snapshot"]["dockerfile"] == _parts(body="RUN echo old").render()
    assert choice["template"]["dockerfile"].startswith("FROM ubuntu:24.04")
    # 没有平台注入段：它两侧都取当下设置，按构造恒等
    assert {s["name"] for s in choice["sections"]} == {"base_image", "dockerfile_body"}
    assert all(s["changed"] for s in choice["sections"]), "两份内容整体不同，各段都应标为变化"
    assert choice.get("container_id") is None, "二选一时不该恢复"


def test_restore_is_silent_when_nothing_changes(db_session, monkeypatch, mock_node_send):
    """没有二选一时直接恢复，响应里没有 requires_choice —— 没有变化就不该打扰用户。"""
    from ...repositories import image_repo

    root, machine, container = create_container_graph()
    container.name = "quiet_me"
    container.bind_mount_path = f"/home/{root.username}/containers/quiet_me_data"
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    _set_recipe(container, _parts(base_image="ubuntu:24.04"))
    db_session.commit()
    mock_node_send({"success": 1})
    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot_id = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one().id

    result = container_tasks.resurrect_container(snapshot_id, operator_user_id=root.id)

    assert not result.get("requires_choice")
    assert result.get("container_id"), "没有二选一就该真的恢复"


def test_preview_marks_only_the_section_that_changed(db_session, monkeypatch, mock_node_send):
    """分段呈现的意义：哪一段变就只标哪一段——否则用户面对一块无法解释的变化。

    判定是**逐字段比对**（留痕存的就是这两项），不需要从渲染后的文本里反解段边界。
    这条同时是"存输入而不是存渲染结果"的收益锁：改成存整段文本后，只能靠"这段文本还在
    不在对方里"那种启发式去猜，而它在段内容增删时会错判。
    """
    from ...services.container_module.restore import _diff_dockerfile_sections
    from ...services.image_tasks import resolve_image_build

    _set_template_body(db_session, "RUN echo new\n")
    template = resolve_image_build(1).dockerfile_parts
    # 只改基础镜像段，业务片段原样
    moved = DockerfileParts(
        base_image="ubuntu:22.04",
        platform_injection=template.platform_injection,
        dockerfile_body=template.dockerfile_body,
    )

    sections = {s["name"]: s["changed"] for s in _diff_dockerfile_sections(template, moved)}

    assert set(sections) == {"base_image", "dockerfile_body"}
    assert sections["base_image"] is True
    assert sections["dockerfile_body"] is False


def test_sections_never_include_platform_injection(db_session, monkeypatch, mock_node_send):
    """分段里**没有平台注入段**——它两侧都取当下设置，按构造恒等，列出来只是噪音。"""
    from ...services.container_module.restore import _diff_dockerfile_sections
    from ...services.image_tasks import resolve_image_build

    # 给模板填个业务片段：内置模板的 body 是空的，而"两侧都空"的段按设计不列出。
    _set_template_body(db_session, "RUN echo new\n")
    template = resolve_image_build(1).dockerfile_parts
    older = DockerfileParts(
        base_image=template.base_image,
        platform_injection=template.platform_injection,
        dockerfile_body="RUN echo old",
    )

    sections = {s["name"]: s["changed"] for s in _diff_dockerfile_sections(template, older)}

    assert set(sections) == {"base_image", "dockerfile_body"}
    assert sections["base_image"] is False
    assert sections["dockerfile_body"] is True


def test_container_always_renders_the_current_injection(db_session):
    """容器留痕**不存注入**：渲染时无条件取当下的系统设置。

    注入不是用户的内容而是平台设施——容器该带的是现在这一版 sshd 那套，不是它当年那版。
    所以存一份旧的就成了"谁也不需要的历史副本"，而它偏偏还是会被抄进每一行新数据的派生值。
    """
    from ...repositories import image_repo
    from ...services import settings_tasks

    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    container.base_image = "ubuntu:22.04"
    container.dockerfile_body = "RUN echo user-content"
    db_session.commit()

    assert "openssh-server" in utils.container_image_dockerfile(container)

    # 注入改了，容器留痕一个字没动，渲染结果必须立刻跟上
    settings_tasks.set_setting_value(
        settings_tasks.IMAGE_PLATFORM_INJECTION_KEY, "RUN echo INJECTION_V2",
    )
    db_session.expire_all()
    changed = containers_repo.get_by_id(container.id, session=db_session)
    rendered = utils.container_image_dockerfile(changed)

    assert "INJECTION_V2" in rendered
    assert "openssh-server" not in rendered
    # 归属与版本戳不受影响——注入不参与身份与新鲜度判定
    assert changed.image_id == 1
    assert changed.base_image == "ubuntu:22.04"


############################################################
# 挂载不变量：与内容来源无关（design D15）
############################################################

def test_restore_mount_is_identical_across_content_sources(db_session, monkeypatch, mock_node_send):
    """无论走哪条内容来源，下发给 Node 的 restore_mount_path 完全相同。

    镜像只决定容器层的内容；数据层不该因内容来源不同而变化。这条是**既有性质**，
    登记为不变量是因为本次新增了内容来源分支——新分支必须与旧分支在挂载上一致。
    """
    seen = []
    for source in ("snapshot", "template"):
        db_session.expire_all()
        root, snapshot_id = _deleted_container_behind(
            db_session, mock_node_send, f"mount_{source}"
        )
        sent = mock_node_send({"success": 1})
        container_tasks.resurrect_container(
            snapshot_id, operator_user_id=root.id, content_source=source,
        )
        call = next(c for c in sent if c["url"].endswith("/create_container"))
        seen.append((call["payload"]["restore_mount_path"], call["payload"]["image_build"] is not None))
        db_session.expire_all()

    assert seen[0][0].endswith("mount_snapshot_data")
    assert seen[1][0].endswith("mount_template_data")
    # 两条路径都下发了构建段（都做了重建），差别只在内容
    assert all(built for _, built in seen)


def test_restore_mount_follows_snapshot_not_new_name(db_session, monkeypatch, mock_node_send):
    """改名不改变数据位置：挂载路径取自快照，不依据新名字推导。

    若按新名字推导，改名恢复会指向一个空目录——表现为"恢复成功但数据全丢"。
    """
    from ...repositories import image_repo

    root, machine, container = create_container_graph()
    original_name = "name_owner"
    container.name = original_name
    container.bind_mount_path = f"/home/{root.username}/containers/{original_name}_data"
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    db_session.commit()
    mock_node_send({"success": 1})
    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot_id = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one().id

    # 占住原名，逼恢复改名
    create_container(machine=machine, name=original_name, image_id=1)
    sent = mock_node_send({"success": 1})

    container_tasks.resurrect_container(snapshot_id, operator_user_id=root.id)

    call = next(c for c in sent if c["url"].endswith("/create_container"))
    assert call["payload"]["config"]["name"] != original_name, "应当被改名"
    assert call["payload"]["restore_mount_path"].endswith(f"{original_name}_data"), \
        "挂载路径必须仍是原路径"


############################################################
# 外键完整性：悬空归属写不进去（design D2）
############################################################

def test_dangling_image_id_cannot_be_written(db_session):
    """外键让"归属指向一个不存在的模板"在数据库层不可能出现。"""
    from sqlalchemy.exc import IntegrityError
    import pytest

    machine = create_machine()
    with pytest.raises(IntegrityError):
        containers_repo.create_container(
            name="dangling", machine_id=machine.id,
            memory_gb=1, shared_gb=0, gpu_number=0, cpu_number=1, port=25000,
            image_id=999999, session=db_session,
        )
    db_session.rollback()


def test_referenced_template_row_cannot_be_physically_deleted(db_session):
    """被引用的模板行删不掉——物理删除这条路在数据库层就被封死。

    因此"移除模板"只能是停用（design D2 第三版）：归属外键永不触发，
    "构建自哪个模板"这个事实不丢。
    """
    from sqlalchemy.exc import IntegrityError
    import pytest

    machine = create_machine()
    create_container(machine=machine, image_id=1)

    from ...repositories import image_repo
    from ...models.image import Image as ImageModel

    template = image_repo.get_by_id(1, session=db_session)
    with pytest.raises(IntegrityError):
        db_session.delete(template)
        db_session.flush()
    db_session.rollback()


############################################################
# 配方的用途边界：只进展示与恢复内容来源（design D7）
############################################################

def test_recipe_never_decides_identity_or_staleness(db_session):
    """改配方内容不影响归属判定，也不影响落后判定。

    配方有且只有两个用途——展示运行基底、作为精确还原的内容来源。它 MUST NOT 参与
    身份与新鲜度的判断：归属只看 image_id，落后只看 last_build_at。
    """
    from ...repositories import image_repo
    from ...services.container_module.utils import is_version_behind

    machine = create_machine()
    container = create_container(machine=machine, image_id=1)
    version_at = image_repo.get_by_id(1, session=db_session).updated_at
    container.last_build_at = version_at
    _set_recipe(container, _parts(base_image="ubuntu:24.04"))
    db_session.commit()

    before_behind = is_version_behind(container.last_build_at, version_at)

    # 把配方改成完全不同的内容
    _set_recipe(container, _parts(base_image="something-else:1.0", body="RUN rm -rf /"))
    db_session.commit()
    db_session.expire_all()
    reloaded = containers_repo.get_by_id(container.id, session=db_session)

    assert reloaded.image_id == 1, "配方内容不参与身份判定"
    assert is_version_behind(reloaded.last_build_at, version_at) is before_behind, \
        "配方内容不参与落后判定"


############################################################
# 走 HTTP 端点：schema 层会静默丢字段，服务层测试抓不到
############################################################

def test_resurrect_api_returns_choice_without_restoring(client, monkeypatch, db_session, mock_node_send):
    """不带 content_source 调恢复：后端**不恢复**，把两份内容交回来。

    这是"公布面只有一处"的落点 —— 容器留痕随恢复请求的响应出去，而不是靠一个
    独立的查询接口。
    """
    _auth(monkeypatch)
    root, snapshot_id, sent = _deleted_behind_container(db_session, mock_node_send, "api_choice")

    resp = client.post("/api/containers/resurrect_container", json={"deleted_id": snapshot_id})

    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_choice"] is True
    assert body["snapshot"]["dockerfile"] == _parts().render()
    assert body["template"]["dockerfile"].startswith("FROM ubuntu:24.04")
    assert {s["name"] for s in body["sections"]}
    assert body.get("container_id") is None, "二选一时不该恢复"
    assert not [c for c in sent if c["url"].endswith("/create_container")], "不该发创建请求"


def test_resurrect_api_honours_content_source(client, monkeypatch, db_session, mock_node_send):
    """带上 content_source=template 才用当前模板。

    ⚠ 这条曾经失败过：`ResurrectContainerRequest` 漏声明 content_source，而基底模型是
    `extra="ignore"` → 字段被**静默丢弃** → 传了 template 也永远走快照，且不报错。
    所以这个用例必须走 HTTP 端点，服务层是抓不到的。
    """
    _auth(monkeypatch)
    root, snapshot_id, sent = _deleted_behind_container(db_session, mock_node_send, "api_template")

    resp = client.post(
        "/api/containers/resurrect_container",
        json={"deleted_id": snapshot_id, "content_source": "template"},
    )

    assert resp.status_code == 200
    assert resp.json().get("requires_choice") in (None, False)
    create_call = next(c for c in sent if c["url"].endswith("/create_container"))
    assert create_call["payload"]["image_build"]["dockerfile_text"].startswith("FROM ubuntu:24.04")


def test_resurrect_api_rejects_unknown_content_source(client, monkeypatch, db_session):
    _auth(monkeypatch)

    resp = client.post(
        "/api/containers/resurrect_container",
        json={"deleted_id": 1, "content_source": "nonsense"},
    )

    assert resp.status_code == 400
    assert resp.json()["error_reason"] == "invalid_payload"
