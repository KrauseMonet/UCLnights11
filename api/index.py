"""Vercel entrypoint. Vercel's Python runtime looks for an ASGI app named `app` here;
the application lives in `web.app` and is only re-exported, so there is one app."""

from web.app import app  # noqa: F401
