"""Rooms: friends draft their own elevens and play one tournament together (SPEC §8).

A room moves lobby -> drafting -> complete. In the lobby people join with the room's
code and choose a formation; the host starts the draft; each seat then drafts on its
own, at its own pace, and the room completes the moment the last eleven is full. The
places nobody took go to real quarter-final sides (game.tournament.play_room).

Every seat in a room is dealt from the room's one seed, so friends see the same squads
in the same order -- until a squad offers someone nothing they can take and is redrawn
for them alone (the deal-time guarantee), which only happens when their eleven's open
places differ.

What is stored is who sits where and each seat's draft state string; a draft is
replayed by game.draft.replay exactly as a solo one is, so a move the deal did not
offer is refused by the same code. Every write locks the room row first, so two
seats finishing at once cannot both miss that the room is complete.

A BENCH ROOM (C42) drafts three more each and plays engine 2. After its picks each seat
chooses a substitution plan and says it is ready; the room completes only when every
seat is, because the tournament is replayed on every read and a plan changed after it
opened would change what everyone had seen. Rooms made before benches have none.
"""

from __future__ import annotations

import random
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from game.colours import palette
from game.deck import Deck
from game import shared_draft as shared
from game.draft import (BENCH, Change, IllegalMove, Move, Pick, Session, carry_plan, check_plan, check_sheet,
                        decode_plan, decode_sheet, decode_state, encode, encode_plan, encode_sheet, replay,
                        why_not)
from game.formations import DEFAULT, FORMATIONS
from game.tournament import ROOM_SIZES, Side, auto_plan
from web.accounts import Account

STYLES = ("turns", "own")
# A turn's clock is allowed this long past its last second before the server picks for
# the seat: the cricket site lost "the last second of every clock" to the round trip
# until it added the same grace (its A146).
CLOCK_GRACE_S = 2.0
# Read through this, so tests can move time on.
clock = time.time

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I to misread
CODE_LENGTH = 6
LOBBY_TTL_DAYS = 3
MY_ROOMS = 12

# A human eleven's colours, by seat: eight hues far enough apart to tell at a glance.
SEAT_COLOURS = ["#7cc4ff", "#ff7499", "#5ad692", "#ffb35c", "#a998ff", "#2ec4d6",
                "#f2c25a", "#ff7a4d"]


class RoomError(ValueError):
    status = 400


class NotFound(RoomError):
    status = 404


class Forbidden(RoomError):
    status = 403


class Conflict(RoomError):
    status = 409


@dataclass
class Seat:
    account_id: int
    username: str
    seat: int
    formation: str
    state: str | None
    plan: str | None = None         # a bench room's: encode_plan once the seat is ready
    sheet: str | None = None        # a bench room's team sheet (C44), encode_sheet; None: as drafted

    @property
    def bench(self) -> bool:
        return bool(self.state) and self.state.startswith("b")

    @property
    def moves(self) -> list[Move]:
        return decode_state(self.state)[2] if self.state else []

    @property
    def picks(self) -> int:
        return sum(isinstance(m, Pick) for m in self.moves)

    @property
    def total(self) -> int:
        return 11 + (BENCH if self.bench else 0)

    @property
    def complete(self) -> bool:
        """An own-pace seat is done: every pick made, and in a bench room its plan in."""
        return self.picks == self.total and (not self.bench or self.plan is not None)


@dataclass
class Room:
    code: str
    size: int
    seed: int
    host_id: int
    status: str
    version: int
    memory: bool
    style: str
    timer_seconds: int
    moves_text: str
    turn_started_at: float | None
    failure_reason: str | None
    bench: bool
    seats: list[Seat]

    def seat_of(self, account_id: int | None) -> Seat | None:
        return next((s for s in self.seats if s.account_id == account_id), None)

    @property
    def moves(self) -> list[int]:
        return shared.decode_moves(self.moves_text)

    @property
    def turns(self) -> bool:
        return self.style == "turns"

    @property
    def picks_each(self) -> int:
        return 11 + (BENCH if self.bench else 0)

    def clock_expired(self, now: float) -> bool:
        # Once every pick is made a bench room waits for plans, and no clock runs on those.
        return (self.turns and self.status == "drafting" and self.turn_started_at is not None
                and len(self.moves) < self.picks_each * len(self.seats)
                and now - self.turn_started_at > self.timer_seconds + CLOCK_GRACE_S)


