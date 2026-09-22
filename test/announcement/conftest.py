"""公告测试的公共装置。"""

import pytest


@pytest.fixture()
def inline_send_thread(monkeypatch):
    """把投递的后台线程换成"start() 就地执行"。

    发送/重发已改成异步（2026-09）：POST 回来时信还没发。要断言审计与终态，
    就得让线程同步跑完。**测试库是 StaticPool 的单条 SQLite 连接**，真起线程会和
    测试会话抢同一条连接；就地执行同时也避开了这个。
    """
    import FuxiYu_CtrKernel.services.announcement_tasks as tasks

    class _InlineThread:
        def __init__(self, target=None, args=(), kwargs=None, **ignored):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(tasks.threading, "Thread", _InlineThread)


# 注：这里**不需要**再关什么冷却了——公告之间没有冷却（2026-09 决策），
# 发信闸门只剩一个纯互斥锁（不等待），而逐封间隔在测试里走的是 mock 传输层。
