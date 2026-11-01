"""容器启动命令（entrypoint）的行为锁。

**它是构建段，不是运行期参数**（2026-09 决策）。Ctrl 把它渲染成最终 Dockerfile 的
**最后一行** `ENTRYPOINT …`，因此它决定镜像内容，Node 侧一个字节都不插手。

为什么这么做（而不是运行期传 command）：Docker 的 command **不覆盖**镜像自带的
ENTRYPOINT，镜像入口会把那条命令当参数吃掉——实测：镜像入口为 /bin/echo 时容器打印
`FROM-ENTRYPOINT tail -f /dev/null`。而 base_image 是自由字符串、没有白名单，任何人填一个
带 ENTRYPOINT 的镜像都会踩到，失败现象还是无从归因的 `sshd gate failed`。

写进 Dockerfile 之后，两件事全靠 Docker 自己的规则生效、不需要运行期做任何动作：
1. **后写的 ENTRYPOINT 覆盖先写的** —— 用户在业务片段里自己写了也不生效；
2. **shell 形式免疫一切** —— 实测：镜像残留的 CMD 被忽略，`docker run` 传的命令也被忽略。

本文件锁住六组性质：
1. 模板侧：写读一致；空串 = 清除，None = 不提供，两者语义不同；
2. 空值归一：NULL / "" / 纯空白一律折成 None，不分叉成两种"空"；
3. 渲染：ENTRYPOINT 恒为最后一行，留空即平台默认；
4. 建容器：容器行的启动命令留痕取自**配方**，wire 上已无此键；
5. 恢复：读容器自己那份配方，不回落模板；
6. 它是配方的一段：改它会改 Dockerfile 文本，容器行留痕随之变化。
"""

import pytest
from sqlalchemy import select

from ...extensions import session_scope
from ...models.containers import Container
from ...models.image import Image
from ...repositories import containers_repo, image_repo, machine_permission_repo
from ...services import container_tasks, image_tasks
from ...services.container_module.utils import container_dockerfile_parts
from ...services.image_tasks import (
    PLATFORM_DEFAULT_ENTRYPOINT,
    DockerfileParts,
    render_final_dockerfile,
    resolve_image_build,
)
from ...utils.Container import Container_info
from ..factories import create_container_graph, create_machine, create_user

pytestmark = pytest.mark.usefixtures("ensure_auth_users")

TPL_TAG = "fuxi/image-1:20260825T090016Z"


def _container_info(name: str) -> Container_info:
    return Container_info(gpu_list=[], cpu_number=1, memory=1, shared_memory=0, name=name, image=TPL_TAG)


def _stored_entrypoint(image_id: int):
    """直读库里的原始值——用来区分 NULL 与空串，出参的归一化会掩盖这个差别。"""
    with session_scope(commit=False) as session:
        return session.get(Image, image_id).entrypoint


def _set_stored_entrypoint(image_id: int, value) -> None:
    with session_scope() as session:
        image_repo.get_by_id(image_id, session=session).entrypoint = value


def _create_template(name: str, **kw) -> int:
    return image_tasks.Create_image(name=name, base_image="ubuntu:24.04", **kw)


def _row_named(db_session, name: str) -> Container:
    return db_session.scalars(select(Container).where(Container.name == name)).first()


############################################################
# ① 模板侧：写读一致 + 空串即清除
############################################################

def test_template_entrypoint_roundtrip(db_session):
    image_id = _create_template("ep-tpl", entrypoint="/app/boot.sh --port 8080")
    assert image_tasks.Get_image_detail(image_id)["entrypoint"] == "/app/boot.sh --port 8080"

    assert image_tasks.Update_image(image_id=image_id, entrypoint="/app/other.sh") is True
    assert image_tasks.Get_image_detail(image_id)["entrypoint"] == "/app/other.sh"

    # 空串 = 清除（回归平台默认）；None = 不提供。两者语义不同，绝不能混。
    assert image_tasks.Update_image(image_id=image_id, entrypoint="") is True
    assert _stored_entrypoint(image_id) is None, "清除写的是 NULL，不是空串"
    assert image_tasks.Get_image_detail(image_id)["entrypoint"] is None

    assert image_tasks.Update_image(image_id=image_id, entrypoint=None) is True
    assert _stored_entrypoint(image_id) is None


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_template_entrypoint_create_normalizes_blank_to_null(db_session, blank):
    image_id = _create_template(f"ep-blank-{len(blank)}-{ord(blank[0]) if blank else 0}", entrypoint=blank)
    assert _stored_entrypoint(image_id) is None


############################################################
# ② 空值归一：三种"空"读出等价
############################################################

