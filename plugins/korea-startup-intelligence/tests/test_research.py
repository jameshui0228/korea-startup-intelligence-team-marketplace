import copy
import json
import unittest
from datetime import timedelta
from unittest.mock import Mock
from test_radar import RadarTest
from ksi_lib import research, research_tools, radar, telegram, grants
from ksi_lib.model import stamp, now


class ResearchTest(RadarTest):
    # Shared fixture methods only; inherit tests intentionally avoided below.
    def test_research_qa_exposes_independence_and_counterevidence_gaps(self):
        result = research_tools.research_qa(self.store)
        row = next(item for item in result['dossiers'] if item['dossier_id'] == self.dossier_id)
        self.assertEqual(row['independent_core_origin_count'], 1)
        self.assertEqual(row['contradicted_dimensions'], [])
        self.assertIn('independent_origin', {item['code'] for item in row['actions']})
        self.assertIn('counterevidence', {item['code'] for item in row['actions']})
        self.assertFalse(result['records_modified'])

    def test_team_queue_prioritizes_stale_research_without_fetching(self):
        with self.store.db:
            self.store.db.execute('UPDATE source_reviews SET reviewed_at=?',
                                  (stamp(now() - timedelta(days=20)),))
        result = research_tools.team_queue(self.store)
        self.assertTrue(any(item['lane'] == 'research_qa' and item['code'] == 'recheck_sources'
                            for item in result['items']))
        self.assertEqual(result['network_requests'], 0)
        self.assertFalse(result['external_actions_taken'])

    def test_old_card_cannot_bypass_new_gate(self):
        card = self.card()
        card.pop("dossier_id")
        card["notification_eligible"] = True
        result = radar.publish_card(self.store, card)
        self.assertFalse(result["notification_eligible"])
        self.bound()
        self.assertEqual(telegram.enqueue(self.store)["queued"], 0)

    def test_provider_marketing_does_not_count_as_customer_pain(self):
        data = copy.deepcopy(self.dossier_input)
        data["findings"]["problem_severity"]["links"][0]["basis"] = "provider_claim"
        result = research.save_dossier(self.store, data)
        self.assertFalse(result["ready_for_opportunity_alert"])
        self.assertIn("missing_customer_evidence:problem_severity", result["blocking_gaps"])

    def test_missing_willingness_to_pay_is_a_gap_not_high_score(self):
        data = copy.deepcopy(self.dossier_input)
        data["findings"].pop("willingness_to_pay")
        research.save_dossier(self.store, data)
        self.assertFalse(radar.validate_card(self.store, self.card())["notification_eligible"])
        saved = self.store.records("dossier")[0]
        self.assertEqual(len(saved["findings"]), 24)
        self.assertEqual(saved["findings"]["willingness_to_pay"]["status"], "UNKNOWN")

    def test_counterevidence_not_treated_as_support(self):
        data = copy.deepcopy(self.dossier_input)
        data["findings"]["willingness_to_pay"]["links"][0]["relation"] = "contradicts"
        result = research.save_dossier(self.store, data)
        self.assertFalse(result["ready_for_opportunity_alert"])
        edges = research.graph(self.store, self.dossier_id)["edges"]
        self.assertTrue(any(e["relation"] == "contradicts" for e in edges))

    def test_context_only_cannot_be_evidence_backed(self):
        data = copy.deepcopy(self.dossier_input)
        data["findings"]["problem_severity"]["links"][0]["relation"] = "context"
        with self.assertRaises(ValueError):
            research.save_dossier(self.store, data)

    def test_unread_source_cannot_support_dossier(self):
        eid = self.source("metadata", scope="metadata_only")
        data = copy.deepcopy(self.dossier_input)
        data["evidence_ids"] = self.eids + [eid]
        data["findings"]["problem_severity"]["links"][0]["evidence_id"] = eid
        with self.assertRaises(ValueError):
            research.save_dossier(self.store, data)

    def test_search_absence_without_domestic_alternative_stays_blocked(self):
        data = copy.deepcopy(self.dossier_input)
        data["competitors"] = []
        self.assertIn("missing_reviewed_korean_alternative", research.save_dossier(self.store, data)["blocking_gaps"])

    def test_foreign_only_search_does_not_pass_korea_gap(self):
        data = copy.deepcopy(self.dossier_input)
        data["search_audit"][0]["market"] = "US"
        self.assertFalse(research.save_dossier(self.store, data)["ready_for_opportunity_alert"])

    def test_reused_dossier_for_another_customer_blocked(self):
        card = self.card()
        card["target"] = "Another customer"
        self.assertFalse(radar.validate_card(self.store, card)["notification_eligible"])

    def test_card_cannot_omit_pain_evidence(self):
        third = self.source("other-product", "product")
        card = self.card()
        card["evidence_ids"] = [self.eids[0], third]
        card["change"]["evidence_ids"] = card["evidence_ids"]
        self.assertIn("card_omits_core_dossier_evidence", radar.validate_card(self.store, card)["quality_gate"]["reasons"])

    def test_rejected_dossier_cancels_queued_card_before_send(self):
        self.queued()
        data = copy.deepcopy(self.dossier_input)
        data["decision"] = "reject"
        research.save_dossier(self.store, data)
        transport = Mock()
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "quality_blocked")
        transport.assert_not_called()

    def test_dossier_revision_and_graph_preserve_counterevidence(self):
        data = copy.deepcopy(self.dossier_input)
        data["findings"]["problem_severity"]["conclusion"] = "New counterfinding"
        data["findings"]["problem_severity"]["links"][0]["relation"] = "contradicts"
        result = research.save_dossier(self.store, data)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM revisions WHERE kind='dossier'").fetchone()[0], 2)

    def test_repeated_same_dossier_does_not_inflate_learning(self):
        self.assertEqual(research.save_dossier(self.store, self.dossier_input)["status"], "unchanged")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM revisions WHERE kind='dossier'").fetchone()[0], 1)

    def test_plan_keeps_breadth_and_followup_work(self):
        tasks = research.research_plan(self.store, 6)["tasks"]
        self.assertTrue(any(t["kind"] == "close_evidence_gap" for t in tasks))
        self.assertGreaterEqual(sum(t["kind"] == "domain_discovery" for t in tasks), 3)

    def test_stale_dossier_creates_recheck_task(self):
        with self.store.db:
            self.store.db.execute("UPDATE source_reviews SET reviewed_at=?", (stamp(now() - timedelta(days=20)),))
        self.assertEqual(research.research_plan(self.store)["tasks"][0]["kind"], "recheck_sources")

    def test_pain_phrase_is_triage_not_customer_count(self):
        eid = self.source("pain", "community")
        review = json.loads(self.store.db.execute("SELECT data FROM source_reviews WHERE evidence_id=?", (eid,)).fetchone()[0])
        review["summary"] = "수작업이 불편하다는 마케팅 설명; 실사용자 확인 전"
        radar.review_source(self.store, review)
        result = research.mine_pain(self.store)
        self.assertEqual(result["candidates"][0]["status"], "needs_customer_context_review")
        self.assertIn("not_people", result["unit"])

    def test_report_has_nine_empty_safe_sections(self):
        result = research.report(self.store)
        data = json.loads((self.workspace / "reports/radar-daily.json").read_text())
        self.assertEqual(len(data["sections"]), 9)
        self.assertEqual(data["candidate_alerts"]["denominator"], 0)
        self.assertIsNone(data["predictive_accuracy"])

    def measurement(self, values=(100, 120, 180)):
        end = now() - timedelta(days=1)
        return {**{k: "Fixture same metric; no real measured demand" for k in
                   ("metric", "unit", "population", "comparability_note", "confounders", "normalization", "low_base_assessment")},
                "intervals": [{"start": stamp(end - timedelta(days=21 - 7*i)),
                    "end": stamp(end - timedelta(days=14 - 7*i)), "value": v, "evidence_ids": self.eids}
                    for i, v in enumerate(values)]}

    def test_measured_two_rates_needed_for_acceleration(self):
        result = radar.measured_acceleration(self.measurement(), self.eids)
        self.assertAlmostEqual(result["rate_change"], .3)
        value = self.measurement()
        value["intervals"] = value["intervals"][:2]
        with self.assertRaises(ValueError):
            radar.measured_acceleration(value, self.eids)

    def test_slowing_growth_is_not_acceleration(self):
        with self.assertRaises(ValueError):
            radar.measured_acceleration(self.measurement((100, 200, 220)), self.eids)

    def test_noncomparable_intervals_rejected(self):
        value = self.measurement()
        value["intervals"][0]["start"] = stamp(now() - timedelta(days=60))
        with self.assertRaises(ValueError):
            radar.measured_acceleration(value, self.eids)

    def test_zero_base_does_not_make_infinite_growth(self):
        with self.assertRaises(ValueError):
            radar.measured_acceleration(self.measurement((0, 2, 20)), self.eids)


