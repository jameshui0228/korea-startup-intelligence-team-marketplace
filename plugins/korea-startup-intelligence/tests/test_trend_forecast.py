import json
from datetime import timedelta
from unittest.mock import patch

from test_radar import RadarTest
from ksi_lib import research_tools, trend_forecast
from ksi_lib.model import now, stamp


class TrendForecastTest(RadarTest):
    def payload(self, key='future-flow', evidence_ids=None):
        cutoff = now()
        evidence_ids = evidence_ids or self.eids
        return {'key': key, 'question': '30일 안에 테스트 지표가 기준을 넘는가',
                'domain_id': self.domain, 'stage': 'Emerging', 'cutoff': stamp(cutoff),
                'deadline': stamp(cutoff + timedelta(days=30)), 'probability': .7,
                'baseline_probability': .2, 'decision_threshold': .5,
                'detected_at': stamp(cutoff - timedelta(hours=2)),
                'evidence_ids': evidence_ids, 'counterevidence_ids': [self.counter],
                'counter_search': '성장하지 않은 사례와 계절성 반례를 별도 조사',
                'target': {'metric': '테스트 채택 기관 수', 'operator': 'gte', 'value': 10,
                           'unit': '기관', 'population': '합성 단위시험 모집단', 'geography': 'KR',
                           'observation_window': '등록 후 30일', 'source_plan': '동일 정의의 공식 집계 원문'},
                'leading_indicator_chain': [
                    {'signal': '공급 기술 등장', 'status': 'INFERENCE', 'evidence_ids': [evidence_ids[0]],
                     'expected_next': '초기 실무자 시험'},
                    {'signal': '사용 행동 노출', 'status': 'INFERENCE', 'evidence_ids': [evidence_ids[-1]],
                     'expected_next': '한국 기관 채택 기준 도달'}],
                'confounders': ['일회성 기사', '낮은 기저', '수집 정의 변경'],
                'review_schedule_days': 7}

    def setUp(self):
        super().setUp()
        self.counter = self.source('counter-trend', 'news', origin='counter-origin')

    def test_prepare_requires_independent_origins_and_does_not_forecast(self):
        result = trend_forecast.prepare(self.store, 5)
        signal = next(row for row in result['candidate_signals'] if row['topic'] == 'water test')
        self.assertTrue(signal['forecast_ready_structure'])
        self.assertGreaterEqual(len(signal['origin_groups']), 2)
        self.assertEqual(result['forecasts_created'], 0)

    def test_register_is_immutable_and_keeps_structural_gaps(self):
        saved = trend_forecast.register(self.store, self.payload())
        self.assertTrue(saved['notification_eligible'])
        self.assertEqual(saved['structural_gaps'], [])
        with self.assertRaises(ValueError):
            trend_forecast.register(self.store, self.payload())
        weak = self.payload('single-origin', [self.eids[0]])
        weak['leading_indicator_chain'][1]['evidence_ids'] = [self.eids[0]]
        saved_weak = trend_forecast.register(self.store, weak)
        self.assertFalse(saved_weak['notification_eligible'])
        self.assertIn('fewer_than_two_origin_groups', saved_weak['structural_gaps'])

    def test_resolve_after_deadline_scores_against_baseline_and_lead(self):
        forecast = trend_forecast.register(self.store, self.payload())
        deadline = trend_forecast.parse_date(forecast['deadline'])
        future = deadline + timedelta(days=1)
        review = json.loads(self.store.db.execute('SELECT data FROM source_reviews WHERE evidence_id=?',
                                                  (self.eids[0],)).fetchone()[0])
        review['reviewed_at'] = stamp(future)
        with self.store.db:
            self.store.db.execute('UPDATE source_reviews SET reviewed_at=?,data=? WHERE evidence_id=?',
                                  (stamp(future), json.dumps(review, ensure_ascii=False), self.eids[0]))
        result_payload = {'forecast_id': forecast['id'], 'state': 'completed', 'outcome': True,
                          'baseline_at': stamp(deadline - timedelta(days=2)),
                          'evidence_ids': [self.eids[0]], 'limitations': ['합성 판정 fixture']}
        with patch('ksi_lib.trend_forecast.now', return_value=future):
            result = trend_forecast.resolve(self.store, result_payload)
            report = trend_forecast.evaluate(self.store)
        self.assertAlmostEqual(result['brier'], .09)
        self.assertAlmostEqual(result['baseline_brier'], .64)
        self.assertGreater(result['lead_seconds'], 0)
        self.assertEqual(report['resolved_denominator'], 1)
        self.assertGreater(report['brier_improvement_vs_baseline'], 0)
        self.assertFalse(report['skill_claim_allowed'])
        with patch('ksi_lib.trend_forecast.now', return_value=future), self.assertRaises(ValueError):
            trend_forecast.resolve(self.store, result_payload)

    def test_early_resolution_and_future_cutoff_are_blocked(self):
        forecast = trend_forecast.register(self.store, self.payload())
        with self.assertRaises(ValueError):
            trend_forecast.resolve(self.store, {'forecast_id': forecast['id'], 'state': 'completed',
                'outcome': False, 'baseline_at': None, 'evidence_ids': [self.eids[0]], 'limitations': ['early']})
        bad = self.payload('future-cutoff')
        bad['cutoff'] = stamp(now() + timedelta(days=1))
        with self.assertRaises(ValueError):
            trend_forecast.register(self.store, bad)

    def test_review_due_forecast_enters_team_queue(self):
        forecast = trend_forecast.register(self.store, self.payload())
        review_time = trend_forecast.parse_date(forecast['next_review_at']) + timedelta(hours=1)
        with patch('ksi_lib.trend_forecast.now', return_value=review_time):
            pending = trend_forecast.status(self.store)['pending'][0]
            queue = research_tools.team_queue(self.store)
        self.assertEqual(pending['state'], 'review_due')
        self.assertTrue(any(row['lane'] == 'trend_forecast' and row['subject_id'] == forecast['id']
                            for row in queue['items']))
