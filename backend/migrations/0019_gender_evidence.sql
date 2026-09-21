-- gender/age_range/region/segment on article_people_opinions are asked of the
-- extraction model with no way to check the call against the article - a
-- "male"/"female" tag is trusted blind. This adds the exact word/phrase the
-- model says it relied on (e.g. "she said", a title like "Mrs."), so a
-- gender call can be audited against real wording instead. Empty whenever
-- gender is 'unknown' - see normalize.normalize_gender_evidence's docstring.
alter table public.article_people_opinions
    add column if not exists gender_evidence text not null default '';
