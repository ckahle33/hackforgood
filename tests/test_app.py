from tests.conftest import login

JOB = dict(accept_applications="1", title="Case Manager", description="Help families.", cause="Hunger & Housing",
           job_type="Full-time", city="Austin", region="TX", country="US", apply_url="https://example.org/apply")


def make_org(c):
    return c.post("/organization/new", data={"name": "Food Bank", "mission": "Feed people."})


def test_public_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/jobs").status_code == 200
    assert client.get("/healthz").json() == {"ok": True}
    assert client.get("/jobs/999").status_code == 404


def test_dashboard_requires_login(client):
    r = client.get("/dashboard")
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_bad_token_rejected(client):
    assert client.post("/auth/session", json={"access_token": "nope"}).status_code == 401


def test_job_lifecycle_and_moderation(client):
    login(client, "tok-org")
    assert make_org(client).status_code == 303
    assert client.post("/dashboard/jobs/new", data=JOB).status_code == 303

    # pending: hidden from public listing and from anonymous detail view
    assert "Case Manager" not in client.get("/jobs").text
    anon = client.__class__(client.app, follow_redirects=False)
    assert anon.get("/jobs/1").status_code == 404
    assert client.get("/jobs/1").status_code == 200  # owner can see it

    # non-admin cannot approve
    assert client.post("/admin/jobs/1/approve").status_code == 403

    admin = client.__class__(client.app, follow_redirects=False)
    login(admin, "tok-admin")
    assert "Case Manager" in admin.get("/admin").text
    assert admin.post("/admin/jobs/1/approve").status_code == 303

    assert "Case Manager" in client.get("/jobs").text
    assert "Case Manager" not in client.get("/jobs?cause=Animals").text
    assert "Case Manager" in client.get("/jobs?q=famil").text

    client.post("/dashboard/jobs/1/close")
    assert "Case Manager" not in client.get("/jobs").text


def test_rejects_dangerous_apply_url(client):
    login(client, "tok-org")
    make_org(client)
    r = client.post("/dashboard/jobs/new", data={**JOB, "apply_url": "javascript:alert(1)"})
    assert r.status_code == 422


def test_html_is_escaped(client):
    login(client, "tok-org")
    make_org(client)
    client.post("/dashboard/jobs/new", data={**JOB, "title": "<script>x</script>"})
    assert "<script>x</script>" not in client.get("/jobs/1").text


def test_cannot_close_other_orgs_job(client):
    login(client, "tok-org")
    make_org(client)
    client.post("/dashboard/jobs/new", data=JOB)
    other = client.__class__(client.app, follow_redirects=False)
    login(other, "tok-admin")
    assert other.post("/dashboard/jobs/1/close").status_code == 404


def approved_job(client, **over):
    login(client, "tok-org")
    make_org(client)
    client.post("/dashboard/jobs/new", data={**JOB, "accept_applications": "1", **over})
    admin = client.__class__(client.app, follow_redirects=False)
    login(admin, "tok-admin")
    admin.post("/admin/jobs/1/approve")


APPLY = dict(name="Sam Seeker", email="sam@example.com", resume_url="https://example.com/sam.pdf", note="Hi")


def test_apply_flow(client):
    approved_job(client)
    seeker = client.__class__(client.app, follow_redirects=False)
    # anonymous is sent to login, and returns to the form afterwards
    r = seeker.get("/jobs/1/apply")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    tok = seeker.post("/auth/session", json={"access_token": "tok-admin"})
    assert tok.json()["next"] == "/jobs/1/apply"
    assert seeker.get("/jobs/1/apply").status_code == 200
    assert seeker.post("/jobs/1/apply", data=APPLY).status_code == 303
    # duplicate rejected
    assert seeker.post("/jobs/1/apply", data=APPLY).status_code == 422
    assert "Case Manager" in seeker.get("/applications").text
    # org owner sees applicant, can update status
    assert "sam@example.com" in client.get("/dashboard/jobs/1/applicants").text
    assert client.post("/dashboard/applications/1/status", data={"status": "contacted"}).status_code == 303
    # seeker cannot see applicants or change status
    assert seeker.get("/dashboard/jobs/1/applicants").status_code == 404
    assert seeker.post("/dashboard/applications/1/status", data={"status": "declined"}).status_code == 404
    # withdraw deletes
    assert seeker.post("/applications/1/withdraw").status_code == 303
    assert "sam@example.com" not in client.get("/dashboard/jobs/1/applicants").text