@pytest.mark.parametrize("stored", [None, "", "   "])
def test_template_entrypoint_null_and_blank_read_as_none(db_session, stored):
    """NULL / 空串 / 纯空白 → 一律折成 None。

    库里三种形态都可能存在（旧行、直连改库、API 变体），读侧不能分叉成"两种空"。
    """
    image_id = _create_template(f"ep-norm-{stored!r}")
    _set_stored_entrypoint(image_id, stored)

    assert image_tasks.Get_image_detail(image_id)["entrypoint"] is None
    assert resolve_image_build(image_id).dockerfile_parts.entrypoint is None


############################################################
# ③ 渲染：ENTRYPOINT 恒为最后一行
############################################################

def test_render_puts_entrypoint_last():
    text = render_final_dockerfile(
        base_image="ubuntu:24.04", platform_injection="RUN echo inject",
        dockerfile_body="RUN echo body", entrypoint="/app/run.sh --port 1",
    )
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    assert lines[0] == "FROM ubuntu:24.04"
    assert lines[-1] == "ENTRYPOINT /app/run.sh --port 1", "必须在最后：后写的才覆盖先写的"
    assert "RUN echo body" in text


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_render_falls_back_to_platform_default(blank):
    """留空 → 平台默认。默认值兜在渲染函数里，因此**渲染出来的 Dockerfile 必定带 ENTRYPOINT**。"""
    text = render_final_dockerfile(
        base_image="ubuntu:24.04", platform_injection="", dockerfile_body=None, entrypoint=blank,
    )
    assert text.strip().endswith(f"ENTRYPOINT {PLATFORM_DEFAULT_ENTRYPOINT}")


def test_render_uses_shell_form_not_exec_form():
    """shell 形式（无方括号）是刻意的：它是唯一能挡住运行期传参的形态。

    exec 形式下镜像残留的 CMD 会变成入口的参数；shell 形式两者都免疫（实测）。
    """
    text = render_final_dockerfile(
        base_image="ubuntu:24.04", platform_injection="", dockerfile_body=None,
        entrypoint="/app/run.sh",
    )
    assert "ENTRYPOINT /app/run.sh" in text
    assert 'ENTRYPOINT ["' not in text


def test_platform_owns_the_entrypoint_line_over_user_body():
    """用户在业务片段里自己写了 ENTRYPOINT 也不生效——平台那行在后面。

    Docker 规则：同一 stage 里只有最后一条 ENTRYPOINT 生效（其余会有一条无害的
    MultipleInstructionsDisallowed 警告）。
    """
    text = render_final_dockerfile(
        base_image="ubuntu:24.04", platform_injection="",
        dockerfile_body='ENTRYPOINT ["/user/wrote/this"]', entrypoint="/app/platform.sh",
    )
    assert text.strip().splitlines()[-1] == "ENTRYPOINT /app/platform.sh"


############################################################
# ④ 建容器：留痕取自配方，wire 上没有这个键
############################################################

def test_create_container_payload_has_no_entrypoint_key(db_session, mock_node_send):
    """wire 契约：`config` 里不再有 entrypoint——跑什么由镜像自己带。"""
    from ...services.container_module.creation import _build_create_payload

    payload = _build_create_payload(_container_info("ep_wire"), "admin")
    assert "entrypoint" not in payload["config"]


def test_container_row_records_entrypoint_from_recipe(db_session, mock_node_send):
    """容器行的启动命令留痕 = **本次采用的配方**里那一段（与 FROM、业务片段同源）。"""
    owner = create_user(username="ep_row_owner")
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    _set_stored_entrypoint(1, "/app/from-recipe.sh")
    db_session.commit()
    mock_node_send({"success": 1})

    build = resolve_image_build(1)
    container_tasks.Create_container(
        owner_user_id=owner.id, machine_id=machine.id,
        container=_container_info("ep_row_1"),
        image_build=build.payload, image_id=1,
        image_version_at=build.version_at, dockerfile_parts=build.dockerfile_parts,
    )
    assert _row_named(db_session, "ep_row_1").entrypoint == "/app/from-recipe.sh"

    # 模板没设启动命令 → 配方里是 None → 行上是 NULL（平台默认不冻进数据）
    _set_stored_entrypoint(1, None)
    build2 = resolve_image_build(1)
    container_tasks.Create_container(
        owner_user_id=owner.id, machine_id=machine.id,
        container=_container_info("ep_row_2"),
        image_build=build2.payload, image_id=1,
        image_version_at=build2.version_at, dockerfile_parts=build2.dockerfile_parts,
    )
    assert _row_named(db_session, "ep_row_2").entrypoint is None


