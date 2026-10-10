"""Apply the SQL files in migrations/ that the database has not seen, in order.

    uv run python -m tools.migrate           # against DATABASE_URL (DIRECT_URL if set)
    uv run python -m tools.migrate --status  # list applied and pending, change nothing

Each file runs in its own transaction together with the row that records it, so a
failing migration leaves nothing behind. A migration is immutable once it has been
applied anywhere: change the schema with a new file, never by editing an old one.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

from web.env import load_dotenv

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def applied(conn) -> set[str]:
    conn.execute("create table if not exists schema_migrations ("
                 " name text primary key, applied_at timestamptz not null default now())")
    conn.commit()
    return {name for (name,) in conn.execute("select name from schema_migrations")}


def migrate(url: str, status_only: bool = False) -> list[str]:
    """The names applied by this call (or pending, with status_only)."""
    with psycopg.connect(url) as conn:
        done = applied(conn)
        pending = [f for f in files() if f.name not in done]
        if status_only:
            return [f.name for f in pending]
        for f in pending:
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("insert into schema_migrations (name) values (%s)", (f.name,))
        return [f.name for f in pending]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    load_dotenv()
    # Neon's pooled endpoint is for the app; DDL goes over the direct one when it is given.
    url = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set (neon deploy writes it to .env)")
    names = migrate(url, args.status)
    verb = "pending" if args.status else "applied"
    print(f"{len(names)} {verb}" + "".join(f"\n  {n}" for n in names))


if __name__ == "__main__":
    main()
