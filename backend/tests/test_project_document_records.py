import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.documents import records
from services.projects import project_document_articles, project_documents_store


def _write(name: str, text: str) -> Path:
    directory = Path(tempfile.mkdtemp())
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


class ParseRecordsTests(unittest.TestCase):
    """A .json/.jsonl document is read by content, not by extension - the two
    formats operators actually have (an export from this app, and a list some
    other tool produced) both have to land as candidates."""

    def test_jsonl_export_becomes_one_record_per_line(self):
        text = "\n".join(
            json.dumps({"title": f"Article {i}", "text": f"Body {i}", "url": f"https://x/{i}"})
            for i in range(3)
        )
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        self.assertEqual(len(parsed.records), 3)
        self.assertEqual(parsed.records[0]["title"], "Article 0")
        self.assertEqual(parsed.records[0]["body"], "Body 0")
        self.assertEqual(parsed.records[0]["metadata"]["url"], "https://x/0")
        self.assertIsNone(parsed.error_summary)

    def test_blank_lines_are_not_records(self):
        text = '{"title": "A", "text": "one"}\n\n\n{"title": "B", "text": "two"}\n'
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        self.assertEqual([record["title"] for record in parsed.records], ["A", "B"])
        self.assertEqual(parsed.skipped, 0)

    def test_json_array_is_accepted(self):
        text = json.dumps([{"title": "A", "text": "one"}, {"title": "B", "text": "two"}])
        parsed = records.parse_records(_write("articles.json", text), "articles.json")
        self.assertEqual(len(parsed.records), 2)

    def test_json_array_saved_with_a_jsonl_extension_still_parses(self):
        """The articles-page import rejects this outright; here the wizard has
        no second chance to offer, so content wins over extension."""
        text = json.dumps([{"title": "A", "text": "one"}])
        parsed = records.parse_records(_write("articles.jsonl", text), "articles.jsonl")
        self.assertEqual(len(parsed.records), 1)

    def test_jsonl_saved_with_a_json_extension_still_parses(self):
        text = '{"title": "A", "text": "one"}\n{"title": "B", "text": "two"}\n'
        parsed = records.parse_records(_write("articles.json", text), "articles.json")
        self.assertEqual([record["title"] for record in parsed.records], ["A", "B"])

    def test_envelope_object_list_is_unwrapped(self):
        text = json.dumps({"articles": [{"title": "A", "text": "one"}], "exported_at": "today"})
        parsed = records.parse_records(_write("articles.json", text), "articles.json")
        self.assertEqual(len(parsed.records), 1)
        self.assertEqual(parsed.records[0]["title"], "A")

    def test_single_object_is_one_record(self):
        text = json.dumps({"title": "A", "text": "one"})
        parsed = records.parse_records(_write("article.json", text), "article.json")
        self.assertEqual(len(parsed.records), 1)

    def test_alternate_field_names_are_matched(self):
        text = json.dumps([{"headline": "H", "content": "C", "description": "D", "link": "https://x/1", "byline": "Sam"}])
        parsed = records.parse_records(_write("a.json", text), "a.json")
        record = parsed.records[0]
        self.assertEqual(record["title"], "H")
        self.assertEqual(record["body"], "C")
        self.assertEqual(record["summary"], "D")
        self.assertEqual(record["metadata"]["url"], "https://x/1")
        self.assertEqual(record["metadata"]["author"], "Sam")

    def test_title_is_derived_when_a_record_has_only_text(self):
        parsed = records.parse_records(
            _write("a.jsonl", json.dumps({"text": "The seats are far too firm."})), "a.jsonl"
        )
        self.assertEqual(parsed.records[0]["title"], "The seats are far too firm.")

    def test_record_with_no_text_at_all_is_reported_not_dropped_silently(self):
        text = '{"title": "A", "text": "one"}\n{"rating": 5}\n'
        parsed = records.parse_records(_write("a.jsonl", text), "a.jsonl")
        self.assertEqual(len(parsed.records), 1)
        self.assertEqual(parsed.skipped, 1)
        self.assertIn("Line 2", parsed.error_summary)

    def test_unparseable_line_does_not_abort_the_file(self):
        text = '{"title": "A", "text": "one"}\nnot json\n{"title": "B", "text": "two"}\n'
        parsed = records.parse_records(_write("a.jsonl", text), "a.jsonl")
        self.assertEqual([record["title"] for record in parsed.records], ["A", "B"])
        self.assertIn("Line 2", parsed.error_summary)

    def test_error_summary_counts_the_ones_it_does_not_list(self):
        text = "\n".join("not json" for _ in range(records.MAX_ERRORS_REPORTED + 4))
        parsed = records.parse_records(_write("a.jsonl", text), "a.jsonl")
        self.assertEqual(parsed.records, [])
        self.assertIn("4 more unusable record(s)", parsed.error_summary)

    def test_invalid_json_file_reports_the_file_rather_than_every_line(self):
        parsed = records.parse_records(_write("a.json", "{not json"), "a.json")
        self.assertEqual(parsed.records, [])
        self.assertIn("File is not valid JSON", parsed.error_summary)

    def test_records_past_the_cap_are_counted_and_flagged(self):
        text = "\n".join(
            json.dumps({"title": f"A{i}", "text": "x"}) for i in range(records.MAX_RECORDS + 7)
        )
        parsed = records.parse_records(_write("big.jsonl", text), "big.jsonl")
        self.assertEqual(len(parsed.records), records.MAX_RECORDS)
        self.assertTrue(parsed.truncated)
        self.assertEqual(parsed.total_seen, records.MAX_RECORDS + 7)

    def test_a_genuine_jsonl_file_is_iterated_lazily_not_parsed_all_at_once(self):
        """_iter_raw's line-delimited path must stay a true generator for the
        common .jsonl/.ndjson case - a multi-thousand-record export must not
        have every record parsed into a list before MAX_RECORDS gets to
        discard most of them (see the module's own note on this). Proven by
        counting json.loads calls against how many items the caller actually
        pulled, rather than the file's full line count."""
        text = "\n".join(json.dumps({"title": f"A{i}", "text": "x"}) for i in range(10))
        calls = []
        original_loads = json.loads

        def counting_loads(raw):
            calls.append(raw)
            return original_loads(raw)

        with patch("services.documents.records.json.loads", side_effect=counting_loads):
            generator = records._iter_raw(text, ".jsonl")
            for _ in range(3):
                next(generator)

        self.assertEqual(len(calls), 3)

    def test_source_run_snapshot_is_carried_through_as_metadata(self):
        snapshot = {"id": "run-1", "started_at": "2026-08-20T00:00:00+00:00", "project_id": 4}
        text = json.dumps({"title": "A", "text": "one", "source_run_snapshot": snapshot})
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        self.assertEqual(parsed.records[0]["metadata"]["source_run_snapshot"], snapshot)

    def test_external_collection_provenance_is_preserved(self):
        text = json.dumps({
            "title": "Oil update", "text": "Production increased.",
            "url": "https://example.test/oil", "publisher": "Example News",
            "collected_at": "2026-09-18T10:00:00Z", "source_type": "news_report",
            "original_record_id": "news-17", "content_hash": "sha256:abc123",
            "speaker": "Energy minister",
        })
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        provenance = parsed.records[0]["metadata"]["source_provenance"]
        self.assertEqual(provenance["publisher"], "Example News")
        self.assertEqual(provenance["original_record_id"], "news-17")
        self.assertEqual(provenance["original_content_hash"], "sha256:abc123")
        self.assertEqual(provenance["verification_status"], "unassessed")

    def test_collection_platform_is_preserved_separately_from_source_type(self):
        text = json.dumps({
            "title": "Post", "text": "A social post.",
            "platform": "threads", "source_type": "social_post",
            "source_url": "https://www.threads.com/@example",
        })
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        provenance = parsed.records[0]["metadata"]["source_provenance"]
        self.assertEqual(provenance["collection_platform"], "threads")
        self.assertEqual(provenance["source_type"], "social_post")
        self.assertEqual(provenance["collection_source_url"], "https://www.threads.com/@example")

    def test_nested_collection_platform_survives_reimport(self):
        text = json.dumps({
            "title": "Post", "text": "A social post.",
            "source_provenance": {"collection_platform": "instagram"},
        })
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        provenance = parsed.records[0]["metadata"]["source_provenance"]
        self.assertEqual(provenance["collection_platform"], "instagram")

    def test_nested_collection_source_url_survives_reimport(self):
        text = json.dumps({
            "title": "Post", "text": "A social post.",
            "url": "https://publisher.example/article",
            "source_url": "document://project-document/2",
            "source_provenance": {
                "collection_source_url": "https://www.instagram.com/example/",
            },
        })
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        provenance = parsed.records[0]["metadata"]["source_provenance"]
        self.assertEqual(
            provenance["collection_source_url"],
            "https://www.instagram.com/example/",
        )

    def test_document_source_url_is_not_treated_as_collection_provenance(self):
        text = json.dumps({
            "title": "Post", "text": "A social post.",
            "source_url": "document://project-document/2",
        })
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        provenance = parsed.records[0]["metadata"]["source_provenance"]
        self.assertNotIn("collection_source_url", provenance)

    def test_source_run_snapshot_missing_id_is_dropped(self):
        """Not scraper-app's shape - e.g. a hand-made file that happens to use
        the same key for something else - so it must not ride through."""
        text = json.dumps({"title": "A", "text": "one", "source_run_snapshot": {"note": "not a run"}})
        parsed = records.parse_records(_write("a.jsonl", text), "a.jsonl")
        self.assertNotIn("source_run_snapshot", parsed.records[0]["metadata"])

    def test_extension_matching(self):
        self.assertTrue(records.is_record_file("a.JSONL"))
        self.assertTrue(records.is_record_file("a.ndjson"))
        self.assertFalse(records.is_record_file("a.pdf"))


