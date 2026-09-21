# Evidence content-quality validation

## Scope

This validation uses the reviewed local fixture in
`backend/tests/fixtures/evidence_quality_evaluation.json`. It contains eight frozen-text examples:
English and Arabic blocked pages, empty extraction, cookie-only boilerplate, a legitimate article
with an incidental cookie notice, substantive English and Arabic articles, and historical evidence.
Five examples are labelled unusable and three usable.

No production server or SSH access was used. The fixture is intentionally small and tests the
deterministic content-quality gate, not end-to-end semantic relevance accuracy.

## Measured result

| Gate | Sample | Exclusion precision | Exclusion recall |
| --- | ---: | ---: | ---: |
| Previous evidence path (no content-quality exclusion) | 8 | N/A (no exclusions) | 0% |
| New deterministic content-quality gate | 8 | 100% | 100% |

The new result means all five labelled unusable examples were excluded and all three usable examples
were retained. It does not establish production precision or recall; the sample was authored to cover
known regression classes and is not a representative random sample.

On the same eight examples in the backend container, one cold rules pass took 0.000566 seconds. The
mean warm pass over 1,000 repetitions took 0.000326 seconds. These timings cover only deterministic
content checks. Passage embeddings, database reads/writes, claim grouping, optional LLM assessment,
and UI requests are excluded.

## Other verified behavior

- Sixty-nine focused evidence, relevance-screening, and pipeline tests pass.
- Tests cover English and Arabic unavailable content, legitimate cookie notices, generic geography,
  grounded and vague candidates, date/quantity passage mismatches, exact duplicates, threshold cache
  invalidation, provider failure, and interrupted publication.
- A fresh PostgreSQL 16 database applied the baseline and all 20 migrations, then passed migration
  verification with no pending migration.
- A database-backed evidence generation created and published one grounded claim, and the workspace
  read path returned it successfully. This verifies SQL shape and atomic publication; it is not a
  relevance-quality benchmark.
- The dashboard production build succeeds. The changed frontend files pass ESLint. Repository-wide
  ESLint still fails on 34 pre-existing errors outside the changed files.
- The dashboard test suite passes 89 of 94 tests; five existing `App.test.jsx` cases fail because the
  test environment exposes `window.localStorage` as undefined. The evidence workspace changes do not
  touch that initialization path.
- The focused backend suite is green. A broader discovery run reaches unrelated existing failures in
  classification/language test doubles and then attempts to download the embedding model; it was
  stopped rather than treating that environment work as evidence-feature validation.

## Not yet measured

Full passage-relevance precision and recall require a larger, human-reviewed corpus containing both
accepted and rejected real project articles. Cold and warm end-to-end timing also require the same
frozen corpus, embedding model cache state, and provider state for both runs. Those numbers must be
collected during rollout; they must not be inferred from the earlier 34-second reused-analysis run or
from this deterministic fixture.

Recommended rollout is observe and review first: rebuild a non-published generation, label a balanced
sample across score bands and languages, calculate precision and recall including false exclusions,
then publish only after the result meets the team's agreed target. Existing published evidence remains
available if processing fails.
