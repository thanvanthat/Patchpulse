"""Checks the migrated database matches the Phase 1 data model. Requires `make migrate`."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from apps.api.config import get_settings

EXPECTED_TABLES = {
    "workspaces",
    "sources",
    "feedback",
    "feedback_ai",
    "feedback_vectors",
    "themes",
    "theme_members",
    "releases",
    "commits",
    "jobs",
}
WORKSPACE_SCOPED = {"sources", "feedback", "themes", "releases", "commits"}


async def _columns(conn: AsyncConnection, table: str) -> dict[str, str]:
    rows = await conn.execute(
        text(
            "SELECT column_name, udt_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return {name: udt for name, udt in rows}


async def test_all_tables_exist(conn: AsyncConnection) -> None:
    rows = await conn.execute(
        text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
    )
    assert set(rows.scalars()) >= EXPECTED_TABLES


async def test_pgvector_extension_installed(conn: AsyncConnection) -> None:
    rows = await conn.execute(text("SELECT extname FROM pg_extension"))
    assert "vector" in set(rows.scalars())


@pytest.mark.parametrize("table", sorted(WORKSPACE_SCOPED))
async def test_user_data_tables_have_workspace_id(conn: AsyncConnection, table: str) -> None:
    assert "workspace_id" in await _columns(conn, table)


@pytest.mark.parametrize(
    ("table", "column"), [("feedback_vectors", "embedding"), ("themes", "centroid")]
)
async def test_vector_columns_have_configured_dim(
    conn: AsyncConnection, table: str, column: str
) -> None:
    dim = await conn.scalar(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = CAST(:t AS regclass) AND attname = :c"
        ),
        {"t": table, "c": column},
    )
    assert dim == get_settings().embedding_dim


@pytest.mark.parametrize("index", ["ix_feedback_vectors_embedding_hnsw", "ix_themes_centroid_hnsw"])
async def test_hnsw_cosine_indexes(conn: AsyncConnection, index: str) -> None:
    indexdef = await conn.scalar(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :i"), {"i": index}
    )
    assert indexdef is not None
    assert "USING hnsw" in indexdef
    assert "vector_cosine_ops" in indexdef


async def test_default_workspace_seeded(conn: AsyncConnection) -> None:
    name = await conn.scalar(text("SELECT name FROM workspaces WHERE id = 1"))
    assert name == "default"


async def test_feedback_unique_per_source_external_id(conn: AsyncConnection) -> None:
    source_id = await conn.scalar(
        text("INSERT INTO sources (workspace_id, kind) VALUES (1, 'csv') RETURNING id")
    )
    insert = text(
        "INSERT INTO feedback (workspace_id, source_id, external_id, text_raw, "
        "created_at, content_hash) VALUES (1, :s, 'ext-1', 'hi', now(), 'h')"
    )
    await conn.execute(insert, {"s": source_id})
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(insert, {"s": source_id})


async def test_source_kind_is_constrained(conn: AsyncConnection) -> None:
    with pytest.raises(IntegrityError):
        async with conn.begin_nested():
            await conn.execute(
                text("INSERT INTO sources (workspace_id, kind) VALUES (1, 'twitter')")
            )