def test_apply_validation_and_guards(client):
    approved_job(client)
    # owner cannot apply to own job
    assert client.post("/jobs/1/apply", data=APPLY).status_code == 422
    seeker = client.__class__(client.app, follow_redirects=False)
    login(seeker, "tok-admin")
    assert seeker.post("/jobs/1/apply", data={**APPLY, "resume_url": "javascript:x"}).status_code == 422
    # honeypot silently dropped
    assert seeker.post("/jobs/1/apply", data={**APPLY, "website": "spam"}).status_code == 303
    assert "sam@example.com" not in client.get("/dashboard/jobs/1/applicants").text


def test_external_jobs_have_no_apply_form(client):
    approved_job(client, accept_applications="")
    seeker = client.__class__(client.app, follow_redirects=False)
    login(seeker, "tok-admin")
    assert seeker.get("/jobs/1/apply").status_code == 404
    assert "https://example.org/apply" in seeker.get("/jobs/1").text


def test_seo_basics(client):
    home = client.get("/").text
    for needle in ('rel="canonical"', 'property="og:title"', 'name="twitter:card"', 'content="index,follow"'):
        assert needle in home
    assert "noindex" in client.get("/login").text
    assert "Disallow: /admin" in client.get("/robots.txt").text


def test_job_structured_data_and_sitemap(client):
    approved_job(client)
    page = client.get("/jobs/1").text
    assert "application/ld+json" in page and '"JobPosting"' in page and "FULL_TIME" in page
    assert "/jobs/1</loc>" in client.get("/sitemap.xml").text
    # pending job: noindex, no structured data, not in sitemap
    client.post("/dashboard/jobs/new", data={**JOB, "title": "Hidden Role"})
    page = client.get("/jobs/2").text
    assert "noindex" in page and "ld+json" not in page
    assert "/jobs/2</loc>" not in client.get("/sitemap.xml").text


def test_google_jobs_fields(client):
    import json, re
    approved_job(client, salary_min="45,000", salary_max="60000", salary_period="YEAR", duration_days="30")
    page = client.get("/jobs/1").text
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', page, re.S).group(1))
    assert ld["jobLocation"]["address"] == {"@type": "PostalAddress", "addressLocality": "Austin",
                                            "addressRegion": "TX", "addressCountry": "US"}
    assert ld["baseSalary"]["value"] == {"@type": "QuantitativeValue", "unitText": "YEAR",
                                         "minValue": 45000, "maxValue": 60000}
    assert ld["validThrough"].endswith("Z") and ld["directApply"] is True
    assert ld["description"].startswith("<p>") and ld["identifier"]["value"] == "1"
    assert "$45,000-$60,000 per year" in page


def test_remote_job_ld(client):
    approved_job(client, remote="1", city="", region="", country="CA")
    import json, re
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', client.get("/jobs/1").text, re.S).group(1))
    assert ld["jobLocationType"] == "TELECOMMUTE"
    assert ld["applicantLocationRequirements"] == {"@type": "Country", "name": "CA"}
    assert "jobLocation" not in ld


def test_location_and_salary_validation(client):
    login(client, "tok-org")
    make_org(client)
    bad = lambda **o: client.post("/dashboard/jobs/new", data={**JOB, **o}).status_code
    assert bad(city="", region="") == 422                       # on-site needs a city and state
    assert bad(country="USA") == 422
    assert bad(salary_min="50000") == 422                       # pay needs a period
    assert bad(salary_min="70000", salary_max="50000", salary_period="YEAR") == 422
    assert bad(salary_min="abc", salary_period="YEAR") == 422
    assert bad(duration_days="45") == 422
    assert bad(remote="1", city="", region="") == 303           # remote needs only a country


