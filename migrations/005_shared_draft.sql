-- The turn-by-turn shared draft (C29): friends take turns in a snake order, a player
-- taken by anyone is gone for everyone, and a pick clock runs out into a random pick.
--
-- What is stored is the room's MOVES (deal indices, in order) and when the current turn
-- began; whose turn it is, what was dealt and who holds whom are replayed from them
-- (game.shared_draft). Rooms made before this keep style 'own', the draft where every
-- seat goes at its own pace, and play on exactly as before.

alter table rooms add column style text not null default 'own'
    check (style in ('own', 'turns'));
alter table rooms add column timer_seconds smallint not null default 30
    check (timer_seconds in (15, 30, 45));
alter table rooms add column moves text not null default ''
    check (moves ~ '^([0-9]{1,3}(\.[0-9]{1,3})*)?$');
-- Epoch seconds from the app server's clock (time.time()), only ever compared with
-- another reading of that same clock, never with Postgres now().
alter table rooms add column turn_started_at double precision;
alter table rooms add column failure_reason text;

alter table rooms drop constraint rooms_status_check;
alter table rooms add constraint rooms_status_check
    check (status in ('lobby', 'drafting', 'complete', 'failed'));
