"""Automatic inclusion must never decide another document's pending review."""

from contextlib import ExitStack
from unittest.mock import patch

import pytest

from services.projects import project_document_articles, project_documents_store
from services.competitors import competitor_document_articles, competitor_documents_store

DOMAINS = [
    (project_documents_store, project_document_articles, "document_extraction"),
    (competitor_documents_store, competitor_document_articles, "competitor_document_extraction"),
]


@pytest.mark.parametrize("store,articles,extraction_name", DOMAINS)
@pytest.mark.parametrize("filename", ["report.txt", "records.jsonl"])
def test_processing_b_leaves_a_pending_and_does_not_start_analysis(
    store, articles, extraction_name, filename, tmp_path
):
    path = tmp_path / filename
    path.write_text('{"title":"B","text":"Body B"}\n')
    document = {"id": 20, "project_id": 9, "original_filename": filename, "storage_path": filename}
    candidates = [
        {"id": 1, "project_id": 9, "document_id": 10, "status": "pending", "article_id": None},
        {"id": 2, "project_id": 9, "document_id": 20, "status": "pending", "article_id": None},
        {"id": 3, "project_id": 9, "document_id": 20, "status": "rejected", "article_id": None},
        {"id": 4, "project_id": 9, "document_id": 20, "status": "approved", "article_id": 104},
        {"id": 5, "project_id": 99, "document_id": 20, "status": "pending", "article_id": None},
    ]

    def select_candidates(sql, params):
        selected = [c for c in candidates if c["project_id"] == params[0]]
        if len(params) > 1:
            selected = [c for c in selected if c["document_id"] in params[1]]
        return selected

    def decide(candidate_id, status):
        candidate = next(c for c in candidates if c["id"] == candidate_id)
        candidate.update(status=status, article_id=100 + candidate_id)
        return dict(candidate)

    with ExitStack() as stack:
        stack.enter_context(patch.object(store, "get_document", return_value=document))
        stack.enter_context(patch.object(store, "STORAGE_DIR", tmp_path))
        execute = stack.enter_context(patch.object(store.db, "execute"))
        stack.enter_context(patch.object(articles.db, "fetch_all", side_effect=select_candidates))
        decide_mock = stack.enter_context(patch.object(articles, "set_status", side_effect=decide))
        stack.enter_context(patch.object(articles, "generate_candidates"))
        stack.enter_context(patch.object(articles, "generate_candidates_from_records"))
        extraction = getattr(store, extraction_name)
        stack.enter_context(patch.object(extraction, "total_chunks", return_value=1))
        stack.enter_context(patch.object(extraction, "iter_chunks", return_value=[
            {"index": 0, "text": "Body B", "method": "text", "error": None},
        ]))
        sync = None
        if store is project_documents_store:
            sync = stack.enter_context(patch.object(store, "sync_competitor_evidence_after_approval"))
        start_run = stack.enter_context(patch("services.pipeline.pipeline.start_or_reuse_analysis_run"))
        reanalyze = stack.enter_context(patch("services.articles.reanalyze.reanalyze_article"))

        store.process_document(20)
        store.process_document(20)  # A retry must not materialize another article.

    assert candidates[0]["status"] == "pending"
    assert candidates[0]["article_id"] is None
    assert candidates[1]["status"] == "approved"
    assert candidates[1]["article_id"] == 102
    assert candidates[2]["status"] == "rejected"
    assert candidates[3]["article_id"] == 104
    assert candidates[4]["status"] == "pending"
    decide_mock.assert_called_once_with(2, "approved")
    if sync:
        sync.assert_called_once_with(9)
    assert any("articles_status = 'ready'" in call.args[0] for call in execute.call_args_list)
    start_run.assert_not_called()
    reanalyze.assert_not_called()


@pytest.mark.parametrize("store,articles,extraction_name", DOMAINS)
def test_scoped_query_preserves_project_boundary_and_deduplicates_documents(store, articles, extraction_name):
    with patch.object(articles.db, "fetch_all", return_value=[]) as fetch:
        assert articles.approve_for_documents(9, [20, 20]) == []
    sql, params = fetch.call_args.args
    assert "project_id = %s" in sql
    assert "document_id = any(%s)" in sql
    assert params == (9, [20])


@pytest.mark.parametrize("store,articles,extraction_name", DOMAINS)
def test_empty_scope_does_not_load_candidates(store, articles, extraction_name):
    with patch.object(articles, "list_candidates") as candidates:
        assert articles.approve_for_documents(9, []) == []
    candidates.assert_not_called()


@pytest.mark.parametrize("store,articles,extraction_name", DOMAINS)
@pytest.mark.parametrize("filename", ["report.txt", "records.jsonl"])
def test_approval_failure_keeps_successful_extraction_recoverable(
    store, articles, extraction_name, filename, tmp_path, caplog
):
    path = tmp_path / filename
    path.write_text('{"title":"B","text":"Body B"}\n')
    document = {"id": 20, "project_id": 9, "original_filename": filename, "storage_path": filename}
    extraction = getattr(store, extraction_name)
    with patch.object(store, "get_document", return_value=document), \
         patch.object(store, "STORAGE_DIR", tmp_path), \
         patch.object(store.db, "execute") as execute, \
         patch.object(articles, "generate_candidates"), \
         patch.object(articles, "generate_candidates_from_records"), \
         patch.object(extraction, "total_chunks", return_value=1), \
         patch.object(extraction, "iter_chunks", return_value=[
             {"index": 0, "text": "Body B", "method": "text", "error": None},
         ]), \
         patch.object(articles, "approve_for_documents", side_effect=RuntimeError("approval failed")):
        store.process_document(20)

    updates = [call.args[0] for call in execute.call_args_list]
    assert any("articles_status = 'ready'" in sql for sql in updates)
    assert not any("articles_status = 'failed'" in sql or "status = 'failed'" in sql for sql in updates)
    assert "auto-approving extracted candidates failed for document 20" in caplog.text