def test_expired_job_is_hidden_and_gone(client):
    import datetime as dt
    approved_job(client)
    from app.db import SessionLocal
    from app.models import Job
    with SessionLocal() as db:
        j = db.get(Job, 1)
        j.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
        db.commit()
    anon = client.__class__(client.app, follow_redirects=False)
    assert anon.get("/jobs/1").status_code == 410
    assert "Case Manager" not in anon.get("/jobs").text
    assert "/jobs/1</loc>" not in anon.get("/sitemap.xml").text
    assert client.get("/jobs/1").status_code == 200  # owner can still see it


def test_renew_and_reopen(client):
    import datetime as dt
    approved_job(client)
    from app.db import SessionLocal
    from app.models import Job
    with SessionLocal() as db:
        db.get(Job, 1).expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
        db.commit()
    anon = client.__class__(client.app, follow_redirects=False)
    assert anon.get("/jobs/1").status_code == 410
    assert "Renew" in client.get("/dashboard").text
    assert client.post("/dashboard/jobs/1/renew", data={"duration_days": "30"}).status_code == 303
    assert anon.get("/jobs/1").status_code == 200          # live again, no re-review needed
    assert client.post("/dashboard/jobs/1/renew", data={"duration_days": "45"}).status_code == 404
    # closed listings reopen into the review queue
    client.post("/dashboard/jobs/1/close")
    assert client.post("/dashboard/jobs/1/renew", data={"duration_days": "60"}).status_code == 303
    assert anon.get("/jobs/1").status_code == 404
    with SessionLocal() as db:
        assert db.get(Job, 1).status == "pending"


def test_only_owner_can_renew(client):
    approved_job(client)
    other = client.__class__(client.app, follow_redirects=False)
    login(other, "tok-admin")
    assert other.post("/dashboard/jobs/1/renew", data={"duration_days": "30"}).status_code == 404


def test_both_buttons_and_requirement(client):
    approved_job(client)  # on-site form + external link
    page = client.get("/jobs/1").text
    assert "/jobs/1/apply" in page and "Apply now" in page
    assert "Visit site" in page and 'href="https://example.org/apply"' in page
    # on-site only: no visit button; neither option: rejected
    other = client.__class__(client.app, follow_redirects=False)
    login(other, "tok-admin")
    make_org_data = {"name": "Other Org", "mission": "x"}
    other.post("/organization/new", data=make_org_data)
    assert other.post("/dashboard/jobs/new", data={**JOB, "apply_url": ""}).status_code == 303
    assert other.post("/dashboard/jobs/new", data={**JOB, "apply_url": "", "accept_applications": ""}).status_code == 422


# ---- newsletter -------------------------------------------------------

import pytest


@pytest.fixture()
def outbox(monkeypatch):
    from app import mail
    sent = []
    monkeypatch.setattr(mail, "send_batch", lambda msgs: sent.extend(msgs) or True)
    monkeypatch.setattr(mail, "configured", lambda: True)
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "mail_address", "1 Main St, Austin, TX 78701")
    monkeypatch.setattr(s, "cron_secret", "s3cret")
    monkeypatch.setattr(s, "resend_api_key", "test-key")
    return sent


def subscribe_and_confirm(client, outbox, email="fan@example.com", **form):
    client.post("/subscribe", data={"email": email, **form})
    from app.db import SessionLocal
    from app.models import Subscriber
    with SessionLocal() as db:
        tok = db.query(Subscriber).filter_by(email=email).one().token
    assert client.post(f"/subscribe/confirm/{tok}").status_code == 200
    return tok


