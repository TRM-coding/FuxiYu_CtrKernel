"""邮件发送工具。

这个模块封装 Ctrl 子系统的邮件发送能力。
核心入口是 send，调用者只需要提供收件人邮箱和邮件内容即可。
"""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class MailConfig:
    """SMTP 发送配置。

    Attributes:
        host: SMTP 服务地址。
        port: SMTP 服务端口。
        username: SMTP 登录用户名。
        password: SMTP 登录密码。
        sender: 邮件发件人地址。
        use_tls: 是否在普通 SMTP 连接上启用 STARTTLS。
        use_ssl: 是否使用 SMTP_SSL 直接加密连接。
        timeout: 连接超时时间（秒）。
    """

    host: str = os.getenv("MAIL_HOST", "localhost")
    port: int = int(os.getenv("MAIL_PORT", "25"))
    username: str | None = os.getenv("MAIL_USERNAME")
    password: str | None = os.getenv("MAIL_PASSWORD")
    sender: str = os.getenv("MAIL_SENDER", os.getenv("MAIL_USERNAME", "noreply@localhost"))
    use_tls: bool = os.getenv("MAIL_USE_TLS", "false").lower() == "true"
    use_ssl: bool = os.getenv("MAIL_USE_SSL", "false").lower() == "true"
    timeout: int = int(os.getenv("MAIL_TIMEOUT", "15"))


def _is_placeholder_password(password: str | None) -> bool:
    return not password or 'your_smtp_auth_code' in str(password).lower()


def _attach_files(msg: EmailMessage, attachments: Iterable[str | Path] | None) -> None:
    """为邮件消息添加附件。

    Args:
        msg: 已创建的邮件消息对象。
        attachments: 附件路径列表。

    Returns:
        None
    """
    if not attachments:
        return
    for item in attachments:
        path = Path(item)
        with path.open("rb") as f:
            data = f.read()
        msg.add_attachment(
            data,
            maintype="application",
            subtype="octet-stream",
            filename=path.name,
        )


def send(
    to: str | list[str],
    subject: str,
    content: str,
    *,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: Iterable[str | Path] | None = None,
    config: MailConfig | None = None,
) -> dict:
    """发送一封邮件。

    Args:
        to: 收件人邮箱，支持单个邮箱或邮箱列表。
        subject: 邮件主题。
        content: 邮件正文（纯文本）。
        cc: 抄送列表。
        bcc: 密送列表。
        attachments: 附件路径列表。
        config: 可选的 SMTP 配置；不传则使用环境变量默认值。

    Returns:
        dict: 发送结果。成功时返回 {"ok": True, "to": [...]}，失败时包含 error 信息。
    """

    cfg = config or MailConfig()
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        raise ValueError("to must not be empty")

    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(content)
    _attach_files(msg, attachments)

    all_recipients = recipients + (cc or []) + (bcc or [])

    try:
        if _is_placeholder_password(cfg.password):
            return {"ok": True, "to": recipients, "mode": "development", "note": "mail password not configured; message not actually sent"}
        if cfg.use_ssl:
            smtp = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout)
        else:
            smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
        with smtp:
            smtp.ehlo()
            if cfg.use_tls and not cfg.use_ssl:
                smtp.starttls()
                smtp.ehlo()
            if cfg.username:
                smtp.login(cfg.username, cfg.password or "")
            smtp.send_message(msg, from_addr=cfg.sender, to_addrs=all_recipients)
        return {"ok": True, "to": recipients}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "to": recipients}
