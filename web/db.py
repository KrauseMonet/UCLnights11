"""One database connection per thread, reused across warm invocations.

Taken from the cricket site (its A120), where measuring showed that opening a Neon
connection costs several times what a query on an open one does, and Vercel keeps a
function's process warm between requests. Not a pool, for the reason found there: a
pool's background maintenance thread does not run while a Lambda is frozen, so its
idea of which connections are fresh cannot be trusted.

A connection idle longer than IDLE_REVALIDATE_S is pinged before use, because a
connection Neon has dropped (its compute suspends when idle) still looks open from
here. The ping runs before the request has done anything, so replacing the connection
can never repeat work; a connection that dies mid-request fails that request instead of
replaying it.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

import psycopg

from web.auth import NotConfigured

CONNECT_TIMEOUT_S = 10
IDLE_REVALIDATE_S = 30
MAX_AGE_S = 900

_LOCAL = threading.local()


def configured() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise NotConfigured("DATABASE_URL is not set")
    return psycopg.connect(url, connect_timeout=CONNECT_TIMEOUT_S)


def _close_quietly(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _alive(conn) -> bool:
    try:
        conn.execute("select 1").fetchone()
        conn.rollback()
        return True
    except Exception:
        return False


def _checkout():
    conn = getattr(_LOCAL, "conn", None)
    now = time.monotonic()
    if conn is not None:
        stale = (conn.closed
                 or now - _LOCAL.opened_at > MAX_AGE_S
                 or (now - _LOCAL.last_used > IDLE_REVALIDATE_S and not _alive(conn)))
        if stale:
            _close_quietly(conn)
            conn = _LOCAL.conn = None
    if conn is None:
        conn = _LOCAL.conn = _connect()
        _LOCAL.opened_at = _LOCAL.last_used = time.monotonic()
    return conn


@contextmanager
def connection():
    """Commits on a clean exit and rolls back on any exception. An application error
    (a refused move) keeps the connection; only an unusable one is dropped."""
    conn = _checkout()
    try:
        yield conn
    except BaseException:
        try:
            if conn.closed:
                _LOCAL.conn = None
            else:
                conn.rollback()
        except Exception:
            _close_quietly(conn)
            _LOCAL.conn = None
        raise
    else:
        try:
            conn.commit()
        except Exception:
            _close_quietly(conn)
            _LOCAL.conn = None
            raise
    finally:
        _LOCAL.last_used = time.monotonic()


def close_all() -> None:
    """This thread's connection, for tests."""
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        _close_quietly(conn)
    _LOCAL.conn = None
