-- Watching a room's tournament together (C52): once the room completes, the host kicks
-- off and every screen follows one clock, round by round (game.watch); only the host can
-- skip ahead. What is stored is when the watch's first countdown began, which a skip
-- moves earlier; where everyone is comes from that and the app's clock. Epoch seconds
-- from the app server's clock, like turn_started_at (005), never compared with now().
--
-- `together` defaults OFF so every room made before this plays as it did (each friend
-- watches alone, at their own pace); the app makes new rooms with it on.
alter table rooms add column together boolean not null default false;
alter table rooms add column watch_started_at double precision;
-- When the room completed, so a seat may kick off if the host hasn't for a while.
alter table rooms add column completed_at double precision;
