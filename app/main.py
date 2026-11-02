import html
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import datetime as dt

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.sessions import SessionMiddleware

from app import auth
from app.config import get_settings
from app.db import get_db
from app.models import APPLICATION_STATUSES, CAUSES, JOB_TYPES, SALARY_PERIODS, Application, Job, Organization, User

BASE = Path(__file__).parent
settings = get_settings()

app = FastAPI(title=settings.site_name, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    same_site="lax",
    https_only=settings.https_only,
    max_age=60 * 60 * 24 * 14,
)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

templates = Jinja2Templates(directory=BASE / "templates")
templates.env.globals.update(
    site_name=settings.site_name, causes=CAUSES, job_types=JOB_TYPES, is_admin=auth.is_admin, salary_periods=SALARY_PERIODS,
    supabase_url=settings.supabase_url, supabase_anon_key=settings.supabase_anon_key,
)


def base_url(request: Request) -> str:
    return (settings.site_url or str(request.base_url)).rstrip("/")


EMPLOYMENT_TYPES = {"Full-time": "FULL_TIME", "Part-time": "PART_TIME", "Contract": "CONTRACTOR",
                    "Volunteer": "VOLUNTEER", "Internship": "INTERN"}


def job_posting_ld(job: Job, url: str) -> dict:
    paragraphs = [p.strip() for p in job.description.replace("\r", "").split("\n\n") if p.strip()]
    ld = {
        "@context": "https://schema.org", "@type": "JobPosting", "title": job.title,
        "description": "".join(f"<p>{html.escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs),
        "datePosted": job.created_at.date().isoformat(),
        "employmentType": EMPLOYMENT_TYPES.get(job.job_type, "OTHER"), "url": url,
        "identifier": {"@type": "PropertyValue", "name": settings.site_name, "value": str(job.id)},
        "directApply": bool(job.accept_applications),
        "hiringOrganization": {"@type": "Organization", "name": job.org.name,
                               **({"sameAs": job.org.website} if job.org.website else {})},
    }
    if job.expires_at:
        ld["validThrough"] = job.expires_at.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if job.remote:
        ld["jobLocationType"] = "TELECOMMUTE"
        ld["applicantLocationRequirements"] = {"@type": "Country", "name": job.country}
    if job.city or not job.remote:
        ld["jobLocation"] = {"@type": "Place", "address": {
            "@type": "PostalAddress", "addressLocality": job.city, "addressRegion": job.region,
            "addressCountry": job.country}}
    if job.salary_min or job.salary_max:
        value = {"@type": "QuantitativeValue", "unitText": job.salary_period}
        if job.salary_min:
            value["minValue"] = job.salary_min
        if job.salary_max:
            value["maxValue"] = job.salary_max
        ld["baseSalary"] = {"@type": "MonetaryAmount", "currency": "USD", "value": value}
    return ld


def render(request: Request, name: str, user: User | None, status_code: int = 200, **ctx):
    base = base_url(request)
    ctx.setdefault("canonical", base + request.url.path)
    ctx.setdefault("og_image", base + "/static/og.png")
    return templates.TemplateResponse(request, name, {"user": user, **ctx}, status_code=status_code)


def safe_url(value: str, allow_mailto: bool = False) -> str | None:
    value = value.strip()
    prefixes = ("http://", "https://") + (("mailto:",) if allow_mailto else ())
    return value if value.lower().startswith(prefixes) and len(value) < 500 else None


def safe_path(p) -> bool:
    return isinstance(p, str) and p.startswith("/") and not p.startswith("//") and "\\" not in p


def visible_jobs():
    return (select(Job).options(joinedload(Job.org))
            .where(Job.status == "approved", or_(Job.expires_at.is_(None), Job.expires_at > dt.datetime.now(dt.timezone.utc))))


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots(request: Request):
    return (
        "User-agent: *\nAllow: /\n"
        "Disallow: /dashboard\nDisallow: /admin\nDisallow: /auth/\nDisallow: /login\n"
        "Disallow: /applications\nDisallow: /organization/\n"
        f"Sitemap: {base_url(request)}/sitemap.xml\n"
    )


@app.get("/sitemap.xml")
def sitemap(request: Request, db: Session = Depends(get_db)):
    base = base_url(request)
    urls = [(f"{base}/", None), (f"{base}/jobs", None)]
    for j in db.scalars(visible_jobs().order_by(Job.created_at.desc()).limit(5000)).all():
        urls.append((f"{base}/jobs/{j.id}", j.created_at.date().isoformat()))
    body = "".join(
        f"<url><loc>{u}</loc>{f'<lastmod>{m}</lastmod>' if m else ''}</url>" for u, m in urls
    )
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    return Response(xml, media_type="application/xml")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db), user=Depends(auth.current_user)):
    latest = db.scalars(visible_jobs().order_by(Job.created_at.desc()).limit(6)).all()
    return render(request, "home.html", user, jobs=latest)


