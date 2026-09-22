-- Article-level cross-source coverage evidence from explicit GDELT checks.
-- This is deliberately separate from legacy publisher-list assessments.
alter table public.articles
    add column if not exists coverage_evidence jsonb not null default '{}'::jsonb;

-- Preserve checks created by the initial GDELT implementation.
update public.articles
   set coverage_evidence = source_reliability_details->'gdelt_coverage'
 where coverage_evidence = '{}'::jsonb
   and jsonb_typeof(source_reliability_details->'gdelt_coverage') = 'object';

create index if not exists articles_coverage_evidence_status_idx
    on public.articles ((coverage_evidence->>'status'));