class ProcessRecordDocumentTests(unittest.TestCase):
    """The records branch has to leave the document row in the same states the
    extraction branch does - the wizard polls those columns and knows nothing
    about which kind of file it uploaded."""

    def _run(self, filename, text):
        path = _write(filename, text)
        document = {"id": 5, "project_id": 9, "storage_path": path.name, "original_filename": filename}
        with patch.object(project_documents_store, "db") as mock_db, \
             patch.object(project_documents_store.project_document_articles,
                          "generate_candidates_from_records") as mock_generate, \
             patch.object(project_documents_store, "_try_approve_all_and_queue_analysis") as mock_approve:
            project_documents_store._process_record_document(document, path, filename)
        updates = " ".join(str(call.args) for call in mock_db.execute.call_args_list)
        return updates, mock_db, mock_generate, mock_approve

    def test_usable_file_ends_processed_and_ready_with_candidates_written(self):
        text = '{"title": "A", "text": "one"}\n{"title": "B", "text": "two"}\n'
        updates, mock_db, mock_generate, mock_approve = self._run("export.jsonl", text)
        self.assertIn("'processed'", updates)
        self.assertIn("articles_status = 'ready'", updates)
        document_id, project_id, parsed_records = mock_generate.call_args.args
        self.assertEqual((document_id, project_id), (5, 9))
        self.assertEqual([record["title"] for record in parsed_records], ["A", "B"])
        mock_approve.assert_called_once_with(9)

    def test_extracted_text_is_article_text_not_raw_json(self):
        _, mock_db, _, _ = self._run("export.jsonl", '{"title": "A", "text": "one"}\n')
        stored = [call.args[1] for call in mock_db.execute.call_args_list if call.args[1:]]
        self.assertIn("A\none", [param for params in stored for param in params if isinstance(param, str)])

    def test_file_with_no_usable_records_fails_and_skips_generation(self):
        updates, _, mock_generate, mock_approve = self._run("export.jsonl", "not json\n")
        self.assertIn("'failed'", updates)
        self.assertIn("articles_status = 'skipped'", updates)
        mock_generate.assert_not_called()
        mock_approve.assert_not_called()

    def test_truncated_file_says_so_on_a_successful_document(self):
        text = "\n".join(json.dumps({"title": f"A{i}", "text": "x"}) for i in range(records.MAX_RECORDS + 2))
        _, mock_db, _, mock_approve = self._run("big.jsonl", text)
        notes = [
            call.args[1][0]
            for call in mock_db.execute.call_args_list
            if "articles_status = 'ready'" in call.args[0] and call.args[1:]
        ]
        self.assertTrue(notes and notes[0] and f"of {records.MAX_RECORDS + 2:,} records" in notes[0])
        mock_approve.assert_called_once_with(9)


