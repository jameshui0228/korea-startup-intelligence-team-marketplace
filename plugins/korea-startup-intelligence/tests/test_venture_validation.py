"""Local synthetic trials only; never send, recruit or populate user state."""
import copy
import json
import subprocess
import sys
import unittest
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import test_radar as fixtures
from ksi_lib import radar, research, validation, venture
from ksi_lib.model import now, parse_date, stamp
from verify_intelligence import verify


class VentureValidationTest(unittest.TestCase):
    setUp = fixtures.RadarTest.setUp
    tearDown = fixtures.RadarTest.tearDown
    source = fixtures.RadarTest.source
    make_dossier = fixtures.RadarTest.make_dossier
    card = fixtures.RadarTest.card

    @contextmanager
    def at(self, instant):
        with patch("ksi_lib.validation.now", return_value=instant), \
                patch("ksi_lib.model.now", return_value=instant), \
                patch("ksi_lib.radar.now", return_value=instant):
            yield

    def review(self):
        data = venture.prepare(self.store, self.dossier_id)["input_template"]
        data["six_questions"]["workaround"] = {"status": "INFERENCE", "conclusion": "Test-only workflow hypothesis",
                                               "evidence_ids": self.eids}
        return data

    def plan_input(self, key="fixture-trial"):
        start = parse_date(stamp()) + timedelta(minutes=5)
        return {"key": key, "dossier_id": self.dossier_id, "hypothesis": "Synthetic trial, not real customer data",
                "method": "Fixture only", "population": "Fixture population", "recruitment": "No actual recruitment",
                "collection_plan": "Fixture counts", "safety_stop": "No external actions permitted",
                "starts_at": stamp(start), "ends_at": stamp(start + timedelta(days=1)), "budget_krw": 0,
                "evidence_ids": self.eids,
                "metric": {"definition": "Successful fictional observations / all fictional observations",
                    "aggregation": "rate", "unit": "fraction", "direction": "higher",
                    "min_sample": 10, "pass_threshold": .6, "stop_threshold": .2}}

    def result_input(self, plan):
        p = plan["record"]
        middle = parse_date(p["starts_at"]) + timedelta(hours=1)
        eid = radar.review_source(self.store, {"topic": "Fixture trial only", "title": "Fictional aggregate, not customer data",
            "url": "https://example.com/fixture-measurement/" + p["id"], "event_at": stamp(middle),
            "read_scope": "relevant_sections", "family": "customer", "summary": "Synthetic result used solely for unit tests",
            "origin_group": "fixture-owned", "origin_note": "Not a real export", "reviewer": "unit-test",
            "collection_basis": "user_owned", "limitations": ["Synthetic fixture"]})["evidence_id"]
        return {"plan_id": plan["id"], "execution_status": "completed", "summary": "Test-only outcome",
                "counterevidence": "Four of ten fixture units did not pass", "limitations": ["Synthetic test"],
                "cost_krw": 0, "data_quality_issues": [],
                "measurement": {"numerator": 6, "denominator": 10, "unit": "fraction",
                    "collected_from": p["starts_at"], "collected_to": p["ends_at"]},
                "evidence_links": [{"evidence_id": eid, "basis": "aggregate_measurement", "locator": "Fixture aggregate",
                                    "note": "Not real customer data"}]}

    def qualitative_plan_input(self, key="fixture-qualitative"):
        start = parse_date(stamp()) + timedelta(minutes=5)
        return {"key": key, "dossier_id": self.dossier_id, "hypothesis": "반복 수작업이 전환 이유인지 확인",
                "method": "사전 질문 순서로 최근 실제 사례를 회고", "population": "가상 적격 사례",
                "recruitment": "테스트 픽스처; 실제 모집 없음", "collection_plan": "사례별 익명 기록",
                "safety_stop": "개인정보가 나오면 기록 중단", "starts_at": stamp(start),
                "ends_at": stamp(start + timedelta(days=1)), "budget_krw": 0, "evidence_ids": self.eids,
                "decision_rule": {"unit_of_analysis": "익명 사례", "minimum_eligible_cases": 2,
                    "pass_patterns": [{"code": "repeated-workaround", "description": "반복 수작업 사례",
                                       "minimum_cases": 2}],
                    "stop_patterns": [{"code": "no-problem", "description": "문제 경험 없음",
                                       "minimum_cases": 2}],
                    "coding_protocol": "사전 코드만 사용하고 애매하면 코드 없음으로 기록",
                    "require_negative_case": True}}

    def qualitative_result_input(self, plan):
        rows = []
        middle = parse_date(plan["record"]["starts_at"]) + timedelta(hours=1)
        for index in range(3):
            eid = radar.review_source(self.store, {"topic": "Fixture qualitative", "title": "익명 사례 " + str(index),
                "url": "https://example.com/fixture-qualitative/" + str(index), "event_at": stamp(middle),
                "read_scope": "relevant_sections", "family": "customer", "summary": "합성 정성 사례",
                "origin_group": "fixture-case-" + str(index), "origin_note": "테스트 전용",
                "reviewer": "unit-test", "collection_basis": "user_owned", "limitations": ["Synthetic fixture"]})["evidence_id"]
            rows.append({"case_id": "case-" + str(index), "eligible": True, "negative_case": index == 2,
                         "observed_codes": ["repeated-workaround"] if index < 2 else [],
                         "evidence_links": [{"evidence_id": eid, "basis": "direct_customer",
                                             "locator": "합성 사례", "note": "테스트 전용 관측"}]})
        return {"plan_id": plan["id"], "execution_status": "completed", "summary": "합성 정성 결과",
                "counterevidence": "한 건은 반복 문제를 확인하지 못함", "limitations": ["Synthetic test"],
                "cost_krw": 0, "data_quality_issues": [], "cases": rows}

    def test_review_draft_does_not_persist(self):
        draft = venture.prepare(self.store, self.dossier_id)
        self.assertIn("draft", draft["status"])
        self.assertEqual(self.store.records("venture_review"), [])
        self.assertEqual(set(draft["input_template"]["six_questions"]), set(venture.QUESTIONS))

    def test_stage_priorities_change_questions_not_evidence(self):
        for stage, priorities in venture.STAGE_PRIORITIES.items():
            with self.subTest(stage=stage):
                draft = venture.prepare(self.store, self.dossier_id, stage)
                self.assertEqual(draft["diagnostic"]["priority_questions"], list(priorities))
                self.assertEqual(set(draft["diagnostic"]["next_questions"]), set(venture.QUESTIONS))
                self.assertTrue(all(a["status"] == "UNKNOWN" for a in draft["input_template"]["six_questions"].values()))
        self.assertEqual(self.store.records("venture_review"), [])

    def test_stage_prepare_reuses_current_answers_and_reject_decision(self):
        review = self.review()
        review.update(product_stage="users", decision="reject")
        venture.save(self.store, review)
        prepared = venture.prepare(self.store, self.dossier_id)
        self.assertEqual(prepared["input_template"]["decision"], "reject")
        self.assertEqual(prepared["diagnostic"]["product_stage"], "users")
        self.assertEqual(prepared["diagnostic"]["reused_current_answers"], ["workaround"])
        self.assertNotIn("workaround", prepared["diagnostic"]["next_questions"])
        self.assertEqual(venture.save(self.store, prepared["input_template"])["status"], "unchanged")

    def test_stage_prepare_does_not_reuse_stale_answers(self):
        review = self.review()
        review["decision"] = "reject"
        venture.save(self.store, review)
        dossier = self.store.records("dossier")[0]
        dossier["target"] += " revised context"
        with self.store.db:
            self.store.record("dossier", dossier)
        prepared = venture.prepare(self.store, self.dossier_id)
        self.assertFalse(prepared["prior_review"]["current"])
        self.assertEqual(prepared["diagnostic"]["reused_current_answers"], [])
        self.assertIn("workaround", prepared["diagnostic"]["next_questions"])
        self.assertEqual(prepared["input_template"]["decision"], "reject")

    def test_stage_declaration_does_not_establish_customer_validation(self):
        review = self.review()
        review["product_stage"] = "paying"
        result = venture.save(self.store, review)
        self.assertEqual(result["assessment"]["customer_validation"], "not_established_by_review")
        self.assertIn("demand", result["assessment"]["unverified_questions"])

    def test_invalid_stage_rejected_and_legacy_review_supported(self):
        for stage in ("profitable", [], None, 1):
            review = self.review()
            review["product_stage"] = stage
            with self.assertRaises(ValueError):
                venture.save(self.store, review)
        review = self.review()
        review.pop("product_stage")
        venture.save(self.store, review)
        self.assertEqual(venture.prepare(self.store, self.dossier_id)["diagnostic"]["product_stage"], "unknown")

    def test_stage_cli_prepare(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scripts/ksi.py"),
            "--workspace", str(self.workspace), "venture-review", "prepare", "--dossier-id", self.dossier_id,
            "--stage", "users"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["diagnostic"]["priority_questions"][0], "workaround")

    def test_review_save_replay_and_markdown(self):
        review = self.review()
        first = venture.save(self.store, review)
        self.assertTrue(first["assessment"]["current"])
        self.assertIn("demand", first["assessment"]["unverified_questions"])
        self.assertTrue(Path(first["report_path"]).is_file())
        self.assertEqual(venture.save(self.store, review)["status"], "unchanged")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM revisions WHERE kind='venture_review'").fetchone()[0], 1)

    def test_review_detects_same_second_dossier_change(self):
        venture.save(self.store, self.review())
        old = self.store.records("dossier")[0]
        old["target"] += " changed"
        with self.store.db:
            self.store.record("dossier", old)
        assessed = venture.status(self.store)["reviews"][0]
        self.assertFalse(assessed["current"])
        self.assertIn("dossier_changed_since_review", assessed["gaps"])

    def test_review_requires_all_questions_and_status_quo(self):
        for mutate in (lambda r: r["six_questions"].pop("demand"),
                       lambda r: r["alternatives"][0].update(kind="expanded"),
                       lambda r: r["alternatives"][1].update(kind="status_quo")):
            r = self.review()
            mutate(r)
            with self.assertRaises(ValueError):
                venture.save(self.store, r)

    def test_review_rejects_fact_without_substantive_dossier_evidence(self):
        for ids in ([], ["missing"], [self.source("external")]):
            r = self.review()
            r["six_questions"]["demand"].update(status="FACT", evidence_ids=ids)
            with self.assertRaises(ValueError):
                venture.save(self.store, r)
        with self.assertRaises(ValueError):
            venture.save(self.store, [])

    def test_review_changed_source_becomes_stale(self):
        venture.save(self.store, self.review())
        row = next(r for r in self.store.observations() if r["id"] == self.eids[0])
        row["title"] = "Changed original content metadata"
        with self.store.db:
            self.store.put_observation(row)
        self.assertFalse(venture.status(self.store)["reviews"][0]["current"])

    def test_negative_review_blocks_eligible_card_without_changing_dossier(self):
        self.assertTrue(research.opportunity_gate(self.store, self.card())["eligible"])
        r = self.review()
        r["decision"] = "reject"
        venture.save(self.store, r)
        gate = research.opportunity_gate(self.store, self.card())
        self.assertIn("venture_decision:reject", gate["reasons"])
        self.assertEqual(self.store.records("dossier")[0]["decision"], "research")

    def test_review_in_research_plan_and_report(self):
        venture.save(self.store, self.review())
        follow = research.research_plan(self.store)["tasks"][0]
        self.assertEqual(follow["venture_review"]["dossier_id"], self.dossier_id)
        research.report(self.store)
        report = json.loads((self.workspace / "reports/radar-daily.json").read_text())
        self.assertEqual(len(report["venture_reviews"]["reviews"]), 1)
        self.assertEqual(report["validation"]["registered"], 0)

    def test_plan_is_prespecified_immutable_and_idempotent(self):
        payload = self.plan_input()
        created = validation.plan(self.store, payload)
        self.assertEqual(created["status"], "registered_not_executed")
        self.assertEqual(validation.plan(self.store, payload)["status"], "unchanged")
        payload["metric"]["pass_threshold"] = .5
        with self.assertRaises(ValueError):
            validation.plan(self.store, payload)
        self.assertEqual(self.store.records("validation_result"), [])

    def test_qualitative_plan_and_result_preserve_cases_and_negative_evidence(self):
        plan = validation.qualitative_plan(self.store, self.qualitative_plan_input())
        self.assertEqual(plan["record"]["method_type"], "qualitative")
        with self.at(parse_date(plan["record"]["ends_at"]) + timedelta(seconds=1)):
            payload = self.qualitative_result_input(plan)
            saved = validation.qualitative_result(self.store, payload)
            self.assertEqual(saved["record"]["outcome"], "criterion_met")
            self.assertEqual(saved["record"]["measurement"]["eligible_cases"], 3)
            self.assertTrue(any(case["negative_case"] for case in saved["record"]["cases"]))
            self.assertEqual(validation.qualitative_result(self.store, payload)["status"], "unchanged")
        self.assertEqual(validation.status(self.store)["experiments"][0]["method_type"], "qualitative")

    def test_qualitative_result_cannot_reuse_one_record_as_two_cases(self):
        plan = validation.qualitative_plan(self.store, self.qualitative_plan_input("fixture-qual-duplicate"))
        with self.at(parse_date(plan["record"]["ends_at"]) + timedelta(seconds=1)):
            payload = self.qualitative_result_input(plan)
            payload["cases"][1]["evidence_links"] = copy.deepcopy(payload["cases"][0]["evidence_links"])
            with self.assertRaises(ValueError):
                validation.qualitative_result(self.store, payload)

    def test_plan_cannot_be_registered_after_start(self):
        payload = self.plan_input()
        payload["starts_at"] = stamp(now() - timedelta(hours=1))
        with self.assertRaises(ValueError):
            validation.plan(self.store, payload)

    def test_plan_requires_timezone_and_ordered_thresholds(self):
        mutations = [lambda p: p.update(starts_at="2026-10-01"),
                     lambda p: p["metric"].update(pass_threshold=.1),
                     lambda p: p["metric"].update(pass_threshold=60),
                     lambda p: p["metric"].update(unit="percent"),
                     lambda p: p["metric"].update(min_sample=True),
                     lambda p: p["metric"].update(pass_threshold=float("nan")),
                     lambda p: p["metric"].update(pass_threshold=10**400),
                     lambda p: p.update(budget_krw=-1)]
        for mutate in mutations:
            payload = self.plan_input()
            mutate(payload)
            with self.assertRaises(ValueError):
                validation.plan(self.store, payload)

    def test_amendment_is_separate_linked_plan_not_overwrite(self):
        first = validation.plan(self.store, self.plan_input())
        payload = self.plan_input("fixture-trial-revised")
        payload["replaces_plan_id"] = first["id"]
        validation.plan(self.store, payload)
        self.assertEqual(validation.status(self.store)["registered"], 2)

    def test_result_computes_outcome_and_does_not_support_idea(self):
        plan = validation.plan(self.store, self.plan_input())
        with self.at(parse_date(plan["record"]["ends_at"]) + timedelta(seconds=1)):
            payload = self.result_input(plan)
            saved = validation.result(self.store, payload)
            self.assertEqual(saved["record"]["outcome"], "criterion_met")
            self.assertEqual(saved["record"]["measurement"]["value"], .6)
            self.assertEqual(validation.result(self.store, payload)["status"], "unchanged")
            self.assertEqual(validation.status(self.store)["resolved"], 1)
        self.assertEqual(self.store.records("idea"), [])

    def test_result_immutable_after_recording(self):
        plan = validation.plan(self.store, self.plan_input())
        with self.at(parse_date(plan["record"]["ends_at"]) + timedelta(seconds=1)):
            payload = self.result_input(plan)
            validation.result(self.store, payload)
            payload["measurement"]["numerator"] = 9
            with self.assertRaises(ValueError):
                validation.result(self.store, payload)

    def test_results_before_deadline_rejected(self):
        plan = validation.plan(self.store, self.plan_input())
        with self.at(parse_date(plan["record"]["ends_at"]) - timedelta(seconds=1)):
            payload = self.result_input(plan)
            with self.assertRaises(ValueError):
                validation.result(self.store, payload)

    def test_small_sample_partial_period_and_quality_issues_inconclusive(self):
        for index, mutate in enumerate((lambda r: r["measurement"].update(numerator=6, denominator=6),
                                      lambda r: r.update(data_quality_issues=["Selection bias in fixture"]),
                                      lambda r: r["measurement"].update(collected_from=stamp(parse_date(r["measurement"]["collected_from"]) + timedelta(minutes=1))))):
            plan = validation.plan(self.store, self.plan_input("trial-gap-" + str(index)))
            with self.at(parse_date(plan["record"]["ends_at"]) + timedelta(seconds=1)):
                payload = self.result_input(plan)
                mutate(payload)
                self.assertEqual(validation.result(self.store, payload)["record"]["outcome"], "inconclusive")

    def test_failure_and_not_run_retained_in_denominator(self):
        failed = validation.plan(self.store, self.plan_input("fixture-failed"))
        skipped = validation.plan(self.store, self.plan_input("fixture-skipped"))
        with self.at(parse_date(skipped["record"]["ends_at"]) + timedelta(seconds=2)):
            payload = self.result_input(failed)
            payload["measurement"]["numerator"] = 1
            validation.result(self.store, payload)
            validation.result(self.store, {"plan_id": skipped["id"], "execution_status": "not_run",
                "summary": "Never ran", "counterevidence": "No observations", "limitations": ["Not run"], "cost_krw": 0})
            state = validation.status(self.store)
        self.assertEqual(state["registered"], 2)
        self.assertEqual(state["outcome_counts"]["stop_criterion_met"], 1)
        self.assertEqual(state["outcome_counts"]["not_run"], 1)

    def test_public_article_cannot_be_customer_experiment_result(self):
        plan = validation.plan(self.store, self.plan_input())
        with self.at(parse_date(plan["record"]["ends_at"]) + timedelta(seconds=1)):
            payload = self.result_input(plan)
            eid = payload["evidence_links"][0]["evidence_id"]
            row = self.store.db.execute("SELECT data FROM source_reviews WHERE evidence_id=?", (eid,)).fetchone()
            review = json.loads(row[0])
            review["collection_basis"] = "public_source_verified"
            with self.store.db:
                self.store.db.execute("UPDATE source_reviews SET data=? WHERE evidence_id=?", (json.dumps(review), eid))
            with self.assertRaises(ValueError):
                validation.result(self.store, payload)

    def test_bad_units_denominators_basis_and_missing_measurement_rejected(self):
        plan = validation.plan(self.store, self.plan_input())
        with self.at(parse_date(plan["record"]["ends_at"]) + timedelta(seconds=1)):
            base = self.result_input(plan)
            mutations = (lambda p: p["measurement"].update(unit="percent"),
                         lambda p: p["measurement"].update(denominator=0),
                         lambda p: p["measurement"].update(numerator=11),
                         lambda p: p["measurement"].update(numerator=float("inf")),
                         lambda p: p["evidence_links"][0].update(basis="provider_claim"),
                         lambda p: p.update(execution_status="not_run"),
                         lambda p: p.pop("measurement"),
                         lambda p: p.update(evidence_links=[]))
            for mutate in mutations:
                payload = copy.deepcopy(base)
                mutate(payload)
                with self.assertRaises(ValueError):
                    validation.result(self.store, payload)

    def test_lower_mean_and_overdue_result_followup(self):
        payload = self.plan_input()
        payload["metric"].update(aggregation="mean", unit="minutes", direction="lower", pass_threshold=5, stop_threshold=10)
        plan = validation.plan(self.store, payload)
        with self.at(parse_date(plan["record"]["ends_at"]) + timedelta(seconds=1)):
            task = research.research_plan(self.store)["tasks"][0]
            self.assertEqual(task["kind"], "record_due_result")
            result = self.result_input(plan)
            result["measurement"].update(numerator=40, unit="minutes")
            saved = validation.result(self.store, result)
            self.assertEqual(saved["record"]["outcome"], "criterion_met")

    def test_legacy_notes_not_counted_as_trials(self):
        with self.store.db:
            self.store.record("experiment", {"id": "legacy-fixture", "status": "complete"})
        state = validation.status(self.store)
        self.assertEqual(state["registered"], 0)
        self.assertEqual(state["legacy_unvalidated_notes"], 1)

    def test_evidence_expiry_keeps_historical_result_but_requires_recheck(self):
        plan = validation.plan(self.store, self.plan_input())
        end = parse_date(plan["record"]["ends_at"])
        with self.at(end + timedelta(seconds=1)):
            payload = self.result_input(plan)
            validation.result(self.store, payload)
        with self.at(end + timedelta(days=30)):
            state = validation.status(self.store)
            self.assertEqual(state["experiments"][0]["evidence_status"], "stale_changed_or_unavailable")
            self.assertEqual(state["outcome_counts"]["criterion_met"], 1)
            self.assertEqual(validation.result(self.store, payload)["status"], "unchanged")

    def test_read_only_snapshot_never_advances_real_research_queue(self):
        original = self.store.db.execute("SELECT COUNT(*) FROM radar_runs").fetchone()[0]
        original_applications = self.store.records("application")
        receipt = verify(self.workspace)
        self.assertEqual(receipt["network_calls"], 0)
        self.assertEqual(receipt["telegram_calls"], 0)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM radar_runs").fetchone()[0], original)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM radar_topic_queue").fetchone()[0], 0)
        self.assertEqual(self.store.records("application"), original_applications)
        self.assertEqual(receipt["key_free_core"]["application_roundtrips"][0]["readiness"], "working_draft")

    def test_missing_dossier_and_non_objects_rejected(self):
        with self.assertRaises(ValueError):
            venture.prepare(self.store, "unknown")
        for method in (validation.plan, validation.result):
            with self.assertRaises(ValueError):
                method(self.store, [])
        with self.assertRaises(ValueError):
            validation.result(self.store, {"plan_id": "missing"})

    def test_experiment_correction_feedback_is_visible_in_status_and_next_work(self):
        plan = validation.plan(self.store, self.plan_input())
        with self.store.db:
            self.store.record("feedback", {"id": "fixture-correction", "subject_id": plan["id"],
                "outcome": "data_issue", "lesson": "Fixture measurement needs correction, not deletion", "evidence_ids": []})
        self.assertEqual(validation.status(self.store)["experiments"][0]["feedback"][0]["id"], "fixture-correction")
        self.assertEqual(research.research_plan(self.store)["tasks"][0]["feedback"][0]["id"], "fixture-correction")

    def test_cli_exposes_new_read_paths(self):
        cli = Path(__file__).resolve().parents[1] / "scripts/ksi.py"
        for command in (("venture-review", "status"), ("validation", "status"), ("list", "validation_result")):
            result = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace), *command],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
