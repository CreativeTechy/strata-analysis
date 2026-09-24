import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

# scripts/ has no __init__.py (it's a standalone-scripts directory, not a
# package) - loaded by path the same way the script itself is invoked
# (`python scripts/import_iffy_dataset.py`), rather than via a dotted import.
# Registered in sys.modules so patch("import_iffy_dataset.requests.get", ...)
# below can resolve it by name like any normally-imported module.
_SPEC = importlib.util.spec_from_file_location(
    "import_iffy_dataset", Path(__file__).resolve().parents[1] / "scripts" / "import_iffy_dataset.py"
)
import_iffy_dataset = importlib.util.module_from_spec(_SPEC)
sys.modules["import_iffy_dataset"] = import_iffy_dataset
_SPEC.loader.exec_module(import_iffy_dataset)


class DownloadTests(unittest.TestCase):
    def _fake_response(self, chunks, status_ok=True):
        response = MagicMock()
        response.raise_for_status = MagicMock() if status_ok else MagicMock(side_effect=RuntimeError("http error"))
        response.iter_content = MagicMock(return_value=iter(chunks))
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    def test_aborts_once_the_streamed_body_exceeds_the_cap_without_buffering_it_all(self):
        """Regression test: the size cap must reject an oversized response
        while it is still streaming in, not only after `requests` has
        already buffered the whole thing into memory (which the cap is
        supposed to prevent in the first place)."""
        oversized_chunk = b"x" * (import_iffy_dataset.MAX_DOWNLOAD_BYTES + 1)
        response = self._fake_response([oversized_chunk])
        with patch("import_iffy_dataset.requests.get", return_value=response) as mock_get:
            with self.assertRaises(ValueError):
                import_iffy_dataset._download("https://example.com/feed")
        mock_get.assert_called_once()
        # stream=True is what makes the incremental cap meaningful at all -
        # without it `requests` already has the whole body before this
        # function gets a chance to look at its length.
        self.assertTrue(mock_get.call_args.kwargs.get("stream"))

    def test_a_response_under_the_cap_is_parsed_normally(self):
        payload = b'[{"Domain": "example.com"}]'
        response = self._fake_response([payload])
        with patch("import_iffy_dataset.requests.get", return_value=response):
            result = import_iffy_dataset._download("https://example.com/feed")
        self.assertEqual(result, [{"Domain": "example.com"}])

    def test_a_non_list_json_body_is_rejected(self):
        response = self._fake_response([b'{"not": "a list"}'])
        with patch("import_iffy_dataset.requests.get", return_value=response):
            with self.assertRaises(ValueError):
                import_iffy_dataset._download("https://example.com/feed")


if __name__ == "__main__":
    unittest.main()
