-- Other names the same company is published under.
--
-- Evidence attribution matches a competitor's `name`, that name with a legal
-- suffix stripped, and its bare domain label. That covers a company written
-- exactly one way in English and nothing else: a Lebanese roaster reported on
-- in Arabic, a group trading under a different retail brand, or a name the
-- press routinely misspells is simply never matched, and the competitor comes
-- back with no evidence for reasons no one can see from the workspace.
--
-- It is also the correct fix for the opposite failure. A competitor whose name
-- is an ordinary word ("Stories") cannot be matched on text alone - it fires on
-- every article containing the word - so such names are dropped as automatic
-- aliases. An alias listed here is a deliberate human statement that this
-- string identifies this company, so it is trusted where a derived one is not.
alter table public.competitors
    add column if not exists aliases jsonb not null default '[]'::jsonb;
