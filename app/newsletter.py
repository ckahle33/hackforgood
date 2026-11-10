"""Email signup, confirmation, unsubscribe, the weekly digest and admin broadcasts."""
import datetime as dt
import hmac
import html
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app import auth, mail
from app.config import get_settings
from app.db import get_db
from app.models import CAUSES, Job, Subscriber, now
from app.web import base_url, render, templates

router = APIRouter()
DIGEST_INTERVAL = dt.timedelta(days=7)
MAX_JOBS_IN_DIGEST = 15


# ---- email rendering ---------------------------------------------------

def render_email(base: str, *, heading: str, paragraphs: list[str], jobs=(), button=None, unsubscribe_url=None):
    ctx = dict(site_name=get_settings().site_name, base=base, heading=heading, paragraphs=paragraphs, jobs=list(jobs),
              button=button, unsubscribe_url=unsubscribe_url, address=get_settings().mail_address)
    html_body = templates.env.get_template("email/message.html").render(**ctx)
    lines = [heading, ""] + [p for p in paragraphs]
    for j in jobs:
        where = "Remote" if j.remote and not j.location else j.location
        lines += ["", f"{j.title} - {j.org.name}", f"{j.cause} | {j.job_type} | {where}", f"{base}/jobs/{j.id}"]
    if button:
        lines += ["", f"{button[0]}: {button[1]}"]
    lines += ["", "--", get_settings().mail_address]
    if unsubscribe_url:
        lines.append(f"Unsubscribe: {unsubscribe_url}")
    return html_body, "\n".join(lines)


def confirm_message(sub: Subscriber, base: str) -> dict:
    html_body, text = render_email(
        base, heading="Confirm your subscription",
        paragraphs=["Tap the button to start getting new non-profit roles in your inbox. "
                    "If you didn't sign up, ignore this email and nothing will happen."],
        button=("Confirm subscription", f"{base}/subscribe/confirm/{sub.token}"),
    )
    return mail.build_message(sub.email, f"Confirm your subscription to {get_settings().site_name}", html_body, text)


# ---- signup ------------------------------------------------------------

@router.post("/subscribe", response_class=HTMLResponse)
def subscribe(request: Request, email: str = Form(...), causes: list[str] = Form([]), website: str = Form(""),
              db: Session = Depends(get_db), user=Depends(auth.current_user)):
    if not (get_settings().resend_api_key and get_settings().mail_address):
        raise HTTPException(404)
    email = email.strip().lower()
    if website:  # honeypot
        return render(request, "subscribe_result.html", user, title="Check your inbox", message="")
    if "@" not in email or len(email) > 200 or " " in email:
        return render(request, "subscribe_result.html", user, status_code=422, title="That email doesn't look right",
                      message="Please go back and check the address.")
    chosen = "|".join(c for c in causes if c in CAUSES)
    sub = db.scalar(select(Subscriber).where(Subscriber.email == email))
    if sub is None:
        sub = Subscriber(email=email, causes=chosen, token=secrets.token_urlsafe(24))
        db.add(sub)
    elif sub.active:
        sub.causes = chosen  # a signed-in-by-email resubscribe just updates preferences
        db.commit()
        # Same response as a new signup, so the form can't be used to discover who is subscribed.
        return render(request, "subscribe_result.html", user, title="Check your inbox", message="")
    else:
        sub.causes = chosen
    recently = sub.confirm_sent_at and (now() - _aware(sub.confirm_sent_at)) < dt.timedelta(hours=1)
    db.commit()
    if not recently and mail.remaining_today(db) > 0:
        if mail.send_batch([confirm_message(sub, base_url(request))]):
            sub.confirm_sent_at = now()
            db.commit()
            mail.log_sent(db, "confirm", 1)
    return render(request, "subscribe_result.html", user, title="Check your inbox", message="")


def _aware(d: dt.datetime) -> dt.datetime:
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _by_token(db: Session, token: str) -> Subscriber:
    sub = db.scalar(select(Subscriber).where(Subscriber.token == token))
    if sub is None:
        raise HTTPException(404)
    return sub


@router.get("/subscribe/confirm/{token}", response_class=HTMLResponse)
def confirm_page(token: str, request: Request, db: Session = Depends(get_db), user=Depends(auth.current_user)):
    # Needs a click (POST), because mail scanners pre-fetch links and would otherwise confirm for the recipient.
    sub = _by_token(db, token)
    return render(request, "subscribe_confirm.html", user, sub=sub)


@router.post("/subscribe/confirm/{token}", response_class=HTMLResponse)
def confirm(token: str, request: Request, db: Session = Depends(get_db), user=Depends(auth.current_user)):
    sub = _by_token(db, token)
    sub.confirmed_at = sub.confirmed_at or now()
    sub.unsubscribed_at = None
    db.commit()
    return render(request, "subscribe_result.html", user, title="You're subscribed",
                  message="You'll get a weekly email with new roles. Every email has an unsubscribe link.")


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe_page(token: str, request: Request, db: Session = Depends(get_db), user=Depends(auth.current_user)):
    return render(request, "unsubscribe.html", user, sub=_by_token(db, token))