class ProcessDocumentFailureTests(unittest.TestCase):
    """The upload step polls `status` with no timeout, so any escape from
    process_document that leaves a document on 'processing' is a permanent
    spinner - for either kind of file."""

    def _crash(self, filename, branch):
        path = _write(filename, "whatever")
        document = {"id": 5, "project_id": 9, "storage_path": path.name, "original_filename": filename}
        with patch.object(project_documents_store, "db") as mock_db, \
             patch.object(project_documents_store, "get_document", return_value=document), \
             patch.object(project_documents_store, "STORAGE_DIR", path.parent), \
             patch.object(project_documents_store, branch, side_effect=RuntimeError("boom")):
            project_documents_store.process_document(5)
        return [call.args for call in mock_db.execute.call_args_list if "status = 'failed'" in call.args[0]]

    def test_records_branch_crash_ends_the_document_failed(self):
        failures = self._crash("export.jsonl", "_process_record_document")
        self.assertTrue(failures)
        self.assertIn("boom", failures[0][1][0])

    def test_extraction_branch_crash_ends_the_document_failed(self):
        failures = self._crash("scan.pdf", "_extract_document")
        self.assertTrue(failures)
        self.assertIn("boom", failures[0][1][0])

    def test_the_right_branch_is_chosen_per_format(self):
        for filename, expected, other in (
            ("export.jsonl", "_process_record_document", "_extract_document"),
            ("scan.pdf", "_extract_document", "_process_record_document"),
        ):
            path = _write(filename, "whatever")
            document = {"id": 5, "project_id": 9, "storage_path": path.name, "original_filename": filename}
            with patch.object(project_documents_store, "db"), \
                 patch.object(project_documents_store, "get_document", return_value=document), \
                 patch.object(project_documents_store, "STORAGE_DIR", path.parent), \
                 patch.object(project_documents_store, expected) as mock_expected, \
                 patch.object(project_documents_store, other) as mock_other:
                project_documents_store.process_document(5)
            self.assertTrue(mock_expected.called, filename)
            self.assertFalse(mock_other.called, filename)


