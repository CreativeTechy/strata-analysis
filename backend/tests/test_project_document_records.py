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

    def test_source_run_snapshot_is_carried_through_as_metadata(self):
        snapshot = {"id": "run-1", "started_at": "2026-08-20T00:00:00+00:00", "project_id": 4}
        text = json.dumps({"title": "A", "text": "one", "source_run_snapshot": snapshot})
        parsed = records.parse_records(_write("export.jsonl", text), "export.jsonl")
        self.assertEqual(parsed.records[0]["metadata"]["source_run_snapshot"], snapshot)

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
                          "generate_candidates_from_records") as mock_generate:
            project_documents_store._process_record_document(document, path, filename)
        updates = " ".join(str(call.args) for call in mock_db.execute.call_args_list)
        return updates, mock_db, mock_generate

    def test_usable_file_ends_processed_and_ready_with_candidates_written(self):
        text = '{"title": "A", "text": "one"}\n{"title": "B", "text": "two"}\n'
        updates, mock_db, mock_generate = self._run("export.jsonl", text)
        self.assertIn("'processed'", updates)
        self.assertIn("articles_status = 'ready'", updates)
        document_id, project_id, parsed_records = mock_generate.call_args.args
        self.assertEqual((document_id, project_id), (5, 9))
        self.assertEqual([record["title"] for record in parsed_records], ["A", "B"])

    def test_extracted_text_is_article_text_not_raw_json(self):
        _, mock_db, _ = self._run("export.jsonl", '{"title": "A", "text": "one"}\n')
        stored = [call.args[1] for call in mock_db.execute.call_args_list if call.args[1:]]
        self.assertIn("A\none", [param for params in stored for param in params if isinstance(param, str)])

    def test_file_with_no_usable_records_fails_and_skips_generation(self):
        updates, _, mock_generate = self._run("export.jsonl", "not json\n")
        self.assertIn("'failed'", updates)
        self.assertIn("articles_status = 'skipped'", updates)
        mock_generate.assert_not_called()

    def test_truncated_file_says_so_on_a_successful_document(self):
        text = "\n".join(json.dumps({"title": f"A{i}", "text": "x"}) for i in range(records.MAX_RECORDS + 2))
        _, mock_db, _ = self._run("big.jsonl", text)
        notes = [
            call.args[1][0]
            for call in mock_db.execute.call_args_list
            if "articles_status = 'ready'" in call.args[0] and call.args[1:]
        ]
        self.assertTrue(notes and notes[0] and "of 502 records" in notes[0])


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

    def _materialize(self, candidate):
        with patch.object(project_document_articles, "save_articles") as mock_save:
            mock_cur = MagicMock()
            mock_cur.fetchone.side_effect = [{"original_filename": "export.jsonl"}, {"id": 42}]
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


class AllowedExtensionTests(unittest.TestCase):
    def test_record_formats_are_uploadable(self):
        for name in ("export.jsonl", "export.json", "export.ndjson"):
            self.assertTrue(project_documents_store.extension_allowed(name), name)

    def test_unrelated_formats_are_still_rejected(self):
        self.assertFalse(project_documents_store.extension_allowed("notes.txt"))


if __name__ == "__main__":
    unittest.main()
