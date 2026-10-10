"""The admin page's work: a look at the site, and the account and room fixes nobody can
yet do for themselves (a forgotten password, an account to delete).

Taken from the cricket site (its A154). Admins are named by ADMIN_ACCOUNT_IDS, a
comma-separated list of account ids; with it unset there are none. Every admin route
answers 404 to anyone else, so the routes do not even confirm they exist.
"""

from __future__ import annotations

import os

from web import auth, failures, rooms
from web.accounts import Account, AccountError

SEARCH_LIMIT = 25
ROOMS_LIMIT = 50


def admin_ids() -> frozenset[int]:
    raw = os.environ.get("ADMIN_ACCOUNT_IDS", "")
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x.isdigit())


def is_admin(account: Account | None) -> bool:
    return account is not None and account.account_id in admin_ids()


def overview(conn) -> dict:
    (accounts, new_week) = conn.execute(
        "select count(*), count(*) filter (where created_at > now() - interval '7 days') from accounts").fetchone()
    by_status = dict(conn.execute("select status, count(*) from rooms group by status").fetchall())
    signups = conn.execute(
        "select d::date, count(a.account_id) from generate_series(current_date - 13, current_date, interval '1 day') d"
        " left join accounts a on a.created_at::date = d::date group by d order by d").fetchall()
    return {
        "accounts": accounts, "accounts_this_week": new_week,
        "rooms": {s: by_status.get(s, 0) for s in ("lobby", "drafting", "complete")},
        "signups": [{"day": d.isoformat(), "n": n} for d, n in signups],
        "failures": failures.summary(conn, days=7, limit=20),
    }


def search_accounts(conn, q: str = "") -> list[dict]:
    """The newest accounts, or those whose username or email contains `q`."""
    q = q.strip()
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = conn.execute(
        "select a.account_id, a.username, a.email, a.created_at,"
        "       (select count(*) from room_seats s where s.account_id = a.account_id),"
        "       (select count(*) from rooms r where r.host_id = a.account_id)"
        "  from accounts a"
        " where %(q)s = '' or a.username ilike %(like)s or a.email ilike %(like)s"
        " order by a.created_at desc limit %(n)s",
        {"q": q, "like": like, "n": SEARCH_LIMIT}).fetchall()
    return [{"id": i, "username": u, "email": e, "created_at": at.isoformat(), "rooms": n, "hosting": h}
            for i, u, e, at, n, h in rows]


def set_password(conn, account_id: int, password: str) -> None:
    """For someone who has forgotten theirs: the site sends no email, so an admin sets a
    new one and passes it on by hand."""
    if not 8 <= len(password) <= 256:
        raise AccountError("a password needs 8 to 256 characters")
    done = conn.execute("update accounts set password_hash = %s where account_id = %s returning 1",
                        (auth.hash_password(password), account_id)).fetchone()
    if done is None:
        raise AccountError("no such account")


def delete_account(conn, account_id: int, by: Account) -> None:
    """Remove an account without taking its friends' rooms with it.

    The schema cascades: deleting an account deletes its seats, and every room it hosts.
    So first each room it hosts passes to the next seat (or, with nobody else in it, goes),
    and afterwards a drafting room whose remaining elevens are all complete is marked
    complete, as it would have been had the deleted seat finished.
    """
    if account_id == by.account_id:
        raise AccountError("an admin can't delete their own account here")
    if conn.execute("select 1 from accounts where account_id = %s", (account_id,)).fetchone() is None:
        raise AccountError("no such account")
    codes = [c for (c,) in conn.execute(
        "select room_code from room_seats where account_id = %s order by room_code", (account_id,))]
    hosted = [c for (c,) in conn.execute(
        "select code from rooms where host_id = %s order by code for update", (account_id,))]
    for code in hosted:
        heir = conn.execute("select account_id from room_seats where room_code = %s and account_id <> %s"
                            " order by seat limit 1", (code, account_id)).fetchone()
        if heir is None:
            conn.execute("delete from rooms where code = %s", (code,))
        else:
            conn.execute("update rooms set host_id = %s where code = %s", (heir[0], code))
    conn.execute("delete from accounts where account_id = %s", (account_id,))
    for code in codes:
        rooms.seat_removed(conn, code)


def list_rooms(conn) -> list[dict]:
    rows = conn.execute(
        "select r.code, r.size, r.status, r.memory, a.username, r.updated_at,"
        "       (select count(*) from room_seats s where s.room_code = r.code)"
        "  from rooms r join accounts a on a.account_id = r.host_id"
        " order by r.updated_at desc limit %s", (ROOMS_LIMIT,)).fetchall()
    return [{"code": c, "size": n, "status": st, "memory": m, "host": h, "updated_at": at.isoformat(),
             "players": p} for c, n, st, m, h, at, p in rows]


def delete_room(conn, code: str) -> None:
    if conn.execute("delete from rooms where code = %s returning 1", (code.strip().upper(),)).fetchone() is None:
        raise AccountError("no such room")
