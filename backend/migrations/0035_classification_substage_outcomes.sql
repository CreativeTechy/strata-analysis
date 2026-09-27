-- classification_status (migration 0034) is a single OR-combined flag
-- across the three independent classify_* calls (category/writer_tone/
-- article_tone - see analysis/orchestrator.py's _combined_stage_outcome),
-- so it can read 'ran' even when one specific sub-stage actually fell back.
-- Give each sub-stage its own status so confidence display can be gated
-- per-field instead of on the combined flag.
alter table public.articles
    add column if not exists category_status text,
    add column if not exists writer_tone_status text,
    add column if not exists article_tone_status text;

alter table public.articles
    drop constraint if exists articles_category_status_check,
    add constraint articles_category_status_check
        check (category_status is null or category_status in ('ran', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists articles_writer_tone_status_check,
    add constraint articles_writer_tone_status_check
        check (writer_tone_status is null or writer_tone_status in ('ran', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists articles_article_tone_status_check,
    add constraint articles_article_tone_status_check
        check (article_tone_status is null or article_tone_status in ('ran', 'skipped_model_unavailable', 'failed'));

-- Backfill from the same positive evidence classification_status's own
-- backfill used: a stage that already carries a confidence value must have
-- run. Rows with no confidence stay NULL (never attempted), not 'ran'.
update public.articles
set category_status = 'ran'
where category_status is null
  and classification_model is not null
  and category_confidence is not null;

update public.articles
set writer_tone_status = 'ran'
where writer_tone_status is null
  and classification_model is not null
  and writer_tone_confidence is not null;

update public.articles
set article_tone_status = 'ran'
where article_tone_status is null
  and classification_model is not null
  and article_tone_confidence is not null;

alter table public.article_analyses
    add column if not exists category_status text,
    add column if not exists writer_tone_status text,
    add column if not exists article_tone_status text;

alter table public.article_analyses
    drop constraint if exists article_analyses_category_status_check,
    add constraint article_analyses_category_status_check
        check (category_status is null or category_status in ('ran', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists article_analyses_writer_tone_status_check,
    add constraint article_analyses_writer_tone_status_check
        check (writer_tone_status is null or writer_tone_status in ('ran', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists article_analyses_article_tone_status_check,
    add constraint article_analyses_article_tone_status_check
        check (article_tone_status is null or article_tone_status in ('ran', 'skipped_model_unavailable', 'failed'));

update public.article_analyses
set category_status = 'ran'
where category_status is null
  and classification_model is not null
  and category_confidence is not null;

update public.article_analyses
set writer_tone_status = 'ran'
where writer_tone_status is null
  and classification_model is not null
  and writer_tone_confidence is not null;

update public.article_analyses
set article_tone_status = 'ran'
where article_tone_status is null
  and classification_model is not null
  and article_tone_confidence is not null;
