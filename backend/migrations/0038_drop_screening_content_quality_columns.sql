-- The article-relevance-screening content-quality gate (added in 0036, its
-- missing column fixed in 0037) turned out to duplicate a more thorough,
-- bilingual content-quality check that already exists at the evidence
-- generation stage (services/evidence/workspace.py's own `_content_quality`,
-- unaffected by this migration). Dropping the columns here rather than
-- reworking them: relevance screening no longer needs its own copy of that
-- concept, and evidence generation already screens for it downstream.

alter table public.article_projects
    drop constraint if exists article_projects_content_quality_decision_check,
    drop column if exists content_quality_decision,
    drop column if exists content_quality_reason;

alter table public.pipeline_run_article_screenings
    drop column if exists content_quality_decision;
