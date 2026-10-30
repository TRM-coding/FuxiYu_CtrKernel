"""Q49：发送中删除公告只删公告行，不取消已受理的后台投递。"""

import FuxiYu_CtrKernel.services.announcement_tasks as tasks
from ...constant import AnnouncementStatus
from ...extensions import session_scope
from ...repositories import announcement_repo
from ...services.announcement_tasks import (
    TargetEntry,
    delete_announcement_service,
    start_batch_send_service,
)
from ..factories import create_user


def test_delete_sending_announcement_does_not_cancel_delivery(monkeypatch):
    user = create_user(email="q49@bjtu.edu.cn")
    with session_scope() as session:
        draft = announcement_repo.save_draft(
            title="Q49 投递中删除",
            content="正文",
            created_by=user.id,
            session=session,
        )
        draft_id = draft.id

    pending = {}

    class _ManualThread:
        def __init__(self, target=None, args=(), kwargs=None, **ignored):
            pending["target"] = target
            pending["args"] = args
            pending["kwargs"] = kwargs or {}

        def start(self):
            pending["started"] = True

    sent = []

    def _capture_send(messages, **kwargs):
        sent.append([dict(message) for message in messages])
        return [
            {"ok": True, "to": [message["to"]]}
            for message in messages
        ]

    monkeypatch.setattr(tasks.threading, "Thread", _ManualThread)
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_batch_smtp", _capture_send)

    accepted = start_batch_send_service(
        [draft_id], [TargetEntry(type="user", id=user.id)]
    )
    announcement_id = accepted.announcement_ids[0]

    with session_scope(commit=False) as session:
        announcement = announcement_repo.get_announcement_by_id(
            announcement_id, session=session
        )
        assert announcement.status == AnnouncementStatus.SENDING
    assert pending["started"] is True
    assert sent == []

    assert delete_announcement_service(announcement_id) is True
    with session_scope(commit=False) as session:
        assert announcement_repo.get_announcement_by_id(
            announcement_id, session=session
        ) is None

    # 模拟后台线程在删除之后才真正发信。
    pending["target"](*pending["args"], **pending["kwargs"])

    assert len(sent) == 1
    assert sent[0][0]["to"] == user.email
    with session_scope(commit=False) as session:
        assert announcement_repo.get_announcement_by_id(
            announcement_id, session=session
        ) is None
