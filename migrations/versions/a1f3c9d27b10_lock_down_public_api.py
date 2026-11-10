"""lock down Supabase public API: enable RLS, revoke anon/authenticated access

The app talks to Postgres directly (postgres role, bypasses RLS). Nothing should
be reachable through Supabase's auto-generated REST API with the public key.

Revision ID: a1f3c9d27b10
Revises: c088a4738191
"""
from alembic import op

revision = "a1f3c9d27b10"
down_revision = "c088a4738191"
branch_labels = None
depends_on = None

TABLES = ["users", "organizations", "jobs", "applications", "subscribers", "email_log", "alembic_version"]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for t in TABLES:
        op.execute(f'ALTER TABLE public."{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'REVOKE ALL ON TABLE public."{t}" FROM anon, authenticated')
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated")
    # future tables/sequences created by the migration role stay private too
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated")


def downgrade() -> None:
    pass  # deliberately not re-opening access
