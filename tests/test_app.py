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
