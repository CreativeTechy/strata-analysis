-- Independent region-detection stage (analysis/region_detection.py) reports
-- a confidence score derived from how many of its signals (text scan,
-- quoted-opinion votes, entity/organization cross-check) agree, alongside
-- the region guess itself. Stored per article, not per quote - confidence is
-- about the article-level region call, not any one person's stated location.
alter table public.articles
    add column if not exists region_confidence numeric;
