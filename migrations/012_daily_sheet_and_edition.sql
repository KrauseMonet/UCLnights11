-- The daily challenge's team sheet and an admin's new challenge for a day (C55).
--
-- Both additive, and both default to what every stored row already means, so a played
-- day replays exactly as it did.

-- A ranked attempt's team sheet (C44's game.draft.encode_sheet: "s" and fourteen base-36
-- pick indices, the eleven in slot order then the bench). NULL is the draft's own order,
-- which is how every attempt before this was played.
alter table daily_results add column sheet text
    check (sheet is null or sheet ~ '^s[0-9a-z]{14}$');

-- The day's edition: 0 as first made, n once an admin has made it again n times. A new
-- edition takes its seeds from the day and this number, so it is as secret as the first.
alter table daily_challenges add column edition smallint not null default 0
    check (edition >= 0);
