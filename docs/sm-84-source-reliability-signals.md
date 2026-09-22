# SM-84: Source reliability signals — implementation record

## Status and scope

This is retrospective documentation for [SM-84](https://creativetechy.atlassian.net/browse/SM-84).
The implementation is already on `main` and was deployed to Hostinger on September 22, 2026,
at commit `fd2e90d`. This documentation PR does not introduce or redeploy the feature.

Scope: the GDELT coverage integration and the dashboard's **Source reliability signals** KPI.
The broader Evidence workspace relevance and grounding changes shipped alongside it are not
the subject of this document. Provider names are technical implementation details, not KPI labels.

## What shipped

- Replaced the source-verification pie chart with a horizontal stacked bar, a readable legend,
  article counts, percentages, accessible descriptions, and links to filtered articles.
- Standardized the user-facing title to **Source reliability signals** without provider branding.
- Removed the Iffy importer and publisher-list scoring from the active application path.
  Historical schema and migration definitions remain; this was not a destructive data purge.
- Added an explicit coverage-check action to article details. When `main` introduced the dedicated
  article detail page, the action and results were moved there rather than restoring the old modal.
- Preserved optional original publisher URLs in uploaded-document provenance while keeping internal
  document URLs for grouping.
- Added permission/project-visibility checks and protection against a delayed result appearing on
  a different article after navigation.

## How the signal works

1. A permitted user requests `POST /api/articles/{article_id}/coverage`.
2. The backend checks access and builds a search query from the article title.
3. The external news index returns candidate headlines. The backend filters candidate URLs and
   headline matches, excludes the original publisher domain when known, and consolidates results
   by publisher domain using bundled public-suffix data.
4. The result, matching links, explanation, and check timestamp are saved in
   `articles.coverage_evidence` and included in dashboard aggregates.

Checks are not automatic during document import or analysis. An explicit check sends the article
title to the configured external service. Domain normalization itself makes no network request.

## Meaning of the results

| Current automatic result | Meaning |
| --- | --- |
| Needs review | Related headlines were found; their claims and independence still need review. |
| Not assessed | There is insufficient matching coverage, or no check has been performed. |

Coverage is not fact-checking, publisher certification, or proof of independent corroboration.
Headline overlap must not automatically produce a high or low reliability rating. Legacy status
keys remain for compatibility; the current checker emits `some_coverage` or `not_checked`.
The accuracy migration withdraws confidence previously inferred only from headline matches.

The KPI drill-down carries project and coverage-status filters. It does not currently carry the
dashboard's selected run/date scope, so its article-list total can differ from a scoped KPI count.

## Implementation history

- [Initial source reliability and KPI work](https://github.com/CreativeTechy/strata-analysis/commit/b4ea744) — included the earlier list-based approach, subsequently replaced.
- [Coverage integration](https://github.com/CreativeTechy/strata-analysis/commit/d0c284e).
- [Switch the active dashboard to coverage signals](https://github.com/CreativeTechy/strata-analysis/commit/109d331).
- [Remove provider details from the interface](https://github.com/CreativeTechy/strata-analysis/commit/1004051).
- [Standardize the KPI title](https://github.com/CreativeTechy/strata-analysis/commit/1ea0b00) and [simplify labels](https://github.com/CreativeTechy/strata-analysis/commit/26589b2).
- [Accuracy and access safeguards](https://github.com/CreativeTechy/strata-analysis/commit/4662853) — also contains separate Evidence workspace work.
- [Merge, migration-number reconciliation, and article-detail integration](https://github.com/CreativeTechy/strata-analysis/commit/fd2e90d).

Current implementation: `backend/services/articles/gdelt_corroboration.py`,
`backend/services/articles/publisher_identity.py`, `backend/main.py`,
`dashboard/src/components/DashboardOverview.jsx`, and `dashboard/src/components/ArticleDetailPage.jsx`.
Related forward migrations are `0022_source_reliability`, `0023_gdelt_coverage`, and
`0024_evidence_accuracy_revalidation`.

## Recorded validation

At deployment, the combined application passed 684 backend tests and 103 frontend tests,
and the frontend production build succeeded. These are whole-application suite counts, not
684 or 103 tests exclusively for this feature. The deployed backend suite also passed using
isolated test configuration. Public dashboard/API health, database connectivity, and unauthenticated
access rejection were checked; migrations had no pending entries.

The server then had 1,901 articles in the Not assessed category. This did not mean their publishers
were unreliable, nor did it establish that a live external lookup had succeeded for every article.
This documentation-only PR performs no new production checks or deployment.
