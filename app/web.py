from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app import auth
from app.config import get_settings
from app.models import CAUSES, JOB_TYPES, SALARY_PERIODS, User

BASE = Path(__file__).parent
settings = get_settings()

templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(
    newsletter_enabled=lambda: bool(settings.resend_api_key and settings.mail_address),
    site_name=settings.site_name, causes=CAUSES, job_types=JOB_TYPES, is_admin=auth.is_admin, salary_periods=SALARY_PERIODS,
    supabase_url=settings.supabase_url, supabase_anon_key=settings.supabase_anon_key,
)


def base_url(request: Request) -> str:
    return (settings.site_url or str(request.base_url)).rstrip("/")


def render(request: Request, name: str, user: User | None, status_code: int = 200, **ctx):
    base = base_url(request)
    ctx.setdefault("canonical", base + request.url.path)
    ctx.setdefault("og_image", base + "/static/og.png")
    return templates.TemplateResponse(request, name, {"user": user, **ctx}, status_code=status_code)
