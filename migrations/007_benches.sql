-- Benches in rooms and the daily challenge (C42): three more picks after the eleven, a
-- plan for using them, and the match engine with tiredness and substitutes (C39-C41).
--
-- Everything here is additive and defaults to OFF, so every room and every day made
-- before it replays exactly as it did: eleven picks, no plan, engine 1.

-- A room drafts a bench when this is set (the host's call, in the lobby).
alter table rooms add column bench boolean not null default false;

-- A seat's substitution plan, game.draft.encode_plan ("p0b60o9.1a70"; "p" alone is no
-- changes). NULL until the seat says it is ready; a bench room completes only when every
-- seat has one, because the tournament is replayed on every read and a plan changed
-- after it opened would change what everyone had already seen.
alter table room_seats add column plan text
    check (plan is null or plan ~ '^p([0-9][ablhnw][0-9]{2}(o[0-9]{1,2})?(\.[0-9][ablhnw][0-9]{2}(o[0-9]{1,2})?){0,2})?$');

-- A day made with a bench is drafted with one and played by engine 2; days made before
-- keep false and play as they did.
alter table daily_challenges add column bench boolean not null default false;

-- The plan of a ranked daily attempt, as above; NULL for a day without a bench.
alter table daily_results add column plan text
    check (plan is null or plan ~ '^p([0-9][ablhnw][0-9]{2}(o[0-9]{1,2})?(\.[0-9][ablhnw][0-9]{2}(o[0-9]{1,2})?){0,2})?$');
