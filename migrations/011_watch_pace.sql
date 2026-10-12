-- The pace a room watches its tournament together at (C54), the host's choice: 'fast',
-- 'normal' or 'slow' (game.watch.PACES, seconds per match minute). Null for every room
-- made before this, which keeps C52's 0.1 s a minute, so a watch already under way or
-- already seen keeps its length and its end. The app makes new rooms 'normal'.
alter table rooms add column watch_pace text check (watch_pace in ('fast', 'normal', 'slow'));
