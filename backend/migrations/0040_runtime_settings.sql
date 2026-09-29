-- Operator overrides for a small allowlist of tuning knobs that otherwise
-- only live in backend/.env (see services/settings/runtime_settings.py for
-- the allowlist and validation). Same shape as source_trust: one table holds
-- the current override per key, a second is an append-only audit trail, and
-- a missing row here just means "use the .env default" - there is no
-- migration of secrets/credentials into this table, by design (see
-- runtime_settings.py's own note on why those stay .env-only).
create table if not exists public.runtime_settings (
    id             bigint generated always as identity primary key,
    key            text not null unique,
    value          text not null,
    set_by_user_id bigint references public.users(id) on delete set null,
    set_by_name    text,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

drop trigger if exists set_runtime_settings_updated_at on public.runtime_settings;
create trigger set_runtime_settings_updated_at before update on public.runtime_settings
for each row execute function public.set_updated_at();

create table if not exists public.runtime_settings_history (
    id             bigint generated always as identity primary key,
    key            text not null,
    value          text not null,
    set_by_user_id bigint references public.users(id) on delete set null,
    set_by_name    text,
    created_at     timestamptz not null default now()
);
create index if not exists runtime_settings_history_key_idx on public.runtime_settings_history (key, created_at desc);
