-- Saved results (C31) and the daily challenge (C32).
--
-- A saved result is a summary the server worked out by replaying the tournament itself
-- (never figures a browser sent), keyed so saving twice is harmless: a solo run by its
-- draft state, a room by its code, a daily by its day. The players' numbers ride along
-- as JSON, since the profile only ever reads one account's results at a time.

create table results (
    result_id    bigserial primary key,
    account_id   integer not null references accounts (account_id) on delete cascade,
    source       text not null check (source in ('solo', 'room', 'daily')),
    natural_key  text not null check (char_length(natural_key) <= 200),
    formation    text not null,
    reached      text not null,
    champion     boolean not null,
    won          smallint not null,
    drawn        smallint not null,
    lost         smallint not null,
    gf           smallint not null,
    ga           smallint not null,
    players      jsonb not null,
    created_at   timestamptz not null default now(),
    unique (account_id, source, natural_key)
);

create index results_account_idx on results (account_id, created_at desc);

-- One challenge a day, made the first time anyone asks for it and then fixed, so a
-- later change to the code can't change a day already played.
create table daily_challenges (
    day           date primary key,
    seed          bigint not null,          -- the deal: the same eleven squads for everyone
    formation     text not null,
    opponent      text not null,            -- a club-season key
    kind          text not null check (kind in ('win', 'win_by', 'clean_sheet', 'score')),
    target        smallint not null,
    success_rate  real not null,            -- measured when the challenge was made
    created_at    timestamptz not null default now()
);

-- One ranked attempt per account per day.
create table daily_results (
    day           date not null references daily_challenges (day) on delete cascade,
    account_id    integer not null references accounts (account_id) on delete cascade,
    moves         text not null,
    met           boolean not null,
    gf            smallint not null,
    ga            smallint not null,
    mark          real,
    submitted_at  timestamptz not null default now(),
    primary key (day, account_id)
);

create index daily_results_rank_idx on daily_results (day, met desc, (gf - ga) desc, gf desc);