@app.get("/jobs", response_class=HTMLResponse)
def jobs(
    request: Request, q: str = "", cause: str = "", job_type: str = "", remote: str = "",
    db: Session = Depends(get_db), user=Depends(auth.current_user),
):
    stmt = visible_jobs().join(Organization)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.description.ilike(like), Organization.name.ilike(like)))
    if cause in CAUSES:
        stmt = stmt.where(Job.cause == cause)
    if job_type in JOB_TYPES:
        stmt = stmt.where(Job.job_type == job_type)
    if remote == "1":
        stmt = stmt.where(Job.remote.is_(True))
    results = db.scalars(stmt.order_by(Job.created_at.desc()).limit(100)).all()
    filters = {"q": q, "cause": cause, "job_type": job_type, "remote": remote}
    return render(request, "jobs.html", user, jobs=results, f=filters)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(job_id: int, request: Request, db: Session = Depends(get_db), user=Depends(auth.current_user)):
    job = db.scalar(select(Job).options(joinedload(Job.org)).where(Job.id == job_id))
    can_see = job and (
        job.status == "approved" or (user and (user.id == job.org.owner_id or auth.is_admin(user)))
    )
    if not can_see:
        raise HTTPException(404)
    live = job.status == "approved" and not job.expired
    if job.status == "approved" and job.expired and not (user and (user.id == job.org.owner_id or auth.is_admin(user))):
        raise HTTPException(410)  # tells search engines the listing is permanently gone
    url = f"{base_url(request)}/jobs/{job.id}"
    return render(request, "job.html", user, job=job, jsonld=job_posting_ld(job, url) if live else None, live=live)


# ---- auth -------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
def login(request: Request, user=Depends(auth.current_user)):
    if user:
        return RedirectResponse("/dashboard", 303)
    return render(request, "login.html", user)


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(request: Request, user=Depends(auth.current_user)):
    return render(request, "callback.html", user)


@app.post("/auth/session")
async def auth_session(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    token = body.get("access_token")
    if not token:
        raise HTTPException(400, "Missing token")
    user = auth.upsert_user(db, auth.fetch_supabase_user(token))
    request.session["uid"] = user.id
    nxt = request.session.pop("next", None)
    return JSONResponse({"ok": True, "next": nxt if safe_path(nxt) else "/dashboard"})


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)


# ---- non-profit dashboard --------------------------------------------

def get_org(db: Session, user: User) -> Organization | None:
    return db.scalar(select(Organization).where(Organization.owner_id == user.id))


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    org = get_org(db, user)
    if org is None:
        return RedirectResponse("/organization/new", 303)
    return render(request, "dashboard.html", user, org=org, jobs=sorted(org.jobs, key=lambda j: -j.id))


