"""Generate the deterministic demo game git repo with planted bugs.

    python -m scripts.make_demo_repo [--out fixtures/demo_game]

Objects are written directly with dulwich (no system git, no user git config), with a
fixed author and fixed timestamps, so every run produces identical commit and tag SHAs.
The answer key is written next to the repo but kept out of its history (and excluded via
.git/info/exclude) so a future agent reading the repo cannot see it.
"""

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dulwich.objects import Blob, Commit, ObjectID, Tag, Tree
from dulwich.porcelain import reset
from dulwich.refs import HEADREF, Ref, local_branch_name, local_tag_name
from dulwich.repo import Repo

from scripts.demo_game_plan import BUGS, RELEASES, CommitSpec, Op

DEFAULT_OUT = Path("fixtures/demo_game")
ANSWER_KEY = "answer_key.json"
IDENTITY = b"Ember Forge Dev <dev@emberforge.example>"
FIRST_RELEASE_START = datetime(2026, 3, 2, tzinfo=UTC)
RELEASE_CADENCE = timedelta(days=14)
FILE_MODE = 0o100644
DIR_MODE = 0o040000


@dataclass
class BuiltCommit:
    sha: str
    tag: str
    message: str
    files: list[str]


def apply_op(files: dict[str, str], op: Op) -> str:
    """Apply one file operation in place and return the path it touched."""
    kind, path = op[0], op[1]
    if kind == "write":
        files[path] = op[2]
    elif kind == "append":
        files[path] = files[path] + op[2]
    elif kind == "replace":
        old, new = op[2], op[3]
        count = files[path].count(old)
        if count != 1:
            raise ValueError(f"replace in {path}: expected 1 match, found {count}: {old!r}")
        files[path] = files[path].replace(old, new)
    else:
        raise ValueError(f"unknown op {kind}")
    return path


def write_tree(repo: Repo, files: dict[str, str]) -> ObjectID:
    """Store all files as blobs and nested trees; return the root tree id."""
    nested: dict[str, object] = {}
    for path, text in files.items():
        node = nested
        *dirs, name = path.split("/")
        for d in dirs:
            node = node.setdefault(d, {})  # type: ignore[assignment]
        node[name] = text

    def build(node: dict[str, object]) -> ObjectID:
        tree = Tree()
        for name, child in node.items():
            if isinstance(child, dict):
                tree.add(name.encode(), DIR_MODE, build(child))
            else:
                blob = Blob.from_string(str(child).encode("utf-8"))
                repo.object_store.add_object(blob)
                tree.add(name.encode(), FILE_MODE, blob.id)
        repo.object_store.add_object(tree)
        return tree.id

    return build(nested)


def make_commit(
    repo: Repo, tree_id: ObjectID, parent: ObjectID | None, message: str, when: datetime
) -> ObjectID:
    commit = Commit()
    commit.tree = tree_id
    commit.parents = [parent] if parent else []
    commit.author = commit.committer = IDENTITY
    commit.author_time = commit.commit_time = int(when.timestamp())
    commit.author_timezone = commit.commit_timezone = 0
    commit.message = message.encode("utf-8") + b"\n"
    repo.object_store.add_object(commit)
    return commit.id


def make_tag(repo: Repo, name: str, commit_id: ObjectID, notes: str, when: datetime) -> None:
    tag = Tag()
    tag.tagger = IDENTITY
    tag.name = name.encode()
    tag.object = (Commit, commit_id)
    tag.tag_time = int(when.timestamp())
    tag.tag_timezone = 0
    tag.message = f"Ember Hollow {name}\n\n{notes}\n".encode()
    repo.object_store.add_object(tag)
    repo.refs[local_tag_name(tag.name)] = tag.id


