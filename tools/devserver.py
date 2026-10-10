"""The site on this machine with a throwaway Postgres, so rooms and accounts can be
played locally without touching Neon.

    uv run python -m tools.devserver           # http://localhost:8031
    uv run python -m tools.devserver --port 8040

`.env.local` holds production's address (`neon deploy` writes it there), and the app
reads it for any variable not already set. This sets DATABASE_URL, DATABASE_URL_UNPOOLED
and SESSION_SECRET first, so the local server can never fall through to production.
The database lives in a temporary directory and is gone when the server stops.
"""

from __future__ import annotations

import argparse
import os
import secrets
import tempfile

import pgserver
import uvicorn

from tools.migrate import migrate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8031)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="uclnights11-db-") as tmp:
        server = pgserver.get_server(tmp, cleanup_mode="stop")
        url = server.get_uri()
        migrate(url)
        os.environ["DATABASE_URL"] = os.environ["DATABASE_URL_UNPOOLED"] = url
        os.environ["SESSION_SECRET"] = secrets.token_hex(32)
        try:
            uvicorn.run("web.app:app", port=args.port)
        finally:
            server.cleanup()


if __name__ == "__main__":
    main()
