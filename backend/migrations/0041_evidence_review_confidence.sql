-- Let an analyst record how sure they are about a manual claim review decision,
-- instead of every manual override being taken as fully certain.
alter table public.evidence_reviews
    add column if not exists confidence text not null default 'high';

alter table public.evidence_reviews
    drop constraint if exists evidence_reviews_confidence_check;
alter table public.evidence_reviews
    add constraint evidence_reviews_confidence_check
        check (confidence in ('low', 'medium', 'high'));
