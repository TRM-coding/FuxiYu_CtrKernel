import datetime as _real_dt
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from ...models.container_cleanup_reminder import NEVER_REMINDED, ContainerCleanupReminder
from ...models.container_ssh_login import ContainerSSHLogin
from ...repositories import (
    container_cleanup_reminder_repo,
    container_ssh_login_repo,
    long_term_container_repo,
)
from ...schedulers import container_cleanup_task
from ...services import container_tasks
from ...services.container_module import utils as cleanup_utils
from ..factories import create_container_graph


pytestmark = pytest.mark.e2e

_CLOCK: dict = {"now": None}


class _ClockedDatetime(_real_dt.datetime):
    """utcnow 由活动时钟供给；其余（fromisoformat / 构造 / 运算）继承真实 datetime。"""

    @classmethod
    def utcnow(cls):
        now = _CLOCK.get("now")
        return now if now is not None else super().utcnow()


class _Clock:
    def __init__(self, now):
        self.now = now
        _CLOCK["now"] = now

    def advance(self, *, minutes=0, hours=0, days=0):
        self.now += timedelta(minutes=minutes, hours=hours, days=days)
        _CLOCK["now"] = self.now


def _install_clock(monkeypatch, now):
    """把倒计时口径的时钟钉住——build_cleanup_info 的 now 走 utils.datetime。"""

    monkeypatch.setattr(cleanup_utils, "datetime", _ClockedDatetime)
    return _Clock(now)


def _stored_level(db_session, container_id, recipient_email):
    return db_session.scalars(
        select(ContainerCleanupReminder.reminder_key).where(
            ContainerCleanupReminder.container_id == int(container_id),
            ContainerCleanupReminder.recipient_email == recipient_email,
        )
    ).first()


def _ssh_record(db_session, machine_id, container_id, last_ssh_login_time):
    record = ContainerSSHLogin(
        machine_id=machine_id,
        container_id=container_id,
        last_ssh_login_time=last_ssh_login_time,
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_ctrl_e2e_cleanup_reminder_sends_mail_for_countdown_container(db_session, monkeypatch):
    root, machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    last_ssh_time = cleanup_at - timedelta(days=7)
    _ssh_record(db_session, machine.id, container.id, last_ssh_time.isoformat())
    calls = []
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert calls
    assert calls[0]["to"] == root.email
    assert container_cleanup_reminder_repo.was_sent(container.id, "12h", root.email, session=db_session) is True


def test_ctrl_e2e_cleanup_reminder_skips_long_term_container(db_session, monkeypatch):
    _root, machine, container = create_container_graph()
    cleanup_at = datetime.utcnow() + timedelta(hours=1)
    last_ssh_time = cleanup_at - timedelta(days=7)
    _ssh_record(db_session, machine.id, container.id, last_ssh_time.isoformat())
    long_term_container_repo.add(container.id, session=db_session)
    db_session.commit()
    calls = []
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp", lambda **kwargs: calls.append(kwargs) or {"ok": True})

    container_cleanup_task.cleanup_expired_containers_once(7)

    assert calls == []


def test_ctrl_e2e_cleanup_reminder_not_resent_while_machine_unavailable(db_session, monkeypatch):
    """回归 daity：机器开窗期间，同一容器只该收到一封提醒。

    窗口开着时 cleanup_at 每轮扫描都往前移（按"窗口已持续时长"折算）。旧实现把它写进
    判重键做精确匹配，于是每轮都判成新周期——生产上 20 分钟一封、刷了 89 封。
    改判档位后 cleanup_at 完全不参与比较，这里两侧同时断言：读数冻结不动，
    而 cleanup_at 照旧每轮都漂（即"旧键会失效"这件事仍然成立），但只发一封。
    """
    root, machine, container = create_container_graph()
    t0 = datetime(2026, 9, 13, 5, 55, 14)
    last_ssh_raw = (t0 - timedelta(days=7) + timedelta(hours=54)).strftime("%Y-%m-%dT%H:%M:%S")
    _ssh_record(db_session, machine.id, container.id, last_ssh_raw)
    m = db_session.get(type(machine), machine.id)
    m.unavailable_since = t0
    db_session.commit()

    calls = []
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})
    clock = _install_clock(monkeypatch, t0)

    seen_cleanup_at = []
    for _ in range(5):
        info = container_tasks.build_cleanup_info(last_ssh_raw, 7, 0, t0)
        assert info["cleanup_status"] == "countdown"
        assert info["seconds_until_cleanup"] == 54 * 3600   # 冻结：读数不动
        seen_cleanup_at.append(info["cleanup_at"])
        container_cleanup_task.cleanup_expired_containers_once(7)
        clock.advance(minutes=20)

    assert len(calls) == 1
    assert calls[0]["to"] == root.email
    assert len(set(seen_cleanup_at)) == 5            # 旧键在这五轮里五个值，必然全落空
    assert _stored_level(db_session, container.id, root.email) == "72h"


