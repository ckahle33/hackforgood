"""Sending email through Resend. Everything else in the app talks to this module only,
so switching providers later means changing just this file."""
import datetime as dt
import logging

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import EmailLog

log = logging.getLogger("mail")
RESERVED_FOR_CONFIRMATIONS = 10


def configured() -> bool:
    return bool(get_settings().resend_api_key)


def send_batch(messages: list[dict]) -> bool:
    """Send up to 100 messages in one API call. Returns True if the provider accepted them."""
    s = get_settings()
    if not messages:
        return True
    if not s.resend_api_key:
        log.warning("RESEND_API_KEY not set; not sending %d message(s)", len(messages))
        return False
    try:
        r = httpx.post(
            "https://api.resend.com/emails/batch", json=messages, timeout=30,
            headers={"Authorization": f"Bearer {s.resend_api_key}"},
        )
    except httpx.HTTPError as e:
        log.error("Resend request failed: %s", e)
        return False
    if r.status_code >= 300:
        log.error("Resend rejected batch (%s): %s", r.status_code, r.text[:300])
        return False
    return True


def sent_today(db: Session) -> int:
    midnight = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.coalesce(func.sum(EmailLog.count), 0)).where(EmailLog.sent_at >= midnight)) or 0


def remaining_today(db: Session, reserve: int = 0) -> int:
    return max(0, get_settings().mail_daily_limit - sent_today(db) - reserve)


def log_sent(db: Session, kind: str, count: int) -> None:
    db.add(EmailLog(kind=kind, count=count))
    db.commit()


def build_message(to: str, subject: str, html: str, text: str, unsubscribe_url: str | None = None) -> dict:
    msg = {"from": get_settings().mail_from, "to": [to], "subject": subject, "html": html, "text": text}
    if unsubscribe_url:
        msg["headers"] = {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    return msg
