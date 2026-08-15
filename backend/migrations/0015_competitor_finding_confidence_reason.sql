-- `competitor_findings.confidence` is a bare 0.0-1.0 the model assigns itself,
-- shown on the card with nothing to justify it. A reader deciding whether to
-- act on a finding needs to know *why* it is a 0.4 - one thin source, evidence
-- that only implies the move, a competitor whose name is ambiguous - because
-- "low confidence" and "low confidence because every source is the company's
-- own press release" call for different responses.
--
-- Nullable with no default: findings generated before this column existed have
-- no explanation and must read as absent rather than as an empty one.
alter table public.competitor_findings
    add column if not exists confidence_reason text;
