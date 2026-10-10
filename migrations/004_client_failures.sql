-- What browsers saw go wrong: a script error, or an API call that failed on the server.
-- Taken from the cricket site (its A180), where Vercel keeping logs for about an hour
-- meant a failure someone met in the evening was gone by the time anyone looked.
--
-- Deliberately nothing that identifies a person: no account, no IP address, no query
-- string. Kept 30 days (web.failures prunes as it writes).

create table client_failure_reports (
    report_id   bigserial primary key,
    kind        text not null check (kind in ('api', 'error', 'rejection')),
    detail      text not null check (char_length(detail) <= 500),
    page        text not null check (char_length(page) <= 100),
    created_at  timestamptz not null default now()
);

create index client_failure_reports_created_idx on client_failure_reports (created_at);
