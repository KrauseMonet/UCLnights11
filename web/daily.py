"""The daily challenge's storage and seeds (C32); the rules are game.daily.

**The seeds are secret.** The deal's and the match's are derived from SESSION_SECRET
and the day by HMAC, so tomorrow's squads can't be known today, and, since the engine's
code is public, nobody can try every eleven offline and submit the one that wins. A
signed-out PRACTICE match uses a third seed, so practising says nothing about the
ranked result either.

**The day is UTC.** One challenge a day, made the first time anyone asks for it and
stored, so a later change to the code can't change a day already played. One ranked
attempt per account per day; the result is replayed on the server from the moves.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime, timezone

from game import daily as rules
from game import match
from game.deck import Deck
from game.draft import IllegalMove, Pick, decode, encode
from game.formations import FORMATIONS
from game.journey import Journey, journey
from game.tournament import Fixture, Side, Tournament, club_side
from web import auth, results
from web.accounts import Account

BOARD_SIZE = 50
STAGE = "Daily challenge"


class DailyError(ValueError):
    status = 400


class AlreadyPlayed(DailyError):
    status = 409


def today() -> date:
    return datetime.now(timezone.utc).date()


def parse_day(text: str | None) -> date:
    if not text:
        return today()
    try:
        d = date.fromisoformat(text)
    except ValueError:
        raise DailyError("a day is YYYY-MM-DD") from None
    if d > today():
        raise DailyError("that day hasn't come yet")
    return d


def seed_for(day: date, purpose: str) -> int:
    """A secret seed for `purpose` ("deal", "ranked" or "practice") on `day`."""
    mac = hmac.new(auth._session_secret().encode(), f"daily:{day.isoformat()}:{purpose}".encode(), hashlib.sha256)
    return int.from_bytes(mac.digest()[:8], "big") % (2**31 - 2) + 1


def get_challenge(conn, deck: Deck, league: match.League, day: date) -> rules.Challenge:
    """The day's challenge, made and stored the first time anyone asks."""
    row = conn.execute("select day, seed, formation, opponent, kind, target, success_rate"
                       " from daily_challenges where day = %s", (day,)).fetchone()
    if row is None:
        ch = rules.make_challenge(deck, league, day.isoformat(), seed_for(day, "deal"))
        conn.execute("insert into daily_challenges (day, seed, formation, opponent, kind, target, success_rate)"
                     " values (%s, %s, %s, %s, %s, %s, %s) on conflict (day) do nothing",
                     (day, ch.seed, ch.formation, ch.opponent, ch.kind, ch.target, ch.success_rate))
        row = conn.execute("select day, seed, formation, opponent, kind, target, success_rate"
                           " from daily_challenges where day = %s", (day,)).fetchone()
    d, seed, formation, opponent, kind, target, rate = row
    return rules.Challenge(d.isoformat(), seed, formation, opponent, kind, target, rate)


def moves_of(ch: rules.Challenge, text: str) -> list[Pick]:
    """A day's moves from "3.0.12": picks only, eleven at most."""
    _, _, moves = decode(encode(ch.seed, ch.formation, []) + (f"-{text}" if text else ""))
    return moves


def play(deck: Deck, league: match.League, ch: rules.Challenge, moves: list, purpose: str):
    """The finished eleven's match: (fixture, journey). Refuses an unfinished draft."""
    s = rules.draft(deck, ch, moves)
    if not s.complete:
        raise IllegalMove("the eleven isn't complete yet")
    you = Side("YOU", "Your XI", "YOU", s.formation, s.picks, you=True)
    opp = club_side(deck.by_key[ch.opponent])
    day = date.fromisoformat(ch.day)
    r = rules.play(league, seed_for(day, purpose), s.picks, deck.by_key[ch.opponent])
    fx = Fixture(STAGE, you, opp, r, ch.day)
    t = Tournament([you, opp], {}, {})
    t.fixtures = [fx]
    return fx, journey(t, you)


def mark_of(j: Journey) -> float | None:
    marks = [p.mark for p in j.players if p.mark is not None]
    return round(sum(marks) / len(marks), 2) if marks else None


def result_of(conn, day: date, account_id: int):
    return conn.execute("select moves, met, gf, ga, mark, submitted_at from daily_results"
                        " where day = %s and account_id = %s", (day, account_id)).fetchone()


def submit(conn, deck: Deck, league: match.League, account: Account, day: date, text: str):
    """The ranked attempt. Only today's, only once."""
    if day != today():
        raise DailyError("only today's challenge can be played")
    if result_of(conn, day, account.account_id) is not None:
        raise AlreadyPlayed("you've played today's challenge")
    ch = get_challenge(conn, deck, league, day)
    moves = moves_of(ch, text)
    fx, j = play(deck, league, ch, moves, "ranked")
    r = fx.result
    ok = rules.met(ch.kind, ch.target, r.home_goals, r.away_goals)
    inserted = conn.execute(
        "insert into daily_results (day, account_id, moves, met, gf, ga, mark) values (%s,%s,%s,%s,%s,%s,%s)"
        " on conflict do nothing returning 1",
        (day, account.account_id, text, ok, r.home_goals, r.away_goals, mark_of(j))).fetchone()
    if inserted is None:                      # a second tab beat this one to it
        raise AlreadyPlayed("you've played today's challenge")
    results.save(conn, account, "daily", ch.day, j, FORMATIONS[ch.formation].label,
                 reached="Goal met" if ok else "Goal missed")
    return ch, fx, j, ok


RANK_ORDER = "met desc, (gf - ga) desc, gf desc, mark desc nulls last, submitted_at asc"


def board(conn, day: date, me: Account | None) -> dict:
    rows = conn.execute(
        f"select a.username, d.met, d.gf, d.ga, d.mark, d.account_id from daily_results d"
        f"  join accounts a using (account_id) where d.day = %s order by {RANK_ORDER} limit %s",
        (day, BOARD_SIZE)).fetchall()
    entries, met = conn.execute("select count(*), count(*) filter (where met) from daily_results where day = %s",
                                (day,)).fetchone()
    mine = None
    if me is not None:
        r = conn.execute(
            f"select rn, met, gf, ga, mark from (select account_id, met, gf, ga, mark,"
            f"  row_number() over (order by {RANK_ORDER}) as rn from daily_results where day = %s) ranked"
            f" where account_id = %s", (day, me.account_id)).fetchone()
        if r is not None:
            mine = {"rank": r[0], "met": r[1], "gf": r[2], "ga": r[3], "mark": r[4]}
    return {"entries": entries, "met": met, "mine": mine,
            "rows": [{"rank": i + 1, "username": u, "met": m, "gf": gf, "ga": ga, "mark": mk,
                      "you": me is not None and aid == me.account_id}
                     for i, (u, m, gf, ga, mk, aid) in enumerate(rows)]}


def days_played(conn, account_id: int) -> list[date]:
    return [d for (d,) in conn.execute("select day from daily_results where account_id = %s", (account_id,))]


def reset(conn, day: date, account_id: int) -> bool:
    """An admin's way to play a day again (for testing): the attempt and its saved result go."""
    gone = conn.execute("delete from daily_results where day = %s and account_id = %s returning 1",
                        (day, account_id)).fetchone()
    conn.execute("delete from results where account_id = %s and source = 'daily' and natural_key = %s",
                 (account_id, day.isoformat()))
    return gone is not None
