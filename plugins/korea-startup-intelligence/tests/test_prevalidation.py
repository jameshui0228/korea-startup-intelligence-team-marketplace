"""Regression tests for progress before customer experiment data exists."""
import tempfile
import unittest
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ksi_lib import blue_ocean, prevalidation
from ksi_lib.model import Store, init_workspace, now, observation, stamp


class PrevalidationBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "state"
        init_workspace(self.workspace)
        self.store = Store(self.workspace)
        self.evidence = observation(
            "manual", "manual_evidence", "소규모 돌봄 기관", "공개 업무 설명 검토",
            "https://example.com/care-work", stamp(now() - timedelta(days=1)),
            collection_basis="user_owned",
        )
        with self.store.db:
            self.store.put_observation(self.evidence)
        payload = {
            "key": "care-zero-data", "title": "돌봄 인수인계 점검", "domain_ids": ["KR-180"],
            "customer": "소규모 돌봄 기관", "problem": "교대 때 기록이 누락되는 문제",
            "payer": "기관 운영자", "current_workaround": "수기와 메신저",
            "why_now": "업무 복잡도 증가", "korea_gap": "국내 대안 추가 조사 필요",
            "smallest_wedge": "기록 누락을 사람이 수동 점검", "business_models": ["운영 대행"],
            "evidence_ids": [self.evidence["id"]], "dossier_id": None, "stage": "detected",
            "assessments": {}, "signal_profile": {}, "alternatives": [],
            "next_action": {"hypothesis": "공개 자료만으로도 먼저 조사 순서를 정할 수 있다",
                            "action": "대안과 공개 가격을 조사한다", "pass_condition": "비교 가능한 대안 3개 확보",
                            "stop_condition": "실제 대안 원문을 찾지 못함",
                            "due_at": stamp(now() + timedelta(days=7)), "estimated_cost_krw": 0,
                            "external_action_required": False},
            "stop_condition": "반복 문제가 확인되지 않음", "reopen_condition": "새 고객 관측",
            "review_after": stamp(now() + timedelta(days=7)), "expected_revision": 0,
        }
        self.candidate_id = blue_ocean.save(self.store, payload)["id"]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_preview_requires_no_experiment_result_and_preserves_unknowns(self):
        result = prevalidation.bootstrap(self.store, self.candidate_id)
        package = result["items"][0]
        self.assertEqual(result["status"], "bootstrap_preview")
        self.assertEqual(package["experiment_data"]["state"], "no_experiment_data")
        self.assertEqual(package["claim_ceiling"]["decision_ceiling_without_results"], "researching")
        self.assertFalse(package["claim_ceiling"]["stage_transition_performed"])
        self.assertIn("problem", package["claim_ceiling"]["customer_validation_required"])
        self.assertIsNone(package["assumption_envelope"]["inputs"]["price_krw"])
        self.assertEqual(len(package["desk_research_tasks"]), 5)
        self.assertTrue(all(not row["external_action_required"] for row in package["desk_research_tasks"]))

    def test_apply_is_idempotent_and_does_not_fake_results_or_advance_stage(self):
        first = prevalidation.bootstrap(self.store, self.candidate_id, apply=True)
        self.assertEqual(first["status"], "bootstrap_saved")
        self.assertEqual(len(self.store.records("prevalidation_bootstrap")), 1)
        self.assertEqual(len(self.store.records("founder_task")), 5)
        self.assertEqual(self.store.records("blue_ocean")[0]["stage"], "detected")
        self.assertEqual(self.store.records("validation_result"), [])
        self.assertTrue(all(not row["external_action_required"] for row in self.store.records("founder_task")))

        second = prevalidation.bootstrap(self.store, self.candidate_id, apply=True)
        self.assertEqual(second["applied"][0]["record_status"], "unchanged")
        self.assertEqual(len(self.store.records("founder_task")), 5)
        revisions = self.store.db.execute(
            "SELECT COUNT(*) FROM revisions WHERE kind='prevalidation_bootstrap'"
        ).fetchone()[0]
        self.assertEqual(revisions, 1)

    def test_empty_portfolio_explains_minimum_nonexperimental_input(self):
        other_tmp = tempfile.TemporaryDirectory()
        try:
            workspace = Path(other_tmp.name) / "empty"
            init_workspace(workspace)
            store = Store(workspace)
            try:
                result = prevalidation.bootstrap(store)
            finally:
                store.close()
            self.assertEqual(result["status"], "candidate_required")
            self.assertIn("실험 데이터는 필요 없지만", result["boundary"])
        finally:
            other_tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
