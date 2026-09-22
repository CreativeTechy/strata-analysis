import unittest
from unittest.mock import patch

from fastapi import HTTPException
import main


class CoverageAccessTests(unittest.TestCase):
    def test_invisible_article_cannot_be_sent_to_external_service(self):
        with patch.object(main, '_visible_project_ids_or_none', return_value=[7]), \
             patch.object(main.db, 'fetch_one', return_value=None), \
             patch.object(main, 'check_gdelt_article') as lookup:
            with self.assertRaises(HTTPException) as exc:
                main.check_article_coverage(11, user={'id': 2})
        self.assertEqual(exc.exception.status_code, 404)
        lookup.assert_not_called()

    def test_visible_article_can_be_checked(self):
        with patch.object(main, '_visible_project_ids_or_none', return_value=[7]), \
             patch.object(main.db, 'fetch_one', return_value={'article_id': 11}), \
             patch.object(main, 'check_gdelt_article', return_value={'status': 'some_coverage'}) as lookup:
            result = main.check_article_coverage(11, user={'id': 2})
        lookup.assert_called_once_with(11)
        self.assertEqual(result['coverage']['status'], 'some_coverage')