def test_ctrl_e2e_cleanup_reminder_rearms_after_real_login(db_session, monkeypatch):
    """真登录 = 新周期：档位打回 NEVER，新周期重新提醒一遍，同周期内保持静默。"""
    root, machine, container = create_container_graph()
    clock = _install_clock(monkeypatch, datetime(2026, 9, 14, 0, 0, 0))
    calls = []
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})

    def _login(hours_left: int) -> str:
        anchor = (clock.now - timedelta(days=7) + timedelta(hours=hours_left)).strftime("%Y-%m-%dT%H:%M:%S")
        container_ssh_login_repo.upsert_last_ssh_login_time(
            machine.id, container.id, anchor, session=db_session)
        db_session.commit()
        return anchor

    _login(1)                                # 周期一：剩 1 小时 → 12h 档
    container_cleanup_task.cleanup_expired_containers_once(7)
    assert len(calls) == 1
    assert _stored_level(db_session, container.id, root.email) == "12h"

    clock.advance(minutes=5)                 # 时间继续走，但仍属同一周期
    container_cleanup_task.cleanup_expired_containers_once(7)
    assert len(calls) == 1, "同一周期内不该重发"

    _login(50)                               # 真登录 → 周期二，档位被打回
    assert _stored_level(db_session, container.id, root.email) == NEVER_REMINDED

    container_cleanup_task.cleanup_expired_containers_once(7)   # 剩 50 小时 → 72h 档
    assert len(calls) == 2

    clock.advance(hours=2)
    container_cleanup_task.cleanup_expired_containers_once(7)
    assert len(calls) == 2
    assert _stored_level(db_session, container.id, root.email) == "72h"


def test_ctrl_e2e_cleanup_reminder_still_fires_when_earlier_level_missed(db_session, monkeypatch):
    """档位状态对"漏扫"鲁棒：72h 那一轮整个错过，走到 24h 时仍会补发 24h。

    因为记的是"已提醒到的最深档位"而不是"某次发送的记录"，所以落档由当前读数决定，
    不依赖中间档位是否发过。
    """
    root, machine, container = create_container_graph()
    t0 = datetime(2026, 9, 14, 0, 0, 0)
    last_ssh_raw = (t0 - timedelta(days=7) + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%S")
    _ssh_record(db_session, machine.id, container.id, last_ssh_raw)
    db_session.commit()

    calls = []
    monkeypatch.setattr("FuxiYu_CtrKernel.utils.mail._send_smtp",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})
    clock = _install_clock(monkeypatch, t0)

    container_cleanup_task.cleanup_expired_containers_once(7)   # 直接落在 24h 档

    assert len(calls) == 1
    assert "1天" in calls[0]["subject"]      # 24h 档，不是 72h
    assert _stored_level(db_session, container.id, root.email) == "24h"

    clock.advance(hours=1)
    container_cleanup_task.cleanup_expired_containers_once(7)
    assert len(calls) == 1
