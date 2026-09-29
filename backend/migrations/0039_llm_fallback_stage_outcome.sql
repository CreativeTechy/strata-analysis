-- Add 'ran_via_llm' as an allowed stage outcome: the structured-extraction
-- LLM call's own sentiment/category/writer_tone/article_tone value was used
-- because the dedicated HF/local classifier for that stage didn't actually
-- run (no model configured, or it fell back to its own default/neutral
-- label). Distinct from 'ran' (the dedicated model produced the value) so
-- readers can tell the two provenances apart. No backfill - this is a
-- going-forward-only outcome value.
alter table public.articles
    drop constraint if exists articles_sentiment_status_check,
    add constraint articles_sentiment_status_check
        check (sentiment_status is null or sentiment_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists articles_classification_status_check,
    add constraint articles_classification_status_check
        check (classification_status is null or classification_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists articles_category_status_check,
    add constraint articles_category_status_check
        check (category_status is null or category_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists articles_writer_tone_status_check,
    add constraint articles_writer_tone_status_check
        check (writer_tone_status is null or writer_tone_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists articles_article_tone_status_check,
    add constraint articles_article_tone_status_check
        check (article_tone_status is null or article_tone_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed'));

alter table public.article_analyses
    drop constraint if exists article_analyses_sentiment_status_check,
    add constraint article_analyses_sentiment_status_check
        check (sentiment_status is null or sentiment_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists article_analyses_classification_status_check,
    add constraint article_analyses_classification_status_check
        check (classification_status is null or classification_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists article_analyses_category_status_check,
    add constraint article_analyses_category_status_check
        check (category_status is null or category_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists article_analyses_writer_tone_status_check,
    add constraint article_analyses_writer_tone_status_check
        check (writer_tone_status is null or writer_tone_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed')),
    drop constraint if exists article_analyses_article_tone_status_check,
    add constraint article_analyses_article_tone_status_check
        check (article_tone_status is null or article_tone_status in ('ran', 'ran_via_llm', 'skipped_model_unavailable', 'failed'));
