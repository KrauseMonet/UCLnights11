"""The daily challenge's storage and seeds (C32); the rules are game.daily.

**The seeds are secret.** The deal's and the match's are derived from SESSION_SECRET
and the day by HMAC, so tomorrow's squads can't be known today, and, since the engine's
code is public, nobody can try every eleven offline and submit the one that wins. A
signed-out PRACTICE match uses a third seed, so practising says nothing about the
ranked result either.

**The day is UTC.** One challenge a day, made the first time anyone asks for it and
stored, so a later change to the code can't change a day already played. A scheduled
job makes today's and tomorrow's ahead of anyone asking (`prepare`, C49), so the first
visitor of a day doesn't wait for one to be measured. One ranked
attempt per account per day; the result is replayed on the server from the moves.

**Each account plays its own ranked match (C59)** on a day made since: the ranked seed
takes the account too, so friends' matches draw different luck. A day stored before
keeps one ranked seed for everyone and replays as it did.

**An admin can make a day again (C55)**: a new edition of it, with new squads, opponent
and goal, every attempt at the old one cleared. Its seeds come from the day and the
edition number, so it is as secret as the first.

**A ranked match can be played with changes made as it goes (C60).** It is held in
`daily_live` while it plays, and let out ten minutes at a time as the page asks: a change
comes at the break the match has been let out to, never earlier, so nobody can watch the
match to the end, see what a change would have spared them and then make it. When it has
all been let out (or the rest is skipped) it becomes the day's attempt like any other. One
left half-way is finished, with no more changes, the next time the board is read after
LIVE_TTL, or once the day is over.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

from game import daily as rules
from game import match
from game.deck import Deck
from game.draft import (Change, IllegalMove, LiveEntry, Pick, decode_live, decode_plan, decode_sheet, decode_state,
                        encode, encode_live, encode_plan, encode_sheet)
from game.formations import FORMATIONS
from game.journey import Journey, journey
from game.tournament import Fixture, Live, MatchPlan, Side, Tournament, bench_options, change_made, club_side
from web import auth, results
from web.accounts import Account

BOARD_SIZE = 50
STAGE = "Daily challenge"
# Every day made from now on has a bench and plays engine 2 (C42). A day already stored
# keeps what it was made with, so a played day never changes.
NEW_DAYS_BENCH = True
# Likewise every day made from now on plays each account's ranked match from its own seed
# (C59); a day already stored keeps the one seed it was played with.
NEW_DAYS_OWN_SEED = True


class DailyError(ValueError):
    status = 400


class AlreadyPlayed(DailyError):
    status = 409


class Changed(DailyError):
    """A draft made against an edition of today an admin has since replaced (C55)."""
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


def seed_for(day: date, purpose: str, edition: int = 0, account_id: int | None = None) -> int:
    """A secret seed for `purpose` ("deal", "ranked" or "practice") on `day`, in the day's
    `edition` (0, the day as first made, keeps the seeds every day before C55 had), and
    for one account's ranked match on a day made with its own seeds (C59; None keeps the
    day's one seed, as every day before had)."""
    text = (f"daily:{day.isoformat()}:{purpose}" + (f":{edition}" if edition else "")
            + (f":account:{account_id}" if account_id is not None else ""))
    mac = hmac.new(auth._session_secret().encode(), text.encode(), hashlib.sha256)
    return int.from_bytes(mac.digest()[:8], "big") % (2**31 - 2) + 1


def get_challenge(conn, deck: Deck, league: match.League, day: date) -> rules.Challenge:
    """The day's challenge, made and stored the first time anyone asks."""
    columns = "day, seed, formation, opponent, kind, target, success_rate, bench, edition, own_seed"
    row = conn.execute(f"select {columns} from daily_challenges where day = %s", (day,)).fetchone()
    if row is None:
        ch = rules.make_challenge(deck, league, day.isoformat(), seed_for(day, "deal"), NEW_DAYS_BENCH)
        conn.execute(f"insert into daily_challenges ({columns}) values (%s, %s, %s, %s, %s, %s, %s, %s, 0, %s)"
                     " on conflict (day) do nothing",
                     (day, ch.seed, ch.formation, ch.opponent, ch.kind, ch.target, ch.success_rate, ch.bench,
                      NEW_DAYS_OWN_SEED))
        row = conn.execute(f"select {columns} from daily_challenges where day = %s", (day,)).fetchone()
    d, seed, formation, opponent, kind, target, rate, bench, edition, own_seed = row
    return rules.Challenge(d.isoformat(), seed, formation, opponent, kind, target, rate, bench, edition, own_seed)


