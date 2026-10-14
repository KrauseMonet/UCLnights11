-- Each account's own ranked match in the daily challenge (C59).
--
-- A day made with this set plays every ranked attempt from a seed of the day AND the
-- account, so two friends' matches draw different luck. Before it, everyone's ranked
-- match drew from one seed for the day, and different elevens kept landing on the same
-- score. Additive and defaulting to false, so every day already stored (and its
-- attempts) replays exactly as it did.
alter table daily_challenges add column own_seed boolean not null default false;
