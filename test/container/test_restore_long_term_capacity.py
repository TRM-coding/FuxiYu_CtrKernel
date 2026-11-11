"""恢复长期标记必须与普通 set_long_term 纳入同一数量上限校验。

本文件锁定：
1. 恢复前的配额预检发生在 Create_container **之前**——超限时 Node 未被调用、容器仍是软删、
   快照与挂载清理记录都未被消费（不产生半恢复，也不静默丢标记）；
2. 校验口径与门户一致：按 root owner 计，只认 root 不认协作者，失败原因带 used/limit；
3. 已存在标记幂等、快照无长期标记时不校验也不补标记；
4. 走真实 HTTP 端点时错误 reason / status 与调用方看到的链条一致。
"""

import pytest
from sqlalchemy import select

from ...api import deps
from ...models.deleted_container_restore_snapshot import DeletedContainerRestoreSnapshot
from ...models.long_term_container import LongTermContainer
from ...models.operation_log import OperationLog
from ...repositories import (
    container_mount_cleanup_repo,
    containers_repo,
    deleted_container_restore_snapshot_repo,
    image_repo,
    long_term_container_repo,
)
from ...services import container_tasks
from ...services.container_module.exceptions import NodeServiceError
from ...services.container_module.long_term import (
    _ensure_long_term_capacity,
    _ensure_long_term_capacity_for_users,
)
from ...services.container_module.restore import (
    _ensure_restore_long_term_capacity,
    _restore_root_user_ids,
)
from ..factories import create_container_graph, create_machine, create_user

pytestmark = pytest.mark.usefixtures("ensure_auth_users")


def _auth(monkeypatch, *, user_id=1):
    monkeypatch.setattr(deps.authentications_repo, "is_token_valid", lambda token, **kwargs: True)
    monkeypatch.setattr(deps.authentications_repo, "get_user_id_by_token", lambda token, **kwargs: user_id)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_entity", lambda uid, code: True)
    monkeypatch.setattr("FuxiYu_CtrKernel.services.rbac_service.user_has_resource", lambda uid, rtype, rid: True)


def _make_long_term_other(db_session, root, machine):
    """给 root 再挂一个长期容器，占满默认上限 1。"""
    _r, _m, other = create_container_graph(root_user=root, machine=machine)
    long_term_container_repo.add(other.id, created_by_user_id=root.id, session=db_session)
    db_session.commit()
    return other


def _deleted_container(db_session, mock_node_send, *, long_term: bool):
    """造一个（可选带长期标记的）容器并软删，返回 root/machine/container/snapshot/sent。"""
    root, machine, container = create_container_graph()
    container.bind_mount_path = f"/home/{root.username}/containers/{container.name}_data"
    container.image_id = 1
    container.last_build_at = image_repo.get_by_id(1, session=db_session).updated_at
    if long_term:
        long_term_container_repo.add(container.id, created_by_user_id=root.id, session=db_session)
    db_session.commit()
    sent = mock_node_send({"success": 1})
    assert container_tasks.remove_container(container.id, operator_user_id=root.id) is True
    snapshot = db_session.scalars(select(DeletedContainerRestoreSnapshot)).one()
    return root, machine, container, snapshot, sent


# ---------------------------------------------------------------------------
# 预检 helper 的口径（portal 与恢复共用同一实现）
# ---------------------------------------------------------------------------

def test_restore_root_users_is_owner_only(app, db_session):
    """恢复后只有 owner 是 root（协作者绑定会被跳过），配额就按这个集合算。"""
    assert _restore_root_user_ids({"user_id": 5, "role": "ROOT"}) == [5]
    assert _restore_root_user_ids({}) == []


def test_preflight_rejects_owner_at_limit_with_counts(app, db_session):
    owner = create_user()
    machine = create_machine()
    _make_long_term_other(db_session, owner, machine)

    with pytest.raises(NodeServiceError) as excinfo:
        _ensure_restore_long_term_capacity({"is_long_term": True}, {"user_id": owner.id})

    assert excinfo.value.reason == "long_term_limit_reached"
    assert "(1/1)" in str(excinfo.value)


