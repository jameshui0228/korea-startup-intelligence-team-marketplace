import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ksi_lib import social
from ksi_lib.collectors import FetchError
from ksi_lib.model import Store, init_workspace, stamp


class SocialTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        init_workspace(self.root)
        self.store = Store(self.root)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def row(self):
        return {'platform': 'instagram', 'url': 'https://www.instagram.com/p/example/',
                'summary': '검토자가 작성한 비식별 문제 요약', 'observed_at': stamp(),
                'read_scope': 'excerpt', 'collection_basis': 'public_source_verified',
                'limitations': '전체 게시물과 실제 구매는 확인하지 않음'}

    def test_batch_atomic_and_idempotent(self):
        payload = {'actor': 'tester', 'privacy_reviewed': True, 'items': [self.row()]}
        first = social.batch_import(self.store, payload)
        self.assertEqual(len(first['inserted']), 1)
        self.assertEqual(social.batch_import(self.store, payload)['existing_not_overwritten'], first['inserted'])
        self.assertEqual(len(self.store.records('wb_signal')), 1)

    def test_invalid_last_row_leaves_no_partial_batch(self):
        payload = {'actor': 'tester', 'privacy_reviewed': True, 'items': [self.row(), {**self.row(), 'platform': 'x'}]}
        with self.assertRaises(ValueError):
            social.batch_import(self.store, payload)
        self.assertEqual(self.store.records('wb_signal'), [])

    def test_private_summary_and_spoof_host_rejected(self):
        for row in ({**self.row(), 'summary': '문의 a@b.com'},
                    {**self.row(), 'url': 'https://www.instagram.com.evil.example/p/id'}):
            with self.assertRaises(ValueError):
                social.batch_import(self.store, {'actor': 'tester', 'privacy_reviewed': True, 'items': [row]})

    def enable(self):
        self.store.config['x_read_access'] = {'enabled': True, 'user_approved_paid_reads': True,
                                            'provider_spend_cap_confirmed': True, 'daily_request_limit': 1}

    def test_disabled_and_missing_approval_never_fetch(self):
        with patch('ksi_lib.social.fetch') as fetch:
            self.assertEqual(social.x_preview(self.store, {'query': '창업'})['status'], 'disabled')
            self.enable()
            self.store.config['x_read_access']['user_approved_paid_reads'] = False
            with self.assertRaises(ValueError):
                social.x_preview(self.store, {'query': '창업'})
            fetch.assert_not_called()

    def test_x_preview_discards_text_and_never_paginates(self):
        self.enable()
        body = {'data': [{'id': '123', 'text': 'never-store-original', 'created_at': stamp()}], 'meta': {'next_token': 'secret-cursor'}}
        with patch('ksi_lib.social.credentials', return_value={'X_BEARER_TOKEN': 'fixture'}), patch(
                'ksi_lib.social.fetch', return_value=(json.dumps(body).encode(), {'bytes': 1})) as fetch:
            result = social.x_preview(self.store, {'query': '창업'})
            self.assertEqual(result['posts'][0]['url'], 'https://x.com/i/web/status/123')
            self.assertNotIn('never-store-original', json.dumps(result))
            self.assertNotIn('secret-cursor', json.dumps(result))
            self.assertTrue(result['has_more'])
            self.assertEqual(social.x_preview(self.store, {'query': '다른 주제'})['status'], 'daily_limit')
            self.assertEqual(fetch.call_count, 1)

    def test_x_failure_latches_without_retry(self):
        self.enable()
        with patch('ksi_lib.social.credentials', return_value={'X_BEARER_TOKEN': 'fixture'}), patch(
                'ksi_lib.social.fetch', side_effect=FetchError('http_429')) as fetch:
            self.assertEqual(social.x_preview(self.store, {'query': '창업'})['status'], 'source_unavailable')
            self.assertEqual(social.x_preview(self.store, {'query': '창업'})['status'], 'blocked_after_failure')
            self.assertEqual(fetch.call_count, 1)

    def test_partial_error_and_malformed_empty_not_success(self):
        for body in ({'data': [], 'errors': [{'detail': 'sensitive'}]}, {}, {'data': {}}):
            with patch('ksi_lib.social.fetch', return_value=(json.dumps(body).encode(), {})):
                with self.assertRaises(FetchError):
                    social.x_recent('query', 'fixture')
        with patch('ksi_lib.social.fetch', return_value=(b'{"meta":{"result_count":0}}', {})):
            self.assertEqual(social.x_recent('query', 'fixture')['posts'], [])

    def test_manual_auth_recovery_preserves_failure_and_does_not_fetch(self):
        self.store.fetch_log('x_preview', 'hash', 'source_unavailable', 0, {'failure_code': 'http_401'})
        self.store.db.commit()
        rid = social.x_status(self.store)['unresolved'][0]['attempt_id']
        payload = {'attempt_id': rid, 'actor': 'tester', 'user_confirmed_resume': True,
                   'billing_and_access_checked': True, 'resolution_summary': 'Synthetic authorization corrected'}
        with patch('ksi_lib.social.fetch') as fetch:
            self.assertFalse(social.x_recover(self.store, payload)['remaining']['blocked'])
            fetch.assert_not_called()
        self.assertEqual(self.store.db.execute('SELECT status FROM fetches').fetchone()[0], 'source_unavailable')
        with self.assertRaises(ValueError):
            social.x_recover(self.store, payload)

    def test_recovery_rejects_unconfirmed_and_ambiguous_attempts(self):
        for code in ('http_429', 'unknown_failure'):
            self.store.fetch_log('x_preview', 'hash', 'source_unavailable', 0, {'failure_code': code})
        self.store.db.commit()
        for row in social.x_status(self.store)['unresolved']:
            with self.assertRaises(ValueError):
                social.x_recover(self.store, {'attempt_id': row['attempt_id'], 'actor': 'tester',
                    'user_confirmed_resume': True, 'billing_and_access_checked': True, 'resolution_summary': 'fixture'})
        with self.assertRaises(ValueError):
            social.x_recover(self.store, {'attempt_id': 1})

    def test_invalid_meta_is_schema_failure(self):
        with patch('ksi_lib.social.fetch', return_value=(b'{"data":[],"meta":null}', {})):
            with self.assertRaises(FetchError):
                social.x_recent('query', 'fixture')


if __name__ == '__main__':
    unittest.main()
