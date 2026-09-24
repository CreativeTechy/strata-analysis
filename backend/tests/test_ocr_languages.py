import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import config
from services.documents import extraction


class OcrLanguagesConfigTests(unittest.TestCase):
    """config.OCR_LANGUAGES: the Tesseract language string every OCR call
    site is required to pass through (see ImageOcrLanguagePassthroughTests
    below)."""

    def _reload_with_env(self, env: dict) -> None:
        with patch.dict(os.environ, env, clear=True), patch.object(Path, "exists", return_value=False):
            importlib.reload(config)

    def tearDown(self):
        importlib.reload(config)

    def test_default_is_eng_plus_ara(self):
        """Arabic OCR only works out of the box if the default actually asks
        Tesseract for the Arabic pack alongside English (the Docker image
        installs both - see Dockerfile)."""
        self._reload_with_env({})
        self.assertEqual(config.OCR_LANGUAGES, "eng+ara")

    def test_env_override_is_respected(self):
        self._reload_with_env({"OCR_LANGUAGES": "eng"})
        self.assertEqual(config.OCR_LANGUAGES, "eng")


class ImageOcrLanguagePassthroughTests(unittest.TestCase):
    """Every pytesseract.image_to_string() call site must pass
    lang=config.OCR_LANGUAGES - otherwise Tesseract silently falls back to
    its own default ("eng"), and Arabic scans never OCR correctly regardless
    of what OCR_LANGUAGES is configured to."""

    def test_image_chunk_passes_configured_ocr_languages(self):
        fake_image = MagicMock()
        with patch.object(extraction, "pytesseract") as mock_tesseract, \
             patch.object(extraction, "Image") as mock_image_module, \
             patch.object(config, "OCR_LANGUAGES", "eng+ara"):
            mock_image_module.open.return_value = fake_image
            mock_tesseract.image_to_string.return_value = "hello"
            list(extraction._image_chunks(Path("fake.png")))
        mock_tesseract.image_to_string.assert_called_once_with(fake_image, lang="eng+ara")

    def test_pdf_ocr_fallback_passes_configured_ocr_languages(self):
        fake_page = MagicMock()
        fake_page.get_text.return_value = ""  # forces the OCR fallback path
        fake_pixmap = MagicMock()
        fake_pixmap.tobytes.return_value = b"fake-png-bytes"
        fake_page.get_pixmap.return_value = fake_pixmap

        fake_doc = MagicMock()
        fake_doc.__iter__.return_value = iter([fake_page])
        fake_doc.close = MagicMock()

        fake_image = MagicMock()

        with patch.object(extraction, "fitz") as mock_fitz, \
             patch.object(extraction, "pytesseract") as mock_tesseract, \
             patch.object(extraction, "Image") as mock_image_module, \
             patch.object(config, "OCR_LANGUAGES", "eng+ara"):
            mock_fitz.open.return_value = fake_doc
            mock_fitz.Matrix.return_value = "matrix"
            mock_image_module.open.return_value = fake_image
            mock_tesseract.image_to_string.return_value = "hello"
            list(extraction._pdf_chunks(Path("fake.pdf")))

        mock_tesseract.image_to_string.assert_called_once_with(fake_image, lang="eng+ara")


if __name__ == "__main__":
    unittest.main()
