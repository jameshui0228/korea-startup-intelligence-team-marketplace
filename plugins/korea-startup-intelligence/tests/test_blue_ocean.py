import json
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ksi_lib import blue_ocean
from ksi_lib.model import Store, init_workspace, now, observation, stamp


class BlueOceanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "state"
        init_workspace(self.workspace)
        self.store = Store(self.workspace)
        self.row = observation(
            "google_news_rss", "article", "care-work", "돌봄기관 업무 변화 관측",
            "https://example.com/care-work", stamp(now() - timedelta(days=1)),
            collection_basis="public_source_verified",
        )
        with self.store.db:
            self.store.put_observation(self.row)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def payload(self):
        return {
            "key": "care-handoff-gap",
            "title": "돌봄기관 인수인계 공백 후보",
            "domain_ids": ["KR-180"],
            "customer": "소규모 돌봄기관 교대 관리자",
            "problem": "교대 시 확인해야 할 업무가 누락될 수 있다는 탐색 가설",
            "payer": "기관 운영자라는 가설이며 예산 미확인",
            "current_workaround": "종이·메신저·구두 인계를 병행한다는 가설",
            "why_now": "인력 부족과 기록 요구 증가가 동시에 나타나는지 확인 필요",
            "korea_gap": "한국 기관의 실제 대안과 전환 이유 미확인",
            "smallest_wedge": "민감정보 없이 누락 여부만 확인하는 수동 체크",
            "business_models": ["기관별 수동 운영 대행", "검증 후 업무 도구 구독"],
            "evidence_ids": [self.row["id"]],
            "dossier_id": None,
            "stage": "detected",
            "assessments": {},
            "signal_profile": {},
            "alternatives": [],
            "next_action": {
                "hypothesis": "기관이 인계 누락에 반복 비용을 쓰고 있다",
                "action": "공개 자료에서 현재 업무 흐름과 비용 단서를 조사한다",
                "pass_condition": "서로 다른 실제 고객 자료 2개에서 반복 업무와 손실을 확인",
                "stop_condition": "반복 문제나 현재 해결 행동을 찾지 못함",
                "due_at": stamp(now() + timedelta(days=7)),
                "estimated_cost_krw": 0,
                "external_action_required": False,
            },
            "stop_condition": "고객 문제와 현재 지출을 확인하지 못하면 폐기",
            "reopen_condition": "새 규제 또는 실제 고객 자료가 생기면 재검토",
            "review_after": stamp(now() + timedelta(days=7)),
            "expected_revision": 0,
        }

    def test_unknown_candidate_is_not_called_blue_ocean(self):
        result = blue_ocean.save(self.store, self.payload())
        self.assertEqual(result["assessment"]["whitespace_state"], "unproven")
        self.assertFalse(result["assessment"]["blue_ocean_proven"])
        self.assertIn("current_workaround_not_compared", result["assessment"]["blocking_gaps"])

    def test_metadata_only_claims_do_not_become_evidence_backed(self):
        payload = self.payload()
        payload["assessments"] = {key: {"status": "FACT", "conclusion": "본문 검토 전 주장",
                                                 "evidence_ids": [self.row["id"]]}
                                  for key in ("problem", "current_spend", "supply_gap")}
        result = blue_ocean.save(self.store, payload)
        self.assertEqual(result["assessment"]["evidence_backed_assessments"], [])
        self.assertEqual(result["assessment"]["whitespace_state"], "unproven")

    def test_revision_required_and_stage_cannot_bypass_transition(self):
        blue_ocean.save(self.store, self.payload())
        changed = self.payload()
        changed["title"] += " 수정"
        with self.assertRaises(ValueError):
            blue_ocean.save(self.store, changed)
        changed["expected_revision"] = 1
        changed["stage"] = "validating"
        with self.assertRaises(ValueError):
            blue_ocean.save(self.store, changed)

    def test_validation_transition_is_gated(self):
        blue_ocean.save(self.store, self.payload())
        transition = {"candidate_id": "blue-ocean-care-handoff-gap", "to_stage": "validating",
                      "reason": "검증 시작", "evidence_ids": [], "expected_revision": 1}
        with self.assertRaises(ValueError):
            blue_ocean.transition(self.store, transition)

    def test_watch_transition_and_event_history(self):
        blue_ocean.save(self.store, self.payload())
        result = blue_ocean.transition(self.store, {
            "candidate_id": "care-handoff-gap", "to_stage": "watching", "reason": "신호 반복 여부 관찰",
            "evidence_ids": [], "expected_revision": 1,
            "review_after": stamp(now() + timedelta(days=14)),
        })
        self.assertEqual(result["event"]["to_stage"], "watching")
        self.assertEqual(len(self.store.records("blue_ocean_event")), 1)
        self.assertEqual(self.store.records("blue_ocean")[0]["stage"], "watching")

    def test_next_and_brief_are_personal_portfolio_views(self):
        blue_ocean.save(self.store, self.payload())
        work = blue_ocean.next_actions(self.store)
        self.assertEqual(work["items"][0]["candidate_id"], "blue-ocean-care-handoff-gap")
        self.assertIn("성공 가능성", work["ordering"])
        report = blue_ocean.brief(self.store)
        self.assertTrue(Path(report["report_path"]).is_file())
        self.assertEqual(report["portfolio_size"], 1)

    def test_cli_prepare_and_template_hide_no_api_dependency(self):
        cli = ROOT / "scripts" / "ksi.py"
        prepared = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace),
                                   "blue-ocean", "prepare", "--limit", "2"], capture_output=True, text=True)
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertFalse(json.loads(prepared.stdout)["api_key_required"])
        templated = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace),
                                    "blue-ocean", "template"], capture_output=True, text=True)
        self.assertEqual(templated.returncode, 0, templated.stderr)
        self.assertIn("counterevidence", json.loads(templated.stdout)["assessments"])

    def test_advanced_stage_cannot_be_created_directly(self):
        payload = self.payload()
        payload["stage"] = "building"
        with self.assertRaises(ValueError):
            blue_ocean.save(self.store, payload)


if __name__ == "__main__":
    unittest.main()
