-- A seat's team sheet (C44): who starts in each slot and who sits on the bench, chosen
-- after the last pick in a bench room. game.draft.encode_sheet: "s" and fourteen base-36
-- pick indices, the eleven in slot order then the bench. NULL is the draft's own order
-- (the first eleven picks by most-played position, the last three on the bench), which is
-- how every seat before this plays, so the column changes nothing that already exists.
alter table room_seats add column sheet text
    check (sheet is null or sheet ~ '^s[0-9a-z]{14}$');