def release_commit(tag: str, notes: str, files: dict[str, str]) -> CommitSpec:
    """Synthesize the version-bump + changelog commit that closes each release."""
    version = tag.removeprefix("v") + ".0"
    old_init = files["game/__init__.py"]
    current = old_init.split('VERSION = "')[1].split('"')[0]
    changelog = files.get("CHANGELOG.md", "# Changelog\n")
    head, _, rest = changelog.partition("\n")
    return CommitSpec(
        f"Release {tag}",
        [
            ("replace", "game/__init__.py", f'VERSION = "{current}"', f'VERSION = "{version}"'),
            ("write", "CHANGELOG.md", f"{head}\n\n## {tag}\n\n{notes}\n{rest}"),
        ],
    )


def build_repo(out: Path) -> dict[str, object]:
    """Create the repo at `out` (replacing a previous generated one) and return the answer key."""
    if out.exists():
        if not (out / ".git").is_dir():
            sys.exit(f"refusing to overwrite {out}: not a generated demo repo")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    repo = Repo.init(str(out))
    repo.refs.set_symbolic_ref(HEADREF, Ref(local_branch_name(b"main")))

    files: dict[str, str] = {}
    parent: ObjectID | None = None
    built: list[BuiltCommit] = []
    intro: dict[str, BuiltCommit] = {}
    fixed: dict[str, BuiltCommit] = {}

    for r_index, release in enumerate(RELEASES):
        start = FIRST_RELEASE_START + r_index * RELEASE_CADENCE - timedelta(days=13)
        n_commits = len(release.commits) + 1  # + the release commit
        if not 6 <= n_commits <= 8:
            raise ValueError(f"{release.tag}: expected 6-8 commits, got {n_commits}")
        when = start
        for c_index in range(n_commits):
            spec = (
                release.commits[c_index]
                if c_index < len(release.commits)
                else release_commit(release.tag, release.notes, files)
            )
            touched = sorted({apply_op(files, op) for op in spec.ops})
            when = start + timedelta(days=2 * c_index, hours=10 + c_index)
            parent = make_commit(repo, write_tree(repo, files), parent, spec.message, when)
            record = BuiltCommit(parent.decode(), release.tag, spec.message, touched)
            built.append(record)
            if spec.introduces:
                intro[spec.introduces] = record
            if spec.fixes:
                fixed[spec.fixes] = record
        assert parent is not None
        make_tag(repo, release.tag, parent, release.notes, when + timedelta(hours=1))

    assert parent is not None
    repo.refs[local_branch_name(b"main")] = parent
    reset(repo, "hard", b"HEAD")
    (out / ".git" / "info").mkdir(exist_ok=True)
    (out / ".git" / "info" / "exclude").write_text(f"{ANSWER_KEY}\n")

    bugs = []
    for bug in BUGS:
        introduced = intro[bug.id]
        fix = fixed.get(bug.id)
        bugs.append(
            {
                "bug_id": bug.id,
                "title": bug.title,
                "description": bug.description,
                "area": bug.area,
                "symptoms": bug.symptoms,
                "introducing_commit": introduced.sha,
                "introducing_tag": introduced.tag,
                "fixing_commit": fix.sha if fix else None,
                "fixing_tag": fix.tag if fix else None,
                "affected_files": bug.affected_files,
                "evidence": bug.evidence,
            }
        )
    key: dict[str, object] = {
        "repo": "ember_hollow",
        "head": parent.decode(),
        "releases": [r.tag for r in RELEASES],
        "commit_count": len(built),
        "bugs": bugs,
    }
    (out / ANSWER_KEY).write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    key = build_repo(args.out)
    print(f"demo repo: {args.out}  head={key['head']}  commits={key['commit_count']}")
    for bug in key["bugs"]:  # type: ignore[attr-defined]
        print(
            f"  {bug['bug_id']}: {bug['introducing_tag']} -> {bug['fixing_tag'] or 'unfixed'}"
            f"  {bug['introducing_commit'][:10]}  {bug['title']}"
        )


if __name__ == "__main__":
    main()
