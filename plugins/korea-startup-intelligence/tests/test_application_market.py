"""Key-free workflows with synthetic fixtures; no grant or customer claims."""
import copy
import json
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import test_radar as fixtures
import test_research as grant_fixtures
from ksi_lib import application, grants, market, research
from ksi_lib.model import now, observation, stamp


class ApplicationMarketTest(unittest.TestCase):
    setUp = fixtures.RadarTest.setUp
    tearDown = fixtures.RadarTest.tearDown
    source = fixtures.RadarTest.source
    make_dossier = fixtures.RadarTest.make_dossier
    notice = grant_fixtures.GrantsTest.notice
    profile = grant_fixtures.GrantsTest.profile

    def draft(self, with_notice=True):
        gid = None
        if with_notice:
            notice = self.notice()
            notice["evaluation_criteria"] = [{"criterion": "Fixture execution", "weight": 30, "locator": "Fixture page"}]
            gid = grants.save_notice(self.store, notice)["id"]
        return application.prepare(self.store, self.dossier_id, gid)["input_template"]

    def filled(self):
        draft = self.draft()
        draft["profile"] = self.profile()
        p = {"text": "Synthetic proposed action, not an observed customer result", "status": "ASSUMPTION", "evidence_ids": [], "founder_fact_ids": []}
        draft["sections"] = {k: [copy.deepcopy(p)] for k in application.SECTIONS}
        draft["criterion_mapping"][0].update(section_ids=["execution"], rationale="Fixture mapping, not a real evaluation")
        draft["budget"] = {"items": [{"name": "Fixture materials", "quantity": 2, "unit_cost_krw": 1000,
                                     "total_krw": 2000, "basis": "Fixture assumption, no purchase"}],
                           "requested_krw": 1500, "own_krw": 500, "basis": "Test only, not a real program budget"}
        draft["milestones"] = [{"start_week": 1, "end_week": 2, "deliverable": "Fixture only", "measurement": "Fixture counter",
                                 "pass_condition": "Fixture criterion", "stop_condition": "Fixture stop"}]
        draft["pitch"] = [{"title": "Fixture slide " + str(i), "answer": copy.deepcopy(p)} for i in range(5)]
        draft["judge_qa"] = [{"question": "Fixture question " + str(i), "answer": copy.deepcopy(p)} for i in range(5)]
        draft["attachments"] = [{"name": "Test-only appendix", "status": "prepared", "basis": "Synthetic fixture assertion"}]
        draft["final_checks"] = {k: {"checked": True, "note": "Synthetic manual review assertion; not a real submission"} for k in application.FINAL_CHECKS}
        return draft

    def test_prepare_is_not_a_completed_business_plan(self):
        draft = application.prepare(self.store, self.dossier_id)
        self.assertEqual(draft["mode"], "no_additional_api_key_required")
        self.assertEqual(self.store.records("application"), [])
        self.assertEqual(set(draft["input_template"]["sections"]), set(application.SECTIONS))
        self.assertEqual(draft["input_template"]["pitch"], [])

    def test_no_keys_credentials_network_or_telegram_needed(self):
        with patch.dict("os.environ", {}, clear=True), \
                patch("ksi_lib.model.credentials", side_effect=AssertionError("Do not ask for keys")), \
                patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Do not call network")), \
                patch("ksi_lib.telegram.api", side_effect=AssertionError("Do not send Telegram")):
            draft = self.filled()
            result = application.save(self.store, draft)
            report = application.check(self.store, result["id"])
            overview = market.overview(self.store, limit=400)
            plan = research.research_plan(self.store)
        self.assertEqual(report["readiness"], "ready_for_human_submission_review")
        self.assertIsNone(report["selection_probability"])
        self.assertFalse(report["automatic_submission"])
        self.assertEqual(overview["returned_domains"], 400)
        self.assertEqual(len(plan["tasks"]), 6)

    def test_missing_notice_remains_working_draft_not_ineligible(self):
        result = application.save(self.store, self.draft(with_notice=False))
        self.assertIn("no_target_notice", result["audit"]["gaps"])
        self.assertIsNone(result["audit"]["eligibility"])
        self.assertTrue(Path(result["report_path"]).is_file())

    def test_full_package_renders_actual_components(self):
        result = application.save(self.store, self.filled())
        rendered = Path(result["report_path"]).read_text()
        for expected in ("Synthetic proposed action", "Fixture materials", "Fixture slide", "Fixture question", "Test-only appendix"):
            self.assertIn(expected, rendered)
        self.assertEqual(application.save(self.store, self.store_payload(result["id"]))["status"], "unchanged")

    def store_payload(self, record_id):
        data = next(d for d in self.store.records("application") if d["id"] == record_id)
        return {**data, "key": record_id.removeprefix("application-")}

    def test_budget_arithmetic_errors_are_rejected(self):
        base = self.filled()
        for mutate in (lambda d: d["budget"]["items"][0].update(total_krw=3000),
                       lambda d: d["budget"].update(own_krw=1000),
                       lambda d: d["budget"].update(requested_krw=True),
                       lambda d: d["budget"]["items"][0].update(quantity=0)):
            value = copy.deepcopy(base)
            mutate(value)
            with self.assertRaises(ValueError):
                application.save(self.store, value)
        self.assertEqual(self.store.records("application"), [])

    def test_unbacked_fact_rejected_and_assumption_not_promoted(self):
        draft = self.filled()
        draft["sections"]["market"][0]["status"] = "FACT"
        with self.assertRaises(ValueError):
            application.save(self.store, draft)
        draft["sections"]["market"][0]["status"] = "ASSUMPTION"
        application.save(self.store, draft)
        self.assertEqual(self.store.records("application")[0]["sections"]["market"][0]["status"], "ASSUMPTION")

    def test_founder_facts_need_real_user_confirmation_field(self):
        draft = self.filled()
        draft["founder_facts"] = {"team-fit": {"statement": "Synthetic team fact", "status": "guessed", "basis": "Fixture"}}
        with self.assertRaises(ValueError):
            application.save(self.store, draft)
        draft["founder_facts"]["team-fit"]["status"] = "user_confirmed"
        draft["sections"]["team"] = [{"text": "Synthetic declared fact", "status": "FACT", "evidence_ids": [], "founder_fact_ids": ["team-fit"]}]
        application.save(self.store, draft)

    def test_private_identifier_profile_rejected(self):
        draft = self.filled()
        draft["profile"]["bank_account"] = {"value": "fixture", "status": "confirmed"}
        with self.assertRaises(ValueError):
            application.save(self.store, draft)

    def test_invented_official_criterion_rejected(self):
        draft = self.filled()
        draft["criterion_mapping"][0]["criterion"] = "Invented criterion"
        with self.assertRaises(ValueError):
            application.save(self.store, draft)

    def test_missing_official_mapping_is_visible(self):
        draft = self.filled()
        draft["criterion_mapping"] = []
        result = application.save(self.store, draft)
        self.assertIn("unmapped_criterion:Fixture execution", result["audit"]["gaps"])

    def test_profile_failure_not_offset_by_good_paperwork(self):
        draft = self.filled()
        draft["profile"] = self.profile(value=7)
        result = application.save(self.store, draft)
        self.assertEqual(result["audit"]["readiness"], "working_draft")
        self.assertEqual(result["audit"]["eligibility"]["eligibility"], "INELIGIBLE_BY_RECORDED_RULE")

    def test_notice_revision_forces_recheck(self):
        result = application.save(self.store, self.filled())
        notice = self.store.records("grant")[0]
        notice["notice_version"] = "Fixture amendment"
        with self.store.db:
            self.store.record("grant", notice)
        self.assertIn("notice_changed", application.check(self.store, result["id"])["gaps"])

    def test_rejected_dossier_does_not_become_ready(self):
        result = application.save(self.store, self.filled())
        dossier = self.store.records("dossier")[0]
        dossier["decision"] = "reject"
        with self.store.db:
            self.store.record("dossier", dossier)
        self.assertIn("dossier_decision:reject", application.check(self.store, result["id"])["gaps"])

    def test_unknowns_and_missing_final_checks_remain_visible(self):
        draft = self.filled()
        draft["sections"]["team"][0]["status"] = "UNKNOWN"
        draft["attachments"][0]["status"] = "missing"
        draft["final_checks"] = {}
        result = application.save(self.store, draft)
        for expected in ("unresolved_section:team", "missing_attachments", "manual_check_pending:truthfulness"):
            self.assertIn(expected, result["audit"]["gaps"])

    def test_substantive_reviews_and_taxonomy_not_confused(self):
        result = market.overview(self.store, limit=400)
        found = next(d for d in result["domains"] if d["domain_id"] == self.domain)
        self.assertEqual(found["substantive_source_reviews"], 2)
        self.assertEqual(found["recorded_results"], 0)
        self.assertEqual(result["matched_status_counts"]["unexplored"], 399)
        self.assertTrue(all(d["trend_stage"] == "not_inferred_from_metadata" for d in result["domains"]))

    def test_unassigned_signal_not_smeared_across_all_markets(self):
        row = observation("github_new", "repo", "unassigned", "Fictional multiuse tool", "https://example.com/new", stamp())
        with self.store.db:
            self.store.put_observation(row)
        result = market.overview(self.store, limit=400)
        self.assertEqual(result["unassigned_source_observations"], 1)
        self.assertEqual(sum(d["early_source_observations"] for d in result["domains"]), 0)

    def test_old_background_and_future_dates_not_recent_changes(self):
        for suffix, dt in (("old", now() - timedelta(days=30)), ("future", now() + timedelta(days=1))):
            row = observation("github_new", "repo", "fixture", "Fictional dated source", "https://example.com/" + suffix,
                              stamp(dt), domain_ids=[self.domain])
            with self.store.db:
                self.store.put_observation(row)
        result = market.overview(self.store, query=self.domain)["domains"][0]
        self.assertEqual(result["linked_sources"], 4)
        self.assertEqual(result["recent_14d_sources"], 2)

    def test_invalid_limit_and_unknown_application(self):
        for limit in (0, 401, True):
            with self.assertRaises(ValueError):
                market.overview(self.store, limit=limit)
        with self.assertRaises(ValueError):
            application.check(self.store, "missing")

    def test_cli_no_key_market_and_application_prepare(self):
        cli = Path(__file__).resolve().parents[1] / "scripts/ksi.py"
        for tail in (("market-map", "--limit", "400"), ("application", "prepare", "--dossier-id", self.dossier_id)):
            output = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace), *tail],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(output.returncode, 0, output.stderr)
            json.loads(output.stdout)


if __name__ == "__main__":
    unittest.main()