class MaterializeRecordCandidateTests(unittest.TestCase):
    """A record carries its own link and date; both have to survive into the
    article, since url is the upsert key and published_at is what every trend
    read in the product groups by."""

    CANDIDATE = {
        "id": 3,
        "document_id": 5,
        "project_id": 9,
        "title": "A",
        "summary": "s",
        "body": "one",
    }

    def _materialize(self, candidate, document=None):
        with patch.object(project_document_articles, "save_articles") as mock_save:
            mock_cur = MagicMock()
            mock_cur.fetchone.side_effect = [
                document or {"original_filename": "export.jsonl", "publisher_url": None},
                {"id": 42},
            ]
            article_id = project_document_articles._materialize(candidate, mock_cur)
        return article_id, mock_save.call_args.args[0][0]

    def test_record_url_author_and_date_are_carried_onto_the_article(self):
        candidate = {
            **self.CANDIDATE,
            "record_metadata": {"url": "https://x/1", "author": "Sam", "published": "2026-01-02"},
        }
        article_id, article = self._materialize(candidate)
        self.assertEqual(article_id, 42)
        self.assertEqual(article["url"], "https://x/1")
        self.assertEqual(article["author"], "Sam")
        self.assertEqual(article["published"], "2026-01-02")

    def test_document_provenance_still_wins_over_the_records_own_source(self):
        """source/source_url stay the document's, which is what the Articles
        page's document filter groups on - only `url` comes from the record."""
        candidate = {**self.CANDIDATE, "record_metadata": {"url": "https://x/1", "source": "Some Site"}}
        _, article = self._materialize(candidate)
        self.assertEqual(article["source"], "export.jsonl")
        self.assertEqual(article["source_url"], "document://project-document/5")

    def test_candidate_without_record_metadata_keeps_the_synthetic_url(self):
        _, article = self._materialize(dict(self.CANDIDATE))
        self.assertEqual(article["url"], "document://project-document/5/article/3")
        self.assertIsNone(article["author"])
        self.assertIsNone(article["published"])
        self.assertIsNone(article["source_run_snapshot"])

    def test_source_run_snapshot_is_carried_onto_the_article(self):
        snapshot = {"id": "run-1", "started_at": "2026-08-20T00:00:00+00:00", "project_id": 4}
        candidate = {**self.CANDIDATE, "record_metadata": {"url": "https://x/1", "source_run_snapshot": snapshot}}
        _, article = self._materialize(candidate)
        self.assertEqual(article["source_run_snapshot"], snapshot)

    def test_document_publisher_url_becomes_original_source_provenance(self):
        _, article = self._materialize(
            dict(self.CANDIDATE),
            {"original_filename": "report.pdf", "publisher_url": "https://publisher.example/report"},
        )
        self.assertEqual(
            article["source_provenance"],
            {"original_url": "https://publisher.example/report"},
        )

    def test_record_original_url_takes_precedence_over_document_publisher(self):
        candidate = {
            **self.CANDIDATE,
            "record_metadata": {"source_provenance": {"original_url": "https://record.example/story"}},
        }
        _, article = self._materialize(
            candidate,
            {"original_filename": "export.jsonl", "publisher_url": "https://batch.example"},
        )
        self.assertEqual(article["source_provenance"]["original_url"], "https://record.example/story")


