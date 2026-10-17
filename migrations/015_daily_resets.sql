-- How many times an admin has let an account play a day again (C63).
--
-- A ranked match is played from a seed of the day and the account (C59), so an attempt
-- reset by an admin replayed on the same luck: a different eleven very often got the same
-- score. The count goes into the seed, so each reset draws new luck. It lives in a table
-- of its own because a reset deletes the attempt it would otherwise sit on. No row is
-- zero resets, which keeps every attempt already stored replaying as it was played.
create table daily_resets (
    day        date     not null,
    account_id integer  not null references accounts (account_id) on delete cascade,
    resets     smallint not null check (resets > 0),
    primary key (day, account_id)
);
