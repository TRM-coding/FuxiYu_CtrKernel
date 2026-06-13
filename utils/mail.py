"""邮件发送工具。

这个模块封装 Ctrl 子系统的邮件发送能力。
核心入口是 send（单封）和 send_batch（批量，复用连接）。
"""

from __future__ import annotations

import logging
import os
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


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


# ══════════════════════════════════════════════════════════════════════
# 内部辅助
# ══════════════════════════════════════════════════════════════════════


def _is_placeholder_password(password: str | None) -> bool:
    return not password or 'your_smtp_auth_code' in str(password).lower()


def _attach_files(msg: EmailMessage, attachments: Iterable[str | Path] | None) -> None:
    """为邮件消息添加附件。"""
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


def _build_message(
    *,
    to: str | list[str],
    subject: str,
    content: str,
    sender: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: Iterable[str | Path] | None = None,
) -> tuple[EmailMessage, list[str]]:
    """构建 EmailMessage 并返回 (msg, all_recipients)。"""
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        raise ValueError("to must not be empty")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(content)
    _attach_files(msg, attachments)

    all_recipients = recipients + (cc or []) + (bcc or [])
    return msg, all_recipients


def _safe_ehlo(smtp: smtplib.SMTP) -> tuple[int, str]:
    """发送 EHLO 并安全解包，兼容 mock（ehlo 返回 None）以及返回 bytes/str 的情况。"""
    result = smtp.ehlo()
    if result is None:
        return (0, "(no response / mock)")
    code, banner = result
    if isinstance(banner, bytes):
        banner = banner.decode(errors="replace")
    return (code, banner.strip())


def _format_smtp_error(exc: Exception) -> dict[str, Any]:
    """从 SMTP / 网络异常中提取详细错误信息。

    Returns:
        dict with keys: error, exc_type, and optionally:
            smtp_code, smtp_error, recipients, errno, reason
    """
    info: dict[str, Any] = {
        "error": str(exc),
        "exc_type": type(exc).__name__,
    }

    # ── SMTP 认证失败 ────────────────────────────────────────
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        info["smtp_code"] = exc.smtp_code
        info["smtp_error"] = _b2s(exc.smtp_error)

    # ── 收件人被拒 ───────────────────────────────────────────
    elif isinstance(exc, smtplib.SMTPRecipientsRefused):
        info["recipients"] = {
            email: {"code": code, "error": _b2s(err)}
            for email, (code, err) in exc.recipients.items()
        }

    # ── 发件人被拒 ───────────────────────────────────────────
    elif isinstance(exc, smtplib.SMTPSenderRefused):
        info["smtp_code"] = exc.smtp_code
        info["smtp_error"] = _b2s(exc.smtp_error)
        info["sender"] = exc.sender

    # ── 数据/内容被拒 ────────────────────────────────────────
    elif isinstance(exc, smtplib.SMTPDataError):
        info["smtp_code"] = exc.smtp_code
        info["smtp_error"] = _b2s(exc.smtp_error)

    # ── 通用 SMTP 响应异常 ───────────────────────────────────
    elif isinstance(exc, smtplib.SMTPResponseException):
        info["smtp_code"] = exc.smtp_code
        info["smtp_error"] = _b2s(exc.smtp_error)

    # ── 连接意外断开 — 通常没有额外字段 ──────────────────────
    elif isinstance(exc, smtplib.SMTPServerDisconnected):
        pass

    # ── 网络层错误 ───────────────────────────────────────────
    elif isinstance(exc, (OSError, socket.error, ssl.SSLError)):
        if hasattr(exc, 'errno') and exc.errno is not None:
            info["errno"] = exc.errno
        if hasattr(exc, 'strerror') and exc.strerror:
            info["reason"] = exc.strerror
        if hasattr(exc, 'filename'):
            info["host"] = exc.filename

    return info


def _b2s(val: Any) -> str:
    """bytes 安全转 str。"""
    if isinstance(val, bytes):
        return val.decode(errors="replace")
    return str(val) if val else ""


# ══════════════════════════════════════════════════════════════════════
# SMTP 连接
# ══════════════════════════════════════════════════════════════════════


def _create_smtp_connection(cfg: MailConfig) -> smtplib.SMTP:
    """创建 SMTP 连接（SSL 或普通），完成 ehlo / starttls / login。

    Raises:
        smtplib.SMTPException 及其子类：SMTP 层面的错误。
        OSError / ssl.SSLError：网络或 TLS 层面的错误。
    """
    if cfg.use_ssl:
        smtp = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout)
    else:
        smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)

    _safe_ehlo(smtp)

    if cfg.use_tls and not cfg.use_ssl:
        smtp.starttls()
        _safe_ehlo(smtp)

    if cfg.username:
        try:
            smtp.login(cfg.username, cfg.password or "")
        except Exception:
            logger.error("[mail] SMTP login FAILED for %s", cfg.username)
            raise

    return smtp


