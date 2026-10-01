# Stand-in for Workstream B - not part of the Part C deliverable
"""The job queue behind HELPMATE_SCHEDULER=pg (adapters/postgres_jobs.py).

Unlike the repository tables this one has no JSONB `data`: jobs are queue bookkeeping, not domain
models, and every column is read by claim().

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE jobs (
            id text PRIMARY KEY,
            kind text NOT NULL,
            run_at timestamptz NOT NULL,
            status text NOT NULL DEFAULT 'queued',
            attempts integer NOT NULL DEFAULT 0,
            locked_until timestamptz,
            last_error text,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            seq bigserial NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX jobs_due ON jobs (status, run_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jobs")
