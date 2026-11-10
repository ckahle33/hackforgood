import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ADMIN_EMAILS"] = "admin@example.org"
os.environ["RESEND_API_KEY"] = ""
os.environ["MAIL_ADDRESS"] = ""
os.environ["CRON_SECRET"] = ""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.db import Base, engine
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    users = {
        "tok-org": {"id": "u1", "email": "org@example.org", "user_metadata": {"full_name": "Org Owner"}},
        "tok-admin": {"id": "u2", "email": "admin@example.org", "user_metadata": {}},
    }

    def fake(token):
        if token not in users:
            raise auth.HTTPException(401, "bad")
        return users[token]

    monkeypatch.setattr(auth, "fetch_supabase_user", fake)
    with TestClient(app, follow_redirects=False) as c:
        yield c


def login(c, token):
    assert c.post("/auth/session", json={"access_token": token}).status_code == 200