def check_edition(ch: rules.Challenge, edition: int | None) -> None:
    """A draft says which edition of the day it was made against; if an admin has made
    the day again since, its picks would replay into other squads, so it is refused.
    None (a page from before C55) is not checked."""
    if edition is not None and edition != ch.edition:
        raise Changed("today's challenge was made again since this draft began: here is the new one")


def prepare(conn, deck: Deck, league: match.League) -> list[date]:
    """Today's and tomorrow's challenges made and stored ahead of anyone asking: making one
    measures it against 200 matches (0.5 s on average, 2 s at worst), which the first
    visitor of the day used to wait for. Tomorrow's stays out of sight until it comes,
    since parse_day refuses a day that hasn't, and the only reads are by day. A day
    already stored is one query, so running this again changes nothing."""
    days = [today(), today() + timedelta(days=1)]
    for d in days:
        get_challenge(conn, deck, league, d)
    return days


def moves_of(ch: rules.Challenge, text: str) -> list[Pick]:
    """A day's moves from "3.0.12": picks only, eleven at most (fourteen with a bench)."""
    _, _, moves, _, _ = decode_state(encode(ch.seed, ch.formation, [], ch.bench) + (f"-{text}" if text else ""))
    return moves


def sheet_of(ch: rules.Challenge, sheet: tuple[int, ...] | list[int] | str | None) -> tuple[int, ...] | None:
    """A day's team sheet (C44), as sent (pick indices) or stored ("s..."); None is the
    draft's own order, and a day without a bench takes none."""
    if sheet is None:
        return None
    if not ch.bench:
        raise IllegalMove("this day has no bench")
    return decode_sheet(sheet) if isinstance(sheet, str) else tuple(sheet)


def plan_of(ch: rules.Challenge, plan: tuple[Change, ...] | str | None) -> tuple[Change, ...] | None:
    """A day's plan, as sent (changes) or stored ("p..."); None is the automatic plan, and
    a day without a bench takes none."""
    if plan is None:
        return None
    if not ch.bench:
        raise IllegalMove("this day has no bench")
    return decode_plan(plan) if isinstance(plan, str) else plan


def match_seed(ch: rules.Challenge, purpose: str, account_id: int | None = None) -> int:
    """The seed a match of the day is played from: on a day made with its own seeds (C59)
    a ranked match is the account's alone; practice and every older day share the day's."""
    own = purpose == "ranked" and ch.own_seed
    if own and account_id is None:
        raise ValueError("a ranked match on this day is played from its account's seed")
    return seed_for(date.fromisoformat(ch.day), purpose, ch.edition, account_id if own else None)


def play(deck: Deck, league: match.League, ch: rules.Challenge, moves: list, purpose: str,
         plan: tuple[Change, ...] | None = None, sheet: tuple[int, ...] | None = None,
         account_id: int | None = None, live: LiveEntry | None = None):
    """The finished eleven's match: (fixture, journey). Refuses an unfinished draft. A
    ranked match names its account, whose seed it is played from on a day made since C59.
    ``live`` is the changes made during the match (C60), for a side that makes its own;
    the match is then a live one (game.tournament.Live), on the same seed."""
    s = rules.draft(deck, ch, moves, plan, sheet)
    if not s.complete:
        raise IllegalMove("the squad isn't complete yet" if ch.bench else "the eleven isn't complete yet")
    you = rules.side_of(s)
    opp = club_side(deck.by_key[ch.opponent])
    seed = match_seed(ch, purpose, account_id)
    engine = ch.engine
    if live is not None:
        if not ch.bench:
            raise IllegalMove("this day has no bench")
        squad = [*you.xi, *you.bench]
        if any(not 0 <= on < len(you.bench) or not 0 <= off < len(squad) for _, on, off in live.changes):
            raise IllegalMove("a change names a man the squad hasn't got")
        you.live = {0: MatchPlan(tuple((m, on, squad[off].id) for m, on, off in live.changes), live.auto_from)}
        engine = Live(f"daily|{seed}", single=True)
    r = rules.play(league, seed, you, deck.by_key[ch.opponent], engine)
    fx = Fixture(STAGE, you, opp, r, ch.day)
    t = Tournament([you, opp], {}, {})
    t.fixtures = [fx]
    return fx, journey(t, you)


