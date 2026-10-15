-- Changes made during a match (C60): a side whose manager makes the substitutions while
-- the match plays, rather than by a plan set before it.
--
-- Everything here is additive and defaults to what every stored row already means (plans
-- only), so every room and every day replays exactly as it did.

-- A live entry is game.draft.encode_live: "m", then per match its number, "a" and a break
-- if the rest of it was skipped with the plan, and "c" and three characters per change.
-- The daily plays one match, so only match 0 can appear.

-- The daily's ranked match while it is being played, when its changes are made as it
-- plays. It lives here, not in daily_results, until it ends: the board, the streak and the
-- profile only ever see finished attempts. `revealed` is how far the server has let the
-- match out (minutes): a change can only come at a break from there on, so nobody can see
-- what a change would have spared them and then make it.
create table daily_live (
    day          date not null references daily_challenges (day) on delete cascade,
    account_id   integer not null references accounts (account_id) on delete cascade,
    moves        text not null,
    plan         text check (plan is null or plan ~ '^p([0-9][ablhnw][0-9]{2}(o[0-9]{1,2})?(\.[0-9][ablhnw][0-9]{2}(o[0-9]{1,2})?){0,2})?$'),
    sheet        text check (sheet is null or sheet ~ '^s[0-9a-z]{14}$'),
    changes      text not null default 'm' check (changes ~ '^m(0(a[0-9a-n])?(c[0-9a-n][0-2][0-9a-d]){0,3})?$'),
    revealed     smallint not null default 0 check (revealed between 0 and 120),
    started_at   timestamptz not null default now(),
    primary key (day, account_id)
);

-- A finished ranked attempt whose changes were made during it; NULL: played by its plan,
-- as every attempt before this was.
alter table daily_results add column changes text
    check (changes is null or changes ~ '^m(0(a[0-9a-n])?(c[0-9a-n][0-2][0-9a-d]){0,3})?$');

-- Rooms. `live` is set for rooms made from now on: one that drafts a bench and watches
-- together then lets out each match minute by minute, stops for half-time, and lets a seat
-- that makes its own changes pause everyone's clock to make one. Rooms made before keep
-- false and watch exactly as they did.
alter table rooms add column live boolean not null default false;
-- A pause (epoch seconds from the app's clock, like watch_started_at) and the seat that
-- asked for it. Resuming moves watch_started_at on by the time paused, so every screen
-- carries on from the same moment.
alter table rooms add column watch_paused_at double precision;
alter table rooms add column watch_paused_by smallint;

-- A seat that makes its own changes, and the changes it has made (encode_live; the squad
-- indices are its own sheet's). NULL: its plan makes them, as every seat's did before.
alter table room_seats add column live text
    check (live is null or live ~ '^m([0-9a-z](a[0-9a-n])?(c[0-9a-n][0-2][0-9a-d]){0,3}(\.[0-9a-z](a[0-9a-n])?(c[0-9a-n][0-2][0-9a-d]){0,3})*)?$');
-- Pauses the seat has ended without a change, so one friend can't keep stopping the room.
alter table room_seats add column idle_pauses smallint not null default 0;

-- A saved solo result is keyed by its link, and a link that makes its own changes carries
-- them (C60): up to 17 matches' worth, so it can run past the 200 characters 006 allowed.
alter table results drop constraint results_natural_key_check;
alter table results add constraint results_natural_key_check check (char_length(natural_key) <= 600);