class GrantsTest(unittest.TestCase):
    setUp = RadarTest.setUp
    tearDown = RadarTest.tearDown
    source = RadarTest.source
    make_dossier = RadarTest.make_dossier

    def notice(self):
        return {"key": "test-only-notice", "title": "Fictional notice, not a real grant", "issuer": "Fixture institution",
                "notice_version": "test-version", "evidence_ids": self.eids, "official_notice_confirmed": True,
                "conditions_complete": True, "coverage_note": "All synthetic fixture conditions only",
                "opens_at": stamp(now() - timedelta(days=1)), "closes_at": stamp(now() + timedelta(days=10)),
                "rules": [{"field": "company_age_years", "operator": "lte", "value": 3,
                    "description": "Test-only age limit", "locator": "Fixture p1", "as_of_basis": "notice reference date",
                    "evidence_ids": self.eids}], "evaluation_criteria": []}

    def profile(self, value=2):
        return {"company_age_years": {"value": value, "status": "confirmed", "basis": "User-supplied fixture",
                                      "as_of_basis": "notice reference date"}}

    def match(self, notice=None, profile=None):
        gid = grants.save_notice(self.store, notice or self.notice())["id"]
        return grants.match_notice(self.store, gid, self.profile() if profile is None else profile)

    def test_matches_do_not_imply_selection(self):
        value = self.match()
        self.assertEqual(value["eligibility"], "MATCHES_RECORDED_RULES")
        self.assertIsNone(value["selection_probability"])

    def test_hard_failure_not_offset_by_score(self):
        value = self.match(profile=self.profile(5))
        self.assertEqual(value["eligibility"], "INELIGIBLE_BY_RECORDED_RULE")
        self.assertFalse(value["actionable_candidate"])

    def test_missing_user_details_remain_unknown(self):
        self.assertEqual(self.match(profile={})["eligibility"], "UNKNOWN")

    def test_different_reference_date_not_silently_used(self):
        profile = self.profile()
        profile["company_age_years"]["as_of_basis"] = "today instead of notice date"
        self.assertEqual(self.match(profile=profile)["eligibility"], "UNKNOWN")

    def test_incomplete_notice_cannot_assert_eligibility(self):
        notice = self.notice()
        notice["conditions_complete"] = False
        self.assertEqual(self.match(notice)["eligibility"], "UNKNOWN")

    def test_closed_notice_is_not_actionable(self):
        notice = self.notice()
        notice["opens_at"] = stamp(now() - timedelta(days=10))
        notice["closes_at"] = stamp(now() - timedelta(days=1))
        self.assertFalse(self.match(notice)["actionable_candidate"])

    def test_unknown_time_not_invented(self):
        notice = self.notice()
        notice["closes_at"] = None
        self.assertEqual(self.match(notice)["application_phase"], "unknown")
        notice["closes_at"] = "2026-10-01"
        with self.assertRaises(ValueError):
            grants.save_notice(self.store, notice)

    def test_type_confusion_does_not_pass_age(self):
        self.assertEqual(self.match(profile=self.profile(True))["eligibility"], "UNKNOWN")
        self.assertEqual(self.match(profile=self.profile("2"))["eligibility"], "UNKNOWN")

    def test_stale_notice_conditions_recheck(self):
        gid = grants.save_notice(self.store, self.notice())["id"]
        with self.store.db:
            self.store.db.execute("UPDATE source_reviews SET reviewed_at=?", (stamp(now() - timedelta(days=20)),))
        self.assertEqual(grants.match_notice(self.store, gid, self.profile())["eligibility"], "UNKNOWN")


# Reuse fixture helpers without running the entire original suite twice.
def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    suite.addTests(ResearchTest(n) for n in ResearchTest.__dict__ if n.startswith("test_"))
    suite.addTests(GrantsTest(n) for n in GrantsTest.__dict__ if n.startswith("test_"))
    return suite


if __name__ == "__main__":
    unittest.main()
