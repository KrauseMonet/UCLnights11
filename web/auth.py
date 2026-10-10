"""Password hashing and the session cookie, stdlib only (as on the cricket site).

PBKDF2-HMAC-SHA256 for passwords and plain HMAC-SHA256 for the cookie. There is no
session table: the signed cookie is the whole session, so verifying one is pure
computation from the cookie and SESSION_SECRET.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

PBKDF2_ITERATIONS = 600_000  # OWASP's PBKDF2-HMAC-SHA256 minimum (2023)

COOKIE_NAME = "ucl_auth"
SESSION_MAX_AGE_S = 60 * 60 * 24 * 30  # 30 days


class NotConfigured(RuntimeError):
    """Accounts need SESSION_SECRET and DATABASE_URL; the solo game needs neither."""


def _session_secret() -> str:
    # Read on use, not at import: the solo game imports this module and must run
    # without any secret configured.
    value = os.environ.get("SESSION_SECRET")
    if not value:
        raise NotConfigured("SESSION_SECRET is not set")
    return value


def hash_password(password: str, iterations: int = PBKDF2_ITERATIONS) -> str:
    """`pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`: self-describing, so raising
    the iteration count later never breaks a stored hash."""
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """A malformed stored value is a mismatch, never a crash."""
    try:
        scheme, iterations_s, salt_hex, hash_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations_s))
        return hmac.compare_digest(derived, bytes.fromhex(hash_hex))
    except (ValueError, TypeError):
        return False


def _sign(payload: str) -> str:
    return hmac.new(_session_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session_cookie(account_id: int, now: float | None = None) -> str:
    """`<account_id>.<expiry_epoch>.<hmac_hex>`, signed over the first two fields."""
    expiry = int(now if now is not None else time.time()) + SESSION_MAX_AGE_S
    payload = f"{account_id}.{expiry}"
    return f"{payload}.{_sign(payload)}"


def verify_session_cookie(token: str, now: float | None = None) -> int | None:
    """The account id, or None for anything malformed, tampered with or expired."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    account_id_s, expiry_s, sig = parts
    if not account_id_s.isdigit() or not expiry_s.isdigit():
        return None
    if not hmac.compare_digest(_sign(f"{account_id_s}.{expiry_s}"), sig):
        return None
    if int(expiry_s) < int(now if now is not None else time.time()):
        return None
    return int(account_id_s)
