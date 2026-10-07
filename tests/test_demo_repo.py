"""Demo game repo: determinism, planted bugs, and the git-history loader."""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from sqlalchemy import create_engine, func, insert, select

from apps.api.config import get_settings
from apps.api.db.models import DEFAULT_WORKSPACE_ID
from apps.api.db.models import Commit as CommitRow
from apps.api.db.models import Release as ReleaseRow
from pipeline.ingest.git_history import CommitRecord, ReleaseRecord, load_history, read_history
from scripts.make_demo_repo import ANSWER_KEY, build_repo


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    out = tmp_path_factory.mktemp("demo") / "demo_game"
    return out, build_repo(out)


@pytest.fixture(scope="module")
def history(
    demo: tuple[Path, dict[str, Any]],
) -> tuple[list[ReleaseRecord], list[CommitRecord]]:
    return read_history(demo[0])


def _file_at(repo: Repo, commit_sha: str, path: str) -> str:
    commit = repo[commit_sha.encode()]
    assert isinstance(commit, Commit)
    tree = repo[commit.tree]
    for part in path.split("/"):
        assert isinstance(tree, Tree)
        _, sha = tree[part.encode()]
        tree = repo[sha]
    assert isinstance(tree, Blob)
    return tree.data.decode("utf-8")


def test_generation_is_deterministic(demo: tuple[Path, dict[str, Any]], tmp_path: Path) -> None:
    out, key = demo
    again = build_repo(tmp_path / "demo_game")
    assert again == key
    assert (tmp_path / "demo_game" / ANSWER_KEY).read_bytes() == (out / ANSWER_KEY).read_bytes()


def test_answer_key_shape(demo: tuple[Path, dict[str, Any]]) -> None:
    _, key = demo
    bugs = key["bugs"]
    assert len(bugs) == 5
    assert sum(1 for b in bugs if b["fixing_tag"]) == 3
    tags = key["releases"]
    for bug in bugs:
        if bug["fixing_tag"]:
            assert tags.index(bug["fixing_tag"]) > tags.index(bug["introducing_tag"])


def test_answer_key_not_in_git_history(
    demo: tuple[Path, dict[str, Any]], history: tuple[list[ReleaseRecord], list[CommitRecord]]
) -> None:
    _, commits = history
    assert all(ANSWER_KEY not in c.files_changed for c in commits)
    assert all("BUG-" not in c.message for c in commits)


def test_releases_and_commit_counts(
    history: tuple[list[ReleaseRecord], list[CommitRecord]],
) -> None:
    releases, commits = history
    assert [r.tag for r in releases] == [f"v0.{i}" for i in range(1, 8)]
    per_release = Counter(c.release_tag for c in commits)
    assert all(6 <= n <= 8 for n in per_release.values())
    assert None not in per_release
    assert all(r.notes for r in releases)


def test_bugs_are_really_planted(
    demo: tuple[Path, dict[str, Any]], history: tuple[list[ReleaseRecord], list[CommitRecord]]
) -> None:
    out, key = demo
    repo = Repo(str(out))
    by_sha = {c.sha: c for c in history[1]}
    for bug in key["bugs"]:
        intro = by_sha[bug["introducing_commit"]]
        assert intro.release_tag == bug["introducing_tag"]
        assert set(bug["affected_files"]) <= set(intro.files_changed)

        path = bug["affected_files"][0]
        assert bug["evidence"] in _file_at(repo, intro.sha, path)
        parent = repo[intro.sha.encode()].parents[0].decode()  # type: ignore[attr-defined]
        assert bug["evidence"] not in _file_at(repo, parent, path)

        if bug["fixing_commit"]:
            fix = by_sha[bug["fixing_commit"]]
            assert fix.release_tag == bug["fixing_tag"]
            assert bug["evidence"] not in _file_at(repo, fix.sha, path)
        else:
            assert bug["evidence"] in _file_at(repo, key["head"], path)


def test_answer_key_file_matches_return_value(demo: tuple[Path, dict[str, Any]]) -> None:
    out, key = demo
    assert json.loads((out / ANSWER_KEY).read_text()) == key


def test_load_history_is_idempotent(
    history: tuple[list[ReleaseRecord], list[CommitRecord]],
) -> None:
    releases, commits = history
    engine = create_engine(get_settings().sync_database_url)
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            for _ in range(2):
                load_history(conn, DEFAULT_WORKSPACE_ID, releases, commits)
            shas = [c.sha for c in commits]
            n_commits = conn.scalar(
                select(func.count()).select_from(CommitRow).where(CommitRow.sha.in_(shas))
            )
            n_releases = conn.scalar(
                select(func.count())
                .select_from(ReleaseRow)
                .where(ReleaseRow.workspace_id == DEFAULT_WORKSPACE_ID)
            )
            assert n_commits == len(commits)
            assert n_releases == len(releases)

            # A stale commit from an older generation is pruned.
            conn.execute(
                insert(CommitRow).values(
                    sha="0" * 40,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    message="stale",
                    author_date=commits[0].author_date,
                )
            )
            load_history(conn, DEFAULT_WORKSPACE_ID, releases, commits, prune=True)
            total = conn.scalar(
                select(func.count())
                .select_from(CommitRow)
                .where(CommitRow.workspace_id == DEFAULT_WORKSPACE_ID)
            )
            assert total == len(commits)
        finally:
            tx.rollback()
    engine.dispose()
