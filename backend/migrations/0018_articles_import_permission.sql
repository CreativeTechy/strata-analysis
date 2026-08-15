-- The Articles page can now restore a JSONL export via POST /api/articles/import
-- (see main.py). That writes rows, so it needs its own permission rather than
-- riding on articles.view - and it is granted alongside articles.delete, since
-- both are bulk mutations of the stored corpus. admin covers it via full_access.
insert into public.permissions (key, description) values
    ('articles.import', 'Import articles from a JSONL export')
on conflict (key) do nothing;

insert into public.role_permissions (role_id, permission_id)
select r.id, p.id
from public.roles r
join public.permissions p on p.key = 'articles.import'
where r.name = 'operator'
on conflict do nothing;
