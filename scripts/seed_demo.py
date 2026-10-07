"""Generate the demo game repo and load its releases and commits into the database.

python -m scripts.seed_demo
"""

from sqlalchemy import create_engine, func, select

from apps.api.config import get_settings
from apps.api.db.models import DEFAULT_WORKSPACE_ID, Commit, Release
from pipeline.ingest.git_history import load_history, read_history
from scripts.make_demo_repo import DEFAULT_OUT, build_repo


def main() -> None:
    key = build_repo(DEFAULT_OUT)
    releases, commits = read_history(DEFAULT_OUT)
    engine = create_engine(get_settings().sync_database_url)
    with engine.begin() as conn:
        load_history(conn, DEFAULT_WORKSPACE_ID, releases, commits, prune=True)
        n_releases = conn.scalar(select(func.count()).select_from(Release))
        n_commits = conn.scalar(select(func.count()).select_from(Commit))
    print(f"head={key['head']}")
    print(f"releases in db: {n_releases}  commits in db: {n_commits}")


if __name__ == "__main__":
    main()
