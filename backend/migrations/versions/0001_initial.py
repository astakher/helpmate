# Stand-in for Workstream B - not part of the Part C deliverable
"""Initial schema: one table per repository.

Each row keeps the full domain model as JSONB (`data`), plus typed columns for everything the
repositories filter or sort on, so queries use indexes and the model can't drift from the table.
`seq` breaks ties in insertion order, like the in-memory repositories.

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = {
    "proposals": "id text PRIMARY KEY, status text NOT NULL, created_at timestamptz NOT NULL",
    "reminders": "id text PRIMARY KEY, status text NOT NULL, due_at timestamptz NOT NULL",
    "tasks": (
        "id text PRIMARY KEY, horizon text NOT NULL, done boolean NOT NULL, "
        "created_at timestamptz NOT NULL"
    ),
    "folders": "id text PRIMARY KEY, created_at timestamptz NOT NULL",
    "items": "id text PRIMARY KEY, folder_id text NOT NULL, created_at timestamptz NOT NULL",
    "chat_sessions": "id text PRIMARY KEY, created_at timestamptz NOT NULL",
    "chat_messages": (
        "id text PRIMARY KEY, session_id text NOT NULL, created_at timestamptz NOT NULL"
    ),
    "memory_suggestions": (
        "id text PRIMARY KEY, status text NOT NULL, created_at timestamptz NOT NULL"
    ),
    "memory_facts": "id text PRIMARY KEY, created_at timestamptz NOT NULL",
    "push_subscriptions": "endpoint text PRIMARY KEY",
    "deliveries": "notification_id text PRIMARY KEY, sent_at timestamptz NOT NULL",
    "audit": "id text PRIMARY KEY, at timestamptz NOT NULL",
    "settings": "key text PRIMARY KEY",
}
INDEXES = [
    "CREATE INDEX proposals_status_created ON proposals (status, created_at DESC)",
    "CREATE INDEX reminders_status_due ON reminders (status, due_at)",
    "CREATE INDEX tasks_horizon ON tasks (horizon, done, created_at)",
    "CREATE INDEX items_folder ON items (folder_id, created_at)",
    "CREATE INDEX chat_messages_session ON chat_messages (session_id, created_at)",
    "CREATE INDEX memory_suggestions_status ON memory_suggestions (status, created_at DESC)",
]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")  # for memory search (Workstream A)
    for table, columns in TABLES.items():
        op.execute(f"CREATE TABLE {table} ({columns}, seq bigserial NOT NULL, data jsonb NOT NULL)")
    for index in INDEXES:
        op.execute(index)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