def seat_palette(seat: int) -> dict[str, str]:
    colour = SEAT_COLOURS[seat % len(SEAT_COLOURS)]
    return palette(colour, colour)


def human_side(seat: Seat, session: Session) -> Side:
    """A seat's finished draft as a tournament side, in its seat's colours: its eleven,
    and in a bench room its bench and plan."""
    f = session.formation
    subs = session.subs()
    return Side(f"P{seat.seat}", seat.username, seat.username[:3].upper(), f, session.xi,
                owner=seat.account_id, club_name=seat.username, label=f.label,
                bench=session.bench, plan=auto_plan(session.bench) if subs is None else subs,
                **seat_palette(seat.seat))


def seat_session(deck: Deck, room: Room, seat: Seat, d: shared.SharedDraft | None = None) -> Session:
    """A seat's draft as a Session, with its plan: replayed from its state when it drafts
    at its own pace, or cut from the room's shared draft when the room takes turns."""
    plan = decode_plan(seat.plan) if seat.plan else None
    sheet = decode_sheet(seat.sheet) if seat.sheet else None
    if room.turns:
        d = d if d is not None else shared_of(deck, room)
        i = next(k for k, x in enumerate(room.seats) if x.account_id == seat.account_id)
        s = Session(room.seed, d.formations[i], picks=list(d.picks[i]),
                    bench_size=BENCH if room.bench else 0)
        if sheet is not None:
            check_sheet(s, sheet)
            s.sheet = sheet
        if plan is not None:
            check_plan(s, plan)
            s.plan = plan
        return s
    seed, formation, moves, bench, _ = decode_state(seat.state)
    return replay(deck, seed, formation, moves, bench, plan, sheet)


# -- reading ----------------------------------------------------------------

ROOM_COLUMNS = ("r.code, r.size, r.seed, r.host_id, r.status, r.version, r.memory, r.style, r.timer_seconds,"
                " r.moves, r.turn_started_at, r.failure_reason, r.bench")
SEAT_COLUMNS = "s.account_id, a.username, s.seat, s.formation, s.state, s.plan, s.sheet"


ROOM_FROM = ("  from rooms r left join room_seats s on s.room_code = r.code"
             "  left join accounts a on a.account_id = s.account_id")
_N_ROOM = len(ROOM_COLUMNS.split(","))


def _rooms_of(rows) -> dict[str, Room]:
    """Joined rows (a room's columns, then one seat's, seat order within each room) as
    rooms by code. A room with no seats comes back as one row of nulls on the seat side."""
    out: dict[str, Room] = {}
    for r in rows:
        room = out.get(r[0])
        if room is None:
            room = out[r[0]] = Room(*r[:_N_ROOM], seats=[])
        if r[_N_ROOM] is not None:
            room.seats.append(Seat(*r[_N_ROOM:]))
    return out


def load_room(conn, code: str, lock: bool = False) -> Room:
    """The room and its seats in ONE query: the room is read on every poll, and every
    query is a round trip to the database, so the seats ride along as joined rows."""
    code = code.strip().upper()
    if lock:
        # Wait at most 5 s for the row, then fail as a 503 the page retries, rather than
        # freezing every request behind one slow one (the cricket site's A92, A180).
        conn.execute("select set_config('lock_timeout', '5s', true)")
    rows = conn.execute(
        f"select {ROOM_COLUMNS}, {SEAT_COLUMNS}{ROOM_FROM} where r.code = %s order by s.seat"
        + (" for update of r" if lock else ""), (code,)).fetchall()
    if not rows:
        raise NotFound("no room with that code")
    return _rooms_of(rows)[code]


