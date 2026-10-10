-- Rooms: friends draft their own elevens and play one tournament together, with real
-- quarter-final sides in every place nobody took (SPEC §9).
--
-- A room stores who is in it and each seat's draft STATE STRING, nothing else. The
-- state is game.draft.encode verbatim ("SEED-FORMATION-moves"), so a seat's eleven is
-- replayed by the same function a solo draft is, and the tournament is a pure function
-- of (seed, size, the seats' states) -- recomputed on read, never stored (C10).

create table rooms (
    code        text primary key,
    size        smallint not null check (size in (2, 4, 8, 16, 32)),
    seed        integer not null check (seed > 0),
    host_id     integer not null references accounts (account_id) on delete cascade,
    status      text not null default 'lobby' check (status in ('lobby', 'drafting', 'complete')),
    -- Bumped on every write, so a polling client can tell new state from a stale reply.
    version     bigint not null default 0,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),

    constraint rooms_code_ck check (code ~ '^[A-Z0-9]{6}$')
);

create table room_seats (
    room_code   text not null references rooms (code) on delete cascade,
    account_id  integer not null references accounts (account_id) on delete cascade,
    seat        smallint not null check (seat >= 0 and seat < 32),
    formation   text not null default '433',
    -- NULL in the lobby; set for every seat when the host starts the draft.
    state       text,
    joined_at   timestamptz not null default now(),
    primary key (room_code, account_id),
    unique (room_code, seat)
);

create index room_seats_account_idx on room_seats (account_id);

comment on column room_seats.state is
    'game.draft.encode(seed, formation, moves): the seat''s whole draft. Every seat in a room shares the room''s seed, so all are dealt from one shuffle.';
