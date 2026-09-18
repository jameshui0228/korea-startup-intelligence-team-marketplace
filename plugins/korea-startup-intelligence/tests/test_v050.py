"""Integration checks for the v0.5 discovery-to-execution path."""
import fcntl
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ksi_lib import blue_ocean, founder_ops, signal_intake, venture_intelligence, venture_ops
from ksi_lib.model import Store, init_workspace, now, observation, stamp


class VentureIntelligenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "state"
        init_workspace(self.workspace)
        self.store = Store(self.workspace)
        self.evidence = observation("manual", "manual_evidence", "돌봄 업무", "돌봄 업무 문제 메모",
                                    "https://example.com/one", stamp(now() - timedelta(days=1)),
                                    collection_basis="user_owned")
        with self.store.db:
            self.store.put_observation(self.evidence)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def candidate(self, key="care-gap"):
        return {"key": key, "title": "돌봄 기록 후보", "domain_ids": ["KR-180"],
                "customer": "소규모 돌봄 기관", "problem": "교대 돌봄 기록 누락 문제",
                "payer": "기관 운영자", "current_workaround": "수기 기록", "why_now": "업무량 변화",
                "korea_gap": "한국 대안 조사 필요", "smallest_wedge": "수동 기록 점검",
                "business_models": ["운영 대행"], "evidence_ids": [self.evidence["id"]],
                "dossier_id": None, "stage": "detected", "assessments": {}, "signal_profile": {},
                "alternatives": [], "next_action": {"hypothesis": "누락이 반복된다", "action": "업무 기록 검토",
                "pass_condition": "반복 사례 확인", "stop_condition": "반복 사례 없음",
                "due_at": stamp(now() + timedelta(days=7)), "estimated_cost_krw": 0,
                "external_action_required": False}, "stop_condition": "반복 문제 부재",
                "reopen_condition": "새 고객 자료", "review_after": stamp(now() + timedelta(days=7)),
                "expected_revision": 0}

    def add_candidate(self, key="care-gap"):
        return blue_ocean.save(self.store, self.candidate(key))["id"]

    def test_prepare_collects_by_default_and_can_skip_network(self):
        with patch("ksi_lib.engine.refresh", return_value={"status": "ok", "requests_made": 2}) as collect:
            result = blue_ocean.prepare(self.store, limit=2)
        self.assertEqual(result["collection"]["requests_made"], 2)
        collect.assert_called_once()
        with patch("ksi_lib.engine.refresh") as collect:
            result = blue_ocean.prepare(self.store, limit=2, no_refresh=True)
        collect.assert_not_called()
        self.assertEqual(result["collection"]["status"], "not_refreshed")

    def test_reassessment_preview_does_not_write_and_apply_does(self):
        self.add_candidate()
        before = len(self.store.records("blue_ocean_assessment"))
        preview = blue_ocean.reassess_all(self.store)
        self.assertTrue(preview["changes"])
        self.assertEqual(len(self.store.records("blue_ocean_assessment")), before)
        blue_ocean.reassess_all(self.store, apply=True)
        self.assertEqual(len(self.store.records("blue_ocean_assessment")), 1)
        self.assertTrue(blue_ocean.history(self.store, "care-gap")["causal_changes"])

    def test_signal_import_records_review_and_graph_without_api(self):
        signal = {
            "source": "jobs", "kind": "job", "topic": "돌봄 업무", "title": "돌봄 기록 담당 채용",
            "url": "https://example.com/job/1", "event_at": stamp(now() - timedelta(hours=1)),
            "geography": "KR", "domain_ids": ["KR-180"], "read_scope": "relevant_sections",
            "summary": "채용 공고의 담당 업무 부분에 돌봄 기록 정리 업무가 기재되어 있다.",
            "origin_group": "example-employer", "origin_note": "고용주 원 공고", "reviewer": "test",
            "collection_basis": "public_source_verified", "limitations": ["한 채용 공고"],
            "demand_or_supply": "context"}
        result = signal_intake.import_signal(self.store, signal)
        self.assertFalse(result["direct_api_collected"])
        self.assertEqual(len(self.store.observations()), 2)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM source_reviews").fetchone()[0], 1)
        graph = venture_intelligence.signal_graph(self.store)
        self.assertEqual(graph["observation_count"], 2)
        self.assertEqual(graph["clusters"][0]["gap_status"], "unresolved")
        self.assertEqual(signal_intake.import_signal(self.store, signal)["status"], "unchanged")

    def test_search_attention_is_not_customer_demand_or_a_market_gap(self):
        for index in (1, 2):
            row = observation("google_trends_rss", "search_spike", "돌봄 업무", f"검색 관심 {index}",
                              f"https://example.com/search/{index}", stamp(now() - timedelta(days=index)),
                              metrics={"retention_rate": 0.8})
            with self.store.db:
                self.store.put_observation(row)
        cluster = venture_intelligence.signal_graph(self.store)["clusters"][0]
        self.assertEqual(cluster["gap_status"], "proxy_only")
        self.assertEqual(cluster["behavioral_demand_origins"], 0)
        self.assertIn("demand_proxy_without_customer_behavior", cluster["manipulation_risks"])
        self.assertNotIn("low_baseline", cluster["manipulation_risks"])

    def test_market_gap_requires_distinct_behavior_origins_days_and_supply_sample(self):
        for index in (1, 2):
            row = observation("manual", "customer_observation", "돌봄 업무", f"반복 누락 {index}",
                              f"https://example.com/customer/{index}", stamp(now() - timedelta(days=index)),
                              collection_basis="user_owned", origin_key=f"customer-{index}")
            with self.store.db:
                self.store.put_observation(row)
        graph = venture_intelligence.signal_graph(self.store)
        cluster = graph["clusters"][0]
        self.assertEqual(cluster["gap_status"], "supply_audit_needed")
        product = observation("manual", "product", "돌봄 업무", "돌봄 기록 제품",
                              "https://example.com/product", stamp(now() - timedelta(days=1)),
                              origin_key="provider-one")
        with self.store.db:
            self.store.put_observation(product)
        cluster = venture_intelligence.signal_graph(self.store)["clusters"][0]
        self.assertEqual(cluster["behavioral_demand_origins"], 2)
        self.assertEqual(cluster["market_supply_origins"], 1)
        self.assertEqual(cluster["gap_status"], "comparison_design_needed")
        self.assertEqual(cluster["comparison_basis"], "unmatched_raw_observation_counts_not_market_gap")
        patterns = venture_intelligence.opportunity_patterns(self.store)
        self.assertEqual(patterns["demand_supply_gaps"], [])
        self.assertEqual(len(patterns["gap_investigations"]), 1)

    def test_unknown_founder_fit_is_not_pareto_frontier(self):
        self.add_candidate()
        decisions = venture_intelligence.portfolio_decisions(self.store, blue_ocean.assess)
        self.assertEqual(decisions["pareto_frontier"], [])
        self.assertEqual(len(decisions["comparison_pending"]), 1)
        self.assertIn("founder_fit", decisions["items"][0]["unknown_dimensions"])
        self.assertEqual(decisions["items"][0]["comparison_status"], "incomplete")

    def test_structured_conditions_apply_time_window_and_evidence_kind(self):
        candidate = self.candidate()
        recent = observation("manual", "transaction", "돌봄 업무", "최근 결제",
                             "https://example.com/recent-payment", stamp(now() - timedelta(days=2)),
                             collection_basis="user_owned")
        old = observation("manual", "transaction", "돌봄 업무", "과거 결제",
                          "https://example.com/old-payment", stamp(now() - timedelta(days=40)),
                          collection_basis="user_owned")
        with self.store.db:
            self.store.put_observation(recent)
            self.store.put_observation(old)
        candidate["evidence_ids"] = [self.evidence["id"], recent["id"], old["id"]]
        blue_ocean.save(self.store, candidate)
        candidate = self.store.records("blue_ocean")[0]
        rules = venture_intelligence.validate_condition_set([{
            "field": "transaction_count", "operator": "gte", "value": 1,
            "window_days": 7, "evidence_kinds": ["transaction"],
        }], "stop_rules")
        result = venture_intelligence.evaluate_conditions(self.store, candidate, rules)
        self.assertTrue(result["matched"])
        self.assertEqual(result["results"][0]["actual"], 1)
        self.assertEqual(result["results"][0]["evaluated_evidence_ids"], [recent["id"]])
        with self.assertRaises(ValueError):
            venture_intelligence.validate_condition_set([{
                "field": "competitor_count", "operator": "gte", "value": 1, "window_days": 7,
            }], "stop_rules")

    def test_multiword_glossary_aliases_share_one_signal_cluster(self):
        with self.store.db:
            self.store.record("wb_glossary", {"id": "wb-glossary-care", "term": "돌봄 기록",
                                               "meaning": "돌봄 업무 기록", "aliases": ["케어 로그"],
                                               "excluded_meanings": [], "query_precision": None})
            self.store.put_observation(observation("manual", "manual_evidence", "케어 로그 자동화",
                                                   "케어 로그", "https://example.com/care-log",
                                                   stamp(now() - timedelta(days=2))))
            self.store.put_observation(observation("manual", "manual_evidence", "돌봄 기록 자동화",
                                                   "돌봄 기록", "https://example.com/care-record",
                                                   stamp(now() - timedelta(days=1))))
        cluster = next(row for row in venture_intelligence.signal_graph(self.store)["clusters"]
                       if "케어 로그 자동화" in row["topics"])
        self.assertEqual(cluster["topics"], ["돌봄 기록 자동화", "케어 로그 자동화"])

    def test_explicit_same_basis_demand_supply_series_needs_three_periods(self):
        for period, demand, supply in (("2026-06", 10, 9), ("2026-07", 14, 10), ("2026-08", 20, 11)):
            for role, value, origin in (("demand", demand, "customer-panel"),
                                        ("supply", supply, "product-panel")):
                row = observation("manual", "aggregate_metric", "돌봄 업무", f"{period} {role}",
                                  f"https://example.com/{role}/{period}", stamp(now() - timedelta(days=1)),
                                  collection_basis="authorized_export", origin_key=origin,
                                  demand_or_supply=role, comparison_key="care-requests-v-products",
                                  metrics={"value": value}, measurement={"definition": role + " count",
                                  "unit": "count", "population": "same sampled institutions",
                                  "period": period, "normalization": "per 100 institutions", "vintage": "2026-09"})
                with self.store.db:
                    self.store.put_observation(row)
        cluster = venture_intelligence.signal_graph(self.store)["clusters"][0]
        self.assertEqual(cluster["gap_status"], "comparable_series_observed")
        comparison = cluster["explicit_comparisons"][0]
        self.assertEqual(comparison["status"], "three_or_more_completed_periods")
        self.assertEqual(comparison["difference_change"], 8)
        self.assertEqual(len(venture_intelligence.opportunity_patterns(self.store)["measured_comparisons"]), 1)

    def test_signal_intake_comparison_key_requires_measured_role(self):
        payload = {
            "source": "kosis", "kind": "aggregate_metric", "topic": "돌봄 업무",
            "title": "돌봄 요청 수", "url": "https://example.com/stat/1",
            "event_at": stamp(now() - timedelta(days=1)), "geography": "KR", "domain_ids": [],
            "read_scope": "relevant_sections", "summary": "공식 표에서 요청 수 항목을 확인했다.",
            "origin_group": "official-table-demand", "origin_note": "공식 통계표", "reviewer": "test",
            "collection_basis": "public_source_verified", "limitations": ["표본 통계"],
            "metrics": {"value": 20}, "measurement": {"definition": "월 요청 수", "unit": "count",
            "population": "sample institutions", "period": "2026-08", "normalization": "per 100",
            "vintage": "2026-09"}, "demand_or_supply": "demand", "comparison_key": "care-gap",
        }
        result = signal_intake.import_signal(self.store, payload)
        self.assertEqual(result["status"], "reviewed_signal_saved")
        saved = next(row for row in self.store.observations() if row["id"] == result["evidence_id"])
        self.assertEqual(saved["comparison_key"], "care-gap")
        payload["demand_or_supply"] = "context"
        with self.assertRaises(ValueError):
            signal_intake.import_signal(self.store, payload)

    def test_public_comment_counts_as_behavior_only_when_customer_role_attested(self):
        base = {"source": "reddit", "kind": "comment", "topic": "야간 돌봄 인수인계",
                "event_at": stamp(now() - timedelta(days=1)), "geography": "KR", "domain_ids": [],
                "read_scope": "relevant_sections", "origin_note": "공개 댓글", "reviewer": "test",
                "collection_basis": "public_source_verified", "limitations": ["자기선택 표본"],
                "metrics": {}, "measurement": None, "demand_or_supply": "demand"}
        unknown = {**base, "title": "댓글 1", "url": "https://www.reddit.com/r/test/comments/abc/comment1",
                   "summary": "작성자 역할을 확인하지 못한 불편 언급이다.", "origin_group": "thread-one"}
        signal_intake.import_signal(self.store, unknown)
        first = next(row for row in venture_intelligence.signal_graph(self.store)["clusters"]
                     if "야간 돌봄 인수인계" in row["topics"])
        self.assertEqual(first["behavioral_demand_origins"], 0)
        customer = {**base, "title": "댓글 2", "url": "https://www.reddit.com/r/test/comments/def/comment2",
                    "summary": "실제 이용자가 반복 인수인계 누락을 자기 경험으로 설명했다.",
                    "origin_group": "thread-two", "speaker_role": "customer"}
        signal_intake.import_signal(self.store, customer)
        second = next(row for row in venture_intelligence.signal_graph(self.store)["clusters"]
                      if "야간 돌봄 인수인계" in row["topics"])
        self.assertEqual(second["behavioral_demand_origins"], 1)

    def test_semantic_duplicate_and_filter_and_metrics_have_denominators(self):
        self.add_candidate()
        other = self.candidate("care-gap-two")
        other["expected_revision"] = 0
        blue_ocean.save(self.store, other)
        self.assertTrue(blue_ocean.status(self.store)["duplicate_warnings"])
        self.assertEqual(len(venture_intelligence.filter_candidates(self.store, stages=["detected"],
                                                                       max_budget=0)), 2)
        metrics = venture_intelligence.performance_metrics(self.store)
        self.assertEqual(metrics["problem_confirmation_denominator"], 2)
        self.assertIsNone(metrics["false_positive_rate"])
        self.assertIsNone(metrics["time_saved_minutes"])

    def test_execution_package_tasks_and_external_action_gate(self):
        candidate_id = self.add_candidate()
        package = venture_ops.execution_package(self.store, candidate_id, apply=True)
        self.assertEqual(len(package["tasks"]), 4)
        self.assertEqual(len(venture_ops.task_board(self.store)["tasks"]), 4)
        action = venture_ops.save_action(self.store, {"key": "interview-1", "candidate_id": candidate_id,
            "title": "고객 인터뷰 연락", "authorization_scope": "한 명에게 연락",
            "budget_cap_krw": 0, "due_at": stamp(now() + timedelta(days=7))})
        with self.assertRaises(ValueError):
            venture_ops.transition_action(self.store, {"action_id": action["id"], "to_state": "approved",
                "reason": "임의 승인", "user_confirmed": False})
        approved = venture_ops.transition_action(self.store, {"action_id": action["id"],
            "to_state": "approved", "reason": "사용자 확인", "user_confirmed": True})
        self.assertEqual(approved["event"]["to_state"], "approved")
        self.assertFalse(approved["event"]["external_action_executed_by_plugin"])

    def test_monthly_plan_needs_explicit_monthly_limits(self):
        self.add_candidate()
        self.assertEqual(venture_ops.monthly_plan(self.store)["status"], "setup_required")
        profile = founder_ops.template("profile")
        profile.update({"weekly_hours_available": 8, "weekly_budget_krw": 100000,
            "cash_budget_krw": 1000000, "protected_reserve_krw": 200000,
            "risk_boundary": "보호 예비금 불가"})
        founder_ops.configure(self.store, profile)
        self.assertEqual(venture_ops.monthly_plan(self.store)["status"], "setup_required")
        profile["expected_revision"] = 1
        profile["monthly_hours_available"] = 32
        profile["monthly_budget_krw"] = 400000
        founder_ops.configure(self.store, profile)
        self.assertEqual(venture_ops.monthly_plan(self.store)["status"], "planned")

    def test_read_only_cli_works_while_writer_lock_held(self):
        self.add_candidate()
        cli = ROOT / "scripts" / "ksi.py"
        with (self.workspace / ".run.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace),
                "blue-ocean", "metrics"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace),
                "operator", "overview"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_read_only_status_does_not_migrate_config_or_open_database_for_writes(self):
        self.add_candidate()
        config_path = self.workspace / "config.json"
        config = json.loads(config_path.read_text())
        config.pop("signal_intake_lanes", None)
        config_path.write_text(json.dumps(config, ensure_ascii=False))
        before = config_path.read_bytes()
        reader = Store(self.workspace, read_only=True)
        try:
            self.assertEqual(reader.db.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                reader.db.execute("CREATE TABLE unexpected_write(id INTEGER)")
        finally:
            reader.close()
        cli = ROOT / "scripts" / "ksi.py"
        result = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace),
            "blue-ocean", "metrics"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
