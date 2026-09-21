# Evidence relevance screening: deployed work and quality improvement plan

## Purpose and status

This document records work already deployed from `feature/article-relevance-screening` and proposes the next evidence-quality improvement. This PR contains documentation only. It does not deploy the feature again or implement the proposed quality filters.

The feature commits were pushed directly to main before a PR was opened. They are already ancestors of main. Review the original implementation here:

https://github.com/CreativeTechy/strata-analysis/compare/449b230...3c382f0

Deployed commits:

- `4138463`: project relevance screening, persistence, manual overrides, run reporting, and batch article embeddings.
- `73d134c`: threshold calibration, threshold-aware decision cache, and schema upgrade correction.
- `127793c`: compact relevance classification batches.
- `3c382f0`: configurable embedding-based evidence relevance and batch claim embeddings.

The screening currently participates in the shared analysis pipeline and limits the evidence snapshot. It is not confined to an evidence-only entry point. Any future change to dashboard analysis selection must be identified explicitly rather than presented as an evidence-only change.

## Recorded production verification

These observations came from the preceding deployment session on September 21, 2026, not a fresh server audit for this document:

- Project: Lebanon Fuel Crisis Monitor, ID 3.
- Run: `d33d92bf7ef54cf0aa03d3575de77c78`, evidence generation 2.
- 1,076 imported articles screened; 218 retained; 858 excluded (approximately 80%).
- Production article accept/exclude thresholds both set to 0.82, bypassing borderline LLM classification while RunPod was timing out. These are semantic similarity thresholds, not calibrated confidence percentages.
- Evidence generation completed in 33.67 seconds using saved material: 387 candidates, 227 labelled direct, 158 contextual, and 2 unrelated.
- Workspace service returned 385 visible claims. HTTP health returned 200. Browser verification was blocked by a browser-tool error.
- This timing covers the evidence rebuild only. It excludes original analysis, the initial article embedding work, and the failed RunPod attempts. It is not a measured end-to-end speedup.
- Nine retained articles still needed successful analysis; RunPod timed out during the first attempt. The analysis run remained failed while evidence generation succeeded using available saved analysis.
- The focused suite passed 60 tests before deployment. That verifies tested behavior, not the relevance or factual quality of every production claim.

## Findings

The application analyzes uploaded/imported text; it does not fetch replacement web articles. Better relevance screening cannot recover missing source text.

The saved production claim samples reveal quality problems even at high similarity scores:

- A fuel-price item described login and verification failures instead of actual fuel prices, despite a 0.863 score.
- Another fuel-price item described incomplete content/account verification errors and scored 0.861.
- A fuel-station item described mostly cookie-policy content and scored 0.841.
- Vague statements such as coverage of energy consumption or implementation through customs were also labelled direct.

These are symptoms requiring inspection of the frozen article bodies. They are not proof that every underlying article is unusable. The previous statement that all 385 were relevant claims was too strong: 385 were classified as visible, and their usefulness was not established.

Code explains why these cases can pass:

- Article similarity accepts a high-scoring document without an independent content-quality check.
- `_claim_candidates` uses stored key points, then falls back to a summary or title. That can promote an explanation of missing content into a claim.
- Embedding relevance detects topic proximity; it does not establish that an assertion is specific, supported, or true.
- Passage qualification influences assessment but does not prevent an unusable candidate from appearing in the default claim list.
- Embedding-mode claim relevance currently stores the configured chat model as `relevance_model`; the provenance should identify the embedding model and thresholds instead.

## Proposed implementation

### 1. Establish a reviewed baseline

With fresh approval for SSH, inspect frozen title/body, saved analysis, score, and proposed claims for accepted and rejected articles. Review examples across score bands, both Arabic and English, different dates, different publishers, and the full range of content quality. Include low-scoring but clearly relevant examples to detect false exclusions.

Build a labelled evaluation set: useful/direct, useful/contextual, unrelated, unusable content, and duplicate. Record human decisions and reasons. Reserve a held-out set for validation. Define the desired historical/current time window in the project scope; do not exclude old evidence automatically.

### 2. Reject unusable source content before expensive evidence work

Add a versioned content-quality result distinct from relevance. Detect login/access-denied pages, predominantly cookie/navigation text, extraction failures, and insufficient meaningful body text. Use combined signals and retained body text rather than one keyword or title match; preserve substantive articles that merely include a cookie notice.

Quarantine unusable items with a readable reason. Retain their originals and allow review/override. Group duplicates for processing reuse while preserving every citation and origin; syndicated copies must not count as independent corroboration.

### 3. Screen relevant passages against explicit project scope

Use project title, description, geography, topic inclusions/exclusions, and optional time window. Score body passages in batches instead of relying solely on one whole-document score. Require a substantive passage connecting the subject to the project. Shared geography or generic energy terminology alone is insufficient.

Keep direct relevance and contextual relevance separate. Calibrate thresholds against the reviewed set and model; do not raise a global threshold just to reduce the count. Reuse vectors only when content, model, input format, and preprocessing versions match.

Send ambiguous items to review or a bounded classifier when available. If the classifier is unavailable, preserve completed evidence and expose pending review; do not silently label ambiguity as confirmed relevance or erase it as unrelated.

### 4. Admit useful claims with traceable support

For the evidence path, require a specific assertion or clearly labelled opinion/forecast and a supporting passage from the frozen article. Reject meta-statements about login failures, inaccessible content, or what an article supposedly discusses when no supporting body is present.

Reuse suitable saved key points only after these checks. Remove unconditional summary/title promotion into visible factual claims. Keep unsupported candidates in a review view with reasons, separate from the default evidence list. Exact quoting alone is insufficient: check attribution, negation, time, and quantities, and route uncertain entailment to review.

Default to useful direct claims, with contextual evidence available as an explicit filter. Keep relevance, passage support, source independence, and factual assessment as separate concepts.

### 5. Keep runs safe and explainable

Apply the next quality improvement within evidence generation. Preserve existing analysis results and dashboard run semantics. Show per-generation counts for screened articles, quality exclusions, topic exclusions, duplicate reuse, pending review, and published claims.

Persist content/scope hashes, actual model, decision method, threshold values, and rule versions with decisions. Invalidate caches when any decision input changes. Publish a completed replacement atomically; failed/retried work must keep the previously published generation available. Do not delete imported articles or historical runs as part of filtering.

### 6. Validate and release gradually

Add regression tests for English and Arabic relevant articles, unrelated items sharing geography, relevant titles with blocked bodies, legitimate articles with cookie notices, duplicates, historic evidence, vague summary fallbacks, numeric/date/negation mismatches, cache invalidation, unavailable models, cancellation, and interrupted publishing.

Run on frozen copies first. Compare old/new article decisions and visible claims against the reviewed baseline. Measure precision and recall, including excluded relevant articles, rather than optimizing only for a smaller claim count.

Suggested acceptance targets, to be confirmed before tuning: at least 95% precision and 90% recall on the held-out useful/direct set; all known blocked-page regressions kept out of the default view; every visible factual claim traceable to a substantive frozen passage. Report sample size and uncertainty with these metrics.

Report cold and warm durations separately for screening, embeddings, extraction, assessment, and publication. Compare the same corpus under the same provider conditions; do not compare a reused-analysis rebuild with a full fresh analysis.

Enable initially for this project's evidence runs, review the resulting sources and claims, then expand after acceptance. Rollback disables the new filters for future generations or restores the prior published generation without altering source data.
