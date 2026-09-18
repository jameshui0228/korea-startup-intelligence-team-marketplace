import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from ksi_lib import business, workbench
from ksi_lib.model import Store, init_workspace


class BusinessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        init_workspace(Path(self.tmp.name))
        self.store = Store(Path(self.tmp.name))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def plan(self):
        data = {k: 'fixture assumption' for k in business.ROLES + ('beachhead', 'reachable_this_month', 'stop_condition', 'reopen_condition')}
        for section, fields in (('mvp', business.MVP_FIELDS), ('gtm', business.GTM_FIELDS)):
            data[section] = {k: 'fixture ' + k for k in fields}
            data[section].update(budget_krw=100, starts_at='2026-01-01T00:00:00+09:00', ends_at='2026-02-01T00:00:00+09:00')
        data['mvp']['minimum_sample'] = 5
        data['alternatives'] = [{'kind': k, 'name': k, 'approach': 'fixture method', 'tradeoff': 'fixture tradeoff'} for k in ('status_quo', 'manual', 'non_ai')]
        return data

    def test_complete_structure_never_market_validation(self):
        result = business.check({'business': self.plan(), 'available_budget_krw': 200})
        self.assertTrue(result['structured_plan_complete'])
        self.assertFalse(result['market_validated'])
        self.assertFalse(result['execution_authorized'])

    def test_budget_and_unknown_roles_flagged(self):
        data = self.plan()
        data['buyer'] = 'UNKNOWN'
        result = business.check({'business': data, 'available_budget_krw': 199})
        self.assertTrue(any(g.startswith('buyer:') for g in result['gaps']))
        self.assertTrue(any(g.startswith('budget:') for g in result['gaps']))

    def test_mvp_contradiction_and_unstructured_plan(self):
        data = self.plan()
        data['mvp']['stop_rule'] = data['mvp']['pass_rule']
        data['gtm'] = 'We will advertise'
        self.assertGreaterEqual(len(business.check({'business': data})['gaps']), 2)

    def test_numbers_reject_nan_and_boolean(self):
        for value in (True, float('nan'), -1):
            data = self.plan()
            data['mvp']['budget_krw'] = value
            with self.assertRaises(ValueError):
                business.check({'business': data})

    def candidate(self, key, **changes):
        return {'id': key, 'basis': 'Explicit test assumptions', 'founder_fit': .5, 'customer_access': .5,
                'evidence_strength': .5, 'test_cost_krw': 100, 'test_days': 5, **changes}

    def test_unknown_is_not_zero_or_rejected(self):
        result = business.portfolio({'candidates': [self.candidate('a'), self.candidate('b', founder_fit=None)]})
        self.assertEqual(result['needs_research'], ['b'])
        self.assertEqual(result['candidates'][1]['dominated_by'], [])
        self.assertFalse(result['automatic_rejection'])

    def test_pareto_tradeoff_and_dominance(self):
        result = business.portfolio({'candidates': [self.candidate('a'), self.candidate('b', test_cost_krw=50),
                     self.candidate('c', founder_fit=.9, test_cost_krw=150)]})
        self.assertEqual(result['candidates'][0]['dominated_by'], ['b'])
        self.assertEqual(result['comparable_frontier'], ['b', 'c'])

    def test_duplicate_candidates_and_invalid_score(self):
        for rows in ([self.candidate('a'), self.candidate('a')],
                     [self.candidate('a'), self.candidate('b', founder_fit=2)]):
            with self.assertRaises(ValueError):
                business.portfolio({'candidates': rows})

    def test_interview_is_unsent_unsaved_plan_with_source_revision(self):
        self.store.record('dossier', {'id': 'd', 'target': 'Local shops', 'problem': 'missed reservations'})
        result = business.interview_pack(self.store, {'dossier_id': 'd'})
        self.assertEqual(result['dossier_revision'], 1)
        self.assertEqual(result['input_template']['data']['execution_status'], 'planned')
        self.assertEqual(len(result['input_template']['data']['nonleading_questions']), 6)
        self.assertFalse(result['contacted_customers'])
        self.assertEqual(self.store.records('wb_interview'), [])

    def test_feedback_changed_is_not_implemented(self):
        self.store.record('dossier', {'id': 'd'})
        self.store.record('wb_feedback_action', {'id': 'f', 'subject_id': 'd', 'subject_snapshot': {'revision': 1}, 'decision': 'reject'})
        self.store.record('dossier', {'id': 'd', 'title': 'unrelated change'})
        result = business.feedback_queue(self.store)['items'][0]
        self.assertTrue(result['subject_changed'])
        self.assertFalse(result['implementation_verified'])
        self.assertIn('적용하지 않음', result['next_action'])

    def test_saved_business_preserves_alternatives_and_check(self):
        self.store.record('dossier', {'id': 'd'})
        plan = {**self.plan(), 'dossier_id': 'd', 'model': 'manual service', 'bottlenecks': 'UNKNOWN'}
        result = workbench.save(self.store, {'kind': 'business', 'actor': 'tester', 'role': 'owner', 'data': plan})
        saved = self.store.checkout('wb_business', result['id'])['data']
        self.assertEqual(len(saved['alternatives']), 3)
        self.assertTrue(saved['plan_check']['structured_plan_complete'])
        self.assertFalse(saved['plan_check']['market_validated'])

    def test_empty_alternative_labels_are_not_complete(self):
        plan = self.plan()
        plan['alternatives'] = [{'kind': k} for k in ('status_quo', 'manual', 'non_ai')]
        self.assertFalse(business.check({'business': plan})['structured_plan_complete'])


if __name__ == '__main__':
    unittest.main()
