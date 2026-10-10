-- Memory mode for a room: the host chooses, in the lobby, whether ratings are shown
-- while everyone drafts. In a memory room the API leaves every rating out of the draft
-- it sends (web.app.session_out), so no one can read them from the page; the
-- tournament afterwards shows them as usual.

alter table rooms add column memory boolean not null default false;
