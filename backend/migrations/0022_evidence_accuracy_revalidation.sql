-- Preserve saved results, but withdraw confidence inferred only from headlines.
update articles
set coverage_evidence = coverage_evidence || jsonb_build_object(
    'previous_status', coverage_evidence->>'status',
    'status', case when coalesce(jsonb_array_length(coverage_evidence->'matches'), 0) > 0
                   then 'some_coverage' else 'not_checked' end,
    'reason', 'Saved headline matches require review before reliability can be assessed.',
    'rules_version', 'coverage-v2')
where coverage_evidence <> '{}'::jsonb
  and coalesce(coverage_evidence->>'rules_version', '') <> 'coverage-v2';

-- Revalidate literal quotations against the frozen source, never live text.
update evidence_items ei
set citation_valid = false, qualifies = false
from evidence_claims ec
where ec.id = ei.claim_id
  and ei.citation_valid
  and not exists (
      select 1 from evidence_run_articles era
      where era.run_id = ec.run_id and era.article_id = ei.article_id
        and length(ei.passage) > 0
        and position(ei.passage in coalesce(era.source_snapshot->>'text','')) > 0
  );

update evidence_claims ec
set citation_checked_count = (
    select count(*) from evidence_items ei where ei.claim_id = ec.id and ei.citation_valid
);
