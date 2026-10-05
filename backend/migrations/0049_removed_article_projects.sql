-- Trash for the ordinary (non-admin) single-article "Remove from project"
-- action on the Article Detail page (SM-134). That action only ever unlinks
-- article_projects - it never touches the articles row or its analysis, even
-- when the article belonged to no other project - so removal is always
-- restorable: the unlinked row is copied here first, then deleted from
-- article_projects, and "restore" just re-inserts it. Permanently destroying
-- an article (or every project's articles) stays a separate, admin-only
-- action (see store.delete_article_permanently / delete_all_articles) that
-- this trash plays no part in.
create table if not exists public.removed_article_projects (
    id                              bigint generated always as identity primary key,
    article_id                      bigint not null references public.articles(id) on delete cascade,
    project_id                      bigint not null references public.projects(id) on delete cascade,
    similarity_score                numeric,
    relevance_decision              text,
    relevance_explanation           text,
    relevance_source                text,
    relevance_scope_hash            text,
    relevance_content_hash          text,
    relevance_model                 text,
    relevance_rules_version         text,
    relevance_screened_at           timestamptz,
    manual_relevance_override       text,
    manual_relevance_reason         text,
    manual_relevance_reviewer_id    bigint references public.users(id) on delete set null,
    manual_relevance_reviewer_name  text,
    manual_relevance_updated_at     timestamptz,
    linked_created_at               timestamptz,
    removed_at                      timestamptz not null default now(),
    removed_by                      text,
    constraint removed_article_projects_unique unique (article_id, project_id)
);

create index if not exists removed_article_projects_project_idx
    on public.removed_article_projects (project_id, removed_at desc);
