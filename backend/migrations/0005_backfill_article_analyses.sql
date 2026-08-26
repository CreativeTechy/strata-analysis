-- Backfill 0004's snapshots for runs that predate it.
--
-- Before 0004, a run-scoped dashboard read `articles where pipeline_run_id = X`.
-- After it, the same read comes from article_analyses - so without this, every
-- run that had already finished would render empty: the article rows still
-- carry their analysis, but nothing had recorded it *as that run's*.
--
-- One snapshot per article, attributed to the run in articles.pipeline_run_id.
-- That column means "the run that first analyzed this article", which is a
-- faithful attribution here precisely because the pre-0004 code had no way to
-- record a second run against the same article - a historical database has at
-- most one run's worth of conclusions per article, and this is it.
--
-- `on conflict do nothing` keeps the file re-runnable and, more importantly,
-- means a snapshot written by the new code path is never overwritten by this
-- reconstruction of it.
insert into public.article_analyses (
    run_id, article_id,
    summary, sentiment, sentiment_score, sentiment_low_confidence, sentiment_model,
    relevance_score, category, article_category, category_confidence,
    writer_tone, writer_tone_confidence, article_tone, article_tone_confidence,
    classification_model,
    insight_json, organizations, entities, topics, key_points, risks,
    opportunities, brands, car_models, people_opinions, extraction_model,
    gender, age_range, region, segment,
    source_language, source_language_confidence,
    analysis_model, analysis_prompt_version, analysis_pipeline_version,
    analysis_status, analysis_error, analyzed_at
)
select
    a.pipeline_run_id, a.id,
    a.summary, a.sentiment, a.sentiment_score, a.sentiment_low_confidence, a.sentiment_model,
    a.relevance_score, a.category, a.article_category, a.category_confidence,
    a.writer_tone, a.writer_tone_confidence, a.article_tone, a.article_tone_confidence,
    a.classification_model,
    a.insight_json, a.organizations, a.entities, a.topics, a.key_points, a.risks,
    a.opportunities, a.brands, a.car_models,
    coalesce((
        select jsonb_agg(jsonb_build_object(
                   'opinion',   po.opinion,
                   'sentiment', po.sentiment,
                   'category',  po.category,
                   'gender',    po.gender,
                   'age_range', po.age_range,
                   'region',    po.region,
                   'segment',   po.segment
               ) order by po.id)
        from public.article_people_opinions po
        where po.article_id = a.id
    ), '[]'::jsonb),
    a.extraction_model,
    a.gender, a.age_range, a.region, a.segment,
    a.source_language, a.source_language_confidence,
    a.analysis_model, a.analysis_prompt_version, a.analysis_pipeline_version,
    a.analysis_status, a.analysis_error, a.analyzed_at
from public.articles a
join public.pipeline_runs pr on pr.id = a.pipeline_run_id
where a.pipeline_run_id is not null
on conflict (run_id, article_id) do nothing;
