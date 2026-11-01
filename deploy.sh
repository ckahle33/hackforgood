#!/usr/bin/env bash
# Deploy to Cloud Run (free tier: scales to zero). Reads secrets from .env.
set -euo pipefail
PROJECT=hackforgood-prod-513419
REGION=us-central1
SERVICE=hackforgood

set -a; source .env; set +a
: "${SUPABASE_URL:?}" "${SUPABASE_ANON_KEY:?}" "${DATABASE_URL:?}" "${SECRET_KEY:?}"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  --project "$PROJECT"

# Values go in a temp env file (YAML) so commas/special characters in secrets are safe.
ENVFILE=$(mktemp); trap 'rm -f "$ENVFILE"' EXIT
python3 - "$ENVFILE" <<'PY'
import json, os, sys
keys = ["SITE_URL", "SUPABASE_URL", "SUPABASE_ANON_KEY", "DATABASE_URL", "SECRET_KEY", "ADMIN_EMAILS", "SITE_NAME"]
with open(sys.argv[1], "w") as f:
    for k in keys:
        if os.environ.get(k):
            f.write(f"{k}: {json.dumps(os.environ[k])}\n")
    f.write('HTTPS_ONLY: "true"\n')
PY

gcloud run deploy "$SERVICE" --source . --project "$PROJECT" --region "$REGION" \
  --allow-unauthenticated --max-instances 2 --memory 512Mi --env-vars-file "$ENVFILE"

gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)'
echo "Add <that url>/auth/callback to Supabase > Authentication > URL Configuration."
