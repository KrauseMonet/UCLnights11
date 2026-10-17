"""A dynasty's seasons on the profile (C66), against a real Postgres."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from web import auth, db
from web.app import app


@pytest.fixture(scope="module", autouse=True)
def configured(database):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", database)
    mp.setenv("SESSION_SECRET", "test-secret")
    mp.setattr(auth, "PBKDF2_ITERATIONS", 1000)
    mp.setattr(auth.hash_password, "__defaults__", (1000,))
    yield
    db.close_all()
    mp.undo()


_n = iter(range(10_000))


def player():
    name = f"dyn{next(_n)}"
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"username": name, "email": f"{name}@example.com", "password": "password1"})
    assert r.status_code == 200, r.text
    return c


def fill(c, d):
    while not d["complete"]:
        i = max((x for x in d["deal"]["cards"] if x["takeable"]), key=lambda x: x["rating"])["i"]
        d = c.post(f"/api/dynasty/{d['state']}/pick", json={"index": i}).json()
    return d


def two_seasons(c, seed=11):
    one = fill(c, c.post("/api/dynasty", json={"formation": "433", "seed": seed}).json())
    two = fill(c, c.post(f"/api/dynasty/{one['state']}/window", json={"formation": "433"}).json())
    return one["state"], two["state"]


def test_a_season_saves_once_and_counts_on_the_profile():
    c = player()
    one, two = two_seasons(c)
    r = c.post("/api/results", json={"source": "dynasty", "key": one})
    assert r.status_code == 200 and r.json()["new"]
    assert not c.post("/api/results", json={"source": "dynasty", "key": one}).json()["new"]
    assert c.get("/api/results/saved", params={"source": "dynasty", "key": one}).json()["saved"]
    assert c.post("/api/results", json={"source": "dynasty", "key": two}).json()["new"]
    t1 = c.get(f"/api/dynasty/{one}/tournament").json()
    t2 = c.get(f"/api/dynasty/{two}/tournament").json()
    p = c.get("/api/profile").json()
    assert p["tournaments"] == 2
    assert p["titles"] == (t1["reached"] == "Champions") + (t2["reached"] == "Champions")
    assert [r["source"] for r in p["recent"]] == ["dynasty", "dynasty"]
    (dyn,) = p["dynasties"]
    assert dyn["seasons"] == 2 and dyn["year"] == 2 and dyn["latest"] == two and dyn["seed"] == "11"
    assert dyn["titles"] == p["titles"]


def test_two_dynasties_are_two_rows():
    c = player()
    a, _ = two_seasons(c, 11)
    b, _ = two_seasons(c, 12)
    for k in (a, b):
        c.post("/api/results", json={"source": "dynasty", "key": k})
    assert len(c.get("/api/profile").json()["dynasties"]) == 2


def test_only_a_finished_dynasty_season_saves():
    c = player()
    assert c.post("/api/results", json={"source": "dynasty", "key": "l3-433"}).status_code == 400
    assert c.post("/api/results", json={"source": "dynasty", "key": "y3-433-0"}).status_code == 409


def test_a_dynastys_key_may_run_past_the_solo_limit(database):
    # Migration 016: a ten-season state with a sheet and plan every season measured 652.
    with psycopg.connect(database) as conn:
        aid = conn.execute("insert into accounts (username, email, password_hash) values ('longkey', 'l@example.com', 'x')"
                           " returning account_id").fetchone()[0]
        row = "insert into results (account_id, source, natural_key, formation, reached, champion, won, drawn, lost," \
              " gf, ga, players) values (%s, %s, %s, '4-3-3', 'Champions', true, 1, 0, 0, 1, 0, '[]')"
        conn.execute(row, (aid, "dynasty", "y" + "1" * 2399))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(row, (aid, "dynasty", "y" + "2" * 2400))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(row, (aid, "elsewhere", "k"))
