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
"""

from __future__ import annotations

import random
import secrets
from dataclasses import dataclass

from game.colours import palette
from game.deck import Deck
from game.draft import Move, Pick, Session, decode, encode, replay, why_not
from game.formations import DEFAULT, FORMATIONS
from game.tournament import ROOM_SIZES, Side
from web.accounts import Account

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O or 1/I to misread
CODE_LENGTH = 6
LOBBY_TTL_DAYS = 3
MY_ROOMS = 12

# A human eleven's colours, by seat: eight hues far enough apart to tell at a glance.
SEAT_COLOURS = ["#f5b83d", "#3ddc97", "#5aa9ff", "#ff7a59", "#c77dff", "#ff5c8a",
                "#2ec4d6", "#a3d65c"]


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

    @property
    def moves(self) -> list[Move]:
        return decode(self.state)[2] if self.state else []

    @property
    def picks(self) -> int:
        return sum(isinstance(m, Pick) for m in self.moves)

    @property
    def complete(self) -> bool:
        return self.picks == 11


@dataclass
class Room:
    code: str
    size: int
    seed: int
    host_id: int
    status: str
    version: int
    memory: bool
    seats: list[Seat]

    def seat_of(self, account_id: int | None) -> Seat | None:
        return next((s for s in self.seats if s.account_id == account_id), None)


def seat_palette(seat: int) -> dict[str, str]:
    colour = SEAT_COLOURS[seat % len(SEAT_COLOURS)]
    return palette(colour, colour)


def human_side(seat: Seat, session: Session) -> Side:
    """A seat's finished draft as a tournament side, in its seat's colours."""
    f = session.formation
    return Side(f"P{seat.seat}", seat.username, seat.username[:3].upper(), f, session.picks,
                owner=seat.account_id, club_name=seat.username, label=f.label,
                **seat_palette(seat.seat))


# -- reading ----------------------------------------------------------------

def load_room(conn, code: str, lock: bool = False) -> Room:
    code = code.strip().upper()
    row = conn.execute(
        "select code, size, seed, host_id, status, version, memory from rooms where code = %s"
        + (" for update" if lock else ""), (code,)).fetchone()
    if row is None:
        raise NotFound("no room with that code")
    seats = [Seat(*r) for r in conn.execute(
        "select s.account_id, a.username, s.seat, s.formation, s.state"
        "  from room_seats s join accounts a using (account_id)"
        " where s.room_code = %s order by s.seat", (code,))]
    return Room(*row, seats=seats)


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


def create_room(conn, account: Account, size: int, formation: str = DEFAULT,
                memory: bool = False) -> str:
    if size not in ROOM_SIZES:
        raise RoomError(f"a room holds {', '.join(map(str, ROOM_SIZES))} sides")
    _check_formation(formation)
    # Lobbies nobody started are swept here, lazily, rather than by a scheduled job.
    conn.execute("delete from rooms where status = 'lobby'"
                 " and updated_at < now() - make_interval(days => %s)", (LOBBY_TTL_DAYS,))
    seed = random.SystemRandom().randrange(1, 2**31 - 1)
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        row = conn.execute("insert into rooms (code, size, seed, host_id, memory) values (%s, %s, %s, %s, %s)"
                           " on conflict (code) do nothing returning code",
                           (code, size, seed, account.account_id, memory)).fetchone()
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


def start_room(conn, account: Account, code: str) -> None:
    room = load_room(conn, code, lock=True)
    if room.host_id != account.account_id:
        raise Forbidden("only the host can start the draft")
    if room.status != "lobby":
        raise Conflict("the draft has already started")
    for s in room.seats:
        conn.execute("update room_seats set state = %s where room_code = %s and account_id = %s",
                     (encode(room.seed, s.formation, []), room.code, s.account_id))
    _touch(conn, room, "drafting")


def _save_state(conn, room: Room, seat: Seat, state: str) -> None:
    conn.execute("update room_seats set state = %s where room_code = %s and account_id = %s",
                 (state, room.code, seat.account_id))
    seat.state = state
    _touch(conn, room, "complete" if all(s.complete for s in room.seats) else None)


def make_move(conn, deck: Deck, account: Account, code: str, move: Move, expect: int) -> None:
    """``expect`` is how many moves the player's screen had seen. A reply that arrives
    after the draft has moved on (a double click, a second tab) is refused rather than
    applied to a squad the player never looked at."""
    room = load_room(conn, code, lock=True)
    seat = room.seat_of(account.account_id)
    if seat is None:
        raise Forbidden("you are not in this room")
    if room.status != "drafting" or seat.complete:
        raise Conflict("there is nothing to draft")
    seed, formation, moves = decode(seat.state)
    if len(moves) != expect:
        raise Conflict("your draft moved on in another window; reloaded")
    moves = moves + [move]
    replay(deck, seed, formation, moves)              # raises IllegalMove
    _save_state(conn, room, seat, encode(seed, formation, moves))


def autopick(deck: Deck, state: str) -> str:
    """Finish a draft by taking the best-rated player each deal offers."""
    seed, formation, moves = decode(state)
    s = replay(deck, seed, formation, moves)
    while not s.complete:
        best = max((i for i, c in enumerate(s.deal.cards) if why_not(c, s.formation, s.picks) is None),
                   key=lambda i: s.deal.cards[i].rating)
        moves.append(Pick(best))
        s = replay(deck, seed, formation, moves)
    return encode(seed, formation, moves)


def seat_removed(conn, code: str) -> None:
    """After a seat is taken out of a started room (an account deleted by an admin): the
    room completes if every eleven left in it is full, as it would have when the last
    pick landed."""
    try:
        room = load_room(conn, code, lock=True)
    except NotFound:
        return
    done = room.status == "drafting" and room.seats and all(s.complete for s in room.seats)
    _touch(conn, room, "complete" if done else None)


def finish_drafts(conn, deck: Deck, account: Account, code: str) -> None:
    """The host's way past a friend who has wandered off: every unfinished eleven is
    completed with the best player each of its remaining deals offers."""
    room = load_room(conn, code, lock=True)
    if room.host_id != account.account_id:
        raise Forbidden("only the host can finish the drafts")
    if room.status != "drafting":
        raise Conflict("there is nothing to finish")
    for seat in room.seats:
        if not seat.complete:
            conn.execute("update room_seats set state = %s where room_code = %s and account_id = %s",
                         (autopick(deck, seat.state), room.code, seat.account_id))
    _touch(conn, room, "complete")


def sides(deck: Deck, room: Room) -> list[Side]:
    """Every seat's eleven as a side, in seat order. The room must be complete."""
    out = []
    for seat in room.seats:
        seed, formation, moves = decode(seat.state)
        out.append(human_side(seat, replay(deck, seed, formation, moves)))
    return out

