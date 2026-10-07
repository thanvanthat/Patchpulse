"""SQLAlchemy ORM models. Mirrors the Alembic migration in apps/api/migrations."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from apps.api.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim
DEFAULT_WORKSPACE_ID = 1

SOURCE_KINDS = ("steam", "discord", "csv", "play_store")
JOB_STATUSES = ("pending", "running", "succeeded", "failed")


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (CheckConstraint(f"kind IN {SOURCE_KINDS}", name="ck_sources_kind"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_feedback_source_external"),
        Index("ix_feedback_content_hash", "content_hash"),
        Index("ix_feedback_created_at", "created_at"),
        Index("ix_feedback_build_version", "build_version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(200))
    text_raw: Mapped[str] = mapped_column(Text)
    text_clean: Mapped[str | None] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String(16))
    rating: Mapped[float | None] = mapped_column(Float)
    build_version: Mapped[str | None] = mapped_column(String(50))
    platform: Mapped[str | None] = mapped_column(String(50))
    author_meta: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, server_default="false")


class FeedbackAI(Base):
    __tablename__ = "feedback_ai"
    __table_args__ = (
        CheckConstraint("sentiment BETWEEN -1 AND 1", name="ck_feedback_ai_sentiment"),
    )

    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"), primary_key=True
    )
    type: Mapped[str] = mapped_column(String(30))
    sentiment: Mapped[float] = mapped_column(Float)
    area: Mapped[str] = mapped_column(String(30))
    is_actionable: Mapped[bool] = mapped_column(Boolean)
    model_version: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackVector(Base):
    __tablename__ = "feedback_vectors"
    __table_args__ = (
        Index(
            "ix_feedback_vectors_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"), primary_key=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    model_name: Mapped[str] = mapped_column(String(200))


class Theme(Base):
    __tablename__ = "themes"
    __table_args__ = (
        Index(
            "ix_themes_centroid_hnsw",
            "centroid",
            postgresql_using="hnsw",
            postgresql_ops={"centroid": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str | None] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)
    centroid: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    item_count: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ThemeMember(Base):
    __tablename__ = "theme_members"

    theme_id: Mapped[int] = mapped_column(
        ForeignKey("themes.id", ondelete="CASCADE"), primary_key=True
    )
    feedback_id: Mapped[int] = mapped_column(
        ForeignKey("feedback.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    similarity: Mapped[float] = mapped_column(Float)


class Release(Base):
    __tablename__ = "releases"
    __table_args__ = (UniqueConstraint("workspace_id", "tag", name="uq_releases_workspace_tag"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    tag: Mapped[str] = mapped_column(String(100))
    commit_sha: Mapped[str] = mapped_column(String(40))
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class Commit(Base):
    __tablename__ = "commits"

    sha: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    release_tag: Mapped[str | None] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    author_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    files_changed: Mapped[list[Any]] = mapped_column(server_default="[]")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (CheckConstraint(f"status IN {JOB_STATUSES}", name="ck_jobs_status"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