def load_rooms(conn, codes: list[str]) -> list[Room]:
    """Several rooms in one query, in the order asked; a code with no room is left out."""
    if not codes:
        return []
    found = _rooms_of(conn.execute(
        f"select {ROOM_COLUMNS}, {SEAT_COLUMNS}{ROOM_FROM} where r.code = any(%s) order by r.code, s.seat",
        (list(codes),)).fetchall())
    return [found[c] for c in codes if c in found]


def my_rooms(conn, account: Account) -> list[dict]:
    rows = conn.execute(
        "select r.code, r.size, r.status, r.host_id = %(me)s,"
        "       (select count(*) from room_seats x where x.room_code = r.code), r.updated_at"
        "  from rooms r join room_seats s on s.room_code = r.code and s.account_id = %(me)s"
        " order by r.updated_at desc limit %(n)s",
        {"me": account.account_id, "n": MY_ROOMS}).fetchall()
    return [{"code": c, "size": size, "status": st, "host": host, "players": n,
             "updated_at": at.isoformat()} for c, size, st, host, n, at in rows]


# -- writing ----------------------------------------------------------------

def _touch(conn, room: Room, status: str | None = None) -> None:
    conn.execute("update rooms set version = version + 1, updated_at = now(),"
                 " status = coalesce(%s, status) where code = %s", (status, room.code))


def _check_formation(formation: str) -> str:
    if formation not in FORMATIONS:
        raise RoomError(f"unknown formation {formation!r}")
    return formation


def _check_style(style: str, timer: int) -> None:
    if style not in STYLES:
        raise RoomError(f"unknown draft style {style!r}")
    if timer not in shared.TIMER_CHOICES:
        raise RoomError(f"a pick clock is {', '.join(map(str, shared.TIMER_CHOICES))} seconds")


def create_room(conn, account: Account, size: int, formation: str = DEFAULT,
                memory: bool = False, style: str = "turns",
                timer: int = shared.DEFAULT_TIMER, bench: bool = True) -> str:
    if size not in ROOM_SIZES:
        raise RoomError(f"a room holds {', '.join(map(str, ROOM_SIZES))} sides")
    _check_formation(formation)
    _check_style(style, timer)
    # Lobbies nobody started are swept here, lazily, rather than by a scheduled job.
    conn.execute("delete from rooms where status = 'lobby'"
                 " and updated_at < now() - make_interval(days => %s)", (LOBBY_TTL_DAYS,))
    seed = random.SystemRandom().randrange(1, 2**31 - 1)
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        row = conn.execute("insert into rooms (code, size, seed, host_id, memory, style, timer_seconds, bench)"
                           " values (%s, %s, %s, %s, %s, %s, %s, %s)"
                           " on conflict (code) do nothing returning code",
                           (code, size, seed, account.account_id, memory, style, timer, bench)).fetchone()
        if row:
            conn.execute("insert into room_seats (room_code, account_id, seat, formation)"
                         " values (%s, %s, 0, %s)", (code, account.account_id, formation))
            return code
    raise RuntimeError("could not find a free room code")


def join_room(conn, account: Account, code: str) -> Room:
    room = load_room(conn, code, lock=True)
    if room.seat_of(account.account_id):
        return room                                   # joining twice is harmless
    if room.status != "lobby":
        raise Conflict("this room has already started")
    if len(room.seats) >= room.size:
        raise Conflict("this room is full")
    taken = {s.seat for s in room.seats}
    seat = next(i for i in range(room.size) if i not in taken)
    conn.execute("insert into room_seats (room_code, account_id, seat) values (%s, %s, %s)",
                 (room.code, account.account_id, seat))
    _touch(conn, room)
    return room


def _remove(conn, room: Room, account_id: int) -> None:
    conn.execute("delete from room_seats where room_code = %s and account_id = %s",
                 (room.code, account_id))
    rest = [s for s in room.seats if s.account_id != account_id]
    if not rest:
        conn.execute("delete from rooms where code = %s", (room.code,))
        return
    if room.host_id == account_id:                    # the host's chair passes on
        conn.execute("update rooms set host_id = %s where code = %s", (rest[0].account_id, room.code))
    _touch(conn, room)