def mark_of(j: Journey) -> float | None:
    marks = [p.mark for p in j.players if p.mark is not None]
    return round(sum(marks) / len(marks), 2) if marks else None


def result_of(conn, day: date, account_id: int):
    return conn.execute("select moves, met, gf, ga, mark, submitted_at, plan, sheet, changes from daily_results"
                        " where day = %s and account_id = %s", (day, account_id)).fetchone()


def live_entry(text: str | None) -> LiveEntry | None:
    """A stored live part (C60) as the match's entry; None for an attempt played by its plan."""
    return None if text is None else decode_live(text).get(0, LiveEntry())


def submit(conn, deck: Deck, league: match.League, account: Account, day: date, text: str,
           plan: tuple[Change, ...] | None = None, sheet: list[int] | None = None, edition: int | None = None):
    """The ranked attempt. Only today's, only once."""
    if day != today():
        raise DailyError("only today's challenge can be played")
    if result_of(conn, day, account.account_id) is not None or live_of(conn, day, account.account_id) is not None:
        raise AlreadyPlayed("you've played today's challenge")
    ch = get_challenge(conn, deck, league, day)
    check_edition(ch, edition)
    moves = moves_of(ch, text)
    plan, sheet = plan_of(ch, plan), sheet_of(ch, sheet)
    fx, j = play(deck, league, ch, moves, "ranked", plan, sheet, account.account_id)
    r = fx.result
    ok = rules.met(ch.kind, ch.target, r.home_goals, r.away_goals)
    # The plan is stored as played, the automatic one written out, so the match replays.
    stored = None if not ch.bench else encode_plan(plan if plan is not None else rules.auto_changes(fx.home.bench))
    inserted = conn.execute(
        "insert into daily_results (day, account_id, moves, met, gf, ga, mark, plan, sheet)"
        " values (%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing returning 1",
        (day, account.account_id, text, ok, r.home_goals, r.away_goals, mark_of(j), stored,
         None if sheet is None else encode_sheet(sheet))).fetchone()
    if inserted is None:                      # a second tab beat this one to it
        raise AlreadyPlayed("you've played today's challenge")
    results.save(conn, account, "daily", ch.day, j, FORMATIONS[ch.formation].label,
                 reached="Goal met" if ok else "Goal missed")
    return ch, fx, j, ok


# -- a ranked match with changes made as it plays (C60) ----------------------------------

LIVE_STEP = 5                      # minutes let out at a time: a change comes at most this far after it is asked for, plus what the page holds ahead
LIVE_TTL = timedelta(minutes=30)   # a match left half-way is finished after this


def live_of(conn, day: date, account_id: int):
    """(moves, plan, sheet, changes, revealed, started_at) of a ranked match being played."""
    return conn.execute("select moves, plan, sheet, changes, revealed, started_at from daily_live"
                        " where day = %s and account_id = %s", (day, account_id)).fetchone()


def replay_live(deck: Deck, league: match.League, ch: rules.Challenge, row, account_id: int,
                 changes: str | None = None):
    moves, plan, sheet, stored = row[0], row[1], row[2], row[3]
    return play(deck, league, ch, moves_of(ch, moves), "ranked", plan_of(ch, plan), sheet_of(ch, sheet),
                account_id, live_entry(changes or stored))


def start_live(conn, deck: Deck, league: match.League, account: Account, day: date, text: str,
               plan: tuple[Change, ...] | None = None, sheet: list[int] | None = None, edition: int | None = None):
    """Kick off the ranked match of a side that makes its own changes: nothing is ranked yet,
    and the first two steps are let out. (challenge, fixture, journey, revealed)."""
    if day != today():
        raise DailyError("only today's challenge can be played")
    if result_of(conn, day, account.account_id) is not None or live_of(conn, day, account.account_id) is not None:
        raise AlreadyPlayed("you've played today's challenge")
    ch = get_challenge(conn, deck, league, day)
    check_edition(ch, edition)
    if not ch.bench:
        raise DailyError("this day has no bench")
    moves = moves_of(ch, text)
    plan, sheet = plan_of(ch, plan), sheet_of(ch, sheet)
    fx, j = play(deck, league, ch, moves, "ranked", plan, sheet, account.account_id, LiveEntry())
    stored = encode_plan(plan if plan is not None else rules.auto_changes(fx.home.bench))
    inserted = conn.execute(
        "insert into daily_live (day, account_id, moves, plan, sheet, revealed) values (%s,%s,%s,%s,%s,%s)"
        " on conflict do nothing returning 1",
        (day, account.account_id, text, stored, None if sheet is None else encode_sheet(sheet), 2 * LIVE_STEP)).fetchone()
    if inserted is None:
        raise AlreadyPlayed("you've played today's challenge")
    return ch, fx, j, 2 * LIVE_STEP