def test_double_opt_in_and_unsubscribe(client, outbox):
    r = client.post("/subscribe", data={"email": "Fan@Example.com"})
    assert r.status_code == 200 and len(outbox) == 1
    assert "/subscribe/confirm/" in outbox[0]["html"] and outbox[0]["to"] == ["fan@example.com"]
    from app.db import SessionLocal
    from app.models import Subscriber
    with SessionLocal() as db:
        sub = db.query(Subscriber).one()
        assert not sub.active                      # not subscribed until they confirm
        tok = sub.token
    assert client.get(f"/subscribe/confirm/{tok}").status_code == 200   # GET alone must not confirm
    with SessionLocal() as db:
        assert not db.query(Subscriber).one().active
    client.post(f"/subscribe/confirm/{tok}")
    with SessionLocal() as db:
        assert db.query(Subscriber).one().active
    assert client.post(f"/unsubscribe/{tok}").status_code == 200       # one-click POST
    with SessionLocal() as db:
        assert not db.query(Subscriber).one().active
    assert client.get("/unsubscribe/bogus").status_code == 404


def test_subscribe_is_quiet_about_existing_and_rate_limited(client, outbox):
    client.post("/subscribe", data={"email": "a@example.com"})
    client.post("/subscribe", data={"email": "a@example.com"})   # within the hour: no second email
    assert len(outbox) == 1
    assert client.post("/subscribe", data={"email": "nope"}).status_code == 422
    client.post("/subscribe", data={"email": "bot@example.com", "website": "x"})
    assert len(outbox) == 1


def test_digest_sends_new_jobs_once_and_respects_causes(client, outbox):
    approved_job(client)                                   # Hunger & Housing job
    subscribe_and_confirm(client, outbox, "all@example.com")
    subscribe_and_confirm(client, outbox, "animals@example.com", causes="Animals")
    outbox.clear()
    assert client.post("/cron/digest").status_code == 403
    r = client.post("/cron/digest", headers={"x-cron-secret": "s3cret"})
    assert r.json()["sent"] == 1 and r.json()["skipped_no_new_jobs"] == 1
    assert [m["to"] for m in outbox] == [["all@example.com"]]
    msg = outbox[0]
    assert "Case Manager" in msg["html"] and "Unsubscribe" in msg["html"] and "Main St" in msg["html"]
    assert msg["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    # a second run the same day sends nothing: each subscriber gets one per 7 days
    outbox.clear()
    assert client.post("/cron/digest", headers={"x-cron-secret": "s3cret"}).json()["sent"] == 0 and not outbox


def test_digest_stays_within_daily_limit(client, outbox, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "mail_daily_limit", 13)   # 10 reserved for confirmations
    approved_job(client)
    for i in range(5):
        subscribe_and_confirm(client, outbox, f"u{i}@example.com")
    # 5 confirmation emails were logged by the fixture's mail.log_sent calls
    from app import mail
    from app.db import SessionLocal
    with SessionLocal() as db:
        left = mail.remaining_today(db, reserve=mail.RESERVED_FOR_CONFIRMATIONS)
    assert left <= 0
    outbox.clear()
    assert client.post("/cron/digest", headers={"x-cron-secret": "s3cret"}).json()["sent"] == 0


def test_digest_refuses_without_mail_config(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "cron_secret", "s3cret")
    monkeypatch.setattr(get_settings(), "mail_address", "")
    assert client.post("/cron/digest", headers={"x-cron-secret": "s3cret"}).status_code == 503


def test_admin_broadcast(client, outbox):
    subscribe_and_confirm(client, outbox, "x@example.com")
    outbox.clear()
    plain = client.__class__(client.app, follow_redirects=False)
    login(plain, "tok-org")
    assert plain.get("/admin/broadcast").status_code == 403
    admin = client.__class__(client.app, follow_redirects=False)
    login(admin, "tok-admin")
    assert admin.post("/admin/broadcast", data={"subject": "News", "body": "Hello\n\nThere"}).status_code == 200
    assert len(outbox) == 1 and outbox[0]["subject"] == "News" and "<p" in outbox[0]["html"]


def test_signup_hidden_until_mail_is_configured(client):
    assert "Get new roles" not in client.get("/").text
    assert client.post("/subscribe", data={"email": "a@example.com"}).status_code == 404


def test_signup_shown_when_configured(client, outbox):
    assert "Get new roles" in client.get("/").text and "Get new roles" in client.get("/jobs").text
