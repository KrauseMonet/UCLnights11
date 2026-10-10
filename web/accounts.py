"""Email+password accounts. Functions take a bare psycopg connection and nothing else.

Signing in is needed only to play with friends, where a seat has to belong to someone;
the solo draft stays anonymous and never touches the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from web import auth

USERNAME_RE = re.compile(r"[A-Za-z0-9_]{3,20}")


class AccountError(ValueError):
    """A failure the player should read as a clean 4xx, never a 500."""


@dataclass(frozen=True)
class Account:
    account_id: int
    username: str


def validate_username(username: str) -> str:
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise AccountError("a username is 3-20 letters, numbers or underscores")
    return username


def create_account(conn, username: str, email: str, password: str) -> Account:
    username = validate_username(username)
    email = email.strip()
    if "@" not in email or len(email) < 3 or len(email) > 254:
        raise AccountError("enter a valid email address")
    if len(password) < 8:
        raise AccountError("a password needs at least 8 characters")
    if len(password) > 256:
        raise AccountError("that password is too long")
    # Checked first so a clash reads as a sentence; the unique indexes (migration 001)
    # are still the guarantee against two registrations racing.
    clash = conn.execute(
        "select lower(username) = lower(%s) from accounts"
        " where lower(username) = lower(%s) or lower(email) = lower(%s)",
        (username, username, email)).fetchone()
    if clash is not None:
        raise AccountError("that username is taken" if clash[0] else "that email is already registered")
    (account_id,) = conn.execute(
        "insert into accounts (username, email, password_hash) values (%s, %s, %s)"
        " returning account_id",
        (username, email, auth.hash_password(password))).fetchone()
    return Account(account_id, username)


def authenticate(conn, identifier: str, password: str) -> Account | None:
    """`identifier` is a username or an email; the form doesn't ask which."""
    identifier = identifier.strip()
    row = conn.execute(
        "select account_id, username, password_hash from accounts"
        " where lower(username) = lower(%s) or lower(email) = lower(%s)",
        (identifier, identifier)).fetchone()
    if row is None or not auth.verify_password(password, row[2]):
        return None
    return Account(row[0], row[1])


def get_account(conn, account_id: int) -> Account | None:
    row = conn.execute("select account_id, username from accounts where account_id = %s",
                       (account_id,)).fetchone()
    return Account(*row) if row else None
