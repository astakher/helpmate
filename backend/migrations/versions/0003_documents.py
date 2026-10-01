# Stand-in for Workstream B - not part of the Part C deliverable
"""Documents and their passages with embeddings (pgvector), for document Q&A.

`embedding` is vector(768), nomic-embed-text's size; a model with another size needs a new
migration and a re-index. Cosine distance (`<=>`) is what search orders by. No ANN index yet: a
single owner's few thousand passages scan in milliseconds; add HNSW when that stops being true.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-01
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "CREATE TABLE documents (id text PRIMARY KEY, created_at timestamptz NOT NULL, "
        "seq bigserial NOT NULL, data jsonb NOT NULL)"
    )
    op.execute(
        "CREATE TABLE document_passages (id text PRIMARY KEY, document_id text NOT NULL "
        "REFERENCES documents (id) ON DELETE CASCADE, seq bigserial NOT NULL, "
        "data jsonb NOT NULL, embedding vector(768) NOT NULL)"
    )
    op.execute("CREATE INDEX document_passages_document ON document_passages (document_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_passages")
    op.execute("DROP TABLE IF EXISTS documents")
