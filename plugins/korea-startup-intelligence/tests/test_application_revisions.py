"""Synthetic document revisions only; never write actual founder claims."""
import copy
import json
from datetime import timedelta
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_application_market as fixtures
from ksi_lib import application, venture
from ksi_lib.model import atomic_json, now, stamp


class ApplicationRevisionTest(unittest.TestCase):
    setUp = fixtures.ApplicationMarketTest.setUp
    tearDown = fixtures.ApplicationMarketTest.tearDown
    source = fixtures.ApplicationMarketTest.source
    make_dossier = fixtures.ApplicationMarketTest.make_dossier
    notice = fixtures.ApplicationMarketTest.notice
    profile = fixtures.ApplicationMarketTest.profile
    draft = fixtures.ApplicationMarketTest.draft
    filled = fixtures.ApplicationMarketTest.filled

    def saved(self):
        return application.save(self.store, self.filled())

    def reviewed(self, app_id, keys=None):
        payload = application.check(self.store, app_id)["attestation_template"]
        payload["checks"] = {k: {"checked": True, "note": "Synthetic reinspection; no real submission"}
                             for k in (keys or application.FINAL_CHECKS)}
        return payload

    def change_review(self, eid):
        row = self.store.db.execute("SELECT data FROM source_reviews WHERE evidence_id=?", (eid,)).fetchone()
        data = json.loads(row[0])
        data["summary"] += " Revised interpretation in test fixture"
        with self.store.db:
            self.store.db.execute("UPDATE source_reviews SET data=? WHERE evidence_id=?", (json.dumps(data), eid))

    def test_resume_preserves_written_text_and_does_not_mutate(self):
        saved = self.saved()
        before = self.store.records("application")
        resumed = application.resume(self.store, saved["id"])
        self.assertEqual(resumed["input_template"]["sections"], before[0]["sections"])
        self.assertEqual(resumed["input_template"]["key"], saved["id"].removeprefix("application-"))
        self.assertEqual(self.store.records("application"), before)
        self.assertEqual(application.save(self.store, resumed["input_template"])["status"], "unchanged")

    def test_edited_text_invalidates_old_review_and_replay_cannot_reapprove(self):
        saved = self.saved()
        draft = application.resume(self.store, saved["id"])["input_template"]
        draft["sections"]["problem"][0]["text"] += " A new synthetic claim"
        revised = application.save(self.store, draft)
        self.assertNotEqual(revised["audit"]["content_fingerprint"], saved["audit"]["content_fingerprint"])
        self.assertEqual(revised["audit"]["readiness"], "working_draft")
        for key in application.FINAL_CHECKS:
            self.assertIn("manual_check_pending:" + key, revised["audit"]["gaps"])
        with self.assertRaisesRegex(ValueError, '편집 충돌'):
            application.save(self.store, draft)
        draft['expected_revision'] = self.store.checkout('application', saved['id'])['expected_revision']
        self.assertEqual(application.save(self.store, draft)["status"], "unchanged")
        self.assertTrue(all(not c["checked"] for c in self.store.records("application")[0]["final_checks"].values()))

    def test_budget_founder_facts_and_attachments_all_invalidate_reviews(self):
        saved = self.saved()
        original = application.resume(self.store, saved["id"])["input_template"]
        for mutation in (lambda d: d["budget"].update(basis="Revised fixture estimate"),
                         lambda d: d["founder_facts"].update({"team-fixture": {"statement": "Fixture only", "status": "user_confirmed", "basis": "Synthetic statement"}}),
                         lambda d: d["attachments"][0].update(basis="Different synthetic file")):
            draft = copy.deepcopy(original)
            draft['expected_revision'] = self.store.checkout('application', saved['id'])['expected_revision']
            mutation(draft)
            result = application.save(self.store, draft)
            self.assertIn("manual_check_pending:truthfulness", result["audit"]["gaps"])

    def test_attest_requires_current_content_fingerprint(self):
        saved = self.saved()
        old_review = self.reviewed(saved["id"])
        draft = application.resume(self.store, saved["id"])["input_template"]
        draft["title"] += " changed"
        application.save(self.store, draft)
        with self.assertRaises(ValueError):
            application.attest(self.store, old_review)

    def test_partial_attestation_does_not_check_unreviewed_items(self):
        draft = self.filled()
        draft["final_checks"] = {}
        saved = application.save(self.store, draft)
        result = application.attest(self.store, self.reviewed(saved["id"], ["truthfulness"]))
        self.assertNotIn("manual_check_pending:truthfulness", result["audit"]["gaps"])
        self.assertIn("manual_check_pending:official_form", result["audit"]["gaps"])
        replay = application.attest(self.store, self.reviewed(saved["id"], ["truthfulness"]))
        self.assertEqual(replay["status"], "unchanged")

    def test_key_free_edit_inspect_attest_roundtrip(self):
        with patch.dict("os.environ", {}, clear=True), \
                patch("ksi_lib.model.credentials", side_effect=AssertionError("No credentials")), \
                patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("No network")), \
                patch("ksi_lib.telegram.api", side_effect=AssertionError("No Telegram")):
            saved = self.saved()
            draft = application.resume(self.store, saved["id"])["input_template"]
            draft["pitch"][0]["answer"]["text"] += " Revised plan"
            revised = application.save(self.store, draft)
            self.assertEqual(revised["audit"]["readiness"], "working_draft")
            result = application.attest(self.store, self.reviewed(saved["id"]))
            self.assertEqual(result["audit"]["readiness"], "ready_for_human_submission_review")
            self.assertFalse(result["audit"]["automatic_submission"])

    def test_reinterpreted_notice_source_requires_rewriting_before_attestation(self):
        saved = self.saved()
        review = self.reviewed(saved["id"])
        eid = self.store.records("grant")[0]["evidence_ids"][0]
        self.change_review(eid)
        self.assertIn("source_interpretation_changed_or_unbound", application.check(self.store, saved["id"])["gaps"])
        with self.assertRaises(ValueError):
            application.attest(self.store, review)
        draft = application.resume(self.store, saved["id"])["input_template"]
        result = application.save(self.store, draft)
        self.assertIn("manual_check_pending:truthfulness", result["audit"]["gaps"])

    def test_timestamp_renewal_and_counters_are_not_reinterpretation(self):
        draft = self.filled()
        draft["sections"]["problem"][0].update(status="INFERENCE", evidence_ids=[self.eids[0]])
        saved = application.save(self.store, draft)
        row = self.store.db.execute("SELECT data FROM source_reviews WHERE evidence_id=?", (self.eids[0],)).fetchone()
        review = json.loads(row[0])
        review["reviewed_at"] = stamp(now() + timedelta(seconds=1))
        obs = next(r for r in self.store.observations() if r["id"] == self.eids[0])
        obs["metrics"] = {"test_counter": 100}
        with self.store.db:
            self.store.put_observation(obs)
            self.store.db.execute("UPDATE source_reviews SET data=?,reviewed_at=? WHERE evidence_id=?",
                                  (json.dumps(review), review["reviewed_at"], self.eids[0]))
        self.assertNotIn("source_interpretation_changed_or_unbound", application.check(self.store, saved["id"])["gaps"])

    def test_notice_change_cannot_be_attested_without_content_refresh(self):
        saved = self.saved()
        notice = self.store.records("grant")[0]
        notice["notice_version"] += " new"
        with self.store.db:
            self.store.record("grant", notice)
        with self.assertRaises(ValueError):
            application.attest(self.store, self.reviewed(saved["id"]))

    def test_stale_venture_review_is_not_ignored(self):
        venture.save(self.store, venture.prepare(self.store, self.dossier_id)["input_template"])
        dossier = self.store.records("dossier")[0]
        dossier["target"] += " changed"
        with self.store.db:
            self.store.record("dossier", dossier)
        saved = self.saved()
        self.assertIn("stale_venture_review", saved["audit"]["gaps"])

    def test_legacy_checked_boolean_is_not_current_revision_attestation(self):
        saved = self.saved()
        data = self.store.records("application")[0]
        for check in data["final_checks"].values():
            check.pop("content_fingerprint")
        with self.store.db:
            self.store.record("application", data)
        report = application.check(self.store, saved["id"])
        self.assertIn("manual_check_revision_mismatch:truthfulness", report["gaps"])

    def test_source_index_covers_pitch_qa_notice_and_founder_facts(self):
        draft = self.filled()
        draft["pitch"][0]["answer"].update(status="INFERENCE", evidence_ids=[self.eids[0]])
        draft["judge_qa"][0]["answer"].update(status="INFERENCE", evidence_ids=[self.eids[1]])
        draft["founder_facts"] = {"team-fixture": {"statement": "Synthetic team assertion", "status": "user_confirmed", "basis": "Fixture confirmation"}}
        draft["sections"]["team"][0].update(status="FACT", founder_fact_ids=["team-fixture"])
        saved = application.save(self.store, draft)
        rendered = Path(saved["report_path"]).read_text()
        self.assertIn("https://example.com/one", rendered)
        self.assertIn("https://example.com/two", rendered)
        self.assertIn("Fixture confirmation", rendered)
        self.assertIn("근거: " + self.eids[0], rendered.split("## 발표 구성")[1])
        self.assertIn("근거: " + self.eids[1], rendered.split("## 심사 질문과 답변")[1])
        output = json.loads(Path(saved["report_path"]).with_suffix(".json").read_text())
        self.assertTrue(all(r["status"] == "current" for r in output["source_appendix"]))

    def test_expired_sources_still_render_with_recheck_status(self):
        saved = self.saved()
        with patch("ksi_lib.radar.now", return_value=now() + timedelta(days=16)):
            report = application.check(self.store, saved["id"])
        self.assertIn("stale_or_changed_draft_evidence", report["gaps"])
        self.assertIn("unavailable_or_needs_review", Path(report["report_path"]).read_text())

    def test_revision_tasks_prioritize_eligibility_and_never_authorize_external_actions(self):
        draft = self.filled()
        draft["profile"] = self.profile(value=7)
        draft["budget"] = None
        draft["final_checks"] = {}
        report = application.save(self.store, draft)["audit"]
        self.assertEqual(report["revision_tasks"][0]["target"], "official_notice")
        self.assertTrue(any(t["target"] == "budget" for t in report["revision_tasks"]))
        self.assertFalse(any(t["external_action_authorized"] for t in report["revision_tasks"]))

    def test_short_pitch_not_failed_by_arbitrary_five_slide_rule(self):
        draft = self.filled()
        draft["pitch"] = draft["pitch"][:2]
        draft["judge_qa"] = draft["judge_qa"][:2]
        result = application.save(self.store, draft)
        self.assertEqual(result["audit"]["readiness"], "ready_for_human_submission_review")
        self.assertEqual(result["audit"]["claim_status_counts"]["ASSUMPTION"], 13)

    def test_decimal_eligibility_is_preserved_but_nan_infinity_rejected(self):
        draft = self.filled()
        field = next(iter(draft["profile"]))
        draft["profile"][field]["value"] = 2.5
        saved = application.save(self.store, draft)
        self.assertEqual(application.resume(self.store, saved["id"])["input_template"]["profile"][field]["value"], 2.5)
        for value in (float("nan"), float("inf"), -float("inf")):
            draft["profile"][field]["value"] = value
            with self.assertRaises(ValueError):
                application.save(self.store, draft)

    def test_invalid_attestation_does_not_change_state(self):
        saved = self.saved()
        before = self.store.records("application")
        for checks in ({}, {"fake": {"checked": True}}, {"truthfulness": True}, {"truthfulness": {"checked": 1, "note": "Fixture"}}):
            payload = self.reviewed(saved["id"])
            payload["checks"] = checks
            with self.assertRaises(ValueError):
                application.attest(self.store, payload)
        self.assertEqual(self.store.records("application"), before)

    def test_cli_resume_and_attest(self):
        saved = self.saved()
        path = self.workspace / "fixture-attestation.json"
        atomic_json(path, self.reviewed(saved["id"]))
        cli = Path(__file__).resolve().parents[1] / "scripts/ksi.py"
        for tail in (("resume", saved["id"]), ("attest", "--file", str(path))):
            run = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace), "application", *tail],
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            json.loads(run.stdout)


if __name__ == "__main__":
    unittest.main()