@app.get("/organization/new", response_class=HTMLResponse)
def org_form(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    if get_org(db, user):
        return RedirectResponse("/dashboard", 303)
    return render(request, "org_form.html", user, errors=[], v={})


@app.post("/organization/new")
def org_create(
    request: Request, name: str = Form(...), mission: str = Form(...), website: str = Form(""),
    location: str = Form(""), db: Session = Depends(get_db), user=Depends(auth.require_user),
):
    if get_org(db, user):
        return RedirectResponse("/dashboard", 303)
    v = {"name": name.strip(), "mission": mission.strip(), "website": website.strip(), "location": location.strip()}
    errors = []
    if not v["name"] or len(v["name"]) > 150:
        errors.append("Organization name is required.")
    if not v["mission"]:
        errors.append("Tell us about your mission.")
    if v["website"] and not safe_url(v["website"]):
        errors.append("Website must start with http:// or https://")
    if not errors and db.scalar(select(Organization).where(Organization.name == v["name"])):
        errors.append("An organization with that name already exists.")
    if errors:
        return render(request, "org_form.html", user, status_code=422, errors=errors, v=v)
    db.add(Organization(owner_id=user.id, **v))
    db.commit()
    return RedirectResponse("/dashboard", 303)


@app.get("/dashboard/jobs/new", response_class=HTMLResponse)
def job_form(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    if get_org(db, user) is None:
        return RedirectResponse("/organization/new", 303)
    return render(request, "job_form.html", user, errors=[], v={})


def parse_money(value: str, errors: list, label: str) -> int | None:
    value = value.strip().replace(",", "").replace("$", "")
    if not value:
        return None
    if not value.isdigit() or not 0 < int(value) <= 10_000_000:
        errors.append(f"{label} must be a whole number of dollars.")
        return None
    return int(value)


@app.post("/dashboard/jobs/new")
def job_create(
    request: Request, title: str = Form(...), description: str = Form(...), cause: str = Form(...),
    job_type: str = Form(...), city: str = Form(""), region: str = Form(""), country: str = Form("US"),
    remote: str = Form(""), salary_min: str = Form(""), salary_max: str = Form(""), salary_period: str = Form(""),
    duration_days: int = Form(60), accept_applications: str = Form(""), apply_url: str = Form(""),
    db: Session = Depends(get_db), user=Depends(auth.require_user),
):
    org = get_org(db, user)
    if org is None:
        return RedirectResponse("/organization/new", 303)
    errors: list[str] = []
    v = {"title": title.strip(), "description": description.strip(), "cause": cause, "job_type": job_type,
         "city": city.strip(), "region": region.strip(), "country": country.strip().upper() or "US",
         "remote": remote == "1", "apply_url": apply_url.strip(),
         "accept_applications": accept_applications == "1"}
    v["salary_min"] = parse_money(salary_min, errors, "Minimum pay")
    v["salary_max"] = parse_money(salary_max, errors, "Maximum pay")
    v["salary_period"] = salary_period if salary_period in SALARY_PERIODS else None
    form_echo = {**v, "salary_min": salary_min, "salary_max": salary_max, "salary_period": salary_period,
                 "duration_days": duration_days}
    if not v["title"] or len(v["title"]) > 150:
        errors.append("Title is required (150 characters max).")
    if not v["description"]:
        errors.append("Add a description.")
    if cause not in CAUSES:
        errors.append("Pick a cause.")
    if job_type not in JOB_TYPES:
        errors.append("Pick a job type.")
    if len(v["country"]) != 2 or not v["country"].isalpha():
        errors.append("Country must be a 2-letter code such as US, CA or GB.")
    if not v["remote"] and not (v["city"] and v["region"]):
        errors.append("Add the city and state or region, or mark the role remote.")
    if (v["salary_min"] or v["salary_max"]) and not v["salary_period"]:
        errors.append("Choose whether the pay is per hour, month or year.")
    if v["salary_min"] and v["salary_max"] and v["salary_min"] > v["salary_max"]:
        errors.append("Minimum pay can't be higher than maximum pay.")
    if duration_days not in (30, 60, 90):
        errors.append("Choose how long the listing stays up.")
    if v["apply_url"] and not safe_url(v["apply_url"], allow_mailto=True):
        errors.append("The link must start with http://, https:// or mailto:")
    if not v["accept_applications"] and not v["apply_url"]:
        errors.append("Let people apply on this site, add a link to the full posting, or both.")
    if errors:
        return render(request, "job_form.html", user, status_code=422, errors=errors, v=form_echo)
    v["location"] = ", ".join(x for x in (v["city"], v["region"]) if x)
    v["expires_at"] = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=duration_days)
    db.add(Job(org_id=org.id, **v))
    db.commit()
    return RedirectResponse("/dashboard", 303)


@app.post("/dashboard/jobs/{job_id}/renew")
def job_renew(job_id: int, duration_days: int = Form(60), db: Session = Depends(get_db),
              user=Depends(auth.require_user)):
    job = db.get(Job, job_id)
    if job is None or job.org.owner_id != user.id or job.status not in ("approved", "closed") or duration_days not in (30, 60, 90):
        raise HTTPException(404)
    # Extend from today, or from the current expiry if it is still in the future.
    start = max(dt.datetime.now(dt.timezone.utc), job.expires_at.replace(tzinfo=job.expires_at.tzinfo or dt.timezone.utc)
                if job.expires_at else dt.datetime.now(dt.timezone.utc))
    job.expires_at = start + dt.timedelta(days=duration_days)
    if job.status == "closed":
        job.status = "pending"  # reopened listings go back through review
    db.commit()
    return RedirectResponse("/dashboard", 303)


@app.post("/dashboard/jobs/{job_id}/close")
def job_close(job_id: int, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    job = db.get(Job, job_id)
    if job is None or job.org.owner_id != user.id:
        raise HTTPException(404)
    job.status = "closed"
    db.commit()
    return RedirectResponse("/dashboard", 303)


# ---- applications -----------------------------------------------------

MAX_APPLICATIONS_PER_DAY = 20


def applyable_job(db: Session, job_id: int) -> Job:
    job = db.scalar(select(Job).options(joinedload(Job.org)).where(Job.id == job_id))
    if job is None or job.status != "approved" or not job.accept_applications:
        raise HTTPException(404)
    return job


@app.get("/jobs/{job_id}/apply", response_class=HTMLResponse)
def apply_form(job_id: int, request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    job = applyable_job(db, job_id)
    existing = db.scalar(select(Application).where(Application.job_id == job_id, Application.user_id == user.id))
    return render(request, "apply.html", user, job=job, existing=existing, errors=[],
                  v={"name": user.name, "email": user.email})


@app.post("/jobs/{job_id}/apply")
def apply_submit(
    job_id: int, request: Request, name: str = Form(...), email: str = Form(...), resume_url: str = Form(...),
    note: str = Form(""), website: str = Form(""),  # "website" is a honeypot for bots
    db: Session = Depends(get_db), user=Depends(auth.require_user),
):
    job = applyable_job(db, job_id)
    v = {"name": name.strip(), "email": email.strip(), "resume_url": resume_url.strip(), "note": note.strip()}
    errors = []
    if website:
        return RedirectResponse(f"/jobs/{job_id}", 303)
    if job.org.owner_id == user.id:
        errors.append("You can't apply to your own organization's job.")
    if db.scalar(select(Application).where(Application.job_id == job_id, Application.user_id == user.id)):
        errors.append("You've already applied to this job.")
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    recent = db.scalar(select(func.count()).select_from(Application)
                       .where(Application.user_id == user.id, Application.created_at > since))
    if recent >= MAX_APPLICATIONS_PER_DAY:
        errors.append("You've reached today's application limit. Please try again tomorrow.")
    if not v["name"] or len(v["name"]) > 150:
        errors.append("Your name is required.")
    if "@" not in v["email"] or len(v["email"]) > 200:
        errors.append("Enter a valid email address.")
    if not safe_url(v["resume_url"]):
        errors.append("Resume link must start with http:// or https://")
    if len(v["note"]) > 2000:
        errors.append("Keep your note under 2000 characters.")
    if errors:
        return render(request, "apply.html", user, status_code=422, job=job, existing=None, errors=errors, v=v)
    db.add(Application(job_id=job_id, user_id=user.id, **v))
    db.commit()
    return RedirectResponse("/applications", 303)


@app.get("/applications", response_class=HTMLResponse)
def my_applications(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    apps = db.scalars(select(Application).options(joinedload(Application.job).joinedload(Job.org))
                      .where(Application.user_id == user.id).order_by(Application.created_at.desc())).all()
    return render(request, "applications.html", user, apps=apps)


@app.post("/applications/{app_id}/withdraw")
def withdraw(app_id: int, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    application = db.get(Application, app_id)
    if application is None or application.user_id != user.id:
        raise HTTPException(404)
    db.delete(application)
    db.commit()
    return RedirectResponse("/applications", 303)


def owned_job(db: Session, user: User, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.org.owner_id != user.id:
        raise HTTPException(404)
    return job


@app.get("/dashboard/jobs/{job_id}/applicants", response_class=HTMLResponse)
def applicants(job_id: int, request: Request, db: Session = Depends(get_db), user=Depends(auth.require_user)):
    job = owned_job(db, user, job_id)
    apps = sorted(job.applications, key=lambda a: a.created_at, reverse=True)
    return render(request, "applicants.html", user, job=job, apps=apps, statuses=APPLICATION_STATUSES)


@app.post("/dashboard/applications/{app_id}/status")
def set_status(app_id: int, status: str = Form(...), db: Session = Depends(get_db), user=Depends(auth.require_user)):
    application = db.get(Application, app_id)
    if application is None or application.job.org.owner_id != user.id or status not in APPLICATION_STATUSES:
        raise HTTPException(404)
    application.status = status
    db.commit()
    return RedirectResponse(f"/dashboard/jobs/{application.job_id}/applicants", 303)


# ---- admin moderation -------------------------------------------------

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    pending = db.scalars(
        select(Job).options(joinedload(Job.org)).where(Job.status == "pending").order_by(Job.created_at)
    ).all()
    return render(request, "admin.html", user, jobs=pending)


@app.post("/admin/jobs/{job_id}/{action}")
def admin_moderate(job_id: int, action: str, db: Session = Depends(get_db), user=Depends(auth.require_admin)):
    if action not in ("approve", "reject"):
        raise HTTPException(404)
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404)
    job.status = "approved" if action == "approve" else "rejected"
    db.commit()
    return RedirectResponse("/admin", 303)


@app.exception_handler(410)
async def gone(request: Request, exc):
    return templates.TemplateResponse(request, "error.html", {"user": None, "code": 410,
        "message": "This listing has closed.", "canonical": base_url(request) + request.url.path,
        "og_image": base_url(request) + "/static/og.png"}, status_code=410)


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(request, "error.html", {"user": None, "code": 404,
        "message": "We couldn't find that page."}, status_code=404)


@app.exception_handler(401)
async def unauthorized(request: Request, exc):
    if request.url.path == "/auth/session":
        return JSONResponse({"detail": exc.detail}, status_code=401)
    if request.method == "GET":
        request.session["next"] = request.url.path
    return RedirectResponse("/login", 303)
