"""Seed a realistic competitor study for demos.

Creates one study end to end — business profile, ranked competitors, their
channels, scraped articles, and the analysis cards — without calling an LLM or
the network, so a demo works on a fresh database with no API keys configured.

The findings here are written by hand rather than generated. Everything *around*
them is real: the articles go through the same `story_groups` deduplication and
the same `validate_competitor_articles` gate the live pipeline uses, so the
counts on the cards, the "filtered out" audit trail, and the syndication collapse
are all genuine rather than hardcoded.

    python seed_competitor_demo.py            # create (idempotent-ish: resets the demo study)
    python seed_competitor_demo.py --wipe     # remove the demo study and exit
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from services.competitors import competitor_analysis
from services.competitors import competitors_store
import db
import dedup

STUDY_NAME = "Northwind - competitor study (demo)"

PROFILE = {
    "name": "Northwind Analytics",
    "website": "https://northwind.example",
    "description": "Supply-chain analytics for mid-market manufacturers.",
    "industry": "B2B SaaS",
    "market": "supply-chain planning and demand forecasting software",
    "geography": "North America and Western Europe",
    "target_countries": ["US", "CA", "GB"],
    "positioning": "Forecasting accuracy without an ERP replacement, live in under 30 days.",
    "offerings": ["demand forecasting", "inventory optimisation", "supplier risk scoring"],
    "audience": ["operations directors", "supply-chain planners", "CFOs at mid-market manufacturers"],
    "differentiators": ["30-day implementation", "no ERP migration required", "usage-based pricing"],
    "keywords": ["demand forecasting", "supply chain", "inventory optimisation", "S&OP"],
    "context_summary": (
        "Northwind sells supply-chain planning software to mid-market manufacturers who cannot "
        "absorb an enterprise ERP programme. It competes on speed of implementation and forecast "
        "accuracy rather than breadth of modules, so competitor moves that lower the cost or "
        "time-to-value of enterprise planning suites are the ones that matter most."
    ),
}

COMPETITORS = [
    {
        "name": "Kinaxis", "website": "https://kinaxis.example", "domain": "kinaxis.example",
        "country": "CA", "size_tier": "enterprise", "size_rank": 1,
        "description": "Concurrent planning platform used by large manufacturers.",
        "size_signals": {"basis": ["publicly listed", "global enterprise footprint"],
                         "why_competitor": "Competes for the same planning budget one tier up.",
                         "search_hits": 4, "site_reachable": True},
        "accounts": [
            {"platform": "news", "url": "https://kinaxis.example", "handle": "kinaxis.example", "confidence": 1.0, "valid": True},
            {"platform": "blog", "url": "https://kinaxis.example/blog/feed", "handle": None, "confidence": 0.9, "valid": True},
            {"platform": "x", "url": "https://x.com/kinaxis_demo", "handle": "kinaxis_demo", "confidence": 0.55, "valid": False},
        ],
    },
    {
        "name": "Blue Yonder", "website": "https://blueyonder.example", "domain": "blueyonder.example",
        "country": "US", "size_tier": "enterprise", "size_rank": 2,
        "description": "End-to-end supply chain suite, part of a larger group.",
        "size_signals": {"basis": ["acquired by a global group", "enterprise install base"],
                         "why_competitor": "Overlaps on forecasting despite a much broader suite.",
                         "search_hits": 4, "site_reachable": True},
        "accounts": [
            {"platform": "news", "url": "https://blueyonder.example", "handle": "blueyonder.example", "confidence": 1.0, "valid": True},
        ],
    },
    {
        "name": "Netstock", "website": "https://netstock.example", "domain": "netstock.example",
        "country": "GB", "size_tier": "smb", "size_rank": 3,
        "description": "Inventory optimisation aimed at small and mid-size distributors.",
        "size_signals": {"basis": ["SMB focus", "self-serve onboarding"],
                         "why_competitor": "Undercuts on price for smaller manufacturers.",
                         "search_hits": 3, "site_reachable": True},
        "accounts": [
            {"platform": "news", "url": "https://netstock.example", "handle": "netstock.example", "confidence": 1.0, "valid": True},
            {"platform": "blog", "url": "https://netstock.example/feed", "handle": None, "confidence": 0.8, "valid": True},
        ],
    },
]

FILLER = (
    "Planning leaders said the decision reflected pressure to shorten deployment timelines while "
    "keeping forecast accuracy intact, a trade-off buyers in the segment have complained about for "
    "several years. Analysts covering the category noted that mid-market manufacturers increasingly "
    "refuse multi-year implementations, and that vendors are responding by unbundling their suites. "
)

# (competitor, url, source, title, lead, days_ago). Two Kinaxis rows carry the same
# lead so the syndication collapse is visible in the demo rather than asserted.
ARTICLES = [
    ("Kinaxis", "https://supplychaindive.example/kinaxis-midmarket", "supplychaindive.example",
     "Kinaxis launches a mid-market tier priced per user",
     "Kinaxis announced a mid-market edition on Tuesday, priced per user per month with a stated "
     "eight-week implementation, explicitly targeting manufacturers under $500m revenue. ", 4),
    ("Kinaxis", "https://logisticsweekly.example/kinaxis-midmarket-tier", "logisticsweekly.example",
     "Kinaxis launches a mid-market tier priced per user",
     "Kinaxis announced a mid-market edition on Tuesday, priced per user per month with a stated "
     "eight-week implementation, explicitly targeting manufacturers under $500m revenue. ", 4),
    ("Kinaxis", "https://manufacturingtoday.example/kinaxis-partners", "manufacturingtoday.example",
     "Kinaxis signs three implementation partners in Germany",
     "Kinaxis has added three regional implementation partners across Germany and Austria to shorten "
     "onboarding for European customers. ", 11),
    ("Kinaxis", "https://shortnote.example/kinaxis-brief", "shortnote.example",
     "Kinaxis brief", "Kinaxis update.", 6),
    ("Blue Yonder", "https://supplychaindive.example/blueyonder-forecasting-ai", "supplychaindive.example",
     "Blue Yonder folds forecasting into its base licence",
     "Blue Yonder will include demand forecasting in its base licence from next quarter, removing it "
     "as a paid add-on for existing suite customers. ", 8),
    ("Netstock", "https://distributiontrends.example/netstock-emea", "distributiontrends.example",
     "Netstock opens an Amsterdam office to serve EMEA distributors",
     "Netstock is opening an Amsterdam office and hiring a regional sales team to serve European "
     "distributors directly rather than through resellers. ", 15),
    ("Netstock", "https://distributiontrends.example/netstock-pricing", "distributiontrends.example",
     "Netstock adds a free tier for single-warehouse operators",
     "Netstock introduced a free tier covering a single warehouse and up to 500 SKUs, positioning it "
     "as an entry point for operators currently using spreadsheets. ", 21),
    # Mentions nobody we track: proves the relevance gate leaves it unlinked
    # rather than attributing the market's news to a company.
    ("(none)", "https://supplychaindive.example/market-roundup", "supplychaindive.example",
     "Planning software spend grew 9% this year",
     "Spending on planning software rose across the category with no single vendor taking obvious "
     "share, according to a survey of 400 operations leaders. ", 9),
]

FINDINGS = {
    "Kinaxis": {
        "headline": "Kinaxis is moving down-market with per-user pricing",
        "whats_up": (
            "Kinaxis launched a mid-market edition priced per user per month, with a stated eight-week "
            "implementation aimed explicitly at manufacturers under $500m revenue. In the same period it "
            "signed three implementation partners across Germany and Austria to shorten European onboarding."
        ),
        "impact": (
            "This attacks Northwind's two clearest advantages at once. Eight weeks narrows the "
            "implementation-speed gap against our 30-day claim from years to weeks, and per-user pricing "
            "makes a like-for-like cost comparison possible where previously an enterprise licence was "
            "simply out of reach for these buyers. The German partner network also lands in a region we "
            "sell into without local delivery support."
        ),
        "impact_level": "high",
        "signals": ["pricing", "down-market", "partnerships", "expansion"],
        "actions": [
            {"action": "Publish an implementation-timeline comparison with named customer references and dates.",
             "rationale": "Our 30-day claim is now contestable rather than unique; unverified claims lose to a competitor's published number.",
             "effort": "low", "urgency": "now"},
            {"action": "Model our usage-based price against their per-user tier at 50, 150 and 400 seats.",
             "rationale": "Sales needs the crossover point before it comes up in a live deal, not after.",
             "effort": "medium", "urgency": "now"},
            {"action": "Line up a delivery partner in DACH before their partner network beds in.",
             "rationale": "Local delivery is the gap their three new partners are there to close.",
             "effort": "high", "urgency": "this_quarter"},
        ],
        "confidence": 0.82,
    },
    "Blue Yonder": {
        "headline": "Blue Yonder is bundling forecasting into its base licence",
        "whats_up": (
            "Blue Yonder will include demand forecasting in its base licence from next quarter, removing it "
            "as a paid add-on for existing suite customers."
        ),
        "impact": (
            "Any prospect already running Blue Yonder can now switch on forecasting at no incremental "
            "licence cost, which removes budget as a reason to evaluate us and reframes the conversation "
            "onto accuracy alone. It matters less for greenfield accounts, where a full suite purchase is "
            "still the barrier that sends buyers to us in the first place."
        ),
        "impact_level": "medium",
        "signals": ["bundling", "pricing"],
        "actions": [
            {"action": "Build an accuracy-benchmark offer for accounts already on a suite.",
             "rationale": "When price stops being the wedge, measured forecast accuracy is the remaining one.",
             "effort": "medium", "urgency": "this_quarter"},
            {"action": "Flag existing-suite accounts in the pipeline so they are qualified differently.",
             "rationale": "These deals now have a free alternative and should not be forecast like greenfield.",
             "effort": "low", "urgency": "now"},
        ],
        "confidence": 0.71,
    },
    "Netstock": {
        "headline": "Netstock is buying the entry-level segment with a free tier",
        "whats_up": (
            "Netstock introduced a free tier covering one warehouse and up to 500 SKUs, aimed at operators "
            "still working in spreadsheets, and opened an Amsterdam office to sell into EMEA directly "
            "instead of through resellers."
        ),
        "impact": (
            "The free tier is below the size of customer we serve, so there is little direct deal overlap "
            "today. The risk is slower and further out: operators who start there grow into our range with "
            "a system already in place, which turns a greenfield sale into a displacement. The EMEA move "
            "puts them in our territory sooner than the free tier will."
        ),
        "impact_level": "low",
        "signals": ["free-tier", "expansion", "land-and-expand"],
        "actions": [
            {"action": "Define the SKU and warehouse count where their free tier stops being sufficient, and target that trigger.",
             "rationale": "Catching accounts at the outgrow moment is cheaper than displacing an embedded system later.",
             "effort": "medium", "urgency": "watch"},
        ],
        "confidence": 0.64,
    },
}


def wipe() -> int:
    row = db.fetch_one("select id from projects where name = %s", (STUDY_NAME,))
    if not row:
        print("No demo study found.")
        return 0
    # Cascades clear business_profiles, competitors, accounts, findings and links.
    db.execute("delete from projects where id = %s", (int(row["id"]),))
    print(f"Removed demo study {row['id']}.")
    return 0


def seed() -> int:
    now = datetime.now(timezone.utc)

    existing = db.fetch_one("select id from projects where name = %s", (STUDY_NAME,))
    if existing:
        db.execute("delete from projects where id = %s", (int(existing["id"]),))
        print("Reset the existing demo study.")

    project = db.fetch_one(
        """
        insert into projects (name, mode, status, description, keywords, repeat_enabled,
                              repeat_interval_value, repeat_interval_unit, next_run_at)
        values (%s, 'competitor', 'active', %s, %s, true, 1, 'days', %s)
        returning id
        """,
        (STUDY_NAME, PROFILE["description"], Jsonb(PROFILE["keywords"]), now + timedelta(days=1)),
    )
    project_id = int(project["id"])
    print(f"Created study {project_id}: {STUDY_NAME}")

    from services.competitors import business_profile_store

    business_profile_store.upsert_profile(project_id, {
        **PROFILE,
        "scrape_status": "success",
        "scraped_pages": 6,
        "scraped_chars": 14820,
        "scraped_at": now - timedelta(minutes=40),
        "analysis_model": "seeded",
    })
    print(f"  business profile: {PROFILE['name']}")

    by_name: dict[str, dict] = {}
    for entry in COMPETITORS:
        accounts = entry.pop("accounts")
        record = competitors_store.upsert_competitor(project_id, {**entry, "status": "tracked"})
        by_name[record["name"]] = record
        entry["accounts"] = accounts  # keep the module-level constant reusable
        for account in accounts:
            stored = competitors_store.upsert_account(record["id"], {
                "platform": account["platform"], "url": account["url"],
                "handle": account["handle"], "confidence": account["confidence"],
            })
            if stored and account["valid"]:
                competitors_store.set_account_validation(stored["id"], "valid", "Confirmed for demo")
        print(f"  competitor: {record['name']} ({record['size_tier']}, rank {record['size_rank']}), "
              f"{len(accounts)} channel(s)")

    competitors_store.rerank_competitors(project_id)

    # Articles go in through the real dedup path so story grouping is genuine.
    with db.transaction() as cur:
        for _competitor, url, source, title, lead, days_ago in ARTICLES:
            published = now - timedelta(days=days_ago)
            text = lead + FILLER * (1 if len(lead) > 60 else 0)
            cur.execute(
                """
                insert into articles (url, source, source_url, title, text, summary,
                                      published, published_at, published_precision,
                                      fetched_at, sentiment, article_category)
                values (%s, %s, %s, %s, %s, %s, %s, %s, 'exact', %s, 'neutral', 'news')
                on conflict (url) do update set title = excluded.title, text = excluded.text
                returning id, title, text, published_at
                """,
                (url, source, f"https://{source}", title, text, lead.strip(),
                 published.isoformat(), published, now),
            )
            row = cur.fetchone()
            story_id, _created = dedup.assign_story(cur, row, project_id=None)
            cur.execute("update articles set story_id = %s where id = %s", (story_id, row["id"]))
            cur.execute(
                """
                insert into article_projects (article_id, project_id, similarity_score)
                values (%s, %s, 0.9) on conflict do nothing
                """,
                (row["id"], project_id),
            )

    collapse = db.fetch_one(
        """
        select count(*)::int a, count(distinct story_id)::int s
        from articles a join article_projects ap on ap.article_id = a.id
        where ap.project_id = %s
        """,
        (project_id,),
    )
    print(f"  articles: {collapse['a']} rows -> {collapse['s']} independent stories")

    # Real validation gate: relevance, length, and duplicate-story rejection.
    tracked = competitors_store.list_competitors(project_id, status="tracked")
    validation = competitor_analysis.validate_competitor_articles(project_id, tracked, period_days=30)
    print(f"  validated: {validation['linked']} links from {validation['scanned']} articles; "
          f"filtered {validation['rejection_reasons'] or '{}'}")

    for competitor in tracked:
        template = FINDINGS.get(competitor["name"])
        if not template:
            continue
        evidence = competitor_analysis._evidence_for(int(competitor["id"]))
        counts = competitor_analysis._counts_for(int(competitor["id"]))
        db.execute(
            """
            insert into competitor_findings (
                project_id, competitor_id, period_start, period_end, headline, whats_up,
                impact, impact_level, actions, signals, evidence, confidence,
                article_count, story_count, validation_status, analysis_model,
                prompt_version, generated_at
            )
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending','seeded',%s,%s)
            """,
            (
                project_id, int(competitor["id"]), now - timedelta(days=30), now,
                template["headline"], template["whats_up"], template["impact"],
                template["impact_level"], Jsonb(template["actions"]), Jsonb(template["signals"]),
                Jsonb([
                    {
                        "article_id": row["id"], "url": row.get("url"), "title": row.get("title"),
                        "source": row.get("source"),
                        "published_at": (row.get("published_at") or row.get("created_at")).isoformat()
                        if (row.get("published_at") or row.get("created_at")) else None,
                        "excerpt": (row.get("summary") or row.get("text") or "")[:400],
                    }
                    for row in evidence
                ]),
                template["confidence"], counts["articles"], counts["stories"],
                competitor_analysis.PROMPT_VERSION, now - timedelta(minutes=12),
            ),
        )
        db.execute("update competitors set last_analyzed_at = %s where id = %s",
                   (now - timedelta(minutes=12), int(competitor["id"])))
        print(f"  finding: {competitor['name']} [{template['impact_level']}] "
              f"{counts['stories']} source(s), {len(template['actions'])} action(s)")

    print(f"\nDone. Open /competitors/{project_id} in the dashboard.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wipe", action="store_true", help="remove the demo study and exit")
    args = parser.parse_args()

    if not db.get_database_url():
        print("DATABASE_URL is missing.")
        return 2
    return wipe() if args.wipe else seed()


if __name__ == "__main__":
    raise SystemExit(main())
