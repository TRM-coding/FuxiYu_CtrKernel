"""镜像构建缓存的换代口径（Q12 / Q13 回归）。

背景：`machine_image` 是"某机器 × 某模板"的构建缓存。改配方（模板内容或平台注入）后
必须换一代标签，否则 Node 的 `images.get(tag)` 会命中旧制品、跑旧内容；而换代只换值
（tag / 版本戳 / 配方指纹），**不换身份**（行 id 与 `(machine_id, image_id)` 不变），
容器归属与授权关系因此不受影响。

本文件锁住五组性质：
1. 平台注入变化会改变缓存版本，且真正下发的 Dockerfile 文本与标签同源；
2. 模板改配方与平台注入改配方都**就地更换同一行**；
3. 未修改配方稳定复用（含改名/改描述这类不动配方的编辑）；
4. 秒级碰撞被正面处理：同秒改配方也拿不到旧标签；
5. 旧库没有指纹列时安全收敛（判旧一次、补齐后恢复命中），构建失败不抹掉派发留痕，
   恢复真正发送的配方决定其版本。
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...repositories import (
    containers_repo, machine_image_repo, machine_permission_repo, usercontainer_repo, userimage_repo,
)
from ...services import container_tasks, image_tasks, settings_tasks
from ...services.image_tasks import DockerfileParts
from ...utils.Container import Container_info
from ..factories import create_container_graph, create_machine, create_user


def _parts(base_image: str = "ubuntu:24.04", body: str | None = None) -> DockerfileParts:
    """造一份配方：平台注入取当下设置（与容器留痕的读取口径一致）。"""
    return DockerfileParts(
        base_image=base_image,
        platform_injection=settings_tasks.get_image_platform_injection_content() or "",
        dockerfile_body=body,
    )


def _container_info(name: str) -> Container_info:
    return Container_info(
        gpu_list=[], cpu_number=1, memory=1, shared_memory=0, name=name, image="ignored",
    )


def _dispatch(owner, machine, name: str, build) -> None:
    """按一份构建留痕派发一次创建（Node 走替身）。"""
    container_tasks.Create_container(
        owner_user_id=owner.id, machine_id=machine.id,
        container=_container_info(name),
        image_build=build.payload, image_id=build.image_id,
        image_version_at=build.version_at, dockerfile_parts=build.dockerfile_parts,
    )


@pytest.fixture()
def node_success(monkeypatch):
    """Node 替身：所有出站调用一律成功，并记录下发内容。"""
    calls: list[dict] = []

    def _send(url, payload, timeout=5.0):
        calls.append({"url": url, "payload": payload, "timeout": timeout})
        return {"success": 1}

    monkeypatch.setattr("FuxiYu_CtrKernel.services.container_module.node_comms.send", _send)
    return calls


def _owner_with_machine(db_session):
    owner = create_user()
    machine = create_machine(max_shared_gb=8, max_memory_gb=64)
    machine_permission_repo.add_permission(machine.id, owner.id, session=db_session)
    db_session.commit()
    return owner, machine


def test_platform_injection_change_changes_cache_version(db_session, node_success):
    """平台注入是最终配方的组成：它一变，缓存版本必须换代，且下发文本跟着变。"""
    owner, machine = _owner_with_machine(db_session)

    first = image_tasks.resolve_image_build(1, machine.id)
    _dispatch(owner, machine, "inj_first", first)
    db_session.expire_all()
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    row_id, old_tag, old_stamp = row.id, row.image_tag, row.created_at

    settings_tasks.set_setting_value(
        settings_tasks.IMAGE_PLATFORM_INJECTION_KEY, "USER root\nRUN echo INJECTION_V2\nEXPOSE 22"
    )
    db_session.expire_all()

    second = image_tasks.resolve_image_build(1, machine.id)
    assert "INJECTION_V2" in second.payload["dockerfile_text"], "下发文本必须带新注入"
    assert second.payload["image_tag"] != old_tag, "注入变了，缓存版本必须换代"
    assert second.version_at > old_stamp, "新版本戳严格晚于上一版"

    _dispatch(owner, machine, "inj_second", second)
    db_session.expire_all()
    replaced = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    assert replaced.id == row_id, "换代就地更换同一行，身份不变"
    assert replaced.image_tag == second.payload["image_tag"]
    assert replaced.created_at == second.version_at
    assert replaced.recipe_fingerprint == image_tasks.recipe_fingerprint(
        second.dockerfile_parts
    )

    # 内容没再变 → 后续派发稳定复用，不再换代
    third = image_tasks.resolve_image_build(1, machine.id)
    assert third.payload["image_tag"] == second.payload["image_tag"]
    assert third.version_at == second.version_at


def test_template_recipe_change_and_metadata_edit_converge_on_the_same_row(db_session, node_success):
    """模板改配方换代、只改元数据仍命中，两种情形都落在同一行上。"""
    owner, machine = _owner_with_machine(db_session)
    userimage_repo.grant_image(owner.id, 1, session=db_session)
    db_session.commit()

    first = image_tasks.resolve_image_build(1, machine.id)
    _dispatch(owner, machine, "conv_first", first)
    db_session.expire_all()
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    row_id, first_tag = row.id, row.image_tag
    old_id = containers_repo.get_id_by_name_machine("conv_first", machine.id, session=db_session)
    old_container = containers_repo.get_by_id(old_id, session=db_session)
    preserved = (old_container.machine_id, old_container.image_id, old_container.last_build_at,
                 old_container.base_image, old_container.dockerfile_body, old_container.entrypoint)
    bindings = usercontainer_repo.get_container_bindings(old_id, session=db_session)

    # 不动配方 → 命中
    assert image_tasks.Update_image(image_id=1, description="只改描述") is True
    db_session.expire_all()
    cached = image_tasks.resolve_image_build(1, machine.id)
    assert cached.payload["image_tag"] == first_tag, "未修改配方必须缓存命中"

    # 改配方 → 换代
    assert image_tasks.Update_image(image_id=1, dockerfile_body="RUN echo new") is True
    db_session.expire_all()
    changed = image_tasks.resolve_image_build(1, machine.id)
    assert changed.payload["image_tag"] != first_tag
    _dispatch(owner, machine, "conv_second", changed)
    db_session.expire_all()

    rows = machine_image_repo.list_by_machine(machine.id, session=db_session)
    assert len(rows) == 1 and rows[0].id == row_id, "始终是同一行"
    assert rows[0].image_tag == changed.payload["image_tag"]
    old_container = containers_repo.get_by_id(old_id, session=db_session)
    assert (old_container.machine_id, old_container.image_id, old_container.last_build_at,
            old_container.base_image, old_container.dockerfile_body, old_container.entrypoint) == preserved
    assert image_tasks.format_image_build_tag(old_container.image_id, old_container.last_build_at) == first_tag
    assert usercontainer_repo.get_container_bindings(old_id, session=db_session) == bindings
    assert 1 in userimage_repo.list_image_ids_by_user(owner.id, session=db_session)


def test_same_second_recipe_change_never_reuses_the_old_tag(db_session, node_success):
    """同秒改配方也拿不到旧标签：新版本戳严格晚于既有那一版。"""
    owner, machine = _owner_with_machine(db_session)

    first = image_tasks.resolve_image_build(1, machine.id)
    _dispatch(owner, machine, "sec_first", first)
    db_session.expire_all()

    # 把这一行钉在"未来两秒"上，模拟改配方与下次派发落在同一秒（同秒时只递进一秒）
    future = datetime.utcnow().replace(microsecond=0) + timedelta(seconds=2)
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    row.created_at = future
    row.image_tag = image_tasks.format_image_build_tag(1, future)
    db_session.commit()
    db_session.expire_all()

    settings_tasks.set_setting_value(
        settings_tasks.IMAGE_PLATFORM_INJECTION_KEY, "USER root\nRUN echo SAME_SECOND\nEXPOSE 22"
    )
    db_session.expire_all()

    second = image_tasks.resolve_image_build(1, machine.id)
    superseding = future + timedelta(seconds=1)
    assert second.version_at == superseding
    assert second.payload["image_tag"] == image_tasks.format_image_build_tag(1, superseding)
    assert second.payload["image_tag"] != image_tasks.format_image_build_tag(1, future)


def test_legacy_row_without_fingerprint_converges_once(db_session, node_success):
    """旧库没有指纹列：判旧一次、就地补齐，之后恢复命中（安全收敛）。"""
    owner, machine = _owner_with_machine(db_session)

    first = image_tasks.resolve_image_build(1, machine.id)
    _dispatch(owner, machine, "legacy_first", first)
    db_session.expire_all()
    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    row_id, first_tag = row.id, row.image_tag
    row.recipe_fingerprint = None          # 模拟旧库行
    db_session.commit()
    db_session.expire_all()

    converged = image_tasks.resolve_image_build(1, machine.id)
    assert converged.payload["image_tag"] != first_tag, "无指纹的行不得复用"
    _dispatch(owner, machine, "legacy_second", converged)
    db_session.expire_all()

    replaced = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    assert replaced.id == row_id and replaced.recipe_fingerprint, "就地补齐指纹"
    again = image_tasks.resolve_image_build(1, machine.id)
    assert again.payload["image_tag"] == replaced.image_tag, "补齐后恢复命中"


def test_failed_build_keeps_the_dispatch_row(db_session, node_success):
    """构建失败也留下派发记录：它是"Ctrl 请求过"的账，不是"制品建成过"的凭据。"""
    owner, machine = _owner_with_machine(db_session)

    build = image_tasks.resolve_image_build(1, machine.id)
    _dispatch(owner, machine, "fail_first", build)

    row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    assert row is not None and row.image_tag == build.payload["image_tag"]
    # 下一次派发仍照发构建段（Node 自己按 images.get(tag) 判定是否重建）
    assert build.payload["dockerfile_text"]


def test_restore_sends_the_recipe_it_actually_dispatched(db_session, node_success):
    """恢复真正发送的配方决定其版本：注入变过 → 恢复的标签必须换，且与文本同源。"""
    root, machine, container = create_container_graph()
    container.name = "snap_inj"
    container.bind_mount_path = f"/home/{root.username}/containers/snap_inj_data"
    container.image_id = 1
    container.base_image = "ubuntu:24.04"
    container.dockerfile_body = ""
    old_stamp = datetime(2020, 1, 1)
    container.last_build_at = old_stamp
    db_session.commit()

    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot_id = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one().id

    settings_tasks.set_setting_value(
        settings_tasks.IMAGE_PLATFORM_INJECTION_KEY, "USER root\nRUN echo RESTORE_V2\nEXPOSE 22"
    )
    db_session.expire_all()

    container_tasks.resurrect_container(snapshot_id, operator_user_id=root.id)

    create_call = next(c for c in node_success if c["url"].endswith("/create_container"))
    image_build = create_call["payload"]["image_build"]
    assert "RESTORE_V2" in image_build["dockerfile_text"], "恢复发送的是当下注入的配方"
    assert create_call["payload"]["config"]["image"] == image_build["image_tag"]
    # 版本戳与实际下发的标签同源，且不再是那个 2020 年的旧标签
    assert image_build["image_tag"] != image_tasks.format_image_build_tag(1, old_stamp)

    db_session.expire_all()
    restored = containers_repo.get_by_id(container.id, session=db_session, include_invalid=True)
    assert image_tasks.format_image_build_tag(restored.image_id, restored.last_build_at) \
        == image_build["image_tag"], "容器留痕不得指向并未实际派发的标签"


def test_snapshot_recipe_is_not_mistaken_for_the_template_cache(db_session, node_success):
    """快照配方（旧业务正文 + 当下注入）指纹不同于当前模板 → 不得复用模板那一版。"""
    owner, machine = _owner_with_machine(db_session)

    template_build = image_tasks.resolve_image_build(1, machine.id)
    _dispatch(owner, machine, "snap_fp_tpl", template_build)
    db_session.expire_all()
    template_row = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    template_tag = template_row.image_tag
    template_fp = template_row.recipe_fingerprint

    old_parts = _parts(base_image="ubuntu:24.04", body="RUN echo old-body")
    tag, version_at = image_tasks.resolve_build_tag_for_recipe(1, machine.id, old_parts)

    assert tag != template_tag, "快照配方必须有自己的版本，不能冒用当前模板缓存"
    db_session.expire_all()
    after = machine_image_repo.get_by_machine_image(machine.id, 1, session=db_session)
    assert after.image_tag == tag and after.recipe_fingerprint == image_tasks.recipe_fingerprint(old_parts)
    assert after.recipe_fingerprint != template_fp

    # 下一次按当前模板解析 → 又识别出差异，正确换代（不会停在快照那一版）
    again = image_tasks.resolve_image_build(1, machine.id)
    assert again.payload["image_tag"] != tag


def test_resolve_refuses_without_recipe_or_machine(db_session):
    """没有配方或没有机器上下文时返回 `(None, None)`，绝不编造可运行标签。"""
    parts = _parts()
    assert image_tasks.resolve_build_tag_for_recipe(1, 1, None) == (None, None)
    assert image_tasks.resolve_build_tag_for_recipe(1, None, parts) == (None, None)
    assert image_tasks.resolve_build_tag_for_recipe(None, 1, parts) == (None, None)


def test_resolve_fails_safe_when_the_cache_is_unreadable(db_session, monkeypatch):
    """缓存读不出来时直接抛出，不现造一个可能与旧制品同名的标签。"""
    machine = create_machine()

    def _boom(*args, **kwargs):
        raise RuntimeError("cache unavailable")

    monkeypatch.setattr(machine_image_repo, "get_by_machine_image", _boom)
    with pytest.raises(RuntimeError, match="cache unavailable"):
        image_tasks.resolve_image_build_tag(1, machine.id)


def test_first_row_race_supersedes_the_winner_version(db_session, monkeypatch):
    """并发首次解析：读时还没有行 → 插入时撞唯一约束 → 重读并按对方版本再推进一秒。

    这里用"首次读返回空"模拟并发窗口；`record_dispatch` 发现行其实已存在时会保留它、
    返回不匹配的行，解析侧据此重来一轮，而不是把算出来的标签当已持久化的值返回。
    """
    machine = create_machine()
    other_stamp = datetime.utcnow().replace(microsecond=0) + timedelta(seconds=5)
    machine_image_repo.record_dispatch(
        machine.id, 1, image_tasks.format_image_build_tag(1, other_stamp), other_stamp,
        "other-recipe", session=db_session,
    )
    db_session.commit()

    real_get = machine_image_repo.get_by_machine_image
    calls = {"n": 0}

    def _blind_first(*args, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_get(*args, **kwargs)

    monkeypatch.setattr(machine_image_repo, "get_by_machine_image", _blind_first)

    tag, version_at = image_tasks.resolve_image_build_tag(1, machine.id)

    assert version_at == other_stamp + timedelta(seconds=1), "必须晚于并发方已登记的版本"
    assert tag == image_tasks.format_image_build_tag(1, other_stamp + timedelta(seconds=1))
    persisted = real_get(machine.id, 1, session=db_session)
    assert persisted.image_tag == tag and persisted.created_at == version_at


def test_read_only_resolution_never_writes_the_cache(db_session):
    """只取 parts / 无机器上下文的路径不登记缓存——展示读取与实际派发必须分开。"""
    machine = create_machine()
    assert machine_image_repo.list_by_machine(machine.id, session=db_session) == []

    image_tasks.resolve_image_build(1)              # 展示/拼装：不传 machine_id
    image_tasks.resolve_image_build_tag(1, None)    # 首次构建口径：无机器上下文
    db_session.expire_all()

    assert machine_image_repo.list_by_machine(machine.id, session=db_session) == []


def test_behind_uses_content_not_timestamps(db_session):
    """落后判据是**模板侧配方内容**：时间戳超前仍识别差异，元数据编辑不误判。"""
    from ...services.container_module.restore import _RestoreTarget, _is_behind

    def _target(version_at, base):
        return _RestoreTarget(
            snapshot={}, container_id=1, machine_id=1, mount_path="/tmp/m",
            mount_cleanup_id=None, removed_at=None, image_id=1,
            image_version_at=version_at,
            dockerfile_parts=None if base is None else _parts(base_image=base),
        )

    template_parts = _parts(base_image="ubuntu:24.04")

    # 版本戳远在未来（纯时间戳口径会说"不落后"），但 FROM 与模板不同 → 仍然落后
    assert _is_behind(_target(datetime(2999, 1, 1), "ubuntu:22.04"), template_parts, None) is True
    # 元数据编辑：内容一致，旧版本戳也不该被判落后
    assert _is_behind(
        _target(datetime(2020, 1, 1), "ubuntu:24.04"), template_parts, datetime(2026, 1, 1)
    ) is False
    # 无留痕的存量容器退回时间戳口径
    assert _is_behind(
        _target(datetime(2020, 1, 1), None), template_parts, datetime(2026, 1, 1)
    ) is True
