"""The health check, browser failure reports and the admin tools."""

import pytest
from fastapi.testclient import TestClient

from web import admin, auth, db, failures
from web.app import app


def test_health_answers_without_touching_the_database(monkeypatch):
    def no(*a, **k):
        raise AssertionError("the health check must not open a connection")
    monkeypatch.setattr(db, "connection", no)
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["club_seasons"] > 200


def test_a_failure_report_is_a_quiet_204_with_no_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    r = TestClient(app).post("/api/client-failures", json={"kind": "error", "detail": "x", "page": "/"})
    assert r.status_code == 204


# -- with a database ----------------------------------------------------------

@pytest.fixture(scope="module")
def conn_url(database):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", database)
    mp.setenv("SESSION_SECRET", "test-secret")
    mp.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    mp.setattr(auth.hash_password, "__defaults__", (1000,))
    yield database
    db.close_all()
    mp.undo()


_n = iter(range(10_000))


def player(name=None):
    name = name or f"ops{next(_n)}"
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    assert r.status_code == 200, r.text
    c.account_id = r.json()["account"]["id"]
    return c


def test_reports_are_kept_trimmed_and_capped(conn_url, monkeypatch):
    c = TestClient(app)
    assert c.post("/api/client-failures", json={"kind": "error", "detail": "boom @ room.js:9",
                                                "page": "/room?join=1"}).status_code == 204
    assert c.post("/api/client-failures", json={"kind": "nonsense", "detail": "x", "page": "/"}).status_code == 204
    with db.connection() as conn:
        rows = failures.summary(conn)
        assert [(r["kind"], r["page"]) for r in rows if r["detail"] == "boom @ room.js:9"] == [("error", "/room")]
        assert not any(r["kind"] == "nonsense" for r in rows)
        # Refused before the insert; the table's check constraint is a second guard, so
        # this asks record() itself rather than the endpoint, which would swallow either.
        assert failures.record(conn, "nonsense", "x", "/") is False
        monkeypatch.setattr(failures, "MAX_PER_HOUR", 0)
        assert failures.record(conn, "error", "over the cap", "/") is False
        monkeypatch.setattr(failures, "MAX_PER_HOUR", 2000)
        conn.execute("insert into client_failure_reports (kind, detail, page, created_at)"
                     " values ('error', 'ancient', '/', now() - interval '40 days')")
        failures.record(conn, "error", "fresh", "/")
        (old,) = conn.execute("select count(*) from client_failure_reports where detail = 'ancient'").fetchone()
        assert old == 0


def test_admin_routes_are_a_404_to_everyone_else(conn_url, monkeypatch):
    stranger = player()
    monkeypatch.setenv("ADMIN_ACCOUNT_IDS", "")
    for path in ("/api/admin/overview", "/api/admin/accounts", "/api/admin/rooms"):
        assert stranger.get(path).status_code == 404
        assert TestClient(app).get(path).status_code == 404
    assert stranger.delete(f"/api/admin/accounts/{stranger.account_id}").status_code == 404
    assert "admin" not in stranger.get("/api/auth/me").json()["account"]


def test_an_admin_sees_the_site_and_can_reset_a_password(conn_url, monkeypatch):
    boss, forgetful = player(), player("forgetful_f")
    monkeypatch.setenv("ADMIN_ACCOUNT_IDS", str(boss.account_id))
    assert boss.get("/api/auth/me").json()["account"]["admin"] is True
    o = boss.get("/api/admin/overview").json()
    assert o["accounts"] >= 2 and len(o["signups"]) == 14
    found = boss.get("/api/admin/accounts", params={"q": "forgetful"}).json()["accounts"]
    assert [a["username"] for a in found] == ["forgetful_f"]
    assert boss.get("/api/admin/accounts", params={"q": "%"}).json()["accounts"] == []   # % is a character, not a wildcard
    assert boss.post(f"/api/admin/accounts/{forgetful.account_id}/password", json={"password": "short"}).status_code == 400
    assert boss.post(f"/api/admin/accounts/{forgetful.account_id}/password", json={"password": "brand-new-1"}).status_code == 200
    again = TestClient(app).post("/api/auth/login", json={"identifier": "forgetful_f", "password": "brand-new-1"})
    assert again.status_code == 200


def test_deleting_an_account_keeps_its_friends_rooms(conn_url, monkeypatch):
    boss, host, guest = player(), player(), player()
    monkeypatch.setenv("ADMIN_ACCOUNT_IDS", str(boss.account_id))
    code = host.post("/api/rooms", json={"bench": False, "together": False, "size": 4, "style": "own"}).json()["code"]
    guest.post(f"/api/rooms/{code}/join")
    host.post(f"/api/rooms/{code}/start")
    room = guest.get(f"/api/rooms/{code}").json()
    while not room["draft"]["complete"]:                       # the guest finishes; the host never does
        d = room["draft"]
        i = next(c["i"] for c in d["deal"]["cards"] if c["takeable"])
        moves = d["state"].split("-")
        room = guest.post(f"/api/rooms/{code}/pick",
                          json={"index": i, "expect": len(moves[2].split(".")) if len(moves) == 3 else 0}).json()
    assert room["status"] == "drafting"
    assert boss.delete(f"/api/admin/accounts/{boss.account_id}").status_code == 400       # not yourself
    assert boss.delete(f"/api/admin/accounts/{host.account_id}").status_code == 200
    after = guest.get(f"/api/rooms/{code}").json()
    assert after["is_host"] and [s["id"] for s in after["seats"]] == [guest.account_id]
    assert after["status"] == "complete"                       # the only eleven left is full
    assert guest.get(f"/api/rooms/{code}/tournament").status_code == 200


def test_deleting_the_only_player_takes_the_empty_room_too(conn_url, monkeypatch):
    boss, alone = player(), player()
    monkeypatch.setenv("ADMIN_ACCOUNT_IDS", str(boss.account_id))
    code = alone.post("/api/rooms", json={"bench": False, "together": False, "size": 2, "style": "own"}).json()["code"]
    boss.delete(f"/api/admin/accounts/{alone.account_id}")
    assert boss.get(f"/api/rooms/{code}").status_code == 404
    assert boss.delete("/api/admin/rooms/ZZZZZZ").status_code == 400


def test_admin_ids_ignore_junk():
    import os
    old = os.environ.get("ADMIN_ACCOUNT_IDS")
    os.environ["ADMIN_ACCOUNT_IDS"] = " 3, x, ,7 "
    try:
        assert admin.admin_ids() == {3, 7}
    finally:
        if old is None:
            del os.environ["ADMIN_ACCOUNT_IDS"]
        else:
            os.environ["ADMIN_ACCOUNT_IDS"] = old