def test_container_image_dockerfile_shows_the_entrypoint_line(db_session):
    """展示出口渲染的是容器自己的配方，因此会带出那一行 ENTRYPOINT。"""
    from ...services.container_module.utils import container_image_dockerfile
    from ...extensions import session_scope as ss

    _root, _machine, container = create_container_graph()
    with ss() as session:
        rec = containers_repo.get_by_id(container.id, session=session, include_invalid=True)
        rec.base_image = "ubuntu:24.04"
        rec.dockerfile_body = "RUN echo body"
        rec.entrypoint = "/app/shown.sh"
    db_session.expire_all()

    with ss(commit=False) as session:
        rec = containers_repo.get_by_id(container.id, session=session, include_invalid=True)
        rendered = container_image_dockerfile(rec)
    assert rendered.strip().endswith("ENTRYPOINT /app/shown.sh")


############################################################
# ⑤ 恢复：读容器自己那份配方
############################################################

def _restore_target_for(container, machine, **overrides):
    from ...services.container_module import restore as restore_mod

    kwargs = dict(
        snapshot={"container_id": container.id, "container_name": container.name},
        container_id=container.id,
        machine_id=machine.id,
        mount_path=container.bind_mount_path,
        mount_cleanup_id=None,
        removed_at=None,
        image_id=1,
        image_version_at=None,
        dockerfile_parts=None,
    )
    kwargs.update(overrides)
    return restore_mod._RestoreTarget(**kwargs)


def test_restore_renders_the_containers_own_entrypoint(db_session):
    """恢复发出的构建段（dockerfile_text）以**容器自己的**启动命令收尾。

    启动命令是配方的一段，随 `dockerfile_parts` 一起走；`_RestoreTarget` 不另存一份——
    两份拷贝就是两个可漂移的来源，正是本仓库一路在清理的东西。
    """
    from ...extensions import session_scope as ss
    from ...services.container_module import restore as restore_mod

    _root, machine, container = create_container_graph()
    with ss() as session:
        rec = containers_repo.get_by_id(container.id, session=session, include_invalid=True)
        rec.base_image = "ubuntu:24.04"
        rec.entrypoint = "/app/its-own.sh"
    # 模板之后被改成别的
    _set_stored_entrypoint(1, "/app/template-newer.sh")

    with ss(commit=False) as session:
        rec = containers_repo.get_by_id(container.id, session=session, include_invalid=True)
        parts = container_dockerfile_parts(rec)

    target = _restore_target_for(container, machine, dockerfile_parts=parts)
    resolved = restore_mod._restore_from_snapshot(target)

    assert resolved.image_build["dockerfile_text"].strip().endswith("ENTRYPOINT /app/its-own.sh")
    assert resolve_image_build(1).dockerfile_parts.entrypoint == "/app/template-newer.sh", \
        "前置：模板确实已经不同"


def test_container_recipe_reader_returns_its_own_entrypoint(db_session):
    """从容器行读配方时，entrypoint 必须一并读回——否则"这份配方"拼出来的是别的镜像。"""
    from ...extensions import session_scope as ss

    _root, _machine, container = create_container_graph()
    with ss() as session:
        rec = containers_repo.get_by_id(container.id, session=session, include_invalid=True)
        rec.base_image = "ubuntu:24.04"
        rec.entrypoint = "/app/mine.sh"

    with ss(commit=False) as session:
        rec = containers_repo.get_by_id(container.id, session=session, include_invalid=True)
        parts = container_dockerfile_parts(rec)
    assert parts.entrypoint == "/app/mine.sh"
    assert parts.render().strip().endswith("ENTRYPOINT /app/mine.sh")


def test_container_recipe_reader_normalizes_blank(db_session):
    """容器行上的 "" 与 NULL 都折成 None（= 渲染时兜平台默认）。"""
    from ...extensions import session_scope as ss

    _root, _machine, container = create_container_graph()
    with ss() as session:
        rec = containers_repo.get_by_id(container.id, session=session, include_invalid=True)
        rec.base_image = "ubuntu:24.04"
        rec.entrypoint = "   "

    with ss(commit=False) as session:
        rec = containers_repo.get_by_id(container.id, session=session, include_invalid=True)
        parts = container_dockerfile_parts(rec)
    assert parts.entrypoint is None
    assert parts.render().strip().endswith(f"ENTRYPOINT {PLATFORM_DEFAULT_ENTRYPOINT}")


############################################################
# ⑥ 它是配方的一段：改它就改 Dockerfile 文本
############################################################

def test_entrypoint_changes_the_dockerfile_text(db_session):
    """与"运行期参数"的区别就在这：改它会改**构建输入**。"""
    image_id = _create_template("ep-build-input")
    before = resolve_image_build(image_id)

    _set_stored_entrypoint(image_id, "/app/x.sh")
    after = resolve_image_build(image_id)

    assert after.payload["dockerfile_text"] != before.payload["dockerfile_text"]
    assert after.payload["dockerfile_text"].strip().endswith("ENTRYPOINT /app/x.sh")
    # tag 只随模板版本戳变，不随配方内容变——本条只改列、不碰 updated_at
    assert after.payload["image_tag"] == before.payload["image_tag"]
