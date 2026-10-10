"""Read a local .env.local and .env into the environment, never overriding a variable
already set (so .env.local wins over .env).

`neon deploy` writes DATABASE_URL and DATABASE_URL_UNPOOLED to .env.local; Vercel sets
its variables itself and ships neither file, so in production this does nothing. Deliberately tiny instead of a dependency:
KEY=VALUE lines, optional quotes, # comments.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv() -> None:
    for name in (".env.local", ".env"):
        _load(ROOT / name)


def _load(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)