def _held(conn, day: date, account: Account):
    row = conn.execute("select moves, plan, sheet, changes, revealed, started_at from daily_live"
                       " where day = %s and account_id = %s for update", (day, account.account_id)).fetchone()
    if row is None:
        raise AlreadyPlayed("that match is over")
    return row


def live_step(conn, deck: Deck, league: match.League, account: Account, day: date, action: str,
              on: int | None = None, off: str | None = None, auto: bool = False):
    """One step of a ranked match being played (C60): "more" lets out the next LIVE_STEP
    minutes, "options" says what can change at the break it has got to, "sub" makes a
    change there, "finish" plays the rest (with the plan if ``auto``). Returns (challenge,
    fixture, journey, revealed, finished, options)."""
    ch = get_challenge(conn, deck, league, day)
    row = _held(conn, day, account)
    revealed = row[4]
    fx, j = replay_live(deck, league, ch, row, account.account_id)
    end = 120 if fx.result.extra_time else 90
    options = None
    if action == "more":
        revealed = min(end, revealed + LIVE_STEP)
    elif action == "options":
        options = revealed
    elif action == "sub":
        entry = live_entry(row[3])
        if off not in bench_options(fx.home, fx.result, 0, revealed).get(on, []):
            raise IllegalMove("that change can't be made now")
        squad = [c.id for c in [*fx.home.xi, *fx.home.bench]]
        text = encode_live({0: replace(entry, changes=(*entry.changes, (revealed, on, squad.index(off))))})
        fx2, j2 = replay_live(deck, league, ch, row, account.account_id, text)
        if not change_made(fx2.result, 0, revealed, fx.home.bench[on], off):
            raise IllegalMove("that change can't be made now")
        conn.execute("update daily_live set changes = %s where day = %s and account_id = %s",
                     (text, day, account.account_id))
        fx, j = fx2, j2
        end = 120 if fx.result.extra_time else 90
    elif action == "finish":
        if auto:
            entry = live_entry(row[3])
            text = encode_live({0: replace(entry, auto_from=min(revealed, 115))})
            conn.execute("update daily_live set changes = %s where day = %s and account_id = %s",
                         (text, day, account.account_id))
            fx, j = replay_live(deck, league, ch, row, account.account_id, text)
        revealed = 120 if fx.result.extra_time else 90
        end = revealed
    else:
        raise DailyError(f"no step {action!r}")
    if revealed >= end:
        finish_live(conn, deck, league, day, account.account_id)
        return ch, fx, j, revealed, True, None
    conn.execute("update daily_live set revealed = %s where day = %s and account_id = %s",
                 (revealed, day, account.account_id))
    return ch, fx, j, revealed, False, options


def finish_live(conn, deck: Deck, league: match.League, day: date, account_id: int) -> bool:
    """A ranked match being played becomes the day's attempt, with the changes made in it,
    ranked and saved like any other. False if there was none (another tab finished it)."""
    row = conn.execute("delete from daily_live where day = %s and account_id = %s"
                       " returning moves, plan, sheet, changes, revealed, started_at",
                       (day, account_id)).fetchone()
    if row is None:
        return False
    ch = get_challenge(conn, deck, league, day)
    fx, j = replay_live(deck, league, ch, row, account_id)
    r = fx.result
    ok = rules.met(ch.kind, ch.target, r.home_goals, r.away_goals)
    conn.execute(
        "insert into daily_results (day, account_id, moves, met, gf, ga, mark, plan, sheet, changes, submitted_at)"
        " values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing",
        (day, account_id, row[0], ok, r.home_goals, r.away_goals, mark_of(j), row[1], row[2], row[3], row[5]))
    results.save(conn, Account(account_id, ""), "daily", ch.day, j, FORMATIONS[ch.formation].label,
                 reached="Goal met" if ok else "Goal missed")
    return True


