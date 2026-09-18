import copy
from datetime import timedelta

from test_radar import RadarTest
from ksi_lib import competition, grants, research_tools
from ksi_lib.model import now, stamp


class CompetitionTest(RadarTest):
    def setUp(self):
        super().setUp()
        self.reference = '공고일 2026-09-18'
        self.profile = {'startup_age_years': {'value': 2, 'status': 'confirmed',
                        'basis': '비식별 사업자 등록일 확인', 'as_of_basis': self.reference}}
        notice = {'key': 'fixture-award', 'title': '테스트 전용 창업 공모전', 'issuer': '테스트 기관',
                  'notice_version': 'fixture-v1', 'evidence_ids': self.eids,
                  'official_notice_confirmed': True, 'conditions_complete': True,
                  'coverage_note': '합성 단위시험 공고이며 외부 신청에 사용하지 않음',
                  'opens_at': stamp(now() - timedelta(days=1)),
                  'closes_at': stamp(now() + timedelta(days=7)),
                  'rules': [{'field': 'startup_age_years', 'operator': 'lte', 'value': 3,
                             'description': '창업 3년 이하', 'locator': '테스트 1쪽',
                             'as_of_basis': self.reference, 'evidence_ids': self.eids}],
                  'evaluation_criteria': [{'criterion': '문제성과 혁신성', 'weight': 40,
                                           'locator': '테스트 평가표'}]}
        self.grant_id = grants.save_notice(self.store, notice)['id']

    def candidate(self, key, budget=100000, dossier=True):
        claim = {'status': 'INFERENCE', 'text': '합성 시험에서만 사용하는 근거 연결 주장',
                 'evidence_ids': [self.eids[0]]}
        return {'key': key, 'title': '테스트 후보 ' + key,
                'target': self.dossier_input['target'], 'problem': self.dossier_input['problem'],
                'solution': '공모전 처리 흐름을 검증하는 합성 해결책',
                'business_model': '테스트용 B2B 구독 가설', 'first_users': '테스트 모집 경로',
                'domain_ids': [self.domain], 'dossier_id': self.dossier_id if dossier else None,
                'claims': {name: copy.deepcopy(claim) for name in competition.CORE_CLAIMS},
                'criterion_mapping': [{'criterion': '문제성과 혁신성', **copy.deepcopy(claim)}],
                'founder_fit': {'status': 'confirmed', 'statement': '테스트 적합성',
                                'basis': '합성 단위시험 입력'},
                'demo': {'method': '수동 데모', 'timebox_days': 5, 'budget_krw': budget,
                         'pass_condition': '사전 정의한 테스트 통과',
                         'stop_condition': '사전 정의한 테스트 실패'},
                'risks': ['실제 고객 수요는 확인되지 않음'],
                'assumptions': ['합성 fixture만 사용함']}

    def test_prepare_pins_notice_criteria_and_diverse_slots(self):
        result = competition.prepare(self.store, self.grant_id, self.profile, 12)
        self.assertEqual(result['eligibility']['eligibility'], 'MATCHES_RECORDED_RULES')
        self.assertEqual(len(result['candidate_slots']), 12)
        self.assertGreaterEqual(len({row['lens'] for row in result['candidate_slots']}), 8)
        self.assertFalse(result['ideas_generated'])
        self.assertIsNone(result['selection_probability'])

    def test_evaluate_shortlists_only_evidence_linked_candidate(self):
        strong = self.candidate('evidence-linked', 50000)
        weak = self.candidate('missing-dossier', 100000, dossier=False)
        result = competition.evaluate(self.store, {'grant_id': self.grant_id,
                                      'profile': self.profile, 'candidates': [strong, weak]})
        self.assertEqual(result['shortlist'], ['evidence-linked'])
        weak_result = next(row for row in result['candidates'] if row['key'] == 'missing-dossier')
        self.assertIn('evidence_linked_dossier_missing', weak_result['evidence_gaps'])
        self.assertIn('evidence-linked', result['pareto_frontier'])
        self.assertNotIn('missing-dossier', result['pareto_frontier'])
        self.assertIsNone(result['candidates'][0]['award_probability'])
        self.assertEqual(competition.status(self.store, self.grant_id)['count'], 1)
        queue = research_tools.team_queue(self.store)
        self.assertTrue(any(row['lane'] == 'competition' and row['subject_id'] == 'missing-dossier'
                            for row in queue['items']))

    def test_evaluate_blocks_unknown_eligibility(self):
        result = competition.evaluate(self.store, {'grant_id': self.grant_id,
                                      'profile': {}, 'candidates': [self.candidate('one'), self.candidate('two')]})
        self.assertEqual(result['shortlist'], [])
        self.assertTrue(all('eligibility_not_confirmed' in row['hard_blocks'] for row in result['candidates']))