# ══════════════════════════════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════════════════════════════


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
    """发送一封邮件（每次调用创建独立 SMTP 连接）。

    Args:
        to: 收件人邮箱，支持单个邮箱或邮箱列表。
        subject: 邮件主题。
        content: 邮件正文（纯文本）。
        cc: 抄送列表。
        bcc: 密送列表。
        attachments: 附件路径列表。
        config: 可选的 SMTP 配置；不传则使用环境变量默认值。

    Returns:
        dict: {"ok": True/False, "to": [...], "error"?: str, "error_detail"?: dict}
    """
    cfg = config or MailConfig()

    recipients = [to] if isinstance(to, str) else list(to)
    try:
        msg, all_recipients = _build_message(
            to=to, subject=subject, content=content,
            sender=cfg.sender, cc=cc, bcc=bcc, attachments=attachments,
        )
    except ValueError:
        raise

    if _is_placeholder_password(cfg.password):
        logger.info("[mail] %s → (development mode, not sent)", recipients)
        return {"ok": True, "to": recipients, "mode": "development",
                "note": "mail password not configured; message not actually sent"}

    try:
        smtp = _create_smtp_connection(cfg)
        with smtp:
            smtp.send_message(msg, from_addr=cfg.sender, to_addrs=all_recipients)
        logger.info("[mail] %s → ok", recipients)
        return {"ok": True, "to": recipients}
    except Exception as exc:
        detail = _format_smtp_error(exc)
        logger.error("[mail] %s → FAILED: %s | %s", recipients, detail["exc_type"], detail["error"])
        return {"ok": False, "error": str(exc), "to": recipients, "error_detail": detail}


def send_batch(
    messages: list[dict],
    *,
    config: MailConfig | None = None,
) -> list[dict]:
    """批量发送邮件，复用单个 SMTP 连接。

    Args:
        messages: 邮件列表，每条 dict 包含:
            to (str|list[str]), subject (str), content (str),
            以及可选的 cc, bcc, attachments。
        config: 可选的 SMTP 配置。

    Returns:
        list[dict]: 与 messages 一一对应的发送结果，
                    每条 {"ok": True/False, "to": [...], "error"?: str, "error_detail"?: dict}。
    """
    if not messages:
        return []

    cfg = config or MailConfig()
    n_total = len(messages)

    # ── 开发模式占位符密码 ──────────────────────────────────
    if _is_placeholder_password(cfg.password):
        results: list[dict] = []
        for m in messages:
            recips = [m["to"]] if isinstance(m["to"], str) else list(m["to"])
            logger.info("[mail] %s → (development mode, not sent)", recips)
            results.append({
                "ok": True, "to": recips, "mode": "development",
                "note": "mail password not configured; message not actually sent",
            })
        return results

    # ── 预构建所有 EmailMessage ─────────────────────────────
    built: list[tuple[dict, EmailMessage | None, list[str]]] = []
    for i, m in enumerate(messages):
        try:
            msg, all_recips = _build_message(
                to=m["to"], subject=m["subject"], content=m["content"],
                sender=cfg.sender, cc=m.get("cc"), bcc=m.get("bcc"),
                attachments=m.get("attachments"),
            )
            built.append((m, msg, all_recips))
        except Exception as exc:
            logger.error("[mail] message build failed for %s: %s", m.get("to"), exc)
            built.append((m, None, []))

    # ── 建立连接 ───────────────────────────────────────────
    try:
        smtp = _create_smtp_connection(cfg)
    except Exception as exc:
        detail = _format_smtp_error(exc)
        logger.error("[mail] SMTP connect FAILED: %s | %s", detail["exc_type"], detail["error"])
        results = []
        for m in messages:
            recips = [m["to"]] if isinstance(m["to"], str) else list(m["to"])
            results.append({"ok": False, "error": str(exc), "to": recips, "error_detail": detail})
        return results

    # ── 逐封发送 ───────────────────────────────────────────
    results = [None] * len(built)
    ok_count = 0
    fail_count = 0
    with smtp:
        for i, (m, msg, all_recips) in enumerate(built):
            recips = [m["to"]] if isinstance(m["to"], str) else list(m["to"])
            if msg is None:
                logger.warning("[mail] %s → skipped (build failed)", recips)
                results[i] = {"ok": False, "error": "message build failed", "to": recips}
                fail_count += 1
                continue

            try:
                smtp.send_message(msg, from_addr=cfg.sender, to_addrs=all_recips)
                logger.info("[mail] %s → ok", recips)
                results[i] = {"ok": True, "to": recips}
                ok_count += 1
            except Exception as exc:
                detail = _format_smtp_error(exc)
                logger.warning("[mail] %s → FAILED: %s | %s", recips, detail["exc_type"], detail["error"])
                results[i] = {"ok": False, "error": str(exc), "to": recips, "error_detail": detail}
                fail_count += 1

    logger.info("[mail] batch done: %d ok / %d fail / %d total", ok_count, fail_count, n_total)
    return results
