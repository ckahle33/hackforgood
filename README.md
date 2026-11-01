# Hack for Good

A job board for non-profit work. Non-profits sign in (Google or GitHub), create an
organization and post roles; an admin approves listings before they go public.

Stack: FastAPI, Jinja2, SQLAlchemy/Alembic, Supabase (Postgres + Auth), Cloud Run.

## Run locally
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env        # fill in values; defaults to a local SQLite file if DATABASE_URL is unset
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed      # optional sample data
.venv/bin/uvicorn app.main:app --reload
.venv/bin/pytest
```

## Supabase setup
1. Authentication > Providers: enable Google and GitHub with your OAuth client IDs/secrets.
2. Authentication > URL Configuration: add `http://localhost:8000/auth/callback` and your
   production `https://<service-url>/auth/callback` to Redirect URLs.
3. Copy the anon key and the pooled database connection string into `.env` / Cloud Run env.

## Deploy
See `deploy.sh`.