def leave_room(conn, account: Account, code: str) -> None:
    room = load_room(conn, code, lock=True)
    if not room.seat_of(account.account_id):
        raise Forbidden("you are not in this room")
    if room.status != "lobby":
        raise Conflict("the draft has started; you can no longer leave")
    _remove(conn, room, account.account_id)


def kick(conn, account: Account, code: str, account_id: int) -> None:
    room = load_room(conn, code, lock=True)
    if room.host_id != account.account_id:
        raise Forbidden("only the host can remove a player")
    if account_id == account.account_id:
        raise RoomError("the host leaves rather than removing themselves")
    if not room.seat_of(account_id):
        raise NotFound("that player is not in this room")
    if room.status != "lobby":
        raise Conflict("the draft has started")
    _remove(conn, room, account_id)


def set_formation(conn, account: Account, code: str, formation: str) -> None:
    room = load_room(conn, code, lock=True)
    if not room.seat_of(account.account_id):
        raise Forbidden("you are not in this room")
    if room.status != "lobby":
        raise Conflict("formations are fixed once the draft starts")
    conn.execute("update room_seats set formation = %s where room_code = %s and account_id = %s",
                 (_check_formation(formation), room.code, account.account_id))
    _touch(conn, room)


def set_memory(conn, account: Account, code: str, memory: bool) -> None:
    """Memory mode is the host's call, and only before the draft: switching it
    halfway would show some picks with ratings and others without."""
    room = load_room(conn, code, lock=True)
    if room.host_id != account.account_id:
        raise Forbidden("only the host can choose whether ratings are shown")
    if room.status != "lobby":
        raise Conflict("ratings are settled once the draft starts")
    conn.execute("update rooms set memory = %s where code = %s", (memory, room.code))
    _touch(conn, room)


def set_bench(conn, account: Account, code: str, bench: bool) -> None:
    """Whether the room drafts a bench (C42): the host's call, in the lobby. Without one,
    a turn of eleven rounds rather than fourteen, and engine 1."""
    room = load_room(conn, code, lock=True)
    if room.host_id != account.account_id:
        raise Forbidden("only the host can choose whether the room drafts a bench")
    if room.status != "lobby":
        raise Conflict("the bench is settled once the draft starts")
    conn.execute("update rooms set bench = %s where code = %s", (bench, room.code))
    _touch(conn, room)


def set_style(conn, account: Account, code: str, style: str, timer: int) -> None:
    """How the room drafts, and how long a turn lasts: the host's call, in the lobby."""
    room = load_room(conn, code, lock=True)
    if room.host_id != account.account_id:
        raise Forbidden("only the host can choose how the room drafts")
    if room.status != "lobby":
        raise Conflict("the draft has already started")
    _check_style(style, timer)
    conn.execute("update rooms set style = %s, timer_seconds = %s where code = %s", (style, timer, room.code))
    _touch(conn, room)


def start_room(conn, account: Account, code: str) -> None:
    room = load_room(conn, code, lock=True)
    if room.host_id != account.account_id:
        raise Forbidden("only the host can start the draft")
    if room.status != "lobby":
        raise Conflict("the draft has already started")
    if room.turns:
        conn.execute("update rooms set moves = '', turn_started_at = %s where code = %s", (clock(), room.code))
        _touch(conn, room, "drafting")
        return
    for s in room.seats:
        conn.execute("update room_seats set state = %s where room_code = %s and account_id = %s",
                     (encode(room.seed, s.formation, [], bench=room.bench), room.code, s.account_id))
    _touch(conn, room, "drafting")


def _save_state(conn, room: Room, seat: Seat, state: str) -> None:
    conn.execute("update room_seats set state = %s where room_code = %s and account_id = %s",
                 (state, room.code, seat.account_id))
    seat.state = state
    _touch(conn, room, "complete" if all(s.complete for s in room.seats) else None)