@router.post("/unsubscribe/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, request: Request, db: Session = Depends(get_db), user=Depends(auth.current_user)):
    # Also the target of the one-click List-Unsubscribe-Post header, so it must answer 200 directly.
    sub = _by_token(db, token)
    sub.unsubscribed_at = sub.unsubscribed_at or now()
    db.commit()
    return render(request, "subscribe_result.html", user, title="You've been unsubscribed",
                  message="You won't get any more email from us.")


# ---- the weekly digest -------------------------------------------------

def run_digest(db: Session, base: str) -> dict:
    """Send each active subscriber a digest if 7 days have passed since their last one and there are new
    roles for them. Safe to call every day: it only sends what is due and stays under the daily limit."""
    s = get_settings()
    t = now()
    cutoff = t - DIGEST_INTERVAL
    quota = mail.remaining_today(db, reserve=mail.RESERVED_FOR_CONFIRMATIONS)
    subs = db.scalars(
        select(Subscriber).where(
            Subscriber.confirmed_at.is_not(None), Subscriber.unsubscribed_at.is_(None),
            or_(Subscriber.last_sent_at.is_(None), Subscriber.last_sent_at <= cutoff),
        ).order_by(Subscriber.last_sent_at.asc().nullsfirst()).limit(max(quota, 0))
    ).all()
    horizon = t - dt.timedelta(days=30)
    jobs = db.scalars(
        select(Job).options(joinedload(Job.org)).where(
            Job.status == "approved", Job.approved_at > horizon,
            or_(Job.expires_at.is_(None), Job.expires_at > t),
        ).order_by(Job.approved_at.desc())
    ).all()

    result = {"due": len(subs), "sent": 0, "skipped_no_new_jobs": 0, "quota": quota}
    pending: list[tuple[Subscriber, dict]] = []
    for sub in subs:
        since = max(_aware(sub.last_sent_at) if sub.last_sent_at else cutoff, horizon)
        mine = [j for j in jobs if _aware(j.approved_at) > since and (not sub.cause_list or j.cause in sub.cause_list)]
        if not mine:
            result["skipped_no_new_jobs"] += 1
            continue
        unsub = f"{base}/unsubscribe/{sub.token}"
        n = len(mine)
        html_body, text = render_email(
            base, heading=f"{n} new role{'s' if n != 1 else ''} at non-profits",
            paragraphs=["Here's what was posted since our last email."], jobs=mine[:MAX_JOBS_IN_DIGEST],
            button=("Browse all jobs", f"{base}/jobs"), unsubscribe_url=unsub)
        pending.append((sub, mail.build_message(sub.email, f"{n} new non-profit role{'s' if n != 1 else ''} this week",
                                                html_body, text, unsub)))
    for i in range(0, len(pending), 100):
        chunk = pending[i:i + 100]
        if mail.send_batch([m for _, m in chunk]):
            for sub, _ in chunk:
                sub.last_sent_at = t
            db.commit()
            mail.log_sent(db, "digest", len(chunk))
            result["sent"] += len(chunk)
    return result


@router.post("/cron/digest")
def cron_digest(request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    given = request.headers.get("x-cron-secret", "")
    if not s.cron_secret or not hmac.compare_digest(given, s.cron_secret):
        raise HTTPException(403)
    if not mail.configured() or not s.mail_address:
        return JSONResponse({"error": "Set RESEND_API_KEY and MAIL_ADDRESS before sending."}, status_code=503)
    return run_digest(db, base_url(request))


# ---- admin: one-off update to everyone ---------------------------------

@router.get("/admin/broadcast", response_class=HTMLResponse)
def broadcast_form(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    n = len(db.scalars(select(Subscriber.id).where(Subscriber.confirmed_at.is_not(None),
                                                   Subscriber.unsubscribed_at.is_(None))).all())
    return render(request, "broadcast.html", user, count=n, remaining=mail.remaining_today(db), errors=[], v={}, sent=None)


@router.post("/admin/broadcast", response_class=HTMLResponse)
def broadcast(request: Request, subject: str = Form(...), body: str = Form(...), cause: str = Form(""),
              db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    s = get_settings()
    subs = [x for x in db.scalars(select(Subscriber).where(
        Subscriber.confirmed_at.is_not(None), Subscriber.unsubscribed_at.is_(None))).all()
        if not cause or not x.cause_list or cause in x.cause_list]
    remaining = mail.remaining_today(db)
    errors = []
    if not subject.strip() or not body.strip():
        errors.append("Subject and message are required.")
    if not mail.configured() or not s.mail_address:
        errors.append("Set RESEND_API_KEY and MAIL_ADDRESS first.")
    if len(subs) > remaining:
        errors.append(f"This would email {len(subs)} people but only {remaining} sends are left today "
                      "under your daily limit. Try again tomorrow or raise MAIL_DAILY_LIMIT after upgrading Resend.")
    if errors:
        return render(request, "broadcast.html", user, status_code=422, count=len(subs), remaining=remaining,
                      errors=errors, v={"subject": subject, "body": body, "cause": cause}, sent=None)
    base = base_url(request)
    paragraphs = [p.strip() for p in body.replace("\r", "").split("\n\n") if p.strip()]
    messages = []
    for sub in subs:
        unsub = f"{base}/unsubscribe/{sub.token}"
        html_body, text = render_email(base, heading=subject.strip(), paragraphs=paragraphs, unsubscribe_url=unsub)
        messages.append(mail.build_message(sub.email, subject.strip(), html_body, text, unsub))
    sent = 0
    for i in range(0, len(messages), 100):
        chunk = messages[i:i + 100]
        if mail.send_batch(chunk):
            sent += len(chunk)
            mail.log_sent(db, "broadcast", len(chunk))
    return render(request, "broadcast.html", user, count=len(subs), remaining=mail.remaining_today(db), errors=[],
                  v={}, sent=sent)
