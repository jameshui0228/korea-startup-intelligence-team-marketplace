import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import ksi
from ksi_lib import insights, workbench, agenda, research
from ksi_lib.collectors import FetchError, youtube_uploads
from ksi_lib.model import Store, init_workspace, now, observation, stamp


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'state'
        init_workspace(self.root)
        self.store = Store(self.root)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def payload(self, kind, data, **extra):
        return {'kind': kind, 'actor': 'tester', 'role': 'owner', 'data': data, **extra}

    def test_cas_preserves_latest_and_diff(self):
        self.store.record('claim', {'id': 'c', 'answer': 'initial'})
        stale = self.store.checkout('claim', 'c')
        self.store.record('claim', {'id': 'c', 'answer': 'new'}, stale['expected_revision'])
        with self.assertRaisesRegex(ValueError, '편집 충돌'):
            self.store.record('claim', stale['data'], stale['expected_revision'])
        self.assertEqual(self.store.checkout('claim', 'c')['data']['answer'], 'new')
        self.assertIn('+  "answer": "new"', workbench.diff(self.store, 'claim', 'c')['diff'])

    def test_cli_missing_revision_blocks_existing_dossier(self):
        self.store.record('dossier', {'id': 'dossier-demo', 'key': 'demo'})
        with patch('pathlib.Path.read_text', return_value=json.dumps({'key': 'demo'})):
            with self.assertRaisesRegex(ValueError, '편집 충돌'):
                ksi.edit_payload(self.store, '/unused', 'dossier', 'dossier-')

    def test_attachment_review_rejects_false_coverage(self):
        data = {'file_sha256': 'a' * 64, 'pages_total': 2, 'pages_read': [1, 3],
                'tables_checked': False, 'footnotes_checked': False, 'ocr_verified': False,
                'limitations': 'Partial review'}
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('attachment_review', data))
        data['pages_read'] = [1]
        saved = workbench.save(self.store, self.payload('attachment_review', data))
        self.assertFalse(saved['data']['all_pages_reported_read'])
        data['ocr_verified'] = 'false'
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('attachment_review', data))

    def test_cas_across_connections_preserves_committed_revision(self):
        self.store.record('claim', {'id': 'shared', 'answer': 'initial'})
        self.store.db.commit()
        other = Store(self.root)
        try:
            revision = other.checkout('claim', 'shared')['expected_revision']
            self.store.record('claim', {'id': 'shared', 'answer': 'winner'}, revision)
            self.store.db.commit()
            with self.assertRaisesRegex(ValueError, '편집 충돌'):
                other.record('claim', {'id': 'shared', 'answer': 'stale'}, revision)
            other.db.rollback()
            self.assertEqual(other.checkout('claim', 'shared')['data']['answer'], 'winner')
        finally:
            other.close()

    def test_founder_reuse_and_stale_update(self):
        data = {k: 'UNKNOWN' for k in workbench.CONTRACTS['founder']}
        first = workbench.save(self.store, self.payload('founder', data, id='founder'))
        updated = {**data, 'region': '부산'}
        workbench.save(self.store, self.payload('founder', updated, id='founder', expected_revision=first['revision']))
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('founder', data, id='founder', expected_revision=1))
        self.assertEqual(workbench.dashboard(self.store)['founder_answers'][0]['region'], '부산')

    def test_roles_and_independent_review(self):
        data = {k: 'UNKNOWN' for k in workbench.CONTRACTS['founder']}
        with self.assertRaises(ValueError):
            workbench.save(self.store, {'kind': 'founder', 'actor': 'reader', 'role': 'reader', 'data': data})
        self.store.record('claim', {'id': 'claim', 'text': 'hypothesis'})
        review = {'subject_id': 'claim', 'author_actor': 'tester', 'verdict': 'reviewed', 'reason': 'fixture', 'independent': True}
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('review', review))
        review['independent'] = False
        saved = workbench.save(self.store, self.payload('review', review))
        self.assertEqual(saved['data']['subject_snapshot']['revision'], 1)
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('review', review, id=saved['id'], expected_revision=1))

    def test_intraday_rates_and_reset(self):
        base = now() - timedelta(hours=3)
        for hours, value in ((0, 100), (0.5, 160), (1.5, 200), (2, 10)):
            row = observation('youtube_stats', 'social_metric', 'fixture', 'video', 'https://www.youtube.com/watch?v=abc123DEF45',
                              metrics={'likes_snapshot': value})
            row['observed_at'] = stamp(base + timedelta(hours=hours))
            self.store.put_observation(row)
        result = insights.velocity(self.store)[0]
        self.assertEqual(result['samples'], 4)
        self.assertEqual(result['intervals'][0]['per_hour'], 120)
        self.assertEqual(result['intervals'][1]['per_hour'], 40)
        self.assertIsNone(result['intervals'][2]['per_hour'])
        self.assertFalse(result['acceleration_verified'])

    def test_compare_different_denominators_and_unknown_format(self):
        row = {k: 'same' for k in ('definition', 'unit', 'population', 'normalization', 'format', 'age_bucket', 'channel_cohort')}
        row.update(value=10, period_seconds=3600)
        right = {**row, 'value': 20}
        self.assertEqual(insights.compare({'left': row, 'right': right})['change_ratio'], 1)
        right['population'] = 'other'
        self.assertFalse(insights.compare({'left': row, 'right': right})['comparable'])
        row['format'] = right['format'] = 'UNKNOWN'
        self.assertFalse(insights.compare({'left': row, 'right': right})['comparable'])

    def test_latency_unknown_and_reversed(self):
        t = now() - timedelta(hours=3)
        result = insights.latency({'published_at': stamp(t), 'collected_at': stamp(t+timedelta(hours=1))})
        self.assertIsNone(result['seconds']['published_at_to_provider_available_at'])
        with self.assertRaises(ValueError):
            insights.latency({'published_at': stamp(t+timedelta(hours=1)), 'collected_at': stamp(t)})

    def test_economics_break_even_and_negative_margin(self):
        row = {'name': 'assumption', 'basis': 'one month assumption', 'price_krw': 100, 'variable_cost_krw': 20,
               'service_cost_krw': 10, 'cac_krw': 40, 'orders_per_customer': 2, 'customers': 10,
               'fixed_cost_krw': 500, 'working_capital_krw': 200}
        result = insights.economics({'scenarios': [row]})['scenarios'][0]
        self.assertEqual(result['break_even_customers'], 5)
        self.assertEqual(result['cash_after_working_capital_krw'], 300)
        row['cac_krw'] = 200
        self.assertIsNone(insights.economics({'scenarios': [row]})['scenarios'][0]['break_even_customers'])
        row['price_krw'] = True
        with self.assertRaises(ValueError):
            insights.economics({'scenarios': [row]})

    def test_intake_dedupe_not_read_and_no_execution(self):
        payload = {'url': 'https://example.com/article?utm_source=test', 'actor': 'tester', 'collection_basis': 'public_source_verified'}
        first = workbench.intake(self.store, payload)
        self.assertEqual(first['item']['read_scope'], 'not_read')
        self.assertEqual(workbench.intake(self.store, {**payload, 'url': 'https://example.com/article'})['status'], 'duplicate')
        self.assertEqual(self.store.observations(), [])
        with self.assertRaises(ValueError):
            workbench.intake(self.store, {**payload, 'url': 'https://example.com/?api_key=forbidden'})

    def test_export_rejects_secret_and_has_no_raw_state(self):
        with self.assertRaises(ValueError):
            workbench.export_public(self.store, {'summary': 'client_secret=fixture', 'privacy_reviewed': True, 'actor': 'tester'})
        result = workbench.export_public(self.store, {'summary': '공개 근거를 읽고 아직 수요는 확인하지 못함', 'privacy_reviewed': True,
                                                    'actor': 'tester', 'public_urls': ['https://example.com/']})
        exported = json.loads(Path(result['path']).read_text())
        self.assertNotIn('data', exported)
        self.assertFalse(result['sent'])

    def test_backup_restore_copy_and_merge_conflicts(self):
        with self.store.db:
            self.store.record('claim', {'id': 'one', 'value': 'original'})
        saved = workbench.backup(self.store)
        destination = Path(self.tmp.name) / 'restored'
        workbench.restore_copy(saved['path'], destination)
        other = Store(destination)
        try:
            self.assertEqual(other.records('claim')[0]['value'], 'original')
            self.assertEqual(other.config['enabled_sources'], [])
        finally:
            other.close()
        with self.store.db:
            self.store.record('claim', {'id': 'one', 'value': 'changed'})
        preview = workbench.merge_preview(self.store, saved['path'])
        self.assertEqual(len(preview['conflicts']), 1)
        self.assertFalse(preview['mutated'])
        with self.assertRaises(ValueError):
            workbench.restore_copy(saved['path'], self.root)

    def test_migration_backup_preserves_original(self):
        self.store.db.execute('DROP TABLE metric_samples')
        self.store.db.commit()
        self.store.close()
        self.store = Store(self.root)
        backups = list((self.root / 'backups').glob('before-intraday-*.sqlite3'))
        self.assertEqual(len(backups), 1)
        db = sqlite3.connect(backups[0])
        try:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertNotIn('metric_samples', {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")})
        finally:
            db.close()

    def test_impact_includes_application(self):
        self.store.record('dossier', {'id': 'd', 'evidence_ids': ['e']})
        self.store.record('application', {'id': 'a', 'dossier_id': 'd'})
        result = workbench.impact(self.store, 'e')
        self.assertEqual(result['direct'][0]['id'], 'd')
        self.assertEqual(result['downstream'][0]['id'], 'a')

    def test_evaluation_keeps_misses_failed_pending(self):
        rows = [{'detected': True, 'truth': True, 'probability': .8}, {'detected': True, 'truth': False},
                {'detected': False, 'truth': True}, {'detected': False, 'truth': False}, {'state': 'failed'}]
        result = insights.evaluate(rows)
        self.assertEqual(result['registered'], 5)
        self.assertEqual(result['precision'], .5)
        self.assertEqual(result['recall_within_registered_truth_set'], .5)
        self.assertEqual(result['failed'], 1)
        self.assertEqual(result['pending'], 1)
        self.assertAlmostEqual(result['mean_brier'], .04)

    def test_benchmark_cannot_use_future_evidence_or_resolve_early(self):
        obs = observation('manual', 'manual_evidence', 'x', 'x', 'https://example.com/x')
        self.store.put_observation(obs)
        plan = {'question': 'test', 'cutoff': stamp(now()-timedelta(days=1)), 'deadline': stamp(now()+timedelta(days=1)),
                'baseline': 'fixed', 'truth_rule': 'fixed', 'queries': ['fixed'], 'rules_version': '1', 'platform': 'web', 'domain_id': 'demo',
                'detected': False, 'probability': .5, 'detected_at': None, 'available_evidence_ids': [obs['id']]}
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('benchmark', plan))
        plan['available_evidence_ids'] = []
        saved = workbench.save(self.store, self.payload('benchmark', plan))
        result = {'benchmark_id': saved['id'], 'truth': True, 'state': 'completed', 'baseline_at': None,
                  'evidence_ids': [obs['id']], 'limitations': ['fixture']}
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('benchmark_result', result))

    def test_checkpoint_budget_exhaustion_preserves_handoff(self):
        session = {'goal': 'test', 'mode': 'explore', 'budget_minutes': 10, 'request_limit': 2, 'context_limit': 1000,
                   'storage_limit_mb': 100, 'model_cost_limit': None, 'next_action': 'research'}
        saved = workbench.save(self.store, self.payload('session', session))
        checkpoint = {'session_id': saved['id'], 'completed': ['plan'], 'remaining': ['read'], 'blockers': [], 'next_action': 'resume',
                      'manual_interventions': 1, 'retries': 0, 'elapsed_minutes': 11, 'requests': 3, 'context_used': 500, 'model_cost': None}
        result = workbench.save(self.store, self.payload('checkpoint', checkpoint))['data']
        self.assertFalse(result['continue_allowed'])
        self.assertEqual(result['budget_exceeded'], ['elapsed_minutes', 'requests'])
        self.assertEqual(result['cost_measurement'], 'unknown')

    def test_youtube_uploads_bounded_and_metadata_only(self):
        data = {'items': [{'snippet': {'title': 'video'}, 'contentDetails': {'videoId': 'abc123DEF45', 'videoPublishedAt': '2026-01-01T00:00:00Z'}}], 'nextPageToken': 'more'}
        with patch('ksi_lib.collectors.fetch', return_value=(json.dumps(data).encode(), {})) as fetch:
            rows, receipt = youtube_uploads('UU' + 'a' * 22, {'YOUTUBE_API_KEY': 'fixture'}, 5)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(rows[0]['content_scope'], 'metadata_only')
        self.assertEqual(rows[0]['video_format'], 'UNKNOWN')
        self.assertTrue(receipt['has_more'])
        with patch('ksi_lib.collectors.fetch') as fetch, self.assertRaises(FetchError):
            youtube_uploads('bad', {'YOUTUBE_API_KEY': 'fixture'}, 5)
        fetch.assert_not_called()

    def test_owner_handoff_blocks_wrong_actor_and_retains_history(self):
        task = research.research_plan(self.store, 2)['tasks'][0]
        started = agenda.start(self.store, task['task_id'], actor='alice')['run']
        with self.assertRaises(ValueError):
            agenda.start(self.store, task['task_id'], actor='bob')
        with self.assertRaises(ValueError):
            agenda.handoff(self.store, started['id'], 'bob', 'carol', 'invalid')
        agenda.handoff(self.store, started['id'], 'alice', 'bob', 'planned handoff')
        resumed = agenda.start(self.store, task['task_id'], actor='bob')
        self.assertEqual(resumed['status'], 'resumed')
        self.assertEqual(len(self.store.records('research_handoff')), 1)

    def test_bad_glossary_and_fake_document_rejected(self):
        data = {'term': 'test', 'meaning': 'test', 'aliases': 'not a list', 'excluded_meanings': [], 'query_precision': None}
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('glossary', data))
        data = {k: None for k in workbench.CONTRACTS['document_qa']}
        data['application_id'] = 'nonexistent'
        with self.assertRaises(ValueError):
            workbench.save(self.store, self.payload('document_qa', data))


if __name__ == '__main__':
    unittest.main()
