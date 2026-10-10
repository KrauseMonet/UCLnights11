"""Failures reported by browsers (migration 004), and the read side for tools.failures
and the admin page.

Reporting must never cost the visitor anything: the endpoint answers 204 whatever
happens, a database that is missing or down simply loses the report, and a global cap
stops a broken page (or anyone else) from filling the table.
"""

from __future__ import annotations

KINDS = ("api", "error", "rejection")
KEEP_DAYS = 30
MAX_PER_HOUR = 2000


def record(conn, kind: str, detail: str, page: str) -> bool:
    """True if the report was kept. Over the hourly cap, or of an unknown kind, it is
    dropped; old reports are pruned on the way in, so no scheduled job is needed."""
    if kind not in KINDS:
        return False
    (recent,) = conn.execute("select count(*) from client_failure_reports"
                             " where created_at > now() - interval '1 hour'").fetchone()
    if recent >= MAX_PER_HOUR:
        return False
    conn.execute("delete from client_failure_reports"
                 " where created_at < now() - make_interval(days => %s)", (KEEP_DAYS,))
    conn.execute("insert into client_failure_reports (kind, detail, page) values (%s, %s, %s)",
                 (kind, detail[:500], page.split("?")[0][:100]))
    return True


def summary(conn, days: int = 7, limit: int = 50) -> list[dict]:
    """The commonest failures of the last `days`, most frequent first."""
    rows = conn.execute(
        "select kind, page, detail, count(*), max(created_at) from client_failure_reports"
        " where created_at > now() - make_interval(days => %s)"
        " group by kind, page, detail order by count(*) desc, max(created_at) desc limit %s",
        (days, limit)).fetchall()
    return [{"kind": k, "page": p, "detail": d, "count": n, "last": at.isoformat()}
            for k, p, d, n, at in rows]