def make_move(conn, deck: Deck, account: Account, code: str, move: Move, expect: int) -> None:
    if load_room(conn, code).turns:
        if not isinstance(move, Pick):
            raise RoomError("there are no rerolls when the room takes turns")
        return make_turn_pick(conn, deck, account, code, move.index, expect)
    _own_pace_move(conn, deck, account, code, move, expect)


def _own_pace_move(conn, deck: Deck, account: Account, code: str, move: Move, expect: int) -> None:
    """``expect`` is how many moves the player's screen had seen. A reply that arrives
    after the draft has moved on (a double click, a second tab) is refused rather than
    applied to a squad the player never looked at."""
    room = load_room(conn, code, lock=True)
    seat = room.seat_of(account.account_id)
    if seat is None:
        raise Forbidden("you are not in this room")
    if room.status != "drafting" or seat.complete:
        raise Conflict("there is nothing to draft")
    seed, formation, moves, bench, _ = decode_state(seat.state)
    if len(moves) != expect:
        raise Conflict("your draft moved on in another window; reloaded")
    moves = moves + [move]
    replay(deck, seed, formation, moves, bench)       # raises IllegalMove
    _save_state(conn, room, seat, encode(seed, formation, moves, bench))


def autopick(deck: Deck, state: str) -> str:
    """Finish a draft by taking the best-rated player each deal offers."""
    seed, formation, moves, bench, _ = decode_state(state)
    s = replay(deck, seed, formation, moves, bench)
    while not s.complete:
        best = max((i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None),
                   key=lambda i: s.deal.cards[i].rating)
        moves.append(Pick(best))
        s = replay(deck, seed, formation, moves, bench)
    return encode(seed, formation, moves, bench)


def _auto_text(session: Session) -> str:
    """The automatic plan written out, for a seat that never said it was ready."""
    return encode_plan(tuple(Change(x.on, x.minute, x.when) for x in auto_plan(session.bench)))


def set_plan(conn, deck: Deck, account: Account, code: str, plan: tuple[Change, ...] | None) -> None:
    """A seat's substitution plan, which also says it is ready (C42); None is the automatic
    plan. Allowed once the seat's picks are all made and until the room completes, so a
    plan can be changed while friends are still drafting but never once the tournament is
    open."""
    room = load_room(conn, code, lock=True)
    seat = room.seat_of(account.account_id)
    if seat is None:
        raise Forbidden("you are not in this room")
    if not room.bench:
        raise RoomError("this room drafts no bench")
    if room.status != "drafting":
        raise Conflict("plans are settled once the tournament opens")
    s = seat_session(deck, room, replace_plan(seat, None))
    if len(s.picks) < s.total:
        raise Conflict("finish your picks first")
    text = _auto_text(s) if plan is None else encode_plan(plan)
    check_plan(s, decode_plan(text))                  # raises IllegalMove
    conn.execute("update room_seats set plan = %s where room_code = %s and account_id = %s",
                 (text, room.code, seat.account_id))
    seat.plan = text
    _touch(conn, room, "complete" if _all_in(deck, room) else None)


def replace_plan(seat: Seat, plan: str | None) -> Seat:
    return Seat(seat.account_id, seat.username, seat.seat, seat.formation, seat.state, plan, seat.sheet)


def set_sheet(conn, deck: Deck, account: Account, code: str, choose) -> None:
    """A seat's team sheet (C44): ``choose(session)`` gives the new one from the seat's
    finished draft (web.app.new_sheet), None for the draft's own order. Like the plan, it
    can change once the seat's picks are all made and until the room completes; unlike the
    plan it doesn't say the seat is ready. A plan already sent follows its men across."""
    room = load_room(conn, code, lock=True)
    seat = room.seat_of(account.account_id)
    if seat is None:
        raise Forbidden("you are not in this room")
    if not room.bench:
        raise RoomError("this room drafts no bench")
    if room.status != "drafting":
        raise Conflict("team sheets are settled once the tournament opens")
    before = seat_session(deck, room, seat)
    if len(before.picks) < before.total:
        raise Conflict("finish your picks first")
    sheet = choose(before)                            # raises IllegalMove
    text = None if sheet is None else encode_sheet(sheet)
    after = seat_session(deck, room, Seat(seat.account_id, seat.username, seat.seat, seat.formation,
                                          seat.state, None, text))
    plan = carry_plan(before, after, before.plan)
    seat.sheet, seat.plan = text, None if plan is None else encode_plan(plan)
    conn.execute("update room_seats set sheet = %s, plan = %s where room_code = %s and account_id = %s",
                 (seat.sheet, seat.plan, room.code, seat.account_id))
    _touch(conn, room)


