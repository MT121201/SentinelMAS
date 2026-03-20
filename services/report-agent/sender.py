"""
Report delivery: webhook POST + optional SMTP.

Webhook payload is a simple JSON with `text` field (compatible with
Slack incoming webhooks, Teams connectors, and generic POST handlers).

SMTP sends a multipart/alternative email with plain-text and HTML parts.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from config import settings
from formatter import wrap_html

log = logging.getLogger(__name__)


async def send_webhook(report_text: str, subject: str = "SentinelMAS Report") -> bool:
    """
    POST report to manager_webhook_url.
    Returns True on 2xx, False otherwise. Never raises.
    """
    url = settings.manager_webhook_url
    if not url:
        log.info("send_webhook: manager_webhook_url not set — skipping")
        return False

    payload = {
        "text": report_text,
        "subject": subject,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.is_success:
                log.info("send_webhook: delivered (status=%s)", resp.status_code)
                return True
            log.warning(
                "send_webhook: non-2xx response status=%s body=%s",
                resp.status_code,
                resp.text[:200],
            )
            return False
    except Exception as exc:
        log.error("send_webhook: failed: %s", exc)
        return False


def _build_email(subject: str, plain_text: str, html_text: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = settings.smtp_to
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_text, "html", "utf-8"))
    return msg


def send_email(report_text: str, subject: str = "SentinelMAS Report") -> bool:
    """
    Send report via SMTP (synchronous — run in thread if needed).
    Returns True on success, False otherwise. Never raises.
    """
    if not (settings.smtp_host and settings.smtp_to):
        log.info("send_email: smtp_host or smtp_to not set — skipping")
        return False

    html = wrap_html(report_text, subject)
    msg = _build_email(subject, report_text, html)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            recipients = [r.strip() for r in settings.smtp_to.split(",") if r.strip()]
            server.sendmail(settings.smtp_from, recipients, msg.as_string())
        log.info("send_email: delivered to %s", settings.smtp_to)
        return True
    except Exception as exc:
        log.error("send_email: failed: %s", exc)
        return False


async def deliver_report(
    report_text: str,
    subject: str = "SentinelMAS Report",
) -> dict[str, bool]:
    """
    Attempt all configured delivery channels.
    Returns {webhook: bool, email: bool}.
    At least one must be configured — logs warning if neither is.
    """
    webhook_ok = await send_webhook(report_text, subject)
    email_ok = send_email(report_text, subject)

    if not webhook_ok and not email_ok:
        log.warning(
            "deliver_report: no delivery channel succeeded. "
            "Configure MANAGER_WEBHOOK_URL or SMTP_HOST+SMTP_TO."
        )

    return {"webhook": webhook_ok, "email": email_ok}
