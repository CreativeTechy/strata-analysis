"""Unit tests for competitor_documents_store.delete_document()'s handling of
a mirrored document (see services/competitors/project_document_bridge.py):
deleting one must mark its source project_documents row excluded so a later
sync doesn't just recreate it, while an ordinary (non-mirrored) upload's
delete is unaffected.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from services.competitors import competitor_documents_store


class DeleteDocumentTests(unittest.TestCase):
    def test_deleting_a_mirrored_document_excludes_its_source(self):
        document = {"id": 9, "storage_path": "mirrored:project-document/3"}
        with patch.object(competitor_documents_store, "get_document", return_value=document), \
             patch.object(competitor_documents_store.db, "fetch_one", return_value={"source_project_document_id": 3}), \
             patch.object(competitor_documents_store.db, "execute") as mock_execute, \
             patch.object(competitor_documents_store.Path, "unlink"):
            result = competitor_documents_store.delete_document(9)

        self.assertTrue(result)
        delete_call, exclude_call = mock_execute.call_args_list
        self.assertIn("delete from competitor_documents", delete_call[0][0])
        self.assertEqual(delete_call[0][1], (9,))
        self.assertIn("competitor_mirror_excluded = true", exclude_call[0][0])
        self.assertEqual(exclude_call[0][1], (3,))

    def test_deleting_an_ordinary_upload_does_not_touch_project_documents(self):
        document = {"id": 9, "storage_path": "competitor_documents/real-upload.pdf"}
        with patch.object(competitor_documents_store, "get_document", return_value=document), \
             patch.object(competitor_documents_store.db, "fetch_one", return_value={"source_project_document_id": None}), \
             patch.object(competitor_documents_store.db, "execute") as mock_execute, \
             patch.object(competitor_documents_store.Path, "unlink"):
            result = competitor_documents_store.delete_document(9)

        self.assertTrue(result)
        mock_execute.assert_called_once()
        self.assertIn("delete from competitor_documents", mock_execute.call_args[0][0])

    def test_missing_document_returns_false_without_deleting(self):
        with patch.object(competitor_documents_store, "get_document", return_value=None), \
             patch.object(competitor_documents_store.db, "execute") as mock_execute:
            result = competitor_documents_store.delete_document(404)

        self.assertFalse(result)
        mock_execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
