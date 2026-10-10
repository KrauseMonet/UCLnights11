"""What browsers have reported going wrong (migration 004), commonest first.

    uv run python -m tools.failures            # the last 7 days
    uv run python -m tools.failures --days 30

Reads DATABASE_URL (from .env.local when set there, which is production). On this Mac,
Neon's hostname needs PGHOSTADDR; see CLAUDE.md. The admin page shows the same list.
"""

from __future__ import annotations

import argparse
import os

import psycopg

from web.env import load_dotenv
from web.failures import KEEP_DAYS, summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    load_dotenv()
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = summary(conn, days=min(args.days, KEEP_DAYS), limit=100)
    if not rows:
        print("nothing reported")
    for r in rows:
        print(f"{r['count']:>5}  {r['kind']:<9} {r['page']:<10} {r['detail']}  (last {r['last'][:16]})")


if __name__ == "__main__":
    main()