def finish_stale(conn, deck: Deck, league: match.League, day: date) -> int:
    """Ranked matches left half-way (C60): finished with the changes made so far, once
    LIVE_TTL has passed or the day is over. How many."""
    cutoff = datetime.now(timezone.utc) - LIVE_TTL
    ids = [a for (a,) in conn.execute(
        "select account_id from daily_live where day = %s and (started_at < %s or day < %s)",
        (day, cutoff, today())).fetchall()]
    for a in ids:
        finish_live(conn, deck, league, day, a)
    return len(ids)


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


# -- an admin's controls (C55) ------------------------------------------------------

def reset(conn, day: date, account_id: int) -> bool:
    """An admin's way to let one account play a day again: the attempt and its saved
    result go."""
    gone = conn.execute("delete from daily_results where day = %s and account_id = %s returning 1",
                        (day, account_id)).fetchone()
    gone = conn.execute("delete from daily_live where day = %s and account_id = %s returning 1",
                        (day, account_id)).fetchone() or gone
    conn.execute("delete from results where account_id = %s and source = 'daily' and natural_key = %s",
                 (account_id, day.isoformat()))
    return gone is not None


def clear(conn, day: date) -> int:
    """Every attempt at a day, and the results they saved, gone: the same challenge, open
    to everyone again. How many attempts there were."""
    n = len(conn.execute("delete from daily_results where day = %s returning 1", (day,)).fetchall())
    n += len(conn.execute("delete from daily_live where day = %s returning 1", (day,)).fetchall())
    conn.execute("delete from results where source = 'daily' and natural_key = %s", (day.isoformat(),))
    return n


def remake(conn, deck: Deck, league: match.League, day: date) -> rules.Challenge:
    """Today made again: the next edition, with its own secret seeds, so new squads, a new
    opponent and a new goal, measured into the band as every day is. Every attempt at the
    old edition is cleared, since its picks name cards in squads that are no longer dealt.
    Only today: a past day's board is history, and tomorrow's must stay unseen."""
    if day != today():
        raise DailyError("only today's challenge can be made again")
    old = get_challenge(conn, deck, league, day)
    # Locked, so two admins pressing at once make one edition each, one after the other.
    (edition,) = conn.execute("select edition from daily_challenges where day = %s for update", (day,)).fetchone()
    edition += 1
    ch = rules.make_challenge(deck, league, day.isoformat(), seed_for(day, "deal", edition), old.bench)
    clear(conn, day)
    conn.execute("update daily_challenges set seed = %s, formation = %s, opponent = %s, kind = %s, target = %s,"
                 " success_rate = %s, edition = %s, created_at = now() where day = %s",
                 (ch.seed, ch.formation, ch.opponent, ch.kind, ch.target, ch.success_rate, edition, day))
    return get_challenge(conn, deck, league, day)


def admin_day(conn, day: date) -> dict:
    """A day's attempts for the admin page, best first, each with its account id."""
    rows = conn.execute(
        f"select d.account_id, a.username, d.met, d.gf, d.ga, d.mark, d.submitted_at, d.sheet is not null"
        f"  from daily_results d join accounts a using (account_id) where d.day = %s order by {RANK_ORDER}",
        (day,)).fetchall()
    return {"rows": [{"id": i, "username": u, "met": m, "gf": gf, "ga": ga, "mark": mk,
                      "submitted_at": at.isoformat(), "sheet": sh} for i, u, m, gf, ga, mk, at, sh in rows]}


def recent_days(conn, upto: date, n: int = 14) -> list[dict]:
    """The last `n` stored days up to `upto` (never a day still to come), with how many
    played and met the goal."""
    rows = conn.execute(
        "select c.day, c.edition, count(d.account_id), count(d.account_id) filter (where d.met)"
        "  from daily_challenges c left join daily_results d using (day)"
        " where c.day <= %s group by c.day order by c.day desc limit %s", (upto, n)).fetchall()
    return [{"day": d.isoformat(), "edition": e, "entries": n, "met": m} for d, e, n, m in rows]
