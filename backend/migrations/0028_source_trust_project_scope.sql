-- Records which project an operator was looking at when they set a "real:"
-- source's trust tier (0026_source_trust.sql). The tier itself stays a
-- global, host-keyed judgement by design (see 0026's own note) - but the
-- free-text `reason` and `set_by_name` an operator writes alongside it can
-- name specifics ("flagged after the Q3 review for the Acme engagement")
-- that were never meant to cross into a second project that happens to cite
-- the same publisher and can see it purely because articles.view + that
-- project's own visibility already let it read /sources. source_trust.py's
-- resolve_many() uses this column to redact reason/set_by for a viewer
-- whose project doesn't match, without hiding the tier.
--
-- Nullable and NOT part of the uniqueness/lookup key: a "document:" key is
-- already scoped to one project by construction (its source_url embeds that
-- project's own document id - see 0026), so this only ever matters for a
-- "real:" override, and resolve_many() treats a null value here (a pre-
-- existing row saved before this migration) the same as a same-project
-- match rather than newly hiding something that was already visible.
alter table public.source_trust
    add column if not exists project_id bigint references public.projects(id) on delete set null;

alter table public.source_trust_reviews
    add column if not exists project_id bigint references public.projects(id) on delete set null;
