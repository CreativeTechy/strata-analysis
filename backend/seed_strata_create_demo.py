"""Seed the real "strata create - competitor study" as a demo dataset.

Unlike `seed_competitor_demo.py` (a fully fictional "Northwind" study), this
reproduces an actual completed run of this pipeline against strata create's
own competitors: the real derived business profile, the ten competitors an
AI discovery pass found and ranked, their verified channels, and the five
AI-generated reports that had run by the time this was captured.

What is intentionally NOT reproduced: the underlying scraped `articles` rows
and the "filtered out" rejection trail behind each report. Those would mean
committing full real scraped article bodies (not just the short excerpts
already carried in a report's evidence) to source control. Each report's
evidence panel renders straight from the `competitor_findings.evidence`
column, so it still shows real excerpts and article counts; only the
report page's "evidence that was filtered out" section is empty for this
seeded project, since that section queries the `articles` table live.

    python seed_strata_create_demo.py            # create (idempotent-ish: resets the study)
    python seed_strata_create_demo.py --wipe      # remove the study and exit
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from services.competitors import business_profile_store
from services.competitors import competitors_store
import db

STUDY_NAME = "strata create - competitor study"

PROFILE = {
    "name": "strata create",
    "website": "https://stratacreate.com",
    "industry": "Experiential Marketing",
    "market": (
        "Brand experience agency for global brands, delivering integrated experiential "
        "solutions across physical, virtual, and hybrid events."
    ),
    "positioning": (
        "A people-first brand experience agency that uses insight, strategy, and creativity "
        "to craft integrated, unforgettable brand experiences that maximize budgets and build "
        "meaningful connections."
    ),
    "offerings": [
        "Immersive brand experiences", "Virtual and hybrid events", "Conference production",
        "Showroom and retail experience design", "Brand strategy and insights",
        "End-to-end integrated experience solutions", "Asset management for experiences",
    ],
    "audience": [
        "Automotive brands (Peugeot, Volvo)",
        "Consumer electronics and technology firms (Sony, developer communities)",
        "Pharmaceutical companies",
        "Beauty and retail brands (Eylure X)",
        "Professional communities (product management via Mind the Product)",
    ],
    "differentiators": [
        "People-first culture and team professionalism",
        "Integrated offering from strategy through production to asset management",
        "Budget-conscious creativity that maximizes value without compromise",
        "Long-term client partnerships (8+ years with Mind the Product)",
        "Calm, reliable on-site execution under pressure",
    ],
    "keywords": [
        "brand experience agency", "experiential marketing", "immersive events", "virtual events",
        "hybrid events", "conference production", "brand activation", "integrated brand experience",
        "global events", "strategic creative",
    ],
    "context_summary": (
        "Strata Create is a brand experience agency that designs and produces immersive events, "
        "conferences, and virtual/hybrid experiences for global brands in automotive, technology, "
        "pharmaceutical, and consumer sectors. The agency positions itself as an insight-driven, "
        "integrated partner that handles everything from strategy to asset management, emphasizing "
        "budget efficiency and long-term client relationships. Its client roster includes Peugeot, "
        "Sony, Volvo, and Mind the Product (an 8-year collaboration), demonstrating credibility "
        "across industries. Any competitor developing integrated experiential capabilities with a "
        "strategic, budget-conscious, and people-first approach would be directly relevant to "
        "Strata’s market."
    ),
    "scraped_pages": 3,
    "scraped_chars": 3618,
    "analysis_model": "deepseek-v4-pro",
}

COMPETITORS = [
    {
        "name": "Freeman", "website": "https://freeman.com", "domain": "freeman.com",
        "size_tier": "enterprise", "size_rank": 1,
        "description": (
            "Global event production and brand experience company offering end-to-end solutions "
            "for large-scale conferences, virtual/hybrid events, and experiential activations."
        ),
        "size_signals": {
            "basis": ["private company", "annual revenue over $2 billion", "operations in 90+ locations worldwide"],
            "why_competitor": "Provides integrated event production and immersive brand experiences that compete directly for automotive, tech, and pharma conference and experiential briefs.",
            "search_hits": 4, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://freeman.com", "handle": "freeman.com", "confidence": 1.0},
            {"platform": "blog", "url": "https://freeman.com/feed", "handle": None, "confidence": 0.7},
        ],
    },
    {
        "name": "Global Experience Specialists (GES)", "website": "https://ges.com", "domain": "ges.com",
        "size_tier": "enterprise", "size_rank": 2,
        "description": (
            "Full-service event marketing and exhibition company creating live experiences, "
            "exhibits, and experiential activations for global brands."
        ),
        "size_signals": {
            "basis": ["public company (Viad Corp)", "major event contractor in North America and EMEA", "global network of offices"],
            "why_competitor": "Competes in designing and producing brand activations and trade show experiences for automotive and consumer technology clients.",
            "search_hits": 3, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://ges.com", "handle": "ges.com", "confidence": 1.0},
            {"platform": "blog", "url": "https://ges.com/feed", "handle": None, "confidence": 0.7},
        ],
    },
    {
        "name": "Jack Morton Worldwide", "website": "https://jackmorton.com", "domain": "jackmorton.com",
        "size_tier": "enterprise", "size_rank": 3,
        "description": (
            "Global brand experience agency creating integrated experiential campaigns, virtual "
            "events, and conference productions for iconic brands."
        ),
        "size_signals": {
            "basis": ["subsidiary of Interpublic Group (IPG)", "offices in over 15 countries", "founded in 1939"],
            "why_competitor": "Delivers end-to-end brand experiences, virtual/hybrid events, and conference production for technology, automotive, and consumer sectors directly overlapping Strata's offerings.",
            "search_hits": 0, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://jackmorton.com", "handle": "jackmorton.com", "confidence": 1.0},
            {"platform": "blog", "url": "https://jackmorton.com/brand-experience/f1-brand-experience-report-may-2026/", "handle": None, "confidence": 0.9},
            {"platform": "x", "url": "https://x.com/jackmorton", "handle": "jackmorton", "confidence": 0.95},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/jack-morton", "handle": "jack-morton", "confidence": 0.9},
            {"platform": "facebook", "url": "https://www.facebook.com/JackMortonWorldwide", "handle": "JackMortonWorldwide", "confidence": 0.85},
        ],
    },
    {
        "name": "George P. Johnson (GPJ)", "website": "https://gpj.com", "domain": "gpj.com",
        "size_tier": "enterprise", "size_rank": 4,
        "description": (
            "Largest independent experiential marketing network, specialising in brand "
            "activations, live events, and integrated experiences for global enterprises."
        ),
        "size_signals": {
            "basis": ["part of Project Worldwide independent holding", "offices across North America, EMEA, and APAC", "recognised as a top experiential agency globally"],
            "why_competitor": "Partners with tech and automotive brands to create immersive experiences and large-scale events, mirroring Strata's integrated strategy-to-execution model.",
            "search_hits": 0, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://gpj.com", "handle": "gpj.com", "confidence": 1.0},
            {"platform": "blog", "url": "https://gpj.com/feed", "handle": None, "confidence": 0.7},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/george-p-johnson", "handle": "george-p-johnson", "confidence": 0.95},
        ],
    },
    {
        "name": "Octagon", "website": "https://octagon.com", "domain": "octagon.com",
        "size_tier": "enterprise", "size_rank": 5,
        "description": (
            "Global sports and entertainment agency creating brand experiences through "
            "sponsorship activations, live events, and content."
        ),
        "size_signals": {
            "basis": ["subsidiary of Interpublic Group (IPG)", "800+ employees worldwide", "works with Fortune 500 brands"],
            "why_competitor": "Delivers large-scale experiential marketing and event production for consumer lifestyle and technology brands, overlapping with Strata's integrated approach and client base.",
            "search_hits": 0, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://octagon.com", "handle": "octagon.com", "confidence": 1.0},
            {"platform": "blog", "url": "https://octagon.com/feed", "handle": None, "confidence": 0.7},
            {"platform": "x", "url": "https://x.com/Octagon", "handle": "Octagon", "confidence": 0.9},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/octagon", "handle": "octagon", "confidence": 0.9},
            {"platform": "instagram", "url": "https://www.instagram.com/octagon", "handle": "octagon", "confidence": 0.9},
        ],
    },
    {
        "name": "MKTG", "website": "https://mktg.com", "domain": "mktg.com",
        "size_tier": "enterprise", "size_rank": 6,
        "description": (
            "Dentsu's lifestyle and experiential marketing network specialising in live events, "
            "brand experiences, and community engagement."
        ),
        "size_signals": {
            "basis": ["subsidiary of Dentsu Group (public)", "global footprint across 25+ markets", "focus on sports, entertainment, and brand experience"],
            "why_competitor": "Produces integrated experiential campaigns and virtual/hybrid events for brands in technology, automotive, and consumer goods, rivalling Strata's offering.",
            "search_hits": 0, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://mktg.com", "handle": "mktg.com", "confidence": 1.0},
            {"platform": "x", "url": "https://x.com/mktg", "handle": "mktg", "confidence": 0.9},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/mktg", "handle": "mktg", "confidence": 0.9},
        ],
    },
    {
        "name": "Momentum Worldwide", "website": "https://momentumww.com", "domain": "momentumww.com",
        "size_tier": "enterprise", "size_rank": 7,
        "description": (
            "Pioneering experiential marketing agency designing integrated brand experiences, "
            "virtual events, and cultural activations for global clients."
        ),
        "size_signals": {
            "basis": ["part of Interpublic Group (IPG)", "global offices in over 20 cities", "recipient of numerous experiential awards"],
            "why_competitor": "Competes in creating insight-driven, end-to-end brand experiences for automotive, pharma, and tech clients, directly matching Strata's strategic and integrated model.",
            "search_hits": 0, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://momentumww.com", "handle": "momentumww.com", "confidence": 1.0},
            {"platform": "news", "url": "https://momentumww.com/news", "handle": "news", "confidence": 0.8},
            {"platform": "blog", "url": "https://www.momentumww.com/advertising-week-advertising-without-a-net-why-creativity-has-to-matter/", "handle": None, "confidence": 0.9},
            {"platform": "x", "url": "https://x.com/momentumWW", "handle": "momentumWW", "confidence": 0.9},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/momentum-worldwide", "handle": "momentum-worldwide", "confidence": 0.95},
            {"platform": "instagram", "url": "https://instagram.com/momentumww", "handle": "momentumww", "confidence": 0.9},
            {"platform": "facebook", "url": "https://facebook.com/momentumww", "handle": "momentumww", "confidence": 0.7},
        ],
    },
    {
        "name": "Pico Far East Holdings", "website": "https://pico.com", "domain": "pico.com",
        "size_tier": "enterprise", "size_rank": 8,
        "description": (
            "Global experiential marketing and exhibition group offering immersive brand "
            "environments, events, and activation services."
        ),
        "size_signals": {
            "basis": ["publicly listed on Hong Kong Stock Exchange", "network in 40+ cities worldwide", "annual revenue over $400 million"],
            "why_competitor": "Delivers experiential marketing and exhibition design for automotive, technology, and pharma sectors, particularly strong in APAC where Strata may also compete.",
            "search_hits": 0, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://pico.com", "handle": "pico.com", "confidence": 1.0},
            {"platform": "news", "url": "https://www.pico.com/news", "handle": "news", "confidence": 0.9},
            {"platform": "blog", "url": "https://pico.com/rss.xml", "handle": None, "confidence": 0.7},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/pico-far-east-holdings-limited", "handle": "pico-far-east-holdings-limited", "confidence": 0.9},
        ],
    },
    {
        "name": "Imagination", "website": "https://imagination.com", "domain": "imagination.com",
        "size_tier": "mid_market", "size_rank": 9,
        "description": (
            "Independent global experience design agency creating immersive brand experiences, "
            "digital installations, and live events for premium brands."
        ),
        "size_signals": {
            "basis": ["independent agency", "offices in 12 cities including London, New York, Shanghai", "over 400 employees"],
            "why_competitor": "Specialises in automotive and technology brand experiences, with an integrated offering from strategy to asset production that mirrors Strata's end-to-end capabilities.",
            "search_hits": 0, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://imagination.com", "handle": "imagination.com", "confidence": 1.0},
            {"platform": "blog", "url": "https://imagination.com/feed", "handle": None, "confidence": 0.7},
            {"platform": "x", "url": "https://x.com/Imagination", "handle": "Imagination", "confidence": 0.9},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/imagination", "handle": "imagination", "confidence": 0.95},
        ],
    },
    {
        "name": "VOK DAMS", "website": "https://vokdams.com", "domain": "vokdams.com",
        "size_tier": "mid_market", "size_rank": 10,
        "description": (
            "International event and experiential agency renowned for automotive and luxury "
            "brand activations, live events, and virtual experiences."
        ),
        "size_signals": {
            "basis": ["independent agency headquartered in Germany", "offices in Europe, Asia, and the Americas", "founded in 1970s with deep automotive expertise"],
            "why_competitor": "Focuses on automotive experiential marketing and event production, directly competing for the same automotive budget-conscious, integrated briefs as Strata.",
            "search_hits": 0, "site_reachable": True,
        },
        "accounts": [
            {"platform": "news", "url": "https://vokdams.com", "handle": "vokdams.com", "confidence": 1.0},
            {"platform": "linkedin", "url": "https://www.linkedin.com/company/vok-dams", "handle": "vok-dams", "confidence": 1.0},
            {"platform": "x", "url": "https://x.com/VOKDAMS", "handle": "VOKDAMS", "confidence": 0.9},
            {"platform": "instagram", "url": "https://instagram.com/vokdams", "handle": "vokdams", "confidence": 0.85},
        ],
    },
]

# Only five of the ten tracked competitors had a report by the time this was
# captured — the rest genuinely hadn't been analyzed yet. That gap is real,
# not an omission, so it is left as-is rather than backfilled.
FINDINGS = {
    "Jack Morton Worldwide": {
        "headline": "Jack Morton static office pages show no new strategic moves",
        "whats_up": (
            "Jack Morton's website features location pages (dated July 2026) for Melbourne, "
            "Madrid, Toronto, New Jersey, Las Vegas, Denver, and Boston. These pages describe a "
            "consistent global portfolio of event and experiential marketing, employee "
            "experiences, trade shows, digital experiences, integrated marketing, and in some "
            "offices fabrication and AV services. No new campaigns, client wins, pricing changes, "
            "or service launches are evident. A 2021 privacy policy is also present but irrelevant "
            "to competitive posture."
        ),
        "impact": (
            "The evidence confirms Jack Morton is a broad-spectrum competitor with fabrication and "
            "AV capabilities, but none of the information indicates a new initiative that would "
            "erode Strata Create's market position. Strata's differentiators—people-first "
            "culture, budget-conscious creativity, and long-term client partnerships—remain "
            "distinct from Jack Morton's enterprise-scale, multi-office model. No immediate threat "
            "to Strata's automotive, tech, pharma, or retail clients is apparent."
        ),
        "impact_level": "low",
        "actions": [],
        "signals": ["global office network"],
        "confidence": 0.3,
        "article_count": 13,
        "story_count": 13,
        "evidence": [
            {"url": "https://jackmorton.com/privacy-policy/", "title": "Privacy Policy | Jack Morton", "source": "jackmorton.com", "excerpt": "The privacy notice details how Jack Morton collects, uses, shares, and protects personal information on jackmorton.com. It covers cookie types, user rights, data retention, and contact information for privacy inquiries.", "published_at": "2021-12-20T00:00:00+00:00"},
            {"url": "https://jackmorton.com/offices/melbourne/", "title": "Melbourne Experiential and Events Agency | Jack Morton", "source": "jackmorton.com", "excerpt": "Jack Morton is a global brand experience agency offering event and experiential marketing, employee experiences, trade shows, digital experiences, and integrated marketing. Their Melbourne office specializes in creating impactful brand experiences across various industries including healthcare and broadcasting.", "published_at": "2026-04-30T00:00:00+00:00"},
            {"url": "https://jackmorton.com/offices/madrid/", "title": "Madrid - Jack Morton | Global Brand Experience Agency", "source": "jackmorton.com", "excerpt": "Jack Morton's Madrid office is a global brand experience agency that creates events and brand activations across Spain and Portugal, combining global expertise with local insight.", "published_at": "2026-07-08T00:00:00+00:00"},
            {"url": "https://jackmorton.com/offices/toronto/", "title": "Toronto - Jack Morton | Global Brand Experience Agency", "source": "jackmorton.com", "excerpt": "The article describes Jack Morton's Toronto office, which offers event and experiential marketing, employee experiences, trade shows, digital experiences, and more. It highlights advanced fabrication capabilities and a specialized AV services team, along with sponsorship consulting and innovation services.", "published_at": "2026-07-22T00:00:00+00:00"},
            {"url": "https://jackmorton.com/offices/new-jersey-office/", "title": "New Jersey - Jack Morton | Global Brand Experience Agency", "source": "jackmorton.com", "excerpt": "Jack Morton's New Jersey office delivers brand experiences through event and experiential marketing, employee experiences, trade shows, and more. The office features a full-service fabrication facility and on-site labor solutions. Their expertise spans sponsorship consulting, innovation, healthcare, and broadcast design.", "published_at": "2026-07-30T00:00:00+00:00"},
            {"url": "https://jackmorton.com/offices/las-vegas/", "title": "Las Vegas - Jack Morton | Global Brand Experience Agency", "source": "jackmorton.com", "excerpt": "Jack Morton is a global brand experience agency with a Las Vegas office that specializes in event and experiential marketing, trade shows, digital experiences, and large-scale fabrication. The agency helps clients drive results through connected systems that scale and deliver lasting impact.", "published_at": "2026-07-22T00:00:00+00:00"},
            {"url": "https://jackmorton.com/offices/denver/", "title": "Denver - Jack Morton | Global Brand Experience Agency", "source": "jackmorton.com", "excerpt": "Jack Morton is a global brand experience agency with a Denver office. They offer services including event and experiential marketing, employee experiences, trade shows, integrated marketing, and digital experiences.", "published_at": "2026-07-22T00:00:00+00:00"},
            {"url": "https://jackmorton.com/offices/boston/", "title": "Boston Marketing Agency | Jack Morton | Global Brand Experience Agency", "source": "jackmorton.com", "excerpt": "Jack Morton is a global brand experience agency based in Boston that offers event and experiential marketing, employee experiences, trade shows, digital experiences, and more. The agency redefines what experiential can achieve with connected systems that scale and deliver lasting impact.", "published_at": "2026-07-22T00:00:00+00:00"},
        ],
    },
    "Octagon": {
        "headline": "Octagon activates Mastercard, Nutrafol at MLB All-Star Week",
        "whats_up": (
            "Octagon delivered fan experiences for Mastercard and Nutrafol during MLB All-Star "
            "Week. Mastercard's activation included a Small Business Contest and a Stand Up To "
            "Cancer moment; Nutrafol focused on hair confidence and the Long Game mentality. "
            "Separately, Octagon's social media highlighted Stephen and Ayesha Curry's "
            "philanthropy award."
        ),
        "impact": (
            "Strata Create’s core business serves automotive, technology, pharmaceutical, and "
            "retail sectors with integrated physical and virtual experiences, not sports "
            "sponsorship activations. While Octagon’s work demonstrates large-scale consumer "
            "brand capability, these activations fall outside Strata’s immediate market focus. "
            "Direct competitive pressure is low, unless Strata clients express interest in "
            "sports-integrated experiences."
        ),
        "impact_level": "low",
        "actions": [
            {
                "action": "Assess current automotive and tech client plans for any sports or fan-experience angles that could require adjusted experiential capabilities.",
                "rationale": "Ensures Strata is prepared to respond if client briefs evolve toward the type of large-scale sponsorship activations Octagon just executed.",
                "effort": "low", "urgency": "watch",
            },
        ],
        "signals": ["sponsorship", "activation", "sports marketing", "consumer brands"],
        "confidence": 0.8,
        "article_count": 2,
        "story_count": 2,
        "evidence": [
            {"url": "https://www.linkedin.com/company/octagon", "title": "Octagon | LinkedIn", "source": "www.linkedin.com", "excerpt": "Octagon supported Mastercard and Nutrafol in creating fan experiences at MLB All-Star Week. Mastercard, in its 10th year as presenting sponsor, featured a Small Business Contest and Stand Up To Cancer moment. Nutrafol activated around hair confidence and the Long Game mentality.", "published_at": "2026-07-21T00:00:00+00:00"},
            {"url": "https://x.com/Octagon/status/2080763917152711085", "title": "@Octagon", "source": "x.com/Octagon", "excerpt": "Stephen and Ayesha Curry were named The Hollywood Reporter's 2026 Philanthropists of the Year. They discussed their Eat. Learn. Play. Foundation, managing multiple businesses, and making a mark on Hollywood.", "published_at": "2026-07-24T21:15:51+00:00"},
        ],
    },
    "MKTG": {
        "headline": "MKTG deepens sports & entertainment focus, not expanding into our brand experience niche",
        "whats_up": (
            "MKTG positions itself as a sports and entertainment lifestyle agency, showcasing "
            "projects like Toyota Sports Fest and Super Bowl Hospitality. Their content and "
            "careers page emphasize fandom, sports leagues (NBA, F1), and a six-month trainee "
            "program for lifestyle marketing graduates. No evidence indicates a move into "
            "integrated, non-sports brand experiences or the industries we serve."
        ),
        "impact": (
            "The evidence shows MKTG operating in a distinct experiential sub-sector "
            "(sports/entertainment lifestyle) with no overlap into our client verticals "
            "(automotive brand, pharma, tech developer communities) or our integrated "
            "strategy-to-asset management approach. Their sports-centric model poses no direct "
            "threat to Strata Create’s positioning, client base, or differentiators."
        ),
        "impact_level": "low",
        "actions": [],
        "signals": ["sports", "entertainment", "lifestyle-marketing", "trainee-program", "hiring"],
        "confidence": 0.85,
        "article_count": 3,
        "story_count": 3,
        "evidence": [
            {"url": "https://mktg.com", "title": "Home", "source": "mktg.com", "excerpt": "MKTG is a global sports and entertainment marketing agency that helps brands connect with fans. They showcase various projects including the 50/50 Pledge, J Harden x J Shed Wines, Bowlway, Toyota Sports Fest, and Super Bowl Hospitality.", "published_at": "2026-01-01T00:00:00+00:00"},
            {"url": "https://mktg.com/speed-reads", "title": "Speed Reads", "source": "mktg.com", "excerpt": "This page is a compilation of short article summaries covering various sports marketing topics, including leagues like NBA, Formula One, NASCAR, and NWSL, as well as brand insights and industry trends.", "published_at": "2026-01-01T00:00:00+00:00"},
            {"url": "https://mktg.com/careers", "title": "Careers", "source": "mktg.com", "excerpt": "MKTG Sports + Entertainment presents itself as an agency of fans dedicated to sports, music, data, art, and culture. The company emphasizes values such as collaboration, community, and excellence, and offers a six-month trainee program for college graduates seeking entry into lifestyle marketing.", "published_at": "2026-01-01T00:00:00+00:00"},
        ],
    },
    "Momentum Worldwide": {
        "headline": "No competitive moves detected from Momentum Worldwide",
        "whats_up": (
            "Momentum Worldwide published a privacy policy update in December 2025 and a team "
            "leadership profile page in July 2026. These are routine content updates with no "
            "indication of new service offerings, strategic shifts, geographic expansion, or "
            "client wins."
        ),
        "impact": (
            "These updates provide no insight into Momentum’s service evolution, market "
            "targeting, or competitive positioning. There is no discernible change that would "
            "affect Strata Create’s client relationships, pitch opportunities, or "
            "differentiation in the integrated experiential space."
        ),
        "impact_level": "low",
        "actions": [],
        "signals": ["privacy", "leadership"],
        "confidence": 0.2,
        "article_count": 2,
        "story_count": 2,
        "evidence": [
            {"url": "https://www.momentumww.com/privacy-policy/", "title": "Privacy Policy", "source": "www.momentumww.com", "excerpt": "This privacy notice describes how Momentum Worldwide collects, uses, and discloses personal information through its website and for California residents. It covers data collection methods, use of cookies, Google Analytics, and data sharing with affiliates and service providers.", "published_at": "2025-12-11T00:00:00+00:00"},
            {"url": "https://www.momentumww.com/people/", "title": "People", "source": "www.momentumww.com", "excerpt": "The article profiles the top executives of the global experiential marketing agency Momentum Worldwide, detailing their roles, responsibilities, and notable achievements within the company.", "published_at": "2026-07-15T00:00:00+00:00"},
        ],
    },
    "Imagination": {
        "headline": "Imagination maintains automotive focus with Detroit office, no new competitive moves evident",
        "whats_up": (
            "Imagination is an independent global experience design agency with offices in Los "
            "Angeles and Detroit. The Detroit location specifically serves automotive clients, "
            "notably Ford. The website highlights their offerings in consultancy, brand "
            "destinations, content, live events, and investor communications, and upcoming "
            "content covers the Transformation Economy, a Ford experience, and generative AI in "
            "live events. The agency also emphasizes its ISO 27001 information security "
            "certification and a global inclusivity statement."
        ),
        "impact": (
            "The Detroit office directly overlaps with Strata Create's automotive client base "
            "(Peugeot, Volvo). However, the evidence shows only static information about "
            "Imagination’s existing operations and capabilities. There is no indication of a "
            "new product launch, pricing change, client win, or strategic shift that would alter "
            "the competitive dynamics for Strata. This does not create any immediate threat or "
            "require a response from our business."
        ),
        "impact_level": "low",
        "actions": [],
        "signals": ["automotive focus", "detroit office", "iso 27001", "content marketing", "inclusivity"],
        "confidence": 0.9,
        "article_count": 34,
        "story_count": 34,
        "evidence": [
            {"url": "https://imagination.com", "title": "Brand Experience Agency | Independent Creativity | Imagination", "source": "imagination.com", "excerpt": "Imagination is a brand experience agency specializing in consultancy, brand destinations, content, live events, and investor communications. The page lists upcoming insights including a piece on the Transformation Economy, a Ford experience, generative AI in live events, and an AI podcast.", "published_at": "2024-06-18T00:00:00+00:00"},
            {"url": "https://imagination.com/key-policies/", "title": "Our Key Policies | Imagination", "source": "imagination.com", "excerpt": "Imagination's key policies focus on risk management and continuous service improvement. They are externally audited by Tempo Audits and certified to ISO 27001 for information security management, ensuring confidentiality, integrity, and availability of client information.", "published_at": "2024-07-03T00:00:00+00:00"},
            {"url": "https://imagination.com/global-inclusivity-statement/", "title": "Global Inclusivity Statement | Imagination", "source": "imagination.com", "excerpt": "Imagination's Global Inclusivity Statement emphasizes their commitment to diversity, equity, and inclusion, fostering an environment where every individual feels valued and empowered. The statement outlines core behaviors—curiosity, rigor, bravery, and respect—that drive innovation and ensure impact. The commitment extends to partners and suppliers to uphold the same standards.", "published_at": "2024-07-03T00:00:00+00:00"},
            {"url": "https://imagination.com/cookies-policy/", "title": "Cookies Policy | Imagination", "source": "imagination.com", "excerpt": "This page explains how Imagination uses cookies on its website, categorizing them into strictly necessary, performance, functionality, and targeting cookies. It details specific cookies, their purposes, and how users can manage preferences through a Preference Centre or browser settings. It also covers third-party cookies and contact information.", "published_at": "2024-07-03T00:00:00+00:00"},
            {"url": "https://imagination.com/privacy-notice/", "title": "Our Privacy Notice | Imagination", "source": "imagination.com", "excerpt": "This privacy notice outlines how The Imagination Group Limited and Imagination Europe Limited collect, use, and share personal data. It covers data collection methods, legal bases for processing, data retention, international transfers, and user rights under GDPR and UK Data Protection Law.", "published_at": "2024-07-03T00:00:00+00:00"},
            {"url": "https://imagination.com/studios/los-angeles/", "title": "Work With Our US Team | Los Angeles Office | Imagination", "source": "imagination.com", "excerpt": "The Los Angeles office of Imagination is located at 7769 Melrose Avenue. The team values creativity, fun, community involvement, and a quirky culture, including pet Halloween costumes.", "published_at": "2026-02-11T00:00:00+00:00"},
            {"url": "https://jackmorton.com/offices/barcelona/", "title": "Barcelona - Jack Morton | Global Brand Experience Agency", "source": "jackmorton.com", "excerpt": "Jack Morton operates a creative and innovation hub in Barcelona, leveraging the city's design, culture, and tech ecosystem to offer strategic brand experience services. The office connects global capabilities with a high-level local creative network to provide clients with world-class design and production expertise.", "published_at": "2026-07-31T00:00:00+00:00"},
            {"url": "https://imagination.com/studios/detroit/", "title": "Work With Our US Team | Detroit Office | Imagination", "source": "imagination.com", "excerpt": "The article describes Imagination's Detroit office location at 400 South Old Woodward Avenue, Suite 204, Birmingham, MI. It highlights the office's focus on automotive clients, particularly Ford, and mentions amenities like a paint-and-sip art class and shuffleboard.", "published_at": "2026-06-02T00:00:00+00:00"},
        ],
    },
}

ANALYSIS_MODEL = "deepseek-v4-pro"
PROMPT_VERSION = "competitor-analysis-2026-07-27"


def wipe() -> int:
    row = db.fetch_one("select id from projects where name = %s", (STUDY_NAME,))
    if not row:
        print("No study found.")
        return 0
    # Cascades clear business_profiles, competitors, accounts, and findings.
    db.execute("delete from projects where id = %s", (int(row["id"]),))
    print(f"Removed study {row['id']}.")
    return 0


def seed() -> int:
    now = datetime.now(timezone.utc)
    scraped_at = now - timedelta(hours=6)
    generated_at = now - timedelta(hours=2)
    period_start = generated_at - timedelta(days=30)

    existing = db.fetch_one("select id from projects where name = %s", (STUDY_NAME,))
    if existing:
        db.execute("delete from projects where id = %s", (int(existing["id"]),))
        print("Reset the existing study.")

    project = db.fetch_one(
        """
        insert into projects (name, mode, status, keywords, repeat_enabled,
                              repeat_interval_value, repeat_interval_unit, next_run_at)
        values (%s, 'competitor', 'active', %s, true, 1, 'days', %s)
        returning id
        """,
        (STUDY_NAME, Jsonb([]), now + timedelta(days=1)),
    )
    project_id = int(project["id"])
    print(f"Created study {project_id}: {STUDY_NAME}")

    business_profile_store.upsert_profile(project_id, {
        **PROFILE,
        "scrape_status": "success",
        "scraped_at": scraped_at,
    })
    print(f"  business profile: {PROFILE['name']}")

    by_name: dict[str, dict] = {}
    for entry in COMPETITORS:
        accounts = entry.pop("accounts")
        record = competitors_store.upsert_competitor(project_id, {**entry, "status": "tracked"})
        by_name[record["name"]] = record
        entry["accounts"] = accounts  # keep the module-level constant reusable
        for account in accounts:
            stored = competitors_store.upsert_account(record["id"], account)
            if stored:
                competitors_store.set_account_validation(stored["id"], "valid", "Confirmed for demo")
        print(f"  competitor: {record['name']} ({record['size_tier']}, rank {record['size_rank']}), "
              f"{len(accounts)} channel(s)")

    competitors_store.rerank_competitors(project_id)

    for name, template in FINDINGS.items():
        competitor = by_name.get(name)
        if not competitor:
            continue
        db.execute(
            """
            insert into competitor_findings (
                project_id, competitor_id, period_start, period_end, headline, whats_up,
                impact, impact_level, actions, signals, evidence, confidence,
                article_count, story_count, validation_status, analysis_model,
                prompt_version, generated_at
            )
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)
            """,
            (
                project_id, int(competitor["id"]), period_start, generated_at,
                template["headline"], template["whats_up"], template["impact"],
                template["impact_level"], Jsonb(template["actions"]), Jsonb(template["signals"]),
                Jsonb(template["evidence"]), template["confidence"],
                template["article_count"], template["story_count"],
                ANALYSIS_MODEL, PROMPT_VERSION, generated_at,
            ),
        )
        db.execute("update competitors set last_analyzed_at = %s where id = %s",
                   (generated_at, int(competitor["id"])))
        print(f"  finding: {name} [{template['impact_level']}] "
              f"{template['story_count']} source(s), {len(template['actions'])} action(s)")

    print(f"\nDone. Open /competitors/{project_id} in the dashboard.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wipe", action="store_true", help="remove the study and exit")
    args = parser.parse_args()

    if not db.get_database_url():
        print("DATABASE_URL is missing.")
        return 2
    return wipe() if args.wipe else seed()


if __name__ == "__main__":
    raise SystemExit(main())