def test_preflight_ignores_collaborator_at_limit(app, db_session):
    """协作者占满上限不该挡住 owner 的恢复——配额按 root 用户计。"""
    collaborator = create_user()
    _c_root, _m, collab_container = create_container_graph(root_user=collaborator)
    long_term_container_repo.add(collab_container.id, created_by_user_id=collaborator.id, session=db_session)
    free_owner = create_user()
    db_session.commit()

    _ensure_restore_long_term_capacity({"is_long_term": True}, {"user_id": free_owner.id})  # 不抛


def test_preflight_is_noop_without_long_term_snapshot(app, db_session):
    owner = create_user()
    machine = create_machine()
    _make_long_term_other(db_session, owner, machine)

    # 快照说不是长期容器（或旧快照根本没有这个键）→ 不校验、也不补标记
    _ensure_restore_long_term_capacity({"is_long_term": False}, {"user_id": owner.id})
    _ensure_restore_long_term_capacity({}, {"user_id": owner.id})


def test_portal_and_restore_share_capacity_implementation(app, db_session):
    """门户 bindings 形态与恢复 owner 形态走同一份配额实现（reason 与数量文案一致）。"""
    owner = create_user()
    machine = create_machine()
    _make_long_term_other(db_session, owner, machine)
    bindings = [{"user_id": owner.id, "role": "ROOT"}]

    with pytest.raises(NodeServiceError) as from_bindings:
        _ensure_long_term_capacity(bindings)
    with pytest.raises(NodeServiceError) as from_users:
        _ensure_long_term_capacity_for_users([owner.id])

    assert from_bindings.value.reason == from_users.value.reason == "long_term_limit_reached"
    assert str(from_bindings.value) == str(from_users.value)


# ---------------------------------------------------------------------------
# 恢复门户：超限时不产生半恢复 / 不消费快照
# ---------------------------------------------------------------------------

def test_restore_rejects_at_capacity_before_any_restore_work(app, db_session, mock_node_send):
    root, machine, container, snapshot, sent = _deleted_container(db_session, mock_node_send, long_term=True)
    _make_long_term_other(db_session, root, machine)
    sent.clear()

    with pytest.raises(NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    assert excinfo.value.reason == "long_term_limit_reached"
    assert "(1/1)" in str(excinfo.value)
    # Node 未被调用（没有创建请求），容器仍是软删
    assert not [c for c in sent if c["url"].endswith("/create_container")]
    db_session.expire_all()
    assert containers_repo.get_by_id(container.id, session=db_session) is None
    retained = containers_repo.get_by_id(container.id, session=db_session, include_invalid=True)
    assert retained is not None and retained.is_valid is False
    # 快照与挂载清理记录都未被消费
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot.id, session=db_session) is not None
    assert container_mount_cleanup_repo.get_by_id(snapshot.mount_cleanup_id, session=db_session) is not None
    # 失败必须留痕，不能静默
    failure = db_session.scalars(select(OperationLog).where(OperationLog.success.is_(False))).all()
    assert [log.error_reason for log in failure] == ["long_term_limit_reached"]


def test_restore_retry_succeeds_after_capacity_is_freed(app, db_session, mock_node_send):
    """容量失败后可闭环：释放一个已有配额，用同一 deleted_id 重试即成功。

    证明失败是**可恢复的拒绝**而不是把快照/容器卡死：第一次超限不动任何状态，
    释放 other 的长期标记后第二次真正恢复，且长期标记与快照消费都正确。
    """
    root, machine, container, snapshot, sent = _deleted_container(db_session, mock_node_send, long_term=True)
    other = _make_long_term_other(db_session, root, machine)
    # 成功恢复会删掉快照行，之后不能再从 ORM 实例取属性——先抓稳定 id
    snapshot_id = snapshot.id
    cleanup_id = snapshot.mount_cleanup_id
    sent.clear()

    # 第一次：配额被 other 占满 → 拒绝，快照未消费、未创建容器
    with pytest.raises(NodeServiceError) as excinfo:
        container_tasks.resurrect_container(snapshot_id, operator_user_id=root.id)
    assert excinfo.value.reason == "long_term_limit_reached"
    db_session.expire_all()
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot_id, session=db_session) is not None
    assert not [c for c in sent if c["url"].endswith("/create_container")]

    # 释放一个已有长期配额：取消 other 的长期标记
    long_term_container_repo.remove(other.id, session=db_session)
    db_session.commit()
    sent.clear()

    # 用同一 deleted_id 重试 → 成功恢复并补回长期标记
    result = container_tasks.resurrect_container(snapshot_id, operator_user_id=root.id)

    db_session.expire_all()
    assert result["container_id"] == container.id
    assert [c for c in sent if c["url"].endswith("/create_container")], "重试应真正发起创建"
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True
    assert long_term_container_repo.count_by_user(root.id, session=db_session) == 1
    # 快照成功消费（含对应挂载清理记录），不再可被二次使用
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot_id, session=db_session) is None
    assert container_mount_cleanup_repo.get_by_id(cleanup_id, session=db_session) is None


