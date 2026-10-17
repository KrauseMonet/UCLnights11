-- Dynasty seasons on the profile (C66).
--
-- Each season of a dynasty is saved like a solo run, keyed by the dynasty's state up to
-- that season (all its tournament depends on), so saving twice is harmless and the profile
-- can link back to it. Such a state grows by a window a season: over 80 simulated
-- ten-season dynasties it reached 652 characters with a sheet and a plan every season,
-- past the 600 that migration 014 allows, and a dynasty may carry on to 30 seasons.
-- 2400 still fits a btree entry of the (account, source, key) unique index.
alter table results drop constraint results_source_check;
alter table results add constraint results_source_check
    check (source in ('solo', 'room', 'daily', 'dynasty'));
alter table results drop constraint results_natural_key_check;
alter table results add constraint results_natural_key_check check (char_length(natural_key) <= 2400);
