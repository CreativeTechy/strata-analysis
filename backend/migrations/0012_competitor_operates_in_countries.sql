-- `competitors.country` is where a company is headquartered, which for a large
-- multinational (McDonald's) is not where it actually competes with the user's
-- business (Lebanon). `operates_in_countries` records that instead: the target
-- countries this specific competitor was matched against during discovery, so
-- the UI can show "competes with you in Lebanon" alongside "based in United
-- States" rather than conflating the two.
alter table public.competitors
    add column if not exists operates_in_countries jsonb not null default '[]'::jsonb;
