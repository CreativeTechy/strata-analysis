# Strata Signal Layer — Structural Plan

Branch: `feature/signal-layer` (from `origin/dev` @ `251eb36`)
Status: **plan only — nothing implemented**

---

## 0. Baseline correction

This plan is written against `origin/dev`, not against the older tree. Two facts
changed the shape of the plan:

1. **The `opinion_claims` pipeline is not in `dev`.** It exists only on 12
   unmerged commits (`origin/feature/social-scrapers` @ `cebeb29`) and is built
   on the abandoned stack (Supabase REST, DeepSeek, pgvector). Its *ideas* are
   worth porting; its code mostly is not.
2. **`dev` is a different, more mature platform**: local Postgres via `psycopg`
   ([db.py](../backend/db.py)), OpenAI Responses API (`gpt-5-nano`,
   [llm_client.py](../backend/llm_client.py)), local embeddings
   (`intfloat/multilingual-e5-small` via sentence-transformers), full RBAC
   (users/roles/permissions/sessions), `projects` (not `events`), scheduling,
   per-source run stats, pipeline cancel, reports page.

### What `dev` has today

| Concern | State |
|---|---|
| Corpus | `articles` only. No `crawl_pages`, no X/FB/spider sources. |
| Enrichment | Fixed-bucket JSON into `articles.insight_json` — 11 feedback lists + `people_opinions[]` + `frequent_ideas[]`. |
| Aggregation | [intelligence.py](../backend/intelligence.py) + `_topic_summary` in [articles_store.py](../backend/articles_store.py) — all in Python, per request. |
| Prevalence | `frequent_ideas` counted by **exact lowercased string match**. Paraphrases never merge, so counts are ~always 1. |
| Evidence | Article-level `{url, title}` only. **No verbatim quote** — a claim cannot be shown in the speaker's words. |
| Subject | **Does not exist.** No self/competitor axis anywhere. |
| Aspect | Hardcoded JSON keys in the prompt (`comfort_issues`, `safety_feedback`, …). Not a queryable dimension. |
| Time | `articles.published` is **`text`**, parsed in Python at read time, falling back to `created_at`. |
| Promotional | **No detection.** `content_guard.py` only blocks Google consent pages. |
| Syndication | **No dedup.** One wire story on 30 sites counts 30 times. |
| Vectors | `embedding_json jsonb`, cosine in Python. No pgvector; `docker-compose` runs plain `postgres:16`. |
| Determinism | Partial — `analysis_model` + `analysis_prompt_version` are stamped per row. Good foundation. |
| Migrations | **None.** `schema.sql` is mounted as `docker-entrypoint-initdb.d/001-schema.sql`, so it runs **only on a fresh volume**. Existing databases never receive changes. |

### What `dev` returns as "intelligence"

`get_project_intelligence()` returns: sentiment counts, `net_sentiment`,
`sentiment_over_time`, `emotional_signature`, `platforms` (with sentiment), plus
regex keyword counts. That is the sentiment-first dashboard, confirmed — the
critique is accurate against current code.

Two things to note in passing, not part of this plan's core:

- `_fetch_project_rows()` selects **`a.text`** for *every* article in a project on
  *every* dashboard load, unbounded. This is the single largest latency item on
  the value-per-second path.
- `emotion_signature()` derives a 6-axis "emotional signature" from a hardcoded
  `TONE_TO_EMOTION` dict. It is a relabeling of two tone strings, presented as a
  measurement. Flagged for honesty review, not for this plan.
