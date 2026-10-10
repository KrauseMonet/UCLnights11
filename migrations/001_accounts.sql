-- Email+password accounts, the same shape as the cricket site's (its migration 026):
-- stdlib PBKDF2 hashes (web/auth.py), a signed cookie for the session and no session
-- table. Case-insensitive uniqueness is a pair of functional indexes, because citext
-- is an extension and nothing here may need one.

create table accounts (
    account_id     serial primary key,
    username       text not null,
    email          text not null,
    password_hash  text not null,
    created_at     timestamptz not null default now(),

    constraint accounts_username_len_ck check (char_length(username) between 3 and 20),
    constraint accounts_username_charset_ck check (username ~ '^[A-Za-z0-9_]+$')
);

create unique index accounts_username_lower_idx on accounts (lower(username));
create unique index accounts_email_lower_idx on accounts (lower(email));

comment on table accounts is
    'Sign-in for playing with friends. No email verification and no password reset yet: both need an email-sending service the site does not have.';
comment on column accounts.password_hash is
    'pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex> (web/auth.py).';