class AutoApproveAndQueueAnalysisTests(unittest.TestCase):
    """Candidates are approved as soon as they're extracted - no human review
    gate - so this is the function that makes that happen. Excluding one from
    then on is a delete on the Articles page, not a pre-approval reject."""

    def test_newly_materialized_candidates_start_an_analysis_run(self):
        with patch.object(project_document_articles, "approve_all",
                           return_value=[{"article_id": 42}]) as mock_approve, \
             patch.object(project_documents_store, "start_or_reuse_analysis_run") as mock_start:
            project_documents_store._try_approve_all_and_queue_analysis(9)
        mock_approve.assert_called_once_with(9)
        mock_start.assert_called_once_with(9)

    def test_nothing_materialized_does_not_start_a_run(self):
        """Every candidate was already approved (e.g. a re-run) - approve_all
        reports them but materialized nothing new, so there's nothing to analyze."""
        with patch.object(project_document_articles, "approve_all", return_value=[]), \
             patch.object(project_documents_store, "start_or_reuse_analysis_run") as mock_start:
            project_documents_store._try_approve_all_and_queue_analysis(9)
        mock_start.assert_not_called()

    def test_approval_failure_is_logged_not_raised(self):
        """A failure here must not propagate: the caller already recorded
        articles_status = 'ready', and process_document's outer guard would
        otherwise overwrite that true state with 'failed'."""
        with patch.object(project_document_articles, "approve_all", side_effect=RuntimeError("boom")), \
             patch.object(project_documents_store, "start_or_reuse_analysis_run") as mock_start:
            project_documents_store._try_approve_all_and_queue_analysis(9)  # must not raise
        mock_start.assert_not_called()


class ApproveForDocumentsTests(unittest.TestCase):
    """approve_for_documents() is approve_all()'s scoped counterpart - the
    Articles page's import uses it so approving what it just uploaded can't
    also sweep up a pending candidate from a wizard mid-review elsewhere in
    the same project."""

    def _candidate(self, candidate_id, document_id, status="pending"):
        return {"id": candidate_id, "document_id": document_id, "status": status}

    def test_only_pending_candidates_from_the_given_documents_are_approved(self):
        candidates = [
            self._candidate(1, document_id=10),  # in scope, pending
            self._candidate(2, document_id=10, status="approved"),  # in scope, already decided
            self._candidate(3, document_id=11),  # not in scope
        ]
        with patch.object(project_document_articles, "list_candidates", return_value=candidates), \
             patch.object(project_document_articles, "set_status",
                           side_effect=lambda cid, status: {"id": cid, "status": status, "article_id": 100 + cid}) as mock_set:
            approved = project_document_articles.approve_for_documents(9, [10])

        mock_set.assert_called_once_with(1, "approved")
        self.assertEqual([a["id"] for a in approved], [1])

    def test_empty_document_ids_approves_nothing(self):
        with patch.object(project_document_articles, "list_candidates") as mock_list, \
             patch.object(project_document_articles, "set_status") as mock_set:
            approved = project_document_articles.approve_for_documents(9, [])

        self.assertEqual(approved, [])
        mock_list.assert_not_called()
        mock_set.assert_not_called()

    def test_a_failed_set_status_is_left_out_of_the_result_not_raised(self):
        candidates = [self._candidate(1, document_id=10)]
        with patch.object(project_document_articles, "list_candidates", return_value=candidates), \
             patch.object(project_document_articles, "set_status", return_value=None):
            approved = project_document_articles.approve_for_documents(9, [10])

        self.assertEqual(approved, [])


