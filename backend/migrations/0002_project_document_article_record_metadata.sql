-- Candidates split out of an uploaded .json/.jsonl document come from records
-- that already carry their own url, author and publication date. Those have no
-- home on project_document_articles (title/summary/body is all an LLM split
-- produces), and dropping them would leave every imported article with a NULL
-- published_at - which is what every trend/timeline read in the product keys
-- off. Kept as jsonb rather than three columns because it is provenance from
-- the uploaded file, not app state: nothing filters or joins on it, only
-- _materialize() reads it, and a future record field costs no migration.
alter table public.project_document_articles
    add column if not exists record_metadata jsonb;
