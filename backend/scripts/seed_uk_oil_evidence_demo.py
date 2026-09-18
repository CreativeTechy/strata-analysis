"""Seed a source-balanced UK oil Evidence demo without making network calls.

The records are concise analyst summaries of the linked public sources. They
are intentionally labelled as summaries rather than scraped/verbatim content.
Run from backend/ (or inside the backend container):

    python scripts/seed_uk_oil_evidence_demo.py
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: F401 - loads backend/.env before db is used
import db
from psycopg.types.json import Jsonb
from services.evidence.workspace import capture_run_snapshot, generate_for_run

PROJECT_NAME = "UK Oil Evidence Demo"
RUN_ID = "sm68-demo-run-c-expanded"

# title, publisher, url, date, summary, sentiment, gender, age, region,
# segment, source class, origin group, key points
SOURCES = [
    ("Clean-energy jobs are not replacing North Sea losses fast enough", "UK Parliament - Scottish Affairs Committee", "https://committees.parliament.uk/committee/136/scottish-affairs-committee/news/209788/mps-warn-clean-energy-jobs-not-being-created-at-the-pace-or-scale-needed-to-match-north-sea-oil-and-gas-decline/", "2025-06-18", "The committee warned that oil and gas employment is declining faster than comparable clean-energy work is being created.", "negative", "unknown", "unknown", "Scotland", "policy researcher", "parliamentary finding", "sac-transition-jobs", ["The North Sea energy transition is not creating clean energy jobs fast enough to replace declining oil and gas employment."]),
    ("North Sea oil and gas report", "UK Parliament - Scottish Affairs Committee", "https://publications.parliament.uk/pa/cm5901/cmselect/cmscotaf/459/report.html", "2025-06-18", "The report records 2024 production at a 21st-century low and estimates 115,000 to 120,000 direct and indirect sector jobs in 2023.", "negative", "unknown", "unknown", "Scotland", "policy researcher", "parliamentary report", "sac-north-sea-report", ["UK oil and gas production in 2024 was substantially below the 1999 peak.", "The UK oil and gas sector supports more than 100,000 direct and indirect jobs.", "UK North Sea oil and gas production is projected to decline substantially through 2050."]),
    ("North Sea oil and gas overview", "UK Parliament POST", "https://post.parliament.uk/north-sea-oil-and-gas/", "2025-07-01", "Parliamentary research summarises the mature basin, falling output, energy-security arguments and transition choices.", "mixed", "unknown", "unknown", "United Kingdom", "policy researcher", "research briefing", "post-north-sea", ["UK North Sea oil and gas production is projected to decline substantially through 2050."]),
    ("Statutory Security of Supply Report 2025", "UK Department for Energy Security and Net Zero", "https://www.gov.uk/government/publications/statutory-security-of-supply-report-2025/statutory-security-of-supply-report-2025", "2025-10-30", "The report says no new exploration licences have only a marginal effect on future production and security of supply; it also records declining domestic output.", "neutral", "unknown", "unknown", "United Kingdom", "government official", "government report", "desnz-security-2025", ["New North Sea oil and gas development does not support UK energy security.", "The UK has been a net importer of oil since 2005.", "UK North Sea oil and gas production is projected to decline substantially through 2050."]),
    ("UK oil and gas imports and exports", "House of Commons Library", "https://commonslibrary.parliament.uk/research-briefings/cbp-10905/", "2026-03-12", "The briefing reports that the UK has generally been a net oil importer since 2005 and a net gas importer since 2004.", "neutral", "unknown", "unknown", "United Kingdom", "policy researcher", "research briefing", "commons-imports", ["The UK has been a net importer of oil since 2005."]),
    ("DESNZ annual performance report 2025 to 2026", "UK Department for Energy Security and Net Zero", "https://www.gov.uk/government/publications/desnz-annual-report-and-accounts-2025-to-2026/performance-report", "2026-07-23", "UK oil production rose 2.5% in 2025 while gas output fell 3.3%, leaving combined production slightly lower.", "mixed", "unknown", "unknown", "United Kingdom", "government official", "government report", "desnz-annual-2026", ["UK oil production increased by 2.5 percent in 2025."]),
    ("Energy Trends March 2026", "UK Department for Energy Security and Net Zero", "https://assets.publishing.service.gov.uk/media/69cd13ee9b2e6e135502d088/Energy_Trends_March_2026.pdf", "2026-03-26", "Official statistics put 2025 primary oil production at 31.4 million tonnes, up 2.4% from the record-low prior year.", "neutral", "unknown", "unknown", "United Kingdom", "energy statistician", "official statistics", "energy-trends-2026", ["UK oil and gas production in 2024 was substantially below the 1999 peak."]),
    ("North Sea future plan", "UK Government", "https://www.gov.uk/government/news/north-sea-future-plan-for-fair-managed-and-prosperous-transition", "2025-11-26", "The plan combines managed decline with clean-energy investment and cites 70,000 oil and gas jobs lost between 2016 and 2023.", "mixed", "unknown", "unknown", "United Kingdom", "government official", "government announcement", "north-sea-future-plan", ["The North Sea energy transition is not creating clean energy jobs fast enough to replace declining oil and gas employment."]),
    ("Consumer impacts of market conditions, wave 6", "Ofgem", "https://www.ofgem.gov.uk/research/consumer-impacts-market-conditions-survey-wave-6-january-february-2025", "2025-05-08", "Ofgem surveyed 3,458 consumers: 34% sought help with bills, 58% found the market complex, and sector trust was 41%.", "negative", "unknown", "unknown", "Great Britain", "energy consumer", "regulator survey", "ofgem-consumer-wave-6", ["Thirty-four percent of surveyed energy consumers sought help with their bills."]),
    ("Energy consumer satisfaction survey", "Ofgem", "https://www.ofgem.gov.uk/cy/research/energy-consumer-satisfaction-survey-july-august-2025", "2025-11-04", "The regulator's recurring survey measures supplier satisfaction, contact experience and consumer vulnerability.", "mixed", "unknown", "unknown", "Great Britain", "energy consumer", "regulator survey", "ofgem-satisfaction-2025", ["Energy supplier satisfaction varies across consumer groups."]),
    ("Attitudes to energy system cost allocation", "Citizens Advice", "https://www.citizensadvice.org.uk/policy/publications/consumers-attitudes-to-energy-system-cost-allocation-and-recovery-spark/", "2025-07-17", "Consumer research explores who the public thinks should bear the cost of upgrading and decarbonising the energy system.", "mixed", "unknown", "unknown", "Great Britain", "energy consumer", "consumer research", "ca-cost-allocation", ["Consumers have mixed views about how energy transition costs should be allocated."]),
    ("Small business experiences of the energy retail market", "Citizens Advice", "https://www.citizensadvice.org.uk/policy/publications/small-and-micro-businesses-experiences-of-the-energy-retail-market/", "2025-02-20", "Research documents billing, contract and support problems experienced by small and micro businesses.", "negative", "unknown", "unknown", "Great Britain", "small business owner", "consumer research", "ca-small-business", ["Small businesses report problems with energy billing, contracts and supplier support."]),
    ("Business Outlook 2025", "Offshore Energies UK", "https://oeuk.org.uk/product/business-outlook-report-2025/", "2025-03-25", "The industry body says the wider offshore energy sector could attract £200 billion of investment by 2035 and support about 200,000 skilled jobs.", "positive", "unknown", "unknown", "United Kingdom", "industry representative", "industry report", "oeuk-outlook-2025", ["New North Sea oil and gas development does support UK energy security.", "The UK oil and gas sector supports more than 100,000 direct and indirect jobs."]),
    ("North Sea policy versus geology", "Offshore Energies UK", "https://oeuk.org.uk/policy-versus-geology-new-report-reveals-165bn-choice-facing-north-sea-future/", "2025-09-09", "OEUK argues that policy choices could affect up to £165 billion of offshore value and the pace of domestic production decline.", "positive", "unknown", "unknown", "United Kingdom", "industry representative", "industry advocacy", "oeuk-policy-geology", ["New North Sea oil and gas development does support UK energy security."]),
    ("Penguins field restarts production", "Shell", "https://www.shell.com/news-and-insights/newsroom/news-and-media-releases/2025/shell-starts-up-new-facility-in-uk-north-sea-restoring-production-from-the-penguins-field.html", "2025-02-04", "Shell says the redeveloped field can peak near 45,000 barrels of oil equivalent per day and supply gas equivalent to around 700,000 UK homes annually.", "positive", "unknown", "unknown", "North Sea", "company spokesperson", "company announcement", "shell-penguins", ["The Penguins redevelopment has a peak production capacity of about 45,000 barrels of oil equivalent per day."]),
    ("Equinor and Shell announce UK joint venture", "Equinor", "https://www.equinor.com/news/20241205-equinor-and-shell-to-create-independent-oil-and-gas-company", "2024-12-05", "The companies said their planned UK joint venture was expected to produce more than 140,000 barrels of oil equivalent per day in 2025.", "positive", "unknown", "unknown", "United Kingdom", "company spokesperson", "company announcement", "equinor-shell-jv", ["The Equinor and Shell UK joint venture expects production above 140,000 barrels of oil equivalent per day."]),
    ("Consultation must create real jobs", "Unite the Union", "https://sharepoint.unitetheunion.org/news-events/news/2025/march/government-s-north-sea-consultation-must-create-real-jobs-unite", "2025-03-05", "Unite says a transition needs a concrete programme of secure, well-paid replacement jobs and domestic manufacturing.", "negative", "female", "unknown", "Scotland", "union representative", "union statement", "unite-consultation", ["The North Sea energy transition is not creating clean energy jobs fast enough to replace declining oil and gas employment."]),
    ("No ban without a plan campaign", "Unite the Union", "https://sharepoint.unitetheunion.org/news-events/news/2025/january/over-half-of-msps-support-unite-s-no-ban-without-a-plan-oil-and-gas-campaign", "2025-01-30", "Unite reports support from 65 MSPs and calls for 35,000 transition jobs by 2030 before further restrictions.", "positive", "unknown", "unknown", "Scotland", "offshore worker", "union campaign", "unite-no-ban", ["The UK should continue permitting new North Sea oil and gas developments."]),
    ("Britain ends new fossil-fuel exploration", "Greenpeace UK", "https://www.greenpeace.org.uk/news/britain-ends-new-fossil-fuel-exploration/", "2025-11-26", "Greenpeace supports ending new exploration licences and argues that fossil-fuel expansion worsens climate and price risks.", "negative", "unknown", "unknown", "United Kingdom", "climate campaigner", "ngo statement", "greenpeace-exploration", ["The UK should not continue permitting new North Sea oil and gas developments."]),
    ("Jackdaw climate-impact challenge", "Greenpeace UK", "https://www.greenpeace.org.uk/news/shell-forced-to-reveal-true-scale-of-jackdaws-climate-impacts/", "2025-08-21", "Greenpeace argues that additional North Sea gas does not lower bills because gas is traded in an international market.", "negative", "unknown", "unknown", "United Kingdom", "climate campaigner", "ngo statement", "greenpeace-jackdaw", ["New North Sea oil and gas development does not support UK energy security."]),
    ("GB adults on new North Sea developments", "YouGov", "https://yougov.com/en-gb/daily-results/20260529-98c5b-1", "2026-05-29", "Among 6,303 GB adults, 46% allowed new developments, 23% preferred existing fields only, 10% wanted existing production closed and 21% did not know.", "positive", "unknown", "unknown", "Great Britain", "survey respondent", "national opinion poll", "yougov-gb-2026", ["Forty-six percent of surveyed GB adults support allowing new North Sea oil and gas developments."]),
    ("Scottish adults: overall view", "YouGov", "https://ygo-assets-websites-editorial-emea.yougov.net/documents/Internal_NorthSeaOilSC_260318.pdf#overall", "2026-03-18", "In a survey of 1,217 Scottish adults, 37% supported banning new developments and 45% opposed a ban.", "positive", "unknown", "unknown", "Scotland", "survey respondent", "Scottish opinion poll", "yougov-scotland-overall", ["Forty-five percent of surveyed Scottish adults oppose a ban on new North Sea oil and gas developments."]),
    ("Scottish men: view on a development ban", "YouGov", "https://ygo-assets-websites-editorial-emea.yougov.net/documents/Internal_NorthSeaOilSC_260318.pdf#gender-male", "2026-03-18", "Among Scottish male respondents, 36% supported a ban on new developments and 56% opposed it.", "positive", "male", "unknown", "Scotland", "survey respondent", "Scottish opinion poll", "yougov-scotland-male", ["Fifty-six percent of surveyed Scottish men oppose a ban on new North Sea oil and gas developments."]),
    ("Scottish women: view on a development ban", "YouGov", "https://ygo-assets-websites-editorial-emea.yougov.net/documents/Internal_NorthSeaOilSC_260318.pdf#gender-female", "2026-03-18", "Among Scottish female respondents, 39% supported a ban and 36% opposed it.", "mixed", "female", "unknown", "Scotland", "survey respondent", "Scottish opinion poll", "yougov-scotland-female", ["Thirty-nine percent of surveyed Scottish women support a ban on new North Sea oil and gas developments."]),
    ("Scottish age 16-24: view on a development ban", "YouGov", "https://ygo-assets-websites-editorial-emea.yougov.net/documents/Internal_NorthSeaOilSC_260318.pdf#age-16-24", "2026-03-18", "For respondents aged 16 to 24, 48% supported a ban and 34% opposed it.", "negative", "unknown", "16-24", "Scotland", "survey respondent", "Scottish opinion poll", "yougov-scotland-16-24", ["Forty-eight percent of surveyed Scottish people aged 16 to 24 support a ban on new North Sea oil and gas developments."]),
    ("Scottish age 25-49: view on a development ban", "YouGov", "https://ygo-assets-websites-editorial-emea.yougov.net/documents/Internal_NorthSeaOilSC_260318.pdf#age-25-49", "2026-03-18", "For respondents aged 25 to 49, 36% supported a ban and 40% opposed it.", "mixed", "unknown", "25-49", "Scotland", "survey respondent", "Scottish opinion poll", "yougov-scotland-25-49", ["Forty percent of surveyed Scottish people aged 25 to 49 oppose a ban on new North Sea oil and gas developments."]),
    ("Scottish age 50-64: view on a development ban", "YouGov", "https://ygo-assets-websites-editorial-emea.yougov.net/documents/Internal_NorthSeaOilSC_260318.pdf#age-50-64", "2026-03-18", "For respondents aged 50 to 64, 38% supported a ban and 49% opposed it.", "positive", "unknown", "50-64", "Scotland", "survey respondent", "Scottish opinion poll", "yougov-scotland-50-64", ["Forty-nine percent of surveyed Scottish people aged 50 to 64 oppose a ban on new North Sea oil and gas developments."]),
    ("Scottish age 65+: view on a development ban", "YouGov", "https://ygo-assets-websites-editorial-emea.yougov.net/documents/Internal_NorthSeaOilSC_260318.pdf#age-65-plus", "2026-03-18", "For respondents aged 65 and over, 34% supported a ban and 57% opposed it.", "positive", "unknown", "65_plus", "Scotland", "survey respondent", "Scottish opinion poll", "yougov-scotland-65-plus", ["Fifty-seven percent of surveyed Scottish people aged 65 and over oppose a ban on new North Sea oil and gas developments."]),
    ("Public attitudes to domestic oil and gas production", "UK Department for Energy Security and Net Zero", "https://www.gov.uk/government/statistics/desnz-public-attitudes-tracker-summer-2025", "2025-11-03", "The nationally representative tracker found 11% agreed the UK should reduce domestic oil and gas production even if this increased imports.", "mixed", "unknown", "unknown", "United Kingdom", "survey respondent", "official opinion survey", "desnz-attitudes-2025", ["Eleven percent of surveyed UK adults support reducing domestic oil and gas production even if imports increase."]),
]


def seed() -> dict:
    project = db.fetch_one("select id from projects where name=%s", (PROJECT_NAME,))
    if not project:
        project = db.execute(
            """insert into projects (name,status,mode,description,location,target_audience,keywords)
               values (%s,'active','sentiment',%s,'United Kingdom',%s,%s) returning id""",
            (PROJECT_NAME, "Evidence-led UK oil, energy security, jobs and public opinion demo.", "UK public, policymakers, workers and energy stakeholders", Jsonb(["North Sea oil", "energy security", "energy transition"])),
        )
        db.execute("insert into project_users (project_id,user_id) select %s,id from users on conflict do nothing", (project["id"],))
    project_id = int(project["id"])

    db.execute("delete from pipeline_runs where id=%s", (RUN_ID,))
    db.execute(
        """insert into pipeline_runs
           (id,pipeline,project_id,status,stage,message,articles_selected,articles_analyzed,articles_failed,started_at,finished_at)
           values (%s,'analysis',%s,'success','analyze',%s,%s,%s,0,now(),now())""",
        (RUN_ID, project_id, "Curated UK public-source corpus loaded for the Evidence demo.", len(SOURCES), len(SOURCES)),
    )

    ids = []
    ids_by_url = {}
    by_publisher = Counter()
    for row in SOURCES:
        title, publisher, url, published, summary, sentiment, gender, age, region, segment, source_type, origin_group, points = row
        base_url = url.split("#", 1)[0]
        text = f"{summary} This is a concise analyst-authored summary of the linked public source, retained for an offline product demonstration."
        provenance = {
            "publisher": publisher,
            "original_url": base_url,
            "original_attribution": publisher,
            "source_type": "curated public-source summary",
            "document_type": source_type,
            "relationship_to_subject": segment,
            "origin_group": origin_group,
            "verification_status": "verified" if ("gov.uk" in base_url or "parliament.uk" in base_url or "ofgem.gov.uk" in base_url) else "unassessed",
            "collection_method": "manual curation from public source",
        }
        article = db.execute(
            """insert into articles
               (url,source,source_url,title,published,published_at,published_precision,text,summary,
                sentiment,relevance_score,category,article_category,writer_tone,article_tone,
                region,gender,age_range,segment,verified,organizations,entities,topics,key_points,
                source_language,source_language_confidence,analysis_status,analysis_model,
                analysis_pipeline_version,analysis_attempt_count,analyzed_at,content_hash,
                pipeline_run_id,source_provenance)
               values (%s,%s,%s,%s,%s,%s::timestamptz,'day',%s,%s,%s,0.95,'public_affairs','news',
                       'formal','neutral',%s,%s,%s,%s,%s,%s,%s,%s,%s,'en',1.0,'success',
                       'curated-demo','evidence-demo-v1',1,now(),%s,%s,%s)
               on conflict (url) do update set
                 source=excluded.source,source_url=excluded.source_url,title=excluded.title,published=excluded.published,
                 published_at=excluded.published_at,text=excluded.text,summary=excluded.summary,sentiment=excluded.sentiment,
                 region=excluded.region,gender=excluded.gender,age_range=excluded.age_range,segment=excluded.segment,
                 verified=excluded.verified,organizations=excluded.organizations,entities=excluded.entities,
                 topics=excluded.topics,key_points=excluded.key_points,analysis_status='success',analyzed_at=now(),
                 content_hash=excluded.content_hash,pipeline_run_id=excluded.pipeline_run_id,source_provenance=excluded.source_provenance
               returning id""",
            (url, publisher, base_url, title, published, f"{published}T12:00:00Z", text, summary, sentiment,
             region, gender, age, segment, provenance["verification_status"] == "verified",
             Jsonb([publisher]), Jsonb(["United Kingdom", "North Sea"]), Jsonb(["UK oil and energy"]), Jsonb(points),
             hashlib.sha256(text.encode()).hexdigest(), RUN_ID, Jsonb(provenance)),
        )
        article_id = int(article["id"])
        ids.append(article_id)
        ids_by_url[url] = article_id
        by_publisher[publisher] += 1
        db.execute("insert into article_projects (article_id,project_id,similarity_score) values (%s,%s,1) on conflict (article_id,project_id) do update set similarity_score=1", (article_id, project_id))
        db.execute(
            """insert into article_analyses
               (run_id,article_id,summary,sentiment,relevance_score,category,article_category,writer_tone,
                article_tone,organizations,entities,topics,key_points,gender,age_range,region,segment,
                source_language,source_language_confidence,analysis_model,analysis_pipeline_version,analysis_status,analyzed_at)
               values (%s,%s,%s,%s,0.95,'public_affairs','news','formal','neutral',%s,%s,%s,%s,%s,%s,%s,%s,'en',1.0,'curated-demo','evidence-demo-v1','success',now())""",
            (RUN_ID, article_id, summary, sentiment, Jsonb([publisher]), Jsonb(["United Kingdom", "North Sea"]),
             Jsonb(["UK oil and energy"]), Jsonb(points), gender, age, region, segment),
        )

    for publisher, count in by_publisher.items():
        db.execute(
            """insert into pipeline_run_documents (run_id,document,selected,analyzed,failed,note)
               values (%s,%s,%s,%s,0,'Curated public-source summaries')""",
            (RUN_ID, publisher, count, count),
        )
    poll_url = "https://ygo-assets-websites-editorial-emea.yougov.net/documents/Internal_NorthSeaOilSC_260318.pdf"
    observations = [
        ("overall", "all adults", "Support ban", 37, 1217), ("overall", "all adults", "Oppose ban", 45, 1217),
        ("gender", "male", "Support ban", 36, None), ("gender", "male", "Oppose ban", 56, None),
        ("gender", "female", "Support ban", 39, None), ("gender", "female", "Oppose ban", 36, None),
        ("age", "16-24", "Support ban", 48, None), ("age", "16-24", "Oppose ban", 34, None),
        ("age", "25-49", "Support ban", 36, None), ("age", "25-49", "Oppose ban", 40, None),
        ("age", "50-64", "Support ban", 38, None), ("age", "50-64", "Oppose ban", 49, None),
        ("age", "65_plus", "Support ban", 34, None), ("age", "65_plus", "Oppose ban", 57, None),
    ]
    for dimension, cohort, answer, percentage, sample_size in observations:
        article_url = f"{poll_url}#{'overall' if dimension == 'overall' else dimension + '-' + cohort.replace('_plus', '-plus')}"
        db.execute(
            """insert into survey_observations
               (project_id,article_id,run_id,study_key,question,answer,percentage,population,
                cohort_dimension,cohort_value,sample_size,fieldwork_start,fieldwork_end,source_url)
               values (%s,%s,%s,'yougov-scotland-north-sea-2026',%s,%s,%s,'Scottish adults',%s,%s,%s,
                       '2026-03-11','2026-03-18',%s)
               on conflict (project_id,study_key,cohort_dimension,cohort_value,answer) do update set
                 article_id=excluded.article_id,run_id=excluded.run_id,percentage=excluded.percentage,
                 sample_size=excluded.sample_size,source_url=excluded.source_url""",
            (project_id, ids_by_url.get(article_url), RUN_ID,
             "Should new North Sea oil and gas developments be banned?", answer, percentage,
             dimension, cohort, sample_size, poll_url),
        )
    db.execute("update projects set status='active',last_run_at=now(),last_run_status='success' where id=%s", (project_id,))
    captured = capture_run_snapshot(RUN_ID, project_id)
    evidence = generate_for_run(RUN_ID, project_id)
    return {"project_id": project_id, "run_id": RUN_ID, "seeded": len(ids), "captured": captured, **evidence}


if __name__ == "__main__":
    print(seed())
