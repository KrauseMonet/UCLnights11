-- A sealed auction's winner pays what he bid (C75), at the user's call: guessing how little
-- will do is the fun of a blind bid. The rule rides on the room, because an auction is
-- replayed every time it is read: a room made before keeps false, the second price it was
-- played at (C68), and every room made since is made with true.
alter table rooms add column first_price boolean not null default false;
