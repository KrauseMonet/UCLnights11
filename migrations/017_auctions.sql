-- Auction drafts (C70): the host's two new ways to draft, sealed-bid rounds (C68) and an
-- open auction (C69).
--
-- What is stored is the auction itself, in a column of its own: a sealed auction's closed
-- rounds of bids (game.auction.encode_rounds), or an open auction's events with the
-- server's times (game.open_auction.encode_events). `moves` keeps its pattern, which is a
-- turn room's picks. Who holds whom, who has what left and what is up for sale are
-- replayed from it, as a turn room's draft is from its moves. A sealed seat's bids for the
-- round still open are its own until the round closes, so they sit on its seat row, where
-- nobody else's reply reads them. Every room made before this keeps 'turns' or 'own' and
-- an empty auction.
alter table rooms drop constraint rooms_style_check;
alter table rooms add constraint rooms_style_check check (style in ('own', 'turns', 'sealed', 'open'));
-- A sealed round needs longer than a pick: a market of several squads to read.
alter table rooms drop constraint rooms_timer_seconds_check;
alter table rooms add constraint rooms_timer_seconds_check check (timer_seconds in (15, 30, 45, 60));
alter table rooms add column auction text not null default ''
    check (char_length(auction) <= 200000);
alter table room_seats add column bids text
    check (bids is null or bids ~ '^(-|[0-9]{1,3}\.[0-9]{1,4}(,[0-9]{1,3}\.[0-9]{1,4}){0,4})$');