class ApproveForDocumentsRouteTests(unittest.TestCase):
    """POST .../document-articles/approve-for-documents: one approval call and
    one run-start for a whole import batch, scoped to the documents it
    actually uploaded."""

    def test_starts_a_run_only_when_something_was_materialized(self):
        from services.projects import project_documents_api

        with patch.object(project_documents_api, "_project_or_404"), \
             patch.object(project_document_articles, "approve_for_documents",
                           return_value=[{"article_id": 42}]) as mock_approve, \
             patch.object(project_documents_api, "start_or_reuse_analysis_run",
                           return_value={"run_id": "run-1"}) as mock_start:
            result = project_documents_api.approve_document_articles_for_documents(
                9, {"document_ids": [10, 11]}, user={"id": 1}
            )

        mock_approve.assert_called_once_with(9, [10, 11])
        mock_start.assert_called_once_with(9)
        self.assertEqual(result, {"articles": [{"article_id": 42}], "run_id": "run-1"})

    def test_no_run_when_nothing_was_materialized(self):
        from services.projects import project_documents_api

        with patch.object(project_documents_api, "_project_or_404"), \
             patch.object(project_document_articles, "approve_for_documents", return_value=[]), \
             patch.object(project_documents_api, "start_or_reuse_analysis_run") as mock_start:
            result = project_documents_api.approve_document_articles_for_documents(
                9, {"document_ids": [10]}, user={"id": 1}
            )

        mock_start.assert_not_called()
        self.assertIsNone(result["run_id"])

    def test_rejects_non_integer_document_ids(self):
        from fastapi import HTTPException

        from services.projects import project_documents_api

        with patch.object(project_documents_api, "_project_or_404"):
            with self.assertRaises(HTTPException) as ctx:
                project_documents_api.approve_document_articles_for_documents(
                    9, {"document_ids": ["not-a-number"]}, user={"id": 1}
                )

        self.assertEqual(ctx.exception.status_code, 400)


class ReanalyzeDocumentArticlesRouteTests(unittest.TestCase):
    """POST .../document-articles/reanalyze must not misreport why nothing
    happened - start_or_reuse_analysis_run() can now legitimately return
    run_id=None, started=False when a self-drain re-check (pipeline.py's
    race-safety fix) finds nothing actually pending, which is a different
    outcome from "a run is already active" and needs a different message."""

    def test_no_approved_candidates_reports_nothing_to_analyze(self):
        from services.projects import project_documents_api

        with patch.object(project_documents_api, "_project_or_404"), \
             patch.object(project_document_articles, "approved_article_ids", return_value=[]), \
             patch.object(project_documents_api, "start_or_reuse_analysis_run") as mock_start:
            result = project_documents_api.reanalyze_document_articles(9, user={"id": 1})

        mock_start.assert_not_called()
        self.assertEqual(result, {"run_id": None, "queued": 0, "message": "No approved articles to analyze yet."})

    def test_a_run_starts_reports_started(self):
        from services.projects import project_documents_api

        with patch.object(project_documents_api, "_project_or_404"), \
             patch.object(project_document_articles, "approved_article_ids", return_value=[101]), \
             patch.object(project_documents_api, "start_or_reuse_analysis_run",
                           return_value={"run_id": "run-1", "started": True}):
            result = project_documents_api.reanalyze_document_articles(9, user={"id": 1})

        self.assertEqual(result, {"run_id": "run-1", "message": "Analysis run started."})

    def test_a_genuinely_active_run_reports_already_active(self):
        from services.projects import project_documents_api

        with patch.object(project_documents_api, "_project_or_404"), \
             patch.object(project_document_articles, "approved_article_ids", return_value=[101]), \
             patch.object(project_documents_api, "start_or_reuse_analysis_run",
                           return_value={"run_id": "run-1", "started": False}):
            result = project_documents_api.reanalyze_document_articles(9, user={"id": 1})

        self.assertEqual(
            result,
            {"run_id": "run-1", "queued": 0, "message": "An analysis run is already active for this project."},
        )

    def test_nothing_actually_pending_reports_nothing_to_reanalyze_not_active(self):
        """start_or_reuse_analysis_run() found an active run, marked this
        project, then its own self-drain re-check discovered the run had
        already finished with nothing left pending - run_id=None,
        started=False. Must not be reported as "already active"."""
        from services.projects import project_documents_api

        with patch.object(project_documents_api, "_project_or_404"), \
             patch.object(project_document_articles, "approved_article_ids", return_value=[101]), \
             patch.object(project_documents_api, "start_or_reuse_analysis_run",
                           return_value={"run_id": None, "started": False}):
            result = project_documents_api.reanalyze_document_articles(9, user={"id": 1})

        self.assertEqual(result, {"run_id": None, "queued": 0, "message": "Nothing to re-analyze."})
        self.assertNotIn("already active", result["message"])


class AllowedExtensionTests(unittest.TestCase):
    def test_record_formats_are_uploadable(self):
        for name in ("export.jsonl", "export.json", "export.ndjson"):
            self.assertTrue(project_documents_store.extension_allowed(name), name)

    def test_unrelated_formats_are_still_rejected(self):
        self.assertFalse(project_documents_store.extension_allowed("notes.txt"))


if __name__ == "__main__":
    unittest.main()
