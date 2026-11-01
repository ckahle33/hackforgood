from tests.conftest import login

JOB = dict(title="Case Manager", description="Help families.", cause="Hunger & Housing",
           job_type="Full-time", location="Austin, TX", apply_url="https://example.org/apply")


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
    r = client.post("/dashboard/jobs/new", data={**JOB, "apply_method": "external", "apply_url": "javascript:alert(1)"})
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
    client.post("/dashboard/jobs/new", data={**JOB, **over})
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
    approved_job(client, apply_method="external")
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
