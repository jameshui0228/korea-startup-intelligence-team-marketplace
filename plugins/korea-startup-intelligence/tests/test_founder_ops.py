import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from ksi_lib import blue_ocean, founder_ops
from ksi_lib.model import Store, init_workspace, now, observation, stamp


class FounderOperationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "state"
        init_workspace(self.workspace)
        self.store = Store(self.workspace)
        self.evidence = observation(
            "manual", "manual_evidence", "operations", "허용된 시장 조사 기록",
            "https://example.com/founder-ops", stamp(now() - timedelta(days=1)),
            collection_basis="user_owned",
        )
        with self.store.db:
            self.store.put_observation(self.evidence)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def candidate_payload(self, key="first-venture"):
        return {
            "key": key, "title": key + " 후보", "domain_ids": ["KR-180"],
            "customer": "접근 가능한 소규모 사업자", "problem": "반복 업무 문제 가설",
            "payer": "사업자", "current_workaround": "수작업", "why_now": "운영 비용 변화",
            "korea_gap": "한국 대안 검토 중", "smallest_wedge": "수동 검증",
            "business_models": ["운영 대행"], "evidence_ids": [self.evidence["id"]], "dossier_id": None,
            "stage": "detected", "assessments": {}, "signal_profile": {}, "alternatives": [],
            "next_action": {"hypothesis": "반복 문제가 있다", "action": "문제 자료를 검토한다",
                            "pass_condition": "반복 문제 확인", "stop_condition": "문제 없음",
                            "due_at": stamp(now() + timedelta(days=14)), "estimated_cost_krw": 0,
                            "external_action_required": False},
            "stop_condition": "핵심 문제 부재", "reopen_condition": "새 고객 또는 거래 근거",
            "review_after": stamp(now() + timedelta(days=14)), "expected_revision": 0,
        }

    def add_candidate(self, key="first-venture"):
        blue_ocean.save(self.store, self.candidate_payload(key))
        return "blue-ocean-" + key

    def profile(self, priorities=None, hours=12, budget=100000, discovery=2):
        return {
            "weekly_hours_available": hours, "weekly_budget_krw": budget,
            "cash_budget_krw": 3000000, "protected_reserve_krw": 1000000,
            "wip_limits": {"discovery": discovery, "validation": 1, "build": 1, "growth": 1},
            "max_total_active": 3, "stale_after_days": 21,
            "policies": {"auto_park_overflow": True, "auto_park_stale": True,
                         "auto_park_founder_misfit": True, "auto_kill_on_stop": True,
                         "auto_reopen_wip": True, "auto_reopen_on_evidence": True,
                         "auto_advance_gated_stages": True},
            "priority_order": priorities or [], "skills": ["고객 인터뷰"],
            "customer_access": ["소규모 사업자"], "constraints": ["1인 운영"],
            "excluded_industries": [], "risk_boundary": "보호 예비금은 사용하지 않는다",
            "expected_revision": 0,
        }

    def fit(self, candidate_id, hours=4, weekly=20000, initial=100000):
        return {"candidate_id": candidate_id,
                "dimensions": {name: {"status": "ALIGNED", "rationale": "사용자가 확인한 실행 조건",
                                      "basis": "user_confirmed"} for name in founder_ops.FIT_DIMENSIONS},
                "weekly_hours_required": hours, "weekly_budget_required_krw": weekly,
                "initial_budget_required_krw": initial, "constraints": [], "expected_revision": 0}

    def pipeline(self, candidate_id, hours=4, budget=20000, tracks=None):
        return {"candidate_id": candidate_id, "weekly_hours_estimate": hours, "weekly_budget_krw": budget,
                "tracks": tracks or {name: {"plan_ids": [], "depends_on": founder_ops.DEFAULT_DEPENDENCIES[name]}
                                      for name in founder_ops.TRACKS},
                "expected_revision": 0}

    def test_founder_fit_keeps_dimensions_and_capacity_conflicts_visible(self):
        candidate_id = self.add_candidate()
        founder_ops.configure(self.store, self.profile([candidate_id], hours=5, budget=30000))
        result = founder_ops.save_fit(self.store, self.fit(candidate_id, hours=8, weekly=40000, initial=2500000))
        self.assertEqual(result["assessment"]["decision"], "misaligned")
        self.assertEqual(set(result["assessment"]["capacity_conflicts"]), {
            "weekly_hours_exceed_founder_capacity", "weekly_budget_exceeds_limit",
            "initial_budget_invades_protected_reserve"})
        self.assertNotIn("score", result["assessment"])

    def test_capacity_wip_auto_parks_and_reopens_without_external_action(self):
        first, second = self.add_candidate("first-venture"), self.add_candidate("second-venture")
        founder_ops.configure(self.store, self.profile([first, second], discovery=1))
        for candidate_id in (first, second):
            founder_ops.save_fit(self.store, self.fit(candidate_id))
            founder_ops.save_pipeline(self.store, self.pipeline(candidate_id))
        plan = founder_ops.capacity_plan(self.store)
        self.assertEqual([item["candidate_id"] for item in plan["focus"]], [first])
        self.assertEqual([item["candidate_id"] for item in plan["overflow"]], [second])
        applied = founder_ops.reconcile(self.store, apply=True)
        self.assertTrue(any(item["candidate_id"] == second and item["type"] == "park" and item["status"] == "applied"
                            for item in applied["results"]))
        self.assertEqual(blue_ocean.status(self.store, second)["candidates"][0]["candidate"]["stage"], "parked")
        no_slot = founder_ops.reconcile(self.store, apply=False)
        self.assertFalse(any(item["candidate_id"] == second and item["type"] == "reopen" for item in no_slot["actions"]))
        current_revision = self.store.db.execute("SELECT revision FROM records WHERE kind='blue_ocean' AND id=?", (first,)).fetchone()[0]
        blue_ocean.transition(self.store, {"candidate_id": first, "to_stage": "killed", "reason": "집중 후보 종료",
                                           "evidence_ids": [], "expected_revision": current_revision})
        reopened = founder_ops.reconcile(self.store, apply=True)
        self.assertTrue(any(item["candidate_id"] == second and item["type"] == "reopen" and item["status"] == "applied"
                            for item in reopened["results"]))
        self.assertEqual(blue_ocean.status(self.store, second)["candidates"][0]["candidate"]["stage"], "detected")
        self.assertFalse(reopened["external_actions_executed"])

    def test_validation_pipeline_connects_interview_mvp_pricing_gtm(self):
        candidate_id = self.add_candidate()
        candidate = self.store.records("blue_ocean")[0]
        candidate["dossier_id"] = "dossier-fixture"
        with self.store.db:
            self.store.record("blue_ocean", candidate, 1)
            self.store.record("validation_plan", {"id": "validation-interview", "dossier_id": "dossier-fixture",
                              "starts_at": stamp(now() - timedelta(days=4)), "ends_at": stamp(now() - timedelta(days=2)),
                              "hypothesis": "반복 문제", "method": "인터뷰", "budget_krw": 0})
            self.store.record("validation_result", {"id": "validation-interview", "plan_id": "validation-interview",
                              "outcome": "criterion_met"})
            self.store.record("validation_plan", {"id": "validation-mvp", "dossier_id": "dossier-fixture",
                              "starts_at": stamp(now() + timedelta(days=1)), "ends_at": stamp(now() + timedelta(days=8)),
                              "hypothesis": "수동 MVP 사용", "method": "수동 MVP", "budget_krw": 50000})
        founder_ops.configure(self.store, self.profile([candidate_id]))
        tracks = {
            "interview": {"plan_ids": ["validation-interview"], "depends_on": []},
            "mvp": {"plan_ids": ["validation-mvp"], "depends_on": ["interview"]},
            "pricing": {"plan_ids": [], "depends_on": ["mvp"]},
            "gtm": {"plan_ids": [], "depends_on": ["pricing"]},
        }
        result = founder_ops.save_pipeline(self.store, self.pipeline(candidate_id, tracks=tracks))
        states = result["pipeline"]["tracks"]
        self.assertEqual(states["interview"]["state"], "passed")
        self.assertEqual(states["mvp"]["state"], "planned")
        self.assertEqual(states["pricing"]["state"], "blocked")
        self.assertEqual(result["pipeline"]["next_track"], "mvp")

    def test_prespecified_stop_result_auto_kills_but_does_not_execute_externally(self):
        candidate_id = self.add_candidate()
        candidate = self.store.records("blue_ocean")[0]
        candidate["dossier_id"] = "dossier-stop"
        with self.store.db:
            self.store.record("blue_ocean", candidate, 1)
            self.store.record("validation_plan", {"id": "validation-stop", "dossier_id": "dossier-stop",
                              "starts_at": stamp(now() - timedelta(days=4)), "ends_at": stamp(now() - timedelta(days=2)),
                              "hypothesis": "문제 반복", "method": "고객 관측", "budget_krw": 0})
            self.store.record("validation_result", {"id": "validation-stop", "plan_id": "validation-stop",
                              "outcome": "stop_criterion_met"})
        founder_ops.configure(self.store, self.profile([candidate_id]))
        tracks = {name: {"plan_ids": ["validation-stop"] if name == "interview" else [],
                         "depends_on": founder_ops.DEFAULT_DEPENDENCIES[name]} for name in founder_ops.TRACKS}
        founder_ops.save_pipeline(self.store, self.pipeline(candidate_id, tracks=tracks))
        result = founder_ops.reconcile(self.store, apply=True)
        self.assertTrue(any(item["candidate_id"] == candidate_id and item["type"] == "kill" and item["status"] == "applied"
                            for item in result["results"]))
        self.assertEqual(next(c["stage"] for c in self.store.records("blue_ocean") if c["id"] == candidate_id), "killed")
        self.assertFalse(result["external_actions_executed"])

    def test_post_launch_kpi_snapshot_requires_owned_measurement(self):
        candidate_id = self.add_candidate()
        candidate = self.store.records("blue_ocean")[0]
        candidate["stage"] = "launched"
        with self.store.db:
            self.store.record("blue_ocean", candidate, 1)
        plan = founder_ops.save_kpi_plan(self.store, {"key": "weekly-core", "candidate_id": candidate_id,
            "cadence": "weekly", "metrics": [{"key": "revenue", "name": "주간 매출",
                "definition": "해당 주 결제 완료 매출", "unit": "KRW", "direction": "higher",
                "target": 100000, "floor": 20000}]})
        measured = observation("manual", "aggregate_metric", "kpi", "주간 매출 집계",
                               "https://example.com/owned-kpi", stamp(now() - timedelta(hours=2)),
                               collection_basis="user_owned")
        with self.store.db:
            self.store.put_observation(measured)
        result = founder_ops.save_kpi_snapshot(self.store, {"plan_id": plan["id"], "week_start": "2026-09-14",
            "values": {"revenue": 120000}, "evidence_ids": [measured["id"]],
            "summary": "허용된 결제 집계 기준", "limitations": ["환불 반영 전"]})
        self.assertEqual(result["record"]["judgements"]["revenue"], "on_target")
        replay = founder_ops.save_kpi_snapshot(self.store, {"plan_id": plan["id"], "week_start": "2026-09-14",
            "values": {"revenue": 120000}, "evidence_ids": [measured["id"]],
            "summary": "허용된 결제 집계 기준", "limitations": ["환불 반영 전"]})
        self.assertEqual(replay["status"], "unchanged")

    def test_weekly_ceo_brief_combines_resources_checkin_and_decisions(self):
        candidate_id = self.add_candidate()
        founder_ops.configure(self.store, self.profile([candidate_id]))
        founder_ops.save_fit(self.store, self.fit(candidate_id))
        founder_ops.save_pipeline(self.store, self.pipeline(candidate_id))
        founder_ops.save_checkin(self.store, {"week_start": "2026-09-14", "summary": "첫 운영 주간",
            "items": [{"candidate_id": candidate_id, "hours_spent": 3, "spend_krw": 10000,
                       "accomplishments": ["문제 인터뷰 계획 정리"], "blockers": ["표본 접근 경로 확인 필요"],
                       "decision": "continue", "evidence_ids": [], "note": "외부 연락은 아직 실행하지 않음"}]})
        result = founder_ops.weekly_brief(self.store, "2026-09-14", apply=False)
        self.assertTrue(Path(result["report_path"]).is_file())
        self.assertEqual(result["checkin"]["total_hours"], 3)
        self.assertEqual(result["capacity"]["allocation"]["hours_planned"], 4)
        self.assertFalse(result["reconciliation"]["external_actions_executed"])


if __name__ == "__main__":
    unittest.main()
