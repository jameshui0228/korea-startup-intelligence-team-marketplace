import sys
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ksi_lib import research_tools as rt
from ksi_lib import workbench
from ksi_lib import research, grants, application
from ksi_lib.model import Store, init_workspace, now, stamp, observation
from ksi_lib.collectors import youtube_comment_sample, FetchError


class ResearchToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        init_workspace(self.root)
        self.store = Store(self.root)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def period(self, offset, receipts=0, payments=0):
        row = {k: 0 for k in ('customer_receipts', 'financing', 'other_receipts', 'supplier_payments',
               'payroll', 'marketing', 'tax', 'refunds', 'capex', 'debt_service', 'other_payments')}
        return {**row, 'ends_at': stamp(now()+timedelta(days=offset)), 'basis': 'Test assumption',
                'customer_receipts': receipts, 'supplier_payments': payments}

    def test_cashflow_carries_losses_and_financing(self):
        rows = [self.period(1, payments=150), self.period(2, receipts=20)]
        result = rt.cashflow({'opening_cash_krw': 100, 'periods': rows})
        self.assertEqual(result['maximum_funding_gap_krw'], 50)
        self.assertEqual(result['periods'][1]['closing_cash_krw'], -30)
        rows[1]['financing'] = 40
        self.assertEqual(rt.cashflow({'opening_cash_krw': 100, 'periods': rows})['periods'][1]['closing_cash_krw'], 10)

    def test_cashflow_invalid_inputs(self):
        for rows in ([], [self.period(2), self.period(1)], [{**self.period(1), 'tax': True}],
                     [{**self.period(1), 'payroll': float('nan')}], [{**self.period(1), 'basis': ''}]):
            with self.assertRaises(ValueError):
                rt.cashflow({'opening_cash_krw': 100, 'periods': rows})

    def test_sampling_denominators_and_overlap(self):
        values = dict(invited=10, responded=8, eligible=6, completed=5, friends=4, incentivized=3, self_selected=5)
        result = rt.sampling(values)
        self.assertEqual(result['completion_rate'], .5)
        self.assertEqual(result['bias_shares']['friends'], .8)
        self.assertFalse(result['representativeness_verified'])
        with self.assertRaises(ValueError):
            rt.sampling({**values, 'completed': 9})
        with self.assertRaises(ValueError):
            rt.sampling({**values, 'friends': 6})

    def test_sampling_zero_is_unknown_not_perfect(self):
        result = rt.sampling(dict.fromkeys(('invited', 'responded', 'eligible', 'completed', 'friends', 'incentivized', 'self_selected'), 0))
        self.assertIsNone(result['response_rate'])

    def test_due_does_not_mark_reviewed(self):
        old = stamp(now()-timedelta(days=9))
        self.store.record('wb_competitor', {'id': 'old', 'checked_at': old})
        self.store.record('wb_competitor', {'id': 'fresh', 'checked_at': stamp()})
        self.store.record('wb_watchlist', {'id': 'unknown', 'review_after': 'UNKNOWN'})
        result = rt.due_reviews(self.store)
        self.assertEqual({r['id'] for r in result['items']}, {'old', 'unknown'})
        self.assertEqual(self.store.checkout('wb_competitor', 'old')['data']['checked_at'], old)

    def test_duplicate_candidates_never_merge(self):
        for source in ('manual', 'google_news_rss'):
            self.store.put_observation(observation(source, 'article', 'topic', '한국 작은 제조 업체 납품 문제',
                                      'https://example.com/' + source))
        result = rt.duplicate_candidates(self.store)
        self.assertEqual(len(result['candidates']), 1)
        self.assertFalse(result['candidates'][0]['auto_merged'])
        self.assertEqual(len(self.store.observations()), 2)

    def test_workflow_unknown_and_rejected(self):
        self.store.record('dossier', {'id': 'd', 'findings': {'payment': {'status': 'UNKNOWN'}}, 'decision': 'research'})
        self.assertEqual(rt.workflow(self.store)['work'][0]['stage'], 'research')
        self.store.record('dossier', {'id': 'd', 'findings': {}, 'decision': 'reject'})
        self.assertEqual(rt.workflow(self.store)['work'][0]['stage'], 'paused')

    def test_usability_groups_do_not_hide_incomplete(self):
        for i, complete in enumerate((True, False)):
            self.store.record('wb_usability', {'id': str(i), 'task': 'same', 'condition': 'plugin',
                'participant_pseudonym': 'same-person', 'completed': complete, 'minutes': 10+i*10,
                'missing_sources': i, 'rework': i, 'incorrect_citations': 0, 'manual_interventions': i})
        group = rt.usability_report(self.store)['groups'][0]
        self.assertEqual(group['completion_rate'], .5)
        self.assertEqual(group['participants'], 1)
        self.assertEqual(group['means']['minutes'], 15)

    def test_ablation_requires_same_truth_set(self):
        row = dict(task='same', cutoff='2026-01-01', truth_set='v1', rules_version='1', cost=10,
                   true_positives=3, false_positives=2, lead_seconds=20)
        result = rt.ablation_compare({'baseline': row, 'without_source': {**row, 'cost': 2, 'true_positives': 1}})
        self.assertEqual(result['source_added_delta']['true_positives'], 2)
        self.assertFalse(rt.ablation_compare({'baseline': row, 'without_source': {**row, 'truth_set': 'v2'}})['comparable'])

    def test_impact_traverses_three_hops_and_cycles(self):
        self.store.record('dossier', {'id': 'd', 'evidence_ids': ['e']})
        self.store.record('application', {'id': 'a', 'dossier_id': 'd'})
        self.store.record('wb_review', {'id': 'r', 'subject_id': 'a'})
        self.store.record('wb_comment', {'id': 'c', 'subject_id': 'r'})
        result = workbench.impact(self.store, 'e')
        self.assertEqual({r['id'] for r in result['downstream']}, {'a', 'r', 'c'})
        self.store.record('wb_comment', {'id': 'self', 'subject_id': 'self'})
        self.assertEqual(len(workbench.impact(self.store, 'e')['downstream']), 3)

    def test_comments_discard_profiles_and_redact_excerpt(self):
        body = {'items': [{'snippet': {'topLevelComment': {'snippet': {'textDisplay': '문의 a@b.com @someone 010-1234-5678',
                   'authorDisplayName': 'Do not keep', 'authorChannelUrl': 'secret', 'publishedAt': stamp()}}}}]}
        with patch('ksi_lib.collectors.fetch', return_value=(json.dumps(body).encode(), {})) as fetch:
            samples, receipt = youtube_comment_sample('abc123DEF45', {'YOUTUBE_API_KEY': 'test-only'})
        self.assertNotIn('a@b.com', samples[0]['excerpt'])
        self.assertNotIn('authorDisplayName', json.dumps(samples))
        self.assertFalse(receipt['author_fields_retained'])
        self.assertEqual(fetch.call_count, 1)
        with self.assertRaises(FetchError):
            youtube_comment_sample('invalid', {})

    def test_comment_attempts_are_bounded_and_no_text_persisted(self):
        payload = {'video_id': 'abc123DEF45', 'public_source_verified': True}
        with patch('ksi_lib.model.credentials', return_value={'YOUTUBE_API_KEY': 'test-only'}), patch(
                'ksi_lib.collectors.youtube_comment_sample', return_value=([{'excerpt': 'private-sample'}], {'sample_count': 1})) as fetch:
            result = workbench.comment_sample(self.store, payload)
            self.assertEqual(result['status'], 'sample_for_review')
            with self.assertRaises(ValueError):
                workbench.comment_sample(self.store, payload)
            self.assertEqual(fetch.call_count, 1)
        row = self.store.db.execute("SELECT status,receipt FROM fetches WHERE source='youtube_comment_sample'").fetchone()
        self.assertEqual(row['status'], 'ok')
        self.assertNotIn('private-sample', row['receipt'])

    def test_comment_failure_is_not_empty_success(self):
        with patch('ksi_lib.model.credentials', return_value={'YOUTUBE_API_KEY': 'test-only'}), patch(
                'ksi_lib.collectors.youtube_comment_sample', side_effect=FetchError('http_403')):
            result = workbench.comment_sample(self.store, {'video_id': 'abc123DEF45', 'public_source_verified': True})
        self.assertEqual(result['status'], 'source_unavailable')
        self.assertEqual(self.store.db.execute('SELECT status FROM fetches').fetchone()[0], 'source_unavailable')

    def test_domain_savers_reject_explicit_stale_revision_before_validation(self):
        for kind, prefix, save in (('dossier', 'dossier-', research.save_dossier),
                                  ('grant', 'grant-', grants.save_notice),
                                  ('application', 'application-', application.save)):
            self.store.record(kind, {'id': prefix + 'demo'})
            self.store.db.commit()
            with self.assertRaisesRegex(ValueError, '편집 충돌'):
                save(self.store, {'key': 'demo', 'expected_revision': 0})


if __name__ == '__main__':
    unittest.main()
