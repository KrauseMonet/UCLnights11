-- The league phase (C50): the full-format room is 36 places, as the competition has been
-- since 2024-25. New rooms are made in 2, 4, 8, 16 or 36 (game.tournament.ROOM_SIZES);
-- a room of 32 made before this keeps its size and still plays the group format, so 32
-- stays allowed here.
--
-- The column's check was created inline in 002, so Postgres named it rooms_size_check.
-- Dropped without "if exists": a different name should stop the migration, not leave
-- two checks of which the old one still refuses 36.
alter table rooms drop constraint rooms_size_check;
alter table rooms add constraint rooms_size_check check (size in (2, 4, 8, 16, 32, 36));