def test_restore_re_adds_marker_when_capacity_available(app, db_session, mock_node_send):
    root, _machine, container, snapshot, sent = _deleted_container(db_session, mock_node_send, long_term=True)
    # 软删期间标记行仍在；先移除以验证恢复确实会重新补上（而不是靠旧行残留）
    long_term_container_repo.remove(container.id, session=db_session)
    db_session.commit()
    assert long_term_container_repo.is_long_term(container.id, session=db_session, include_invalid=True) is False
    sent.clear()

    result = container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    db_session.expire_all()
    assert result["container_id"] == container.id
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is True
    assert long_term_container_repo.count_by_user(root.id, session=db_session) == 1


def test_restore_keeps_existing_marker_idempotent(app, db_session, mock_node_send):
    root, _machine, container, snapshot, sent = _deleted_container(db_session, mock_node_send, long_term=True)
    sent.clear()

    container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    db_session.expire_all()
    rows = db_session.scalars(
        select(LongTermContainer).where(LongTermContainer.container_id == container.id)
    ).all()
    assert len(rows) == 1, "已存在的长期标记不得重复插入"
    assert long_term_container_repo.count_by_user(root.id, session=db_session) == 1


def test_restore_of_short_term_snapshot_ignores_capacity(app, db_session, mock_node_send):
    root, machine, container, snapshot, sent = _deleted_container(db_session, mock_node_send, long_term=False)
    _make_long_term_other(db_session, root, machine)
    sent.clear()

    result = container_tasks.resurrect_container(snapshot.id, operator_user_id=root.id)

    db_session.expire_all()
    assert result["container_id"] == container.id
    assert long_term_container_repo.is_long_term(container.id, session=db_session) is False


# ---------------------------------------------------------------------------
# HTTP 链路：reason / status / message 数量值
# ---------------------------------------------------------------------------

def test_resurrect_api_maps_capacity_to_409_and_keeps_snapshot(app, client, monkeypatch, db_session, mock_node_send):
    _auth(monkeypatch, user_id=1)
    root, machine, container, snapshot, sent = _deleted_container(db_session, mock_node_send, long_term=True)
    _make_long_term_other(db_session, root, machine)
    sent.clear()

    resp = client.post("/api/containers/resurrect_container", json={"deleted_id": snapshot.id})

    assert resp.status_code == 409
    body = resp.json()
    assert body["error_reason"] == "long_term_limit_reached"
    assert "(1/1)" in body["message"]
    assert not [c for c in sent if c["url"].endswith("/create_container")]
    db_session.expire_all()
    assert deleted_container_restore_snapshot_repo.get_by_id(snapshot.id, session=db_session) is not None
    retained = containers_repo.get_by_id(container.id, session=db_session, include_invalid=True)
    assert retained is not None and retained.is_valid is False


def test_resurrect_api_maps_missing_snapshot_to_404(client, monkeypatch):
    _auth(monkeypatch, user_id=1)

    resp = client.post("/api/containers/resurrect_container", json={"deleted_id": 99999})

    assert resp.status_code == 404
    assert resp.json()["error_reason"] == "not_found"