- `chat_completion(max_tokens=900, timeout=30)` at [enrich.py:842](../backend/enrich.py#L842)
  is tight for a prompt requesting 11 lists + two object arrays. **Verify** whether
  responses truncate before assuming enrichment is healthy. (The 30s/4000-token
  timeout bug diagnosed earlier was on the stale branch and does **not** apply here.)

---

## 1. Governing principle: value per second

One rule, and every decision below follows from it:

> **No model call, and no unbounded scan, on the critical path of a click.**

Everything the user sees on load or on click is read from precomputed rollups
keyed to a single `rollup_version`. The LLM runs on ingest and on rollup refresh —
never while a human is waiting. Consequences:

- Clicking a header cell is a single indexed query (target < 100 ms).
- A brief is a cached row lookup, not a generation (target < 50 ms).
- The same view always renders identically until new data lands. No reshuffling,
  no regenerated prose, no "different answer on the second click."

`rollup_version` is the linchpin: a monotonic integer bumped when a rollup
refresh commits. Cell counts, rail order, and brief text all carry it, so
everything on screen is provably from one consistent snapshot.

---

## 2. The coordinate system

Today a finding has no coordinates — it's a string in a JSON array on an article.
Give every finding four:

**subject** (whose thing) × **aspect** (which facet) × **time** (when) × **stance** (direction)

### 2.1 `subjects` — the missing axis

Per-project entities with an explicit role. This is what makes "my stuff" vs
"competitor stuff" a `WHERE` clause instead of an impossibility.

```sql
create table subjects (
    id          bigint generated always as identity primary key,
    project_id  bigint not null references projects(id) on delete cascade,
    name        text not null,
    role        text not null check (role in ('self','competitor','category')),
    aliases     jsonb not null default '[]'::jsonb,   -- match strings, incl. misspellings
    parent_id   bigint references subjects(id),        -- brand -> product line -> model
    created_at  timestamptz not null default now(),
    unique (project_id, name)
);
```

Resolution happens **at claim level**, not article level. Today `articles.brands`
attributes every brand in a comparison review to the whole document, so a
BMW-vs-Audi piece pollutes both. Claim-level resolution is what fixes that.

### 2.2 `aspects` — a pinned taxonomy, not model-invented strings

```sql
create table aspects (
    id          bigint generated always as identity primary key,
    project_id  bigint references projects(id) on delete cascade,  -- null = global seed
    path        text not null,        -- 'interior.seats', 'pricing.value'
    label       text not null,
    parent_path text,
    active      boolean not null default true,
    unique (project_id, path)
);
```

The extractor must **select from this list**; unmatched aspects go to
`aspect_candidates` for review rather than inventing a new string. Rationale:
free-text aspects fragment (`interior.leather` / `leather` / `leather_quality`),
and because clustering buckets within an aspect first, fragmentation **silently
splits clusters and deflates the headline counts**. The taxonomy is the integrity
of the numbers.

### 2.3 `claims` — the atomic unit

```sql
create table claims (
    id             bigint generated always as identity primary key,
    project_id     bigint not null references projects(id) on delete cascade,
    article_id     bigint not null references articles(id) on delete cascade,
    story_id       bigint references story_groups(id),      -- syndication collapse
    subject_id     bigint references subjects(id),
    subject_role   text,                                     -- denormalized for fast filters
    aspect_id      bigint references aspects(id),
    aspect_path    text not null,                            -- denormalized
    stance         text not null check (stance in ('positive','negative','mixed','neutral')),
    kind           text not null check (kind in ('complaint','praise','request','question','fact')),
    claim          text not null,                            -- normalized, English
    evidence       text not null,                            -- VERBATIM span from source
    evidence_start integer,                                  -- offset into articles.text
    speaker_type   text not null default 'unknown',
    severity       numeric not null default 0,               -- 0..1
    confidence     numeric not null default 0.5,
    is_promotional boolean,                                   -- null = unclassified
    promo_score    numeric,
    observed_at    timestamptz not null,                     -- REAL publish time
    claim_key      text not null unique,                     -- sha256(article_id|normalized claim)
    content_hash   text not null,                            -- for extraction cache
    model          text not null,
    prompt_version text not null,
    created_at     timestamptz not null default now()
);
```

**The evidence gate** (port this from the unmerged branch — it is the single best
idea in it): a claim is **discarded** unless `evidence`, whitespace-normalized and
casefolded, occurs verbatim in the source text. This makes "every number clicks
through to a real quote" an enforceable guarantee rather than a hope, and almost
nothing in this market can make that promise.

### 2.4 Time: fix `published`

`articles.published text` cannot support any of this. Add a real column, backfill
by parsing, and derive `claims.observed_at` from it:

```sql
alter table articles add column if not exists published_at timestamptz;
alter table articles add column if not exists published_precision text;  -- day|hour|exact|unknown
create index if not exists articles_published_at_idx on articles (published_at desc);
```

Keep `published` as the raw string for provenance. Rows whose date cannot be
parsed get `published_precision='unknown'` and are **excluded from trend math**
(never silently coerced to `created_at`, which is what happens today and which
turns "when it was said" into "when we happened to scrape it").

### 2.5 `story_groups` — syndication collapse

```sql
create table story_groups (
    id            bigint generated always as identity primary key,
    project_id    bigint not null references projects(id) on delete cascade,
    canonical_article_id bigint references articles(id),
    simhash       bigint not null,
    member_count  integer not null default 1,
    first_seen_at timestamptz not null,
    created_at    timestamptz not null default now()
);
create index story_groups_simhash_idx on story_groups (project_id, simhash);
```

Independent-source counting keys on `story_id`, **not** `url`. Without this, "14
independent sources" can be one AP story republished 14 times — and the first
time a client clicks through and sees that, credibility is gone permanently.

Method: 64-bit SimHash over shingled body text, banded into 4×16-bit buckets for
candidate lookup, Hamming distance ≤ 3 to join. Deterministic, cheap, no model
call, no vector index needed.

### 2.6 Rollups — what the UI actually reads

```sql
create table claim_clusters (
    id             bigint generated always as identity primary key,
    project_id     bigint not null,
    subject_id     bigint,
    aspect_path    text not null,
    stance         text not null,
    label          text not null,          -- representative claim text
    centroid       vector(384),            -- or jsonb fallback, see §7
    claim_count    integer not null,
    story_count    integer not null,       -- INDEPENDENT sources
    first_seen_at  timestamptz not null,
    last_seen_at   timestamptz not null,
    max_severity   numeric not null default 0,
    rollup_version bigint not null,
    cluster_key    text not null,          -- stable across refreshes
    unique (project_id, cluster_key)
);

create table claim_daily (
    project_id  bigint not null,
    subject_id  bigint,
    aspect_path text not null,
    stance      text not null,
    day         date not null,
    claim_count integer not null,
    story_count integer not null,
    primary key (project_id, subject_id, aspect_path, stance, day)
);
```

`claim_daily` is the entire time axis: "Emerging", "Shifting", trend arrows, and
the head-to-head gap view are all single queries against it.

---

## 3. Promotional cleanup + archive

Promotional content is the largest source of false signal: a manufacturer press
release praising its own product is indistinguishable from an owner doing so, and
in competitor mode it is *exactly* what must be excluded.

### 3.1 Two-stage classification (cheap first, model only when unsure)

**Stage A — deterministic rules, no model call.** Produces `promo_score` 0..1 from
additive signals: source is the subject's own domain/handle; `speaker_type =
official`; press-release markers ("announced today", "is pleased to", boilerplate
contact blocks); affiliate/UTM link density; CTA density ("book now", "starting
at", "configure yours"); byline matching a PR wire; near-duplicate of an official
release already in `story_groups`.

**Stage B — model, only for `0.35 ≤ promo_score ≤ 0.75`.** Bounded and cached by
`content_hash`, so the ambiguous band is classified once, ever.

Below 0.35 → organic. Above 0.75 → promotional. This keeps model spend
proportional to genuine ambiguity.

### 3.2 Archive, never delete

```sql
create table content_archive (
    id            bigint generated always as identity primary key,
    entity_type   text not null check (entity_type in ('article','claim')),
    entity_id     bigint not null,
    project_id    bigint,
    reason        text not null,      -- promotional | blocked_domain | syndicated_dup | low_quality | manual
    reason_detail text,
    promo_score   numeric,
    payload       jsonb not null,     -- full row snapshot, restorable
    archived_by   bigint references users(id),
    archived_at   timestamptz not null default now(),
    restored_at   timestamptz,
    unique (entity_type, entity_id)
);
```

Rules:
- Archiving **moves** the row (snapshot to `payload`, then delete from the live
  table) inside one transaction. Fully reversible via `restore_archived()`.
- All rollups exclude archived entities and `is_promotional = true` by default.
- **Never filter on `is_promotional = false` alone.** The unmerged branch's RPC
  did exactly that, which silently excludes every *unclassified* (`null`) row —
  with a mostly-unpopulated column that empties the result set. Use
  `coalesce(is_promotional, false) = false` and surface the unclassified count.
- The UI shows an **auditable count**: "1,204 promotional items archived · review".
  Silent removal is as damaging to trust as silent inclusion.
- One-click **restore** and a per-project override list (a source the client
  insists is organic, or vice versa).

### 3.3 Backlog cleanup

A one-shot pass over existing `articles`: score, classify the ambiguous band,
archive with `reason='promotional'`. Dry-run mode first, emitting a CSV of what
*would* move, for human review before the destructive commit.

---

## 4. Determinism contract

Explicit requirements, because "the number changed and I don't know why" is the
failure mode that kills this category of tool.

| Concern | Guarantee | Mechanism |
|---|---|---|
| Extraction | Same content + same prompt version ⇒ no second model call | `content_hash` + `prompt_version` cache; already half-built via `PROMPT_VERSION` |
| Model output drift | Every row records what produced it | `model`, `prompt_version` on `claims` (pattern exists on `articles`) |
| Clustering | Same input ⇒ byte-identical clusters | Process claims in `order by id`; fixed threshold from config, never env-drift; `cluster_key = sha256(project|subject|aspect|stance|representative)` so ids survive refresh |
| Counts on screen | Cell, rail, and brief always agree | All carry the same `rollup_version` |
| Brief text | Same data ⇒ same words | Cache key `(lens_id, rollup_version)`; regenerate on version bump, never on click |
| Rail order | Stable across refreshes and pagination | No `random()`; final tie-break `cluster_id asc`; cursor is `(rank_index, cluster_id)` pinned to `rollup_version` |
| Rollup refresh | Readers never see a half-built snapshot | Build into `_next` tables, swap in one transaction, then bump version |
| Migrations | Same sequence on every environment | Numbered, idempotent, recorded in `schema_migrations` |
| Time | "When said", not "when scraped" | `published_at` + `published_precision`; unparseable rows excluded from trends |

---

## 5. The rail: ranking without randomization

The ask was a randomized scroll. Randomization is the wrong mechanic — it means
the client cannot re-find what they saw, cannot tell whether they've seen
everything, and cannot trust that position 1 is position 1 for a reason.
Refresh-roulette reads as "the tool doesn't know what matters either."

What's actually wanted is **variety without instability**. Four deterministic
stages:

### Stage 1 — Candidate set (indexed SQL)
Cluster-representative rows for `(project, lens filters, period)`, excluding
archived and promotional. Cap at 500 candidates.

### Stage 2 — Value score (per cluster, not per claim)

```
value =  w_vol  * ln(1 + story_count)          -- independent sources, not URLs
       + w_rec  * exp(-days_since_last / 14)   -- 14-day half-life
       + w_sev  * max_severity                 -- safety defect > trim gripe
       + w_nov  * novelty                      -- 1.0 if first_seen inside period
       + w_div  * (distinct_publishers / story_count)
       - w_seen * seen_decay(user, cluster)
```

Weights are per-lens, defaults pinned in code and versioned. No randomness.
Ties break on `cluster_id asc`.

`w_sev` and `w_nov` are what make the ranking feel like *judgment* rather than
counting: three owners reporting a safety defect must outrank forty people mildly
annoyed by a trim colour, and a theme that didn't exist three weeks ago must
outrank a known one of equal volume.

### Stage 3 — Greedy diversification (MMR-style)
Walk the sorted list, emit a card only if quotas allow, else skip and continue —
so the rail still fills to 12:
- ≤ 2 cards per top-level aspect
- ≤ 1 card per `(aspect, publisher)`
- ≤ 3 cards per subject (competitor mode)

This is where the variety the client wanted actually comes from: never five cards
of the same complaint from the same outlet, while position 1 is still the most
important thing.

### Stage 4 — Stable cursor + seen state
- Rail size **12**, with "show all N" as the escape hatch. The rail's job is to
  *argue the number*, not reproduce the corpus.
- Cursor = `(rank_index, cluster_id)` pinned to `rollup_version`. New data mid-scroll
  surfaces as a "**N new**" pill, and never reorders under the user's cursor.
- `cluster_seen (user_id, cluster_id, seen_at)` applies `w_seen` from the **next
  session onward**, so scrolling back up doesn't reshuffle what you just read.

Net effect: the top of the rail is always the most decision-relevant thing, it's
different tomorrow because the data and seen-state changed, and it's identical on
refresh today.

---

## 6. Surfaces

### 6.1 Header strip — four cells, opinions not documents

```
┌──────────────────┬──────────────────┬──────────────────┬──────────────────┐
│ POSITIVE     63% │ NEGATIVE     27% │ EMERGING       6 │ SHIFTING         │
│ 3,032 of 4,812   │ 1,299 opinions   │ new themes, none │ interior.seats    │
│ opinions         │ 890 sources      │ existed 30d ago  │ ↑ 3.4× in 21d    │
│ 1,340 sources    │                  │                  │                  │
└──────────────────┴──────────────────┴──────────────────┴──────────────────┘
        click ─────────────► rail (§5) + cached brief (§6.2)
```

Counts are **claims with an independent-source denominator**, not documents. An
article isn't satisfied; a person is — and one sentiment label smeared across a
15,000-character review that praises the powertrain and pans the seats is a
number that survives no scrutiny.

Cells 3–4 replace neutral/mixed (nobody clicks "neutral") with the time axis.
Positive and negative *confirm* what the client suspects; **Emerging** tells them
something they didn't know to ask, which is the cell that earns daily opens.

All four are one query against `claim_daily` + `claim_clusters`.

### 6.2 Briefs — precomputed, per lens

```sql
create table briefs (
    id             bigint generated always as identity primary key,
    lens_id        bigint not null references lenses(id) on delete cascade,
    rollup_version bigint not null,
    slice_key      text not null,        -- 'positive' | 'negative' | 'emerging' | 'shifting' | aspect path
    body           text not null,
    evidence_refs  jsonb not null,       -- cluster_ids + claim_ids backing every statement
    model          text not null,
    prompt_version text not null,
    generated_at   timestamptz not null default now(),
    unique (lens_id, rollup_version, slice_key)
);
```

Generated on rollup commit, never on click. The brief prompt receives **only
precomputed counts** and is instructed not to restate them — the counts come from
SQL, the prose explains them. Displayed with "as of 4,812 opinions · updated 2h
ago", which reads as rigor instead of as a chatbot guessing.

### 6.3 Lenses — the customization primitive

```sql
create table lenses (
    id              bigint generated always as identity primary key,
    project_id      bigint not null references projects(id) on delete cascade,
    user_id         bigint references users(id) on delete cascade,  -- null = shared
    name            text not null,
    mode            text not null check (mode in ('voice','competitor')),
    subject_ids     jsonb not null default '[]'::jsonb,
    aspect_paths    jsonb not null default '[]'::jsonb,
    stances         jsonb not null default '[]'::jsonb,
    speaker_types   jsonb not null default '[]'::jsonb,
    period          text not null default '30d',
    exclude_promotional boolean not null default true,
    brief_instruction   text,             -- the "what I wanna know" setting
    weights         jsonb,                -- per-lens ranking weights (§5)
    is_default      boolean not null default false,
    subscribe_cadence text,               -- null | daily | weekly
    subscribe_channel text,               -- email | slack
    created_at      timestamptz not null default now()
);
```

The structural win: **a lens and a subscription are the same object.** What
configures the screen is what sends the Monday email. One abstraction yields the
custom dashboard, push delivery, and shareable saved views. Most tools in this
category die quietly because nobody logs in — the lens is what lets the tool
reach the client where they already are.

### 6.4 Competitor mode

**Head-to-head aspect gap** — the highest-value view in the product, and a pure
`claim_daily` query:

> **interior.seats** — You: 71% negative, 34 independent sources.
> Them: 22% negative, 41 sources. **Gap: 49 pts.** 6 quotes explain it ↓

Sorted by gap size, the competitive question answers itself with nobody typing a
query. This is a roadmap input, and it's the screen a client forwards to their boss.

**Moves timeline** — a distinct content type. "What competitors are *doing*"
(launches, price changes, market entries, spec updates) is not "what people *say*
about competitors". Different extraction (event, from official sources),
different display (timeline, not sentiment split):

```sql
create table moves (
    id          bigint generated always as identity primary key,
    project_id  bigint not null references projects(id) on delete cascade,
    subject_id  bigint not null references subjects(id) on delete cascade,
    move_type   text not null,     -- launch|price|feature|recall|expansion|partnership|marketing
    headline    text not null,
    evidence    text not null,     -- verbatim
    article_id  bigint references articles(id),
    occurred_at timestamptz not null,
    created_at  timestamptz not null default now()
);
```

Overlaying the two is where it stops looking like a dashboard: *they shipped a fix
on 12 March → complaints on that aspect fell 60% over the following six weeks.*
Cheap once both objects share a time axis.

---

## 7. Migrations (local Postgres)

### 7.1 The problem to solve first

`schema.sql` is mounted at `docker-entrypoint-initdb.d/001-schema.sql`, which
Postgres runs **only when the data directory is empty**. Every schema change since
the first `docker compose up` has therefore reached existing databases only by
someone pasting SQL by hand. That does not survive this plan's ~10 new tables.

### 7.2 Introduce a real runner

```
backend/migrations/
  0001_baseline.sql              -- current schema.sql, unchanged, idempotent
  0002_published_at.sql
  0003_subjects_aspects.sql
  0004_claims.sql
  0005_story_groups.sql
  0006_rollups.sql
  0007_archive.sql
  0008_lenses_briefs.sql
  0009_moves.sql
  0010_seen_state.sql
backend/migrate.py               -- applies pending files in order, in one txn each
```

```sql
create table if not exists schema_migrations (
    version     text primary key,
    checksum    text not null,
    applied_at  timestamptz not null default now()
);
```

Rules: forward-only; every file idempotent (`if not exists` / guarded `do` blocks);
checksum verified so an edited-after-apply file fails loudly; `migrate.py` runs on
backend startup **and** is invocable standalone; `0001_baseline` is the existing
schema so a fresh volume and an existing database converge on the same state.
Keep the initdb mount pointed at `0001_baseline.sql` only.

### 7.3 pgvector decision

Clustering needs vector similarity. Today embeddings are `jsonb` with cosine
computed in Python — workable for a few thousand article vectors, but claims are
roughly 10–30× more numerous, and clustering is O(n·k) per aspect bucket. At
100k+ claims, Python cosine over jsonb will not hold.

**Recommendation:** switch the image to `pgvector/pgvector:pg16` and add
`vector(384)` columns (matching `multilingual-e5-small`) with HNSW cosine indexes.
It is a one-line compose change plus `create extension vector`.

**Fallback if the image can't change:** keep `centroid` as `jsonb`, cluster in a
batch job rather than on read, and cap per-aspect candidate sets. Slower to build,
identical to read, because the UI only ever reads `claim_clusters` — the abstraction
holds either way. Marked as an open decision in §10.

---

## 8. Backfill — no re-crawling

Everything needed to build the coordinate system is already in Postgres:
`articles.text` (full body), `articles.insight_json` (existing extracted findings),
`articles.published` (raw date string). So:

1. **`published_at`** — pure parsing, no model. Free.
2. **`story_groups`** — SimHash over existing `articles.text`. No model. Free.
3. **`subjects`** — seed per project from `projects.keywords`/`usernames` plus a
   human confirming which subject is `self`. One short session per project.
4. **`aspects`** — seed the global taxonomy from the 11 existing bucket names
   (they are a reasonable first vertical taxonomy), then expand from observed
   `frequent_ideas` categories.
5. **`claims`** — the only model spend. Re-extract from stored `articles.text`
   with the claims prompt (subject + aspect from the pinned lists, verbatim
   evidence required). Ordered by `published_at desc` so the most recent, most
   valuable window lands first and the dashboard is useful before the backfill
   finishes. Bounded by a per-run budget and resumable via `content_hash`.
6. **Promo pass** — Stage A on everything (free), Stage B on the ambiguous band only.
7. **Rollups** — pure SQL from `claims`.

`insight_json` is retained untouched. Nothing in this plan deletes it, and the
current dashboard keeps working throughout.

---

## 9. Phasing — value delivered per phase

Each phase is independently shippable and leaves the product better.

**Phase 0 — Foundations (no user-visible change)**
Migration runner + baseline. `published_at` + backfill. SimHash `story_groups`.
Bound `_fetch_project_rows` (stop selecting full `a.text` on every dashboard load).
Verify the `max_tokens=900` truncation risk.
→ *Unblocks everything; fixes the worst latency item.*

**Phase 1 — Coordinates**
`subjects`, `aspects`, `claims` + evidence gate. Claims extraction in the pipeline.
Backfill recent window first.
→ *"My stuff" vs "competitor stuff" becomes a query for the first time.*

**Phase 2 — Promo cleanup + archive**
Stage A/B classification, `content_archive`, dry-run backlog pass, auditable count
and restore in the UI.
→ *Counts stop being inflated by marketing; competitor mode becomes trustworthy.*

**Phase 3 — Rollups + the strip**
`claim_clusters`, `claim_daily`, `rollup_version` swap-and-bump. Four-cell header,
rail with §5 ranking, seen state.
→ *The screen from the vision, on real coordinates, sub-100ms.*

**Phase 4 — Lenses + briefs**
`lenses`, `briefs`, precomputed generation on rollup commit, "what I wanna know".
→ *Dashboard becomes the client's own instrument panel.*

**Phase 5 — Competitor mode**
Head-to-head gap view, `moves` extraction, overlay.
→ *The screen they forward to their boss.*

**Phase 6 — Push**
Lens subscriptions → daily/weekly digest, "what changed since you last looked".
→ *Value without requiring a login; the highest perceived-value-per-hour item on
the list, and nearly free once `observed_at` + seen-state exist.*

---

## 10. Open decisions — needed before Phase 1

1. **pgvector or jsonb?** (§7.3) Recommend `pgvector/pgvector:pg16`. Blocks the
   `claim_clusters.centroid` column type.
2. **Port or rebuild the unmerged claims work?** Recommend: **rebuild on `dev`,
   port three ideas** — the verbatim evidence gate, distinct-source counting, and
   deterministic clustering. The rest is tied to Supabase/DeepSeek/pgvector-384.
   The other 12 commits (spider engine, X/FB via Apify, `crawl_pages`) are a
   separate merge question, out of scope here.
3. **Who is `self`?** Per project, a human must designate the subject with
   `role='self'`. There is no way to infer it. Needs a wizard step.
4. **First taxonomy vertical.** The 11 existing buckets are automotive-shaped
   while the platform has been genericized to "projects". Seed automotive and add
   a second vertical later, or design generic-first?
5. **Backlog promo pass authority.** Who approves the dry-run CSV before rows move
   to archive?
6. **Ticket convention.** Branch is `feature/signal-layer`; existing branches use
   `feature/CT-###-…`. Want CT numbers assigned per phase?

---

## 11. Explicitly out of scope

- Re-merging the spider / X / Facebook sources (`crawl_pages`) — separate decision.
- Replacing `emotion_signature` — flagged in §0, not addressed here.
- Frontend implementation detail beyond the contracts in §6.
- Any change to auth/RBAC.
