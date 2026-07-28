"""Modular article analysis pipeline.

Each stage is its own module with a lazy-loaded, reused model instance:

- article_prep      - normalize/sanitize/chunk text for model input
- sentiment         - overall_sentiment (cardiffnlp/twitter-roberta-base-sentiment-latest)
- classification    - zero-shot article_category, writer_tone, article_tone (mDeBERTa)
- structured_extraction - summary/feedback lists/opinions/ideas (provider-backed LLM via llm_client)
- entity_extraction - optional dedicated NER pass
- aggregation       - cross-article frequent-idea/tone rollup

`orchestrator.analyze_article()` runs them in order and returns the same
article dict shape the old single-LLM enrich_article() used to return, so
store.py/articles_store.py/the dashboard need no changes.
"""
