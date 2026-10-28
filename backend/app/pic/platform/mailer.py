"""Outbound e-mail (PO documents, supplier invitations, notifications).

Configured by environment variables; without PIC_SMTP_HOST every send returns "DISABLED" and nothing leaves the
platform, so callers record the status instead of failing.
    PIC_SMTP_HOST, PIC_SMTP_PORT (587), PIC_SMTP_USER, PIC_SMTP_PASSWORD, PIC_SMTP_FROM, PIC_SMTP_STARTTLS (true)
"""
import logging
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

log = logging.getLogger("pic.mailer")


def configured() -> bool:
    return bool(os.environ.get("PIC_SMTP_HOST"))


def send(to: str, subject: str, text: str, html: Optional[str] = None,
         attachments: Optional[list[tuple[str, bytes, str]]] = None) -> str:
    """Send one message. Returns SENT, DISABLED or FAILED (the error is logged, never raised)."""
    if not configured():
        return "DISABLED"
    msg = EmailMessage()
    msg["From"] = os.environ.get("PIC_SMTP_FROM") or os.environ.get("PIC_SMTP_USER") or "pic@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    for name, content, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream", filename=name)
    try:
        with smtplib.SMTP(os.environ["PIC_SMTP_HOST"], int(os.environ.get("PIC_SMTP_PORT", "587")), timeout=20) as smtp:
            if os.environ.get("PIC_SMTP_STARTTLS", "true").lower() != "false":
                smtp.starttls()
            if os.environ.get("PIC_SMTP_USER"):
                smtp.login(os.environ["PIC_SMTP_USER"], os.environ.get("PIC_SMTP_PASSWORD", ""))
            smtp.send_message(msg)
        return "SENT"
    except Exception as exc:  # noqa: BLE001 - delivery problems must not break business transactions
        log.warning("mail to %s failed: %s", to, exc)
        return "FAILED"
