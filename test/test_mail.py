"""邮件模块测试。

这个测试默认采用真实 SMTP 配置发出一封邮件，方便在启动整套 Ctrl 系统后做端到端验证。
运行前请设置 MAIL_HOST / MAIL_PORT / MAIL_SENDER / MAIL_TEST_TO 等环境变量。
"""

from __future__ import annotations

import os

import pytest

from ..utils.mail import MailConfig, send


@pytest.mark.integration
def test_send_mail_integration():
    """测试邮件发送是否成功。

    Args:
        None

    Returns:
        None
    """
    to = os.getenv("MAIL_TEST_TO")
    host = os.getenv("MAIL_HOST")
    sender = os.getenv("MAIL_SENDER")
    port = os.getenv("MAIL_PORT")

    if not all([to, host, sender, port]):
        pytest.skip("MAIL_TEST_TO / MAIL_HOST / MAIL_SENDER / MAIL_PORT 未配置，跳过真实邮件测试")

    cfg = MailConfig()
    result = send(
        to=to,
        subject="Ctrl subsystem mail test",
        content="This is a test email from the Ctrl subsystem mail module.",
        config=cfg,
    )
    assert result.get("ok") is True, f"邮件发送失败: {result}"
