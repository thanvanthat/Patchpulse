"""initial schema: all Phase 1 tables, pgvector, HNSW indexes

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

from apps.api.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Vector size is fixed at migration time. Changing EMBEDDING_DIM later needs a new migration.
DIM = get_settings().embedding_dim

TS = sa.DateTime(timezone=True)


def _workspace_fk() -> sa.Column[int]:
    return sa.Column(
        "workspace_id",
        sa.BigInteger,
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "workspaces",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
    )
    # Single default workspace for Phase 1 (id=1). Identity restarts past it.
    op.execute("INSERT INTO workspaces (id, name) OVERRIDING SYSTEM VALUE VALUES (1, 'default')")
    op.execute("ALTER TABLE workspaces ALTER COLUMN id RESTART WITH 2")

    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _workspace_fk(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("config", JSONB, server_default="{}", nullable=False),
        sa.Column("last_synced_at", TS),
        sa.CheckConstraint(
            "kind IN ('steam', 'discord', 'csv', 'play_store')", name="ck_sources_kind"
        ),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _workspace_fk(),
        sa.Column(
            "source_id",
            sa.BigInteger,
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(200), nullable=False),
        sa.Column("text_raw", sa.Text, nullable=False),
        sa.Column("text_clean", sa.Text),
        sa.Column("lang", sa.String(16)),
        sa.Column("rating", sa.Float),
        sa.Column("build_version", sa.String(50)),
        sa.Column("platform", sa.String(50)),
        sa.Column("author_meta", JSONB, server_default="{}", nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("is_synthetic", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.UniqueConstraint("source_id", "external_id", name="uq_feedback_source_external"),
    )
    op.create_index("ix_feedback_content_hash", "feedback", ["content_hash"])
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])
    op.create_index("ix_feedback_build_version", "feedback", ["build_version"])

    op.create_table(
        "feedback_ai",
        sa.Column(
            "feedback_id",
            sa.BigInteger,
            sa.ForeignKey("feedback.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("sentiment", sa.Float, nullable=False),
        sa.Column("area", sa.String(30), nullable=False),
        sa.Column("is_actionable", sa.Boolean, nullable=False),
        sa.Column("model_version", sa.String(200), nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sentiment BETWEEN -1 AND 1", name="ck_feedback_ai_sentiment"),
    )

    op.create_table(
        "feedback_vectors",
        sa.Column(
            "feedback_id",
            sa.BigInteger,
            sa.ForeignKey("feedback.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_feedback_vectors_embedding_hnsw ON feedback_vectors "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "themes",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _workspace_fk(),
        sa.Column("name", sa.String(200)),
        sa.Column("summary", sa.Text),
        sa.Column("centroid", Vector(DIM), nullable=False),
        sa.Column("item_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    )
    op.execute(
        "CREATE INDEX ix_themes_centroid_hnsw ON themes USING hnsw (centroid vector_cosine_ops)"
    )

    op.create_table(
        "theme_members",
        sa.Column(
            "theme_id",
            sa.BigInteger,
            sa.ForeignKey("themes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "feedback_id",
            sa.BigInteger,
            sa.ForeignKey("feedback.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("similarity", sa.Float, nullable=False),
    )
    op.create_index("ix_theme_members_feedback_id", "theme_members", ["feedback_id"])

    op.create_table(
        "releases",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        _workspace_fk(),
        sa.Column("tag", sa.String(100), nullable=False),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("released_at", TS, nullable=False),
        sa.Column("notes", sa.Text),
        sa.UniqueConstraint("workspace_id", "tag", name="uq_releases_workspace_tag"),
    )

    op.create_table(
        "commits",
        sa.Column("sha", sa.String(40), primary_key=True),
        _workspace_fk(),
        sa.Column("release_tag", sa.String(100)),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("author_date", TS, nullable=False),
        sa.Column("files_changed", JSONB, server_default="[]", nullable=False),
    )
    op.create_index("ix_commits_release_tag", "commits", ["release_tag"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')", name="ck_jobs_status"
        ),
    )


def downgrade() -> None:
    for table in (
        "jobs",
        "commits",
        "releases",
        "theme_members",
        "themes",
        "feedback_vectors",
        "feedback_ai",
        "feedback",
        "sources",
        "workspaces",
    ):
        op.drop_table(table)
    # The vector extension is left installed; other databases objects may depend on it.
