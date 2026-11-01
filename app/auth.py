"""Login via Supabase Auth.

The browser completes the GitHub/Google OAuth flow with supabase-js, then posts
the resulting access token to /auth/session. We verify it against Supabase,
upsert the user, and keep only a signed session cookie with the user id.
"""
import httpx
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User


def fetch_supabase_user(access_token: str) -> dict:
    s = get_settings()
    r = httpx.get(
        f"{s.supabase_url}/auth/v1/user",
        headers={"Authorization": f"Bearer {access_token}", "apikey": s.supabase_anon_key},
        timeout=10,
    )
    if r.status_code != 200:
        raise HTTPException(401, "Invalid login token")
    return r.json()


def upsert_user(db: Session, data: dict) -> User:
    meta = data.get("user_metadata") or {}
    user = db.get(User, data["id"])
    if user is None:
        user = User(id=data["id"], email=(data.get("email") or "").lower())
        db.add(user)
    user.name = meta.get("full_name") or meta.get("user_name") or meta.get("name") or user.email
    user.avatar_url = meta.get("avatar_url") or meta.get("picture") or ""
    db.commit()
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    return db.get(User, uid) if uid else None


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(401, "Please sign in")
    return user


def is_admin(user: User | None) -> bool:
    return bool(user and user.email.lower() in get_settings().admins)


def require_admin(user: User = Depends(require_user)) -> User:
    if not is_admin(user):
        raise HTTPException(403, "Admins only")
    return user
