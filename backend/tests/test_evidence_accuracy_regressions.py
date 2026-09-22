import unittest
from unittest.mock import MagicMock, patch

from services.evidence import workspace as w
from services.articles.publisher_identity import publisher_domain


class AccuracyRegressionTests(unittest.TestCase):
    def test_missing_key_points_never_turn_a_title_into_a_claim(self):
        row = {'title': 'North Sea production bulletin', 'summary': 'An overview of energy markets.'}
        self.assertEqual(w._claim_candidates(row), [])
        row['text'] = 'Oil production increased by 10 percent in August 2026.'
        self.assertEqual(w._claim_candidates(row), [('General', row['text'])])

    def test_low_confidence_relevance_requires_review(self):
        result = w._validate_relevance_result({'results': [{'id': 'a', 'relevance': 'direct', 'score': .6,
                                                          'explanation': 'Shared broad topic.'}]}, {'a'})
        self.assertEqual(result['a']['relevance'], 'uncertain')

    def test_provider_timeout_does_not_trigger_recursive_retries(self):
        from llm_client import LLMTimeoutError
        group = {'fingerprint': 'a', 'canonical': {'claim': 'Oil production increased', 'topic': 'Oil', 'row': {}}}
        with patch.object(w, 'chat_completion', side_effect=LLMTimeoutError()) as call:
            with self.assertRaisesRegex(RuntimeError, 'could not complete'):
                w._classify_relevance_resilient({'name': 'Oil'}, [group, group])
        self.assertEqual(call.call_count, 1)

    def test_high_similarity_does_not_merge_different_facts(self):
        pairs = [
            ('Toyota vehicle sales increased in 2025', 'Tesla vehicle sales increased in 2025'),
            ('Scottish men support the new energy policy', 'Scottish women support the new energy policy'),
            ('Acme acquired Beta in the European market in 2025', 'Beta acquired Acme in the European market in 2025'),
            ('Fuel prices rose in Lebanon', 'Fuel prices rose in Jordan'),
        ]
        for left, right in pairs:
            with self.subTest(left=left):
                self.assertFalse(w._claims_match({'claim': left, 'embedding': [1, 0]}, {'claim': right, 'embedding': [1, 0]}))
                self.assertNotEqual(w._fingerprint('Topic', left), w._fingerprint('Topic', right))

    def test_same_publisher_without_metadata_is_one_origin(self):
        rows = [{'id': 1, 'story_id': 1, 'url': 'https://news.example.com/a'},
                {'id': 2, 'story_id': 2, 'url': 'https://mobile.example.com/b'}]
        origins = w._origin_components(rows)
        self.assertEqual(origins[1], origins[2])

    def test_one_uploaded_document_is_not_multiple_origins(self):
        rows = [{'id': i, 'story_id': i, 'source_url': 'document://project-document/10'} for i in (1, 2)]
        self.assertEqual(len(set(w._origin_components(rows).values())), 1)

    def test_copied_bodies_cannot_inflate_support(self):
        rows = [{'id': i, 'text': 'The same syndicated news report.',
                 'source_provenance': {'publisher': f'Publisher {i}'}} for i in (1, 2)]
        self.assertEqual(len(set(w._origin_components(rows).values())), 1)

    def test_public_suffix_and_private_hosting_identity(self):
        self.assertEqual(publisher_domain('https://news.alpha.co.za/a'), 'alpha.co.za')
        self.assertEqual(publisher_domain('https://beta.co.za/a'), 'beta.co.za')
        self.assertNotEqual(publisher_domain('https://alpha.blogspot.com'), publisher_domain('https://beta.blogspot.com'))

    def run_generation(self, rows):
        written = []
        screened = []
        def classify(scope, groups):
            screened.extend(g['canonical']['claim'] for g in groups)
            return {g['fingerprint']: {'relevance': 'unrelated' if 'football' in g['canonical']['claim'] else 'direct',
                                      'explanation': 'fixture', 'score': 1, 'status': 'success'} for g in groups}
        def execute(sql, params=()):
            if 'insert into evidence_claims' in sql:
                written.append({'claim': params[4], 'assessment': params[12], 'support': params[15],
                                'quotes': params[20], 'relevance': params[24]})
            return {'id': len(written)}
        with patch.object(w, '_snapshot_rows', return_value=rows), \
             patch.object(w, '_screen_articles', return_value=(rows, {'source_articles': len(rows), 'usable_articles': len(rows), 'excluded_articles': 0, 'duplicate_articles': 0, 'pending_articles': 0, 'decision_config': {}})), \
             patch.object(w, '_evaluate_claim_candidate', side_effect=lambda row, topic, claim: {'fingerprint': w._fingerprint(topic, claim), 'status': 'accepted', 'passage': w._best_passage(row, claim), 'reason': 'fixture'}), \
             patch.object(w, 'get_embeddings', return_value=[]), \
             patch.object(w, '_project_scope', return_value={'name': 'Oil production'}), \
             patch.object(w, '_classify_relevance', side_effect=classify), \
             patch.object(w.config, 'EVIDENCE_LLM_ASSESSMENT', False), \
             patch.object(w.db, 'execute', side_effect=execute), \
             patch.object(w.db, 'transaction', return_value=MagicMock()):
            w._generate_for_run('fixture', 1, 1)
        return written, screened

    def test_opposing_document_passages_do_not_support_extracted_claim(self):
        rows = [{'id': i, 'text': f'Oil production did not increase during the previous reporting month. Publisher {i}.',
                 'key_points': ['Oil production increased during the previous reporting month'],
                 'source_provenance': {'publisher': f'Publisher {i}'}} for i in (1, 2)]
        written, screened = self.run_generation(rows)
        self.assertEqual(len(screened), 2)
        self.assertEqual(written[0]['support'], 0)
        self.assertEqual(written[0]['assessment'], 'contradicted')

    def test_each_claim_is_screened_and_duplicate_quotes_count_once(self):
        claim = 'Oil production increased during the previous reporting month'
        rows = [{'id': 1, 'text': claim + '.', 'key_points': [claim, claim, 'The football club won its final match']}]
        written, screened = self.run_generation(rows)
        self.assertEqual(len(screened), 2)
        self.assertEqual(len(written), 2)
        oil = next(item for item in written if item['claim'] == claim)
        unrelated = next(item for item in written if 'football' in item['claim'])
        self.assertEqual(oil['quotes'], 1)
        self.assertEqual(unrelated['relevance'], 'unrelated')


if __name__ == '__main__':
    unittest.main()
