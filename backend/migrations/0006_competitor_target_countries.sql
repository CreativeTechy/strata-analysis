-- Study-level country targeting for competitor discovery: which countries
-- competitors should be located in. `target_countries` feeds discovery as a
-- filter/steering signal; `competitors.country` is the resolved value the
-- model reports back for each competitor, stored for display.
--
-- No CHECK constraint: ISO 3166-1 alpha-2 is ~249 codes, unmaintainable as a
-- SQL `in (...)` list. Validated in application code instead (see
-- services/competitors/countries.py), same as offerings/audience/
-- differentiators/keywords already are on business_profiles.
alter table public.business_profiles
    add column if not exists target_countries jsonb not null default '[]'::jsonb;

alter table public.competitors
    add column if not exists country text;
