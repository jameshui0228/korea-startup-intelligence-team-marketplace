"""Research progress is separate from query counts or validated customer demand."""
import copy
import json
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import test_radar as fixtures
from ksi_lib import agenda, radar, research
from ksi_lib.engine import coverage
from ksi_lib.model import now, observation, parse_date, stamp


class ResearchAgendaTest(unittest.TestCase):
    setUp = fixtures.RadarTest.setUp
    tearDown = fixtures.RadarTest.tearDown
    source = fixtures.RadarTest.source
    make_dossier = fixtures.RadarTest.make_dossier
    card = fixtures.RadarTest.card

    def task(self):
        return research.research_plan(self.store)["tasks"][0]

    def run_task(self, task=None):
        return agenda.start(self.store, (task or self.task())["task_id"])["run"]

    def blocked(self, run):
        return {"run_id": run["id"], "outcome": "blocked", "blocker": "customer_permission",
                "summary": "Fixture customer access not authorized; no interviews performed",
                "next_action": "Await concrete permission; no automated customer contact",
                "limitations": ["No external actions"], "evidence_ids": [], "dossier_ids": []}

    def investigated(self, run):
        return {"run_id": run["id"], "outcome": "investigated", "summary": "Fixture dossier reviewed, not real demand",
                "next_action": "Keep unknowns and look for measured evidence", "limitations": ["All synthetic fixtures"],
                "evidence_ids": self.eids, "dossier_ids": [self.dossier_id]}

    def test_plan_is_not_a_started_or_completed_investigation(self):
        research.research_plan(self.store)
        self.assertEqual(agenda.status(self.store)["started_runs"], 0)
        self.assertEqual(coverage(self.store)["domains_with_investigation_receipts"], 0)

    def test_start_is_resumable_and_not_completion(self):
        task = self.task()
        first = agenda.start(self.store, task["task_id"])
        self.assertEqual(first["status"], "started_not_researched")
        second = agenda.start(self.store, task["task_id"])
        self.assertEqual(second["status"], "resumed")
        self.assertEqual(second["run"]["id"], first["run"]["id"])
        planned = research.research_plan(self.store)
        self.assertNotIn(task["task_id"], {t["task_id"] for t in planned["tasks"]})
        self.assertEqual(planned["in_progress"][0]["run_id"], first["run"]["id"])

    def test_unknown_task_rejected(self):
        with self.assertRaises(ValueError):
            agenda.start(self.store, "fake-task")

    def test_blocked_task_cools_down_and_does_not_claim_review(self):
        run = self.run_task()
        payload = self.blocked(run)
        completed = agenda.complete(self.store, payload)
        self.assertEqual(completed["receipt"]["outcome"], "blocked")
        planned = research.research_plan(self.store)
        self.assertNotIn(run["task_id"], {t["task_id"] for t in planned["tasks"]})
        self.assertEqual(planned["cooling_down_count"], 1)
        self.assertEqual(coverage(self.store)["domains_with_investigation_receipts"], 0)
        self.assertEqual(agenda.complete(self.store, payload)["status"], "unchanged")

    def test_completed_receipts_are_immutable(self):
        run = self.run_task()
        payload = self.blocked(run)
        agenda.complete(self.store, payload)
        payload["summary"] = "Changed conclusion"
        with self.assertRaises(ValueError):
            agenda.complete(self.store, payload)

    def test_explicit_revisit_bypasses_schedule_not_evidence_rules(self):
        run = self.run_task()
        agenda.complete(self.store, self.blocked(run))
        with self.assertRaises(ValueError):
            agenda.start(self.store, run["task_id"])
        second = agenda.start(self.store, run["task_id"], revisit=True)
        self.assertNotEqual(second["run"]["id"], run["id"])
        bad = self.investigated(second["run"])
        bad["evidence_ids"] = []
        with self.assertRaises(ValueError):
            agenda.complete(self.store, bad)

    def test_due_date_reopens_question(self):
        run = self.run_task()
        completed = agenda.complete(self.store, self.blocked(run))["receipt"]
        with patch("ksi_lib.agenda.now", return_value=parse_date(completed["revisit_at"]) + timedelta(seconds=1)):
            self.assertEqual(agenda.availability(run["task"], agenda.snapshot(self.store))["reason"], "revisit_due")

    def test_new_evidence_reopens_without_waiting(self):
        run = self.run_task()
        agenda.complete(self.store, self.blocked(run))
        row = observation("google_news_rss", "article", "Fixture relevant new event", "Fictional new source",
                          "https://example.com/new-material", stamp(), domain_ids=[self.domain])
        with self.store.db:
            self.store.put_observation(row)
        available = agenda.availability(run["task"], agenda.snapshot(self.store))
        self.assertEqual(available["reason"], "context_changed")
        self.assertEqual(available["state"], "ready")

    def test_metadata_refetch_and_small_counter_change_are_not_new_learning(self):
        run = self.run_task()
        agenda.complete(self.store, self.blocked(run))
        row = self.store.observations()[0]
        row["observed_at"] = stamp(now() + timedelta(seconds=1))
        row["metrics"] = {"stars_snapshot": 11}
        with self.store.db:
            self.store.put_observation(row)
        self.assertEqual(agenda.availability(run["task"], agenda.snapshot(self.store))["state"], "cooling_down")

    def test_unrelated_sector_does_not_reopen_question(self):
        run = self.run_task()
        agenda.complete(self.store, self.blocked(run))
        row = observation("google_news_rss", "article", "Unrelated fixture", "Fixture only",
                          "https://example.com/elsewhere", stamp(), domain_ids=["KR-400"])
        with self.store.db:
            self.store.put_observation(row)
        self.assertEqual(agenda.availability(run["task"], agenda.snapshot(self.store))["state"], "cooling_down")

    def test_feedback_reopens_question(self):
        run = self.run_task()
        agenda.complete(self.store, self.blocked(run))
        with self.store.db:
            self.store.record("feedback", {"id": "fixture-feedback", "subject_id": self.dossier_id,
                "outcome": "new_context", "lesson": "Fixture only new evidence access", "evidence_ids": []})
        self.assertEqual(agenda.availability(run["task"], agenda.snapshot(self.store))["reason"], "context_changed")

    def test_investigation_requires_sources_and_dossier_link(self):
        run = self.run_task()
        for mutate in (lambda p: p.update(evidence_ids=[]), lambda p: p.update(dossier_ids=[]),
                       lambda p: p.update(dossier_ids=["unknown"]), lambda p: p.update(evidence_ids=["unknown"])):
            payload = self.investigated(run)
            mutate(payload)
            with self.assertRaises(ValueError):
                agenda.complete(self.store, payload)

    def test_metadata_only_not_counted_as_investigation(self):
        run = self.run_task()
        payload = self.investigated(run)
        payload["evidence_ids"] = [self.source("title-only", scope="metadata_only")]
        with self.assertRaises(ValueError):
            agenda.complete(self.store, payload)

    def test_investigated_receipt_does_not_inflate_fetch_coverage_or_customer_results(self):
        run = self.run_task()
        before = coverage(self.store)
        agenda.complete(self.store, self.investigated(run))
        after = coverage(self.store)
        self.assertEqual(after["attempted_domains"], before["attempted_domains"])
        self.assertEqual(after["successfully_queried_domains"], before["successfully_queried_domains"])
        self.assertEqual(after["domains_with_investigation_receipts"], 1)
        self.assertEqual(self.store.records("validation_result"), [])

    def test_no_evidence_needs_actual_search_log(self):
        run = self.run_task()
        payload = self.blocked(run)
        payload.update(outcome="no_evidence", blocker=None)
        with self.assertRaises(ValueError):
            agenda.complete(self.store, payload)
        payload["search_log"] = [{"query": "Test-only query", "channel": "fixture", "checked_at": stamp(),
                                  "outcome": "no_results", "read_evidence_ids": []}]
        agenda.complete(self.store, payload)
        self.assertEqual(agenda.status(self.store)["domains_with_investigation_receipts"], 0)

    def test_search_log_cannot_be_future_or_before_run(self):
        run = self.run_task()
        payload = self.blocked(run)
        for dt in (now() + timedelta(days=1), now() - timedelta(days=1)):
            payload["search_log"] = [{"query": "Fixture", "channel": "fixture", "checked_at": stamp(dt),
                                      "outcome": "no_results", "read_evidence_ids": []}]
            with self.assertRaises(ValueError):
                agenda.complete(self.store, payload)

    def test_all_sector_candidates_preserved_and_subfield_rotates(self):
        follow, domains = research.research_candidates(self.store)
        self.assertEqual(len(domains), 400)
        task = next(t for t in domains if t["domain"]["domain_id"] == self.domain)
        run = self.run_task(task)
        agenda.complete(self.store, self.investigated(run))
        next_task = next(t for t in research.research_candidates(self.store)[1] if t["task_id"] == task["task_id"])
        self.assertNotEqual(task["domain"]["subfield_id"], next_task["domain"]["subfield_id"])
        self.assertEqual(agenda.availability(next_task, agenda.snapshot(self.store))["state"], "cooling_down")

    def test_unfinished_run_interrupt_and_retry_are_not_completed(self):
        run = self.run_task()
        with patch("ksi_lib.agenda.now", return_value=parse_date(run["started_at"]) + timedelta(hours=25)):
            state = agenda.status(self.store)
            self.assertEqual(state["unfinished_runs"][0]["status"], "interrupted")
            retry = agenda.start(self.store, run["task_id"])
            self.assertNotEqual(run["id"], retry["run"]["id"])
        self.assertEqual(agenda.status(self.store)["recorded_outcomes"], 0)

    def test_invalid_input_types_and_unbounded_cooldown(self):
        with self.assertRaises(ValueError):
            agenda.complete(self.store, [])
        run = self.run_task()
        for mutate in (lambda p: p.update(outcome=[]), lambda p: p.update(blocker=[]),
                       lambda p: p.update(revisit_after_hours=True), lambda p: p.update(revisit_after_hours=9999),
                       lambda p: p.update(search_log={})):
            payload = self.blocked(run)
            mutate(payload)
            with self.assertRaises(ValueError):
                agenda.complete(self.store, payload)

    def test_report_includes_distinct_research_denominator(self):
        run = self.run_task()
        agenda.complete(self.store, self.investigated(run))
        research.report(self.store)
        output = json.loads((self.workspace / "reports/radar-daily.json").read_text())
        self.assertEqual(output["research_journal"]["domains_with_investigation_receipts"], 1)
        self.assertEqual(output["validation"]["resolved"], 0)

    def test_cli_history_and_start(self):
        cli = Path(__file__).resolve().parents[1] / "scripts/ksi.py"
        for tail in (("research-work", "start", "--task-id", self.task()["task_id"]), ("research-work", "history")):
            output = subprocess.run([sys.executable, str(cli), "--workspace", str(self.workspace), *tail],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(output.returncode, 0, output.stderr)
            json.loads(output.stdout)


if __name__ == "__main__":
    unittest.main()
