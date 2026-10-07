"""Read releases (annotated/lightweight tags) and commits from a git repo and upsert them.

Pure-Python via dulwich, so it runs anywhere without a git binary. Idempotent: releases
upsert on (workspace_id, tag) and commits on sha.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dulwich.diff_tree import tree_changes
from dulwich.objects import Commit, ObjectID, Tag
from dulwich.refs import Ref
from dulwich.repo import Repo
from sqlalchemy import Connection, delete
from sqlalchemy.dialects.postgresql import insert

from apps.api.db.models import Commit as CommitRow
from apps.api.db.models import Release as ReleaseRow


@dataclass(frozen=True)
class ReleaseRecord:
    tag: str
    commit_sha: str
    released_at: datetime
    notes: str | None


@dataclass(frozen=True)
class CommitRecord:
    sha: str
    release_tag: str | None
    message: str
    author_date: datetime
    files_changed: list[str]


def _ts(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


def _changed_paths(repo: Repo, commit: Commit) -> list[str]:
    parent_tree = repo[commit.parents[0]].tree if commit.parents else None  # type: ignore[attr-defined]
    paths: set[str] = set()
    for change in tree_changes(repo.object_store, parent_tree, commit.tree):
        for entry in (change.old, change.new):
            if entry is not None and entry.path is not None:
                paths.add(entry.path.decode("utf-8"))
    return sorted(paths)


def _ancestors(repo: Repo, head: ObjectID) -> list[ObjectID]:
    """All commits reachable from head, oldest first."""
    return [entry.commit.id for entry in repo.get_walker(include=[head], reverse=True)]


def read_history(repo_path: Path) -> tuple[list[ReleaseRecord], list[CommitRecord]]:
    repo = Repo(str(repo_path))
    releases: list[ReleaseRecord] = []
    for ref, target in repo.refs.as_dict(Ref(b"refs/tags")).items():
        obj = repo[target]
        notes = None
        if isinstance(obj, Tag):
            notes = obj.message.decode("utf-8").strip()
            released_at = _ts(obj.tag_time)
            obj = repo[obj.object[1]]
        assert isinstance(obj, Commit)
        if notes is None:
            released_at = _ts(obj.commit_time)
        releases.append(ReleaseRecord(ref.decode(), obj.id.decode(), released_at, notes))
    releases.sort(key=lambda r: r.released_at)

    # A commit belongs to the first release (by date) whose tag can reach it.
    release_of: dict[ObjectID, str] = {}
    for release in releases:
        for sha in _ancestors(repo, ObjectID(release.commit_sha.encode())):
            release_of.setdefault(sha, release.tag)

    commits: list[CommitRecord] = []
    for sha in _ancestors(repo, repo.head()):
        commit = repo[sha]
        assert isinstance(commit, Commit)
        commits.append(
            CommitRecord(
                sha=sha.decode(),
                release_tag=release_of.get(sha),
                message=commit.message.decode("utf-8").strip(),
                author_date=_ts(commit.author_time),
                files_changed=_changed_paths(repo, commit),
            )
        )
    return releases, commits


def load_history(
    conn: Connection,
    workspace_id: int,
    releases: list[ReleaseRecord],
    commits: list[CommitRecord],
    *,
    prune: bool = False,
) -> None:
    """Upsert releases and commits. With prune=True, also delete this workspace's releases
    and commits that are not in the given history (use when the workspace tracks one repo)."""
    if prune:
        conn.execute(
            delete(ReleaseRow).where(
                ReleaseRow.workspace_id == workspace_id,
                ReleaseRow.tag.not_in([r.tag for r in releases]),
            )
        )
        conn.execute(
            delete(CommitRow).where(
                CommitRow.workspace_id == workspace_id,
                CommitRow.sha.not_in([c.sha for c in commits]),
            )
        )
    if releases:
        stmt = insert(ReleaseRow).values(
            [
                {
                    "workspace_id": workspace_id,
                    "tag": r.tag,
                    "commit_sha": r.commit_sha,
                    "released_at": r.released_at,
                    "notes": r.notes,
                }
                for r in releases
            ]
        )
        conn.execute(
            stmt.on_conflict_do_update(
                constraint="uq_releases_workspace_tag",
                set_={
                    "commit_sha": stmt.excluded.commit_sha,
                    "released_at": stmt.excluded.released_at,
                    "notes": stmt.excluded.notes,
                },
            )
        )
    if commits:
        cstmt = insert(CommitRow).values(
            [
                {
                    "sha": c.sha,
                    "workspace_id": workspace_id,
                    "release_tag": c.release_tag,
                    "message": c.message,
                    "author_date": c.author_date,
                    "files_changed": c.files_changed,
                }
                for c in commits
            ]
        )
        conn.execute(
            cstmt.on_conflict_do_update(
                index_elements=["sha"],
                set_={
                    "release_tag": cstmt.excluded.release_tag,
                    "message": cstmt.excluded.message,
                    "files_changed": cstmt.excluded.files_changed,
                },
            )
        )