def _all_in(deck: Deck, room: Room, d: shared.SharedDraft | None = None) -> bool:
    """Every pick made, and in a bench room every plan in."""
    if room.turns:
        d = d if d is not None else shared_of(deck, room)
        return d.complete and (not room.bench or all(s.plan is not None for s in room.seats))
    return all(s.complete for s in room.seats)


def seat_removed(conn, code: str) -> None:
    """After a seat is taken out of a started room (an account deleted by an admin): the
    room completes if every eleven left in it is full, as it would have when the last
    pick landed. A room that took turns can't lose a seat: every later pick's owner is
    its place in the snake, so the room is marked failed rather than replayed wrongly."""
    try:
        room = load_room(conn, code, lock=True)
    except NotFound:
        return
    if room.turns and room.status != "lobby":
        conn.execute("update rooms set failure_reason = %s where code = %s",
                     ("a player's account was deleted during the draft", room.code))
        _touch(conn, room, "failed")
        return
    done = room.status == "drafting" and room.seats and all(s.complete for s in room.seats)
    _touch(conn, room, "complete" if done else None)


def finish_drafts(conn, deck: Deck, account: Account, code: str) -> None:
    """The host's way past a friend who has wandered off: every unfinished eleven is
    completed with the best player each of its remaining deals offers. When the room
    takes turns, every remaining turn is played that way, in snake order."""
    room = load_room(conn, code, lock=True)
    if room.host_id != account.account_id:
        raise Forbidden("only the host can finish the drafts")
    if room.status != "drafting":
        raise Conflict("there is nothing to finish")
    if room.turns:
        moves = room.moves
        try:
            d = shared_of(deck, room, moves)
            while not d.complete:
                moves.append(shared.best_pick(d))
                d = shared_of(deck, room, moves)
        except shared.Stranded as e:
            _fail(conn, room, str(e))
            return
        room.moves_text = shared.encode_moves(moves)
        _plan_the_rest(conn, deck, room, d)
        _save_moves(conn, room, moves, "complete")
        return
    for seat in room.seats:
        if seat.picks < seat.total:
            seat.state = autopick(deck, seat.state)
            conn.execute("update room_seats set state = %s where room_code = %s and account_id = %s",
                         (seat.state, room.code, seat.account_id))
    _plan_the_rest(conn, deck, room)
    _touch(conn, room, "complete")


def _plan_the_rest(conn, deck: Deck, room: Room, d: shared.SharedDraft | None = None) -> None:
    """The host's finish, in a bench room: anyone not yet ready gets the automatic plan."""
    if not room.bench:
        return
    for seat in room.seats:
        if seat.plan is None:
            seat.plan = _auto_text(seat_session(deck, room, seat, d))
            conn.execute("update room_seats set plan = %s where room_code = %s and account_id = %s",
                         (seat.plan, room.code, seat.account_id))


def sides(deck: Deck, room: Room) -> list[Side]:
    """Every seat's eleven as a side, in seat order. The room must be complete."""
    d = shared_of(deck, room) if room.turns else None
    return [human_side(seat, seat_session(deck, room, seat, d)) for seat in room.seats]


def engine(room: Room) -> int:
    """A bench room plays engine 2 (C39); a room without one, engine 1, as every room
    made before benches did."""
    return 2 if room.bench else 1



# -- taking turns (C29) --------------------------------------------------------

SHARED_CACHE_SIZE = 64
_shared_cache: OrderedDict = OrderedDict()
_shared_lock = threading.Lock()   # requests run on a thread pool


