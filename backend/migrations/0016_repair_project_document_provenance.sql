-- Restore uploaded-document provenance on articles whose real URL was later
-- re-upserted by another import. The candidate/article link is authoritative.
update public.articles a
set source = pd.original_filename,
    source_url = 'document://project-document/' || pd.id::text
from public.project_document_articles pda
join public.project_documents pd on pd.id = pda.document_id
where pda.article_id = a.id
  and (
      a.source_url is distinct from ('document://project-document/' || pd.id::text)
      or a.source is distinct from pd.original_filename
  );
