-- Preserve whether classifier-backed stages actually produced their stored
-- values.  NULL means the stage has never been attempted (pending/legacy),
-- while the constrained values distinguish a real result from a fallback.
alter table public.articles
    add column if not exists sentiment_status text,
    add column if not exists classification_status text;

alter table public.articles
    drop constraint if exists articles_sentiment_status_check,
    add constraint articles_sentiment_status_check
        check (sentiment_status is null or sentiment_status in ('ran', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists articles_classification_status_check,
    add constraint articles_classification_status_check
        check (classification_status is null or classification_status in ('ran', 'skipped_model_unavailable', 'failed'));

-- Only backfill rows for which the old schema contains positive evidence that
-- the stage ran.  In particular, analysis_status='success' by itself is not
-- evidence: imported placeholder rows historically defaulted to success.
update public.articles
set sentiment_status = 'ran'
where sentiment_status is null
  and sentiment_model is not null
  and sentiment_score is not null;

update public.articles
set classification_status = 'ran'
where classification_status is null
  and classification_model is not null
  and category_confidence is not null;

alter table public.article_analyses
    add column if not exists sentiment_status text,
    add column if not exists classification_status text;

alter table public.article_analyses
    drop constraint if exists article_analyses_sentiment_status_check,
    add constraint article_analyses_sentiment_status_check
        check (sentiment_status is null or sentiment_status in ('ran', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists article_analyses_classification_status_check,
    add constraint article_analyses_classification_status_check
        check (classification_status is null or classification_status in ('ran', 'skipped_model_unavailable', 'failed'));

update public.article_analyses
set sentiment_status = 'ran'
where sentiment_status is null
  and sentiment_model is not null
  and sentiment_score is not null;

update public.article_analyses
set classification_status = 'ran'
where classification_status is null
  and classification_model is not null
  and category_confidence is not null;

create index if not exists articles_sentiment_status_idx
    on public.articles (sentiment_status);
