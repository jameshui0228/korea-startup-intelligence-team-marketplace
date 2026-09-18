import json
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ksi_lib import frontier, radar
from ksi_lib.model import Store, init_workspace, now, observation, stamp


class FrontierDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "state"
        init_workspace(self.workspace)
        self.store = Store(self.workspace)
        self.rows = [
            observation("manual", "customer_observation", "산업 장비 부품",
                        "노후 장비의 단종 부품을 찾는 시간이 반복된다",
                        "https://example.com/customer-parts", stamp(now() - timedelta(days=4)),
                        collection_basis="user_owned", origin_key="customer-parts-one",
                        domain_ids=["KR-047"]),
            observation("regulation", "regulation", "산업 장비 부품",
                        "수리 가능성과 부품 정보 제공 규칙이 바뀐다",
                        "https://example.com/repair-rule", stamp(now() - timedelta(days=10)),
                        collection_basis="public_source_verified", origin_key="regulator-one",
                        domain_ids=["KR-047", "KR-036"]),
            observation("procurement", "procurement_award", "산업 장비 부품",
                        "공공 장비 유지보수 부품 계약이 발주됐다",
                        "https://example.com/procurement-parts", stamp(now() - timedelta(days=2)),
                        collection_basis="public_source_verified", origin_key="buyer-one",
                        domain_ids=["KR-047"]),
        ]
        with self.store.db:
            for row in self.rows:
                self.store.put_observation(row)
        radar.review_source(self.store, {
            "evidence_id": self.rows[1]["id"], "read_scope": "full_text",
            "family": "policy", "summary": "원문에서 수리·부품 정보 제공 변경을 확인했다.",
            "origin_group": "regulator-one", "origin_note": "규제 원문",
            "reviewer": "test", "collection_basis": "public_source_verified",
            "limitations": ["특정 제도 범위"],
        })

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def candidate(self, key, domain, archetype, structure, title, customer, change, insight):
        return {
            "key": key,
            "title": title,
            "customer": customer,
            "trigger_moment": "단종된 부품이 고장나 납품 기한 전에 대체 경로를 확정해야 하는 순간",
            "structural_change": change,
            "non_obvious_insight": insight,
            "solution": "재고를 무작정 보유하지 않고 진단·호환·납기 책임을 한 건의 결과로 묶는 수동 서비스",
            "business_structure": structure,
            "business_model": "호환 부품 확보 건당 검증 이용료와 긴급 납품 성과 수수료",
            "incumbent_disadvantage": "대형 부품사는 종류별 작은 수요와 책임을 감수하며 단종 장비까지 다루기 어렵다.",
            "korea_wedge": "한국의 중소 제조 집적지와 조달 납기, 장비별 책임 구조를 묶어 지역 단위로 시작한다.",
            "why_now": "최근 부품 정보 공개 범위 변경과 유지보수 계약 발주가 겹쳐 호환 확인 책임을 건별로 팔 시점인지 검토한다.",
            "horizon_months": 18,
            "archetype": archetype,
            "domain_ids": [domain],
            "evidence_ids": [row["id"] for row in self.rows],
            "counterevidence_ids": [self.rows[2]["id"]],
            "assumptions": ["단종 부품 확보 시간이 실제 납기 비용을 만든다."],
            "leading_indicator": "동일 장비군의 부품 탐색 요청과 긴급 구매 건수가 두 곳 이상에서 반복된다.",
            "falsifier": "사용 기업이 제조사 계약으로 납기 손실 없이 모두 해결하면 가설을 폐기한다.",
            "low_cost_probe": "노후 장비 10건의 공개 부품표와 중고 공급 가능성을 수동으로 맞춰 소요 시간을 기록한다.",
            "first_users": "산업단지 내 10년 이상 장비를 운영하는 소규모 제조사의 설비 보전 담당자",
        }

    def test_packet_forces_divergence_and_does_not_call_prompts_ideas(self):
        packet = frontier.frontier_packet(self.store, limit=30)
        self.assertEqual(len(packet["generation_prompts"]), 30)
        self.assertGreaterEqual(len({row["archetype"]["id"] for row in packet["generation_prompts"]}), 6)
        self.assertGreaterEqual(len({row["business_structure"] for row in packet["generation_prompts"]}), 5)
        self.assertIn("30→10→3", packet["boundary"].replace(" ", "") + packet["instruction"].replace(" ", ""))
        self.assertNotIn("검증된 아이디어", packet["mode"])
        self.assertEqual(packet["coverage"]["reviewed_recent_atoms_120d"], 1)
        self.assertEqual(packet["generation_prompts"][0]["source_domain"]["domain_id"], "KR-047")
        self.assertEqual(packet["generation_prompts"][0]["trend_anchor_status"], "reviewed_recent_original")

    def test_tournament_rejects_generic_ai_repackaging(self):
        strong_one = self.candidate(
            "parts-survival-pool", "KR-047", "reverse_trend", "verification_service",
            "단종 장비 부품 생존 보증 풀", "노후 장비를 유지하는 중소 제조사 설비 보전 담당자",
            "수리 가능성 규칙과 부품 정보 공개가 넓어지며 환경이 다른 장비 간 호환 조사 비용이 낮아진다.",
            "장비를 새로 파는 시장이 커질수록 반대로 단종 장비 유지 책임은 작은 공급사에게 집중된다.")
        strong_two = self.candidate(
            "hospital-cold-capacity", "KR-122", "capacity_market", "shared_infrastructure",
            "야간 의료 냉장 용량 예약권", "밤에 짧은 기간 냉장 공간이 필요한 소규모 진단 기관",
            "온도 센서 검증 비용이 낮아져 서로 다른 기관의 유휴 냉장 용량을 시간대별로 검증할 수 있게 된다.",
            "냉장고 공급을 늘리는 것보다 책임과 예약 순서를 표준화하는 것이 때문에 실제 유효 용량이 늘어난다.")
        generic = self.candidate(
            "generic-ai-platform", "KR-020", "workflow_unbundling", "workflow_tool",
            "AI 기반 통합 플랫폼", "모든 중소기업 업무 담당자",
            "디지털 전환이 늘어 여러 업무를 하나의 앱에서 관리할 수 있게 된다.",
            "혁신적인 AI 기반 통합 플랫폼이 때문에 모든 업무 효율이 높아진다.")
        generic["solution"] = "AI 기반 통합 플랫폼으로 모든 업무를 혁신적으로 관리하는 올인원 서비스"
        result = frontier.evaluate_tournament(self.store, {
            "batch_key": "test-frontier", "topic": "유휴 자원과 단종 시장",
            "candidates": [strong_one, strong_two, generic],
        })
        generic_eval = next(row for row in result["evaluations"] if row["candidate_id"] == "frontier-generic-ai-platform")
        self.assertEqual(generic_eval["tier"], "reject_generic")
        self.assertGreaterEqual(generic_eval["generic_phrase_hits"], 2)
        self.assertNotIn("frontier-generic-ai-platform", result["shortlist"])
        self.assertIn("raw_pool_below_30", result["diversity"]["quality_gaps"])

    def test_apply_preserves_all_outcomes_as_learning_denominator(self):
        rows = [
            self.candidate("parts-one", "KR-047", "reverse_trend", "verification_service",
                           "단종 부품 재공급 보증 계약", "중소 제조사 설비 보전과 긴급 구매 담당자",
                           "수리 규칙과 부품 정보 공개가 넓어져 이종 장비 간 호환 조사 비용이 낮아진다.",
                           "신제품 공급이 늘어날수록 반대로 단종 장비 유지 책임이 지역 수리사에게 집중된다."),
            self.candidate("parts-two", "KR-036", "trust_and_verification", "managed_service",
                           "수리 이력 책임 인수인계", "중고 장비를 도입하는 지역 유지보수 회사 품질 담당자",
                           "수리 이력 공개 범위가 넓어져 장비 상태와 책임 구간을 건별로 인계할 수 있게 된다.",
                           "부품 판매보다 수리 이력의 책임 단절이 때문에 거래 후 손실이 커진다는 가설을 검증한다."),
            self.candidate("parts-three", "KR-180", "coordination_failure", "outcome_pricing",
                           "부품 납기 실패 책임 대행", "여러 수리업체와 거래하는 소규모 제조사 구매 책임자",
                           "조달·재고·수리 상태가 서로 다른 시스템에 기록되며 납기 책임을 건별로 계약할 여지가 생겼다.",
                           "재고 부족이 아니라 책임 주체의 불일치 때문에 긴급 납기 비용이 발생한다는 반대 가설을 확인한다."),
        ]
        result = frontier.evaluate_tournament(self.store, {
            "batch_key": "saved-frontier", "topic": "산업 장비 수명 연장", "candidates": rows,
        }, apply=True)
        self.assertTrue(result["saved"])
        self.assertEqual(len(self.store.records("frontier_hypothesis")), 3)
        self.assertEqual(len(self.store.records("frontier_batch")), 1)
        self.assertEqual(frontier.saved_hypotheses(self.store)["count"], 3)

    def test_old_signal_does_not_become_current_trend_from_review_alone(self):
        old = observation("manual", "regulation", "설비 전환", "오래된 설비 교체 고시",
                          "https://example.com/old-rule", stamp(now() - timedelta(days=400)),
                          collection_basis="public_source_verified", origin_key="old-rule",
                          domain_ids=["KR-047"])
        with self.store.db:
            self.store.put_observation(old)
        radar.review_source(self.store, {
            "evidence_id": old["id"], "read_scope": "full_text", "family": "policy",
            "summary": "오래된 고시의 원문을 읽고 적용 범위를 확인했다.",
            "origin_group": "old-rule", "origin_note": "고시 원문", "reviewer": "test",
            "collection_basis": "public_source_verified", "limitations": ["현재 변화 근거 아님"],
        })
        candidate = self.candidate(
            "old-rule-hypothesis", "KR-047", "constraint_flip", "managed_service",
            "노후 설비의 유지 계약 재설계", "장비 교체를 미루는 지역 제조사의 설비 담당자",
            "기존 고시가 오래전에 시행되어 당시에는 새로운 유지 계약을 설계할 여지가 생겼다.",
            "변화가 이미 오래전에 일어났기 때문에 지금의 급성장 신호로 해석해서는 안 된다.")
        candidate["evidence_ids"] = [old["id"]]
        candidate["counterevidence_ids"] = []
        result = frontier.evaluate_tournament(self.store, {
            "batch_key": "old-signal-test", "candidates": [candidate, {
                **candidate, "key": "old-rule-variant", "title": "노후 설비의 다른 유지 계약"
            }, {
                **candidate, "key": "old-rule-third", "title": "노후 설비의 세 번째 계약"
            }],
        })
        row = next(item for item in result["evaluations"] if item["candidate_id"] == "frontier-old-rule-hypothesis")
        self.assertFalse(row["trend_dimensions"]["recent_signal_120d"])
        self.assertIn("no_reviewed_recent_original_120d", row["warnings"])
        self.assertNotEqual(row["tier"], "emerging_candidate")
        self.assertNotEqual(row["tier"], "executable_candidate")

    def test_review_older_than_fourteen_days_is_not_a_current_original(self):
        evidence_id = self.rows[1]["id"]
        with self.store.db:
            self.store.db.execute("UPDATE source_reviews SET reviewed_at=? WHERE evidence_id=?",
                                  (stamp(now() - timedelta(days=20)), evidence_id))
        packet = frontier.frontier_packet(self.store, limit=30)
        self.assertEqual(packet["coverage"]["reviewed_recent_mechanism_anchors_120d"], 0)
        self.assertTrue(all(prompt["trend_anchor_status"] == "unanchored_research_prompt"
                            for prompt in packet["generation_prompts"]))

    def test_cli_frontier_is_read_only_and_returns_thirty_prompts(self):
        cli = ROOT / "scripts" / "ksi.py"
        completed = subprocess.run([
            sys.executable, str(cli), "--workspace", str(self.workspace),
            "blue-ocean", "frontier", "--limit", "30",
        ], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(json.loads(completed.stdout)["generation_prompts"]), 30)


if __name__ == "__main__":
    unittest.main()