def shared_of(deck: Deck, room: Room, moves: list[int] | None = None) -> shared.SharedDraft:
    """The room's draft, replayed: seats in the order they sat down, host first.

    Kept for the next request, because every seat polls the same room every second
    while a clock runs and each poll used to replay the whole draft two or three times.
    It is a pure function of the key, so a hit is the same answer; callers only read
    the draft (a move makes a new list of moves, hence a new key). The deck itself is
    held in the entry so a different deck (the tests') can never share one."""
    moves = room.moves if moves is None else moves
    key = (id(deck), room.seed, tuple(s.formation for s in room.seats), tuple(moves), room.bench)
    with _shared_lock:
        hit = _shared_cache.get(key)
        if hit is not None and hit[0] is deck:
            _shared_cache.move_to_end(key)
            return hit[1]
    d = shared.replay_shared(deck, room.seed, [s.formation for s in room.seats], moves, room.bench)
    with _shared_lock:
        _shared_cache[key] = (deck, d)
        while len(_shared_cache) > SHARED_CACHE_SIZE:
            _shared_cache.popitem(last=False)
    return d


def _save_moves(conn, room: Room, moves: list[int], status: str | None = None) -> None:
    conn.execute("update rooms set moves = %s, turn_started_at = %s where code = %s",
                 (shared.encode_moves(moves), clock(), room.code))
    room.moves_text = shared.encode_moves(moves)
    _touch(conn, room, status)


def _fail(conn, room: Room, reason: str) -> None:
    conn.execute("update rooms set failure_reason = %s where code = %s", (reason, room.code))
    _touch(conn, room, "failed")


def resolve(conn, deck: Deck, room: Room) -> bool:
    """Pick for a seat whose clock ran out. Called with the room locked, before any
    move and on any poll that finds the clock expired, so there is no scheduled job: if
    nobody is looking, the clock simply waits. One pick at most, since the pick starts
    the next turn's clock."""
    if not room.clock_expired(clock()):
        return False
    moves = room.moves
    try:
        d = shared_of(deck, room, moves)
        moves.append(shared.autopick(d))
        d = shared_of(deck, room, moves)
    except shared.Stranded as e:
        _fail(conn, room, str(e))
        return True
    _save_moves(conn, room, moves, "complete" if _all_in(deck, room, d) else None)
    return True


def resolve_if_due(conn, deck: Deck, code: str) -> Room:
    """For a poll: a lock-free look first, and the locked resolve only when a clock has
    actually run out (the cricket site's A92: polls taking the pick lock froze drafts).
    Returns the room as it now stands, so the poll needn't read it again."""
    room = load_room(conn, code)
    if room.clock_expired(clock()) and resolve(conn, deck, load_room(conn, code, lock=True)):
        room = load_room(conn, code)
    return room


def make_turn_pick(conn, deck: Deck, account: Account, code: str, index: int, expect: int) -> None:
    """``expect`` is how many picks the room had when this player chose: a pick sent
    after the turn moved on (the clock ran out, a second tab) is refused, never applied
    to a deal the player didn't see (the cricket site's A146)."""
    room = load_room(conn, code, lock=True)
    seat = room.seat_of(account.account_id)
    if seat is None:
        raise Forbidden("you are not in this room")
    if room.status != "drafting":
        raise Conflict("there is nothing to draft")
    if resolve(conn, deck, room):
        room = load_room(conn, code, lock=True)
        if room.status != "drafting":
            raise Conflict("the draft is over")
    moves = room.moves
    if len(moves) != expect:
        raise Conflict("that turn has passed; the room has moved on")
    d = shared_of(deck, room, moves)
    if d.active is None or room.seats[d.active].account_id != account.account_id:
        raise Conflict("it isn't your turn")
    moves.append(index)
    try:
        d = shared_of(deck, room, moves)        # raises IllegalMove on a pick the deal didn't offer
    except shared.Stranded as e:
        _fail(conn, room, str(e))
        return
    _save_moves(conn, room, moves, "complete" if _all_in(deck, room, d) else None)
