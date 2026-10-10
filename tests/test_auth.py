"""Passwords and the session cookie."""

import pytest

from web import auth


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")


def test_a_password_verifies_and_a_wrong_one_does_not():
    h = auth.hash_password("correct horse", iterations=1000)
    assert h.startswith("pbkdf2_sha256$1000$")
    assert auth.verify_password("correct horse", h)
    assert not auth.verify_password("correct hors", h)


@pytest.mark.parametrize("stored", ["", "nonsense", "md5$1$aa$bb", "pbkdf2_sha256$x$zz$yy"])
def test_a_malformed_hash_is_a_mismatch_not_a_crash(stored):
    assert auth.verify_password("anything", stored) is False


def test_a_cookie_round_trips():
    assert auth.verify_session_cookie(auth.make_session_cookie(42)) == 42


def test_a_tampered_cookie_is_refused():
    token = auth.make_session_cookie(42)
    account, expiry, sig = token.split(".")
    assert auth.verify_session_cookie(f"43.{expiry}.{sig}") is None
    assert auth.verify_session_cookie(f"{account}.{int(expiry) + 1}.{sig}") is None
    assert auth.verify_session_cookie("42.1") is None


def test_an_expired_cookie_is_refused():
    token = auth.make_session_cookie(42, now=1_000_000)
    assert auth.verify_session_cookie(token, now=1_000_000 + auth.SESSION_MAX_AGE_S - 1) == 42
    assert auth.verify_session_cookie(token, now=1_000_000 + auth.SESSION_MAX_AGE_S + 1) is None


def test_a_cookie_signed_with_another_secret_is_refused(monkeypatch):
    token = auth.make_session_cookie(42)
    monkeypatch.setenv("SESSION_SECRET", "another")
    assert auth.verify_session_cookie(token) is None


def test_no_secret_is_a_clear_error_not_an_open_door(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET")
    with pytest.raises(auth.NotConfigured):
        auth.make_session_cookie(1)
