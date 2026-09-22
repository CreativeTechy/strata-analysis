-- Mirrors migration 0019 (gender_evidence): the exact word/phrase (or the
-- raw stated age) the model says signaled `age_range`, so an age call can be
-- audited against real wording instead of trusted blind. Empty whenever
-- age_range is 'unknown' - see normalize.normalize_age_evidence's docstring.
alter table public.article_people_opinions
    add column if not exists age_evidence text not null default '';
