import copy
import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ksi_lib import research, telegram, radar
from ksi_lib.collectors import FetchError, youtube_statistics
from ksi_lib.engine import refresh
from ksi_lib.model import now, observation, stamp
from test_radar import RadarTest
from test_research import GrantsTest


class YoutubeStatisticsTest(unittest.TestCase):
    setUp = RadarTest.setUp
    tearDown = RadarTest.tearDown
    source = RadarTest.source
    make_dossier = RadarTest.make_dossier

    def payload(self, counters=None):
        return {"items": [{"id": "abc123DEF45", "snippet": {"title": "Fixture video", "publishedAt": "2026-01-01T00:00:00Z"},
                           "statistics": counters if counters is not None else {"viewCount": "1234", "likeCount": "42"}}]}

    def collect(self, data=None, ids="abc123DEF45"):
        with patch("ksi_lib.collectors.fetch", return_value=(json.dumps(data or self.payload()).encode(), {})) as call:
            result = youtube_statistics(ids, {"YOUTUBE_API_KEY": "fixture_only"}, 5)
        self.assertEqual(call.call_count, 1)
        self.assertIn("/videos?", call.call_args.args[0])
        return result

    def test_versioned_counts_and_missing_not_zero(self):
        rows, receipt = self.collect()
        self.assertEqual(rows[0]["metrics"]["views_play_start_20260824_snapshot"], 1234)
        self.assertNotIn("comment_count_snapshot", rows[0]["metrics"])
        self.assertEqual(rows[0]["geography"], "unknown_audience")
        self.assertEqual(receipt["quota_units_documented"], 1)
        self.assertNotIn("fixture_only", json.dumps([rows, receipt]))

    def test_invalid_ids_fail_before_network(self):
        for ids in ("", "short", "abc123DEF45,abc123DEF45", ",".join(str(n).zfill(11) for n in range(21))):
            with patch("ksi_lib.collectors.fetch") as call, self.assertRaises(FetchError):
                youtube_statistics(ids, {"YOUTUBE_API_KEY": "fixture_only"}, 5)
            call.assert_not_called()

    def test_invalid_counters_not_silently_coerced(self):
        for value in (-1, "1.5", True, "NaN"):
            with self.assertRaises(FetchError):
                self.collect(self.payload({"viewCount": value}))

    def test_missing_video_is_coverage_gap(self):
        rows, receipt = self.collect({"items": []})
        self.assertEqual(rows, [])
        self.assertEqual(receipt["missing_video_count"], 1)

    def test_unrequested_video_rejected(self):
        data = self.payload()
        data["items"][0]["id"] = "notRequest1"
        with self.assertRaises(FetchError):
            self.collect(data)

    def test_snapshot_stores_counter_not_viewer_estimate(self):
        rows, _ = self.collect()
        with self.store.db:
            self.store.put_observation(rows[0])
        metrics = {r["metric"]: r["value"] for r in self.store.db.execute("SELECT * FROM metric_snapshots")}
        self.assertEqual(metrics["views_play_start_20260824_snapshot"], 1234)
        self.assertNotIn("unique_viewers", metrics)

    def test_request_budget_one_batch_and_no_hidden_search(self):
        self.store.config["youtube_video_ids"] = ["abc123DEF45", "def123ABC45"]
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture_only"}), patch("ksi_lib.engine.collect", return_value=([], {})) as call:
            result = refresh(self.store, sources=["youtube_stats"], budget=1, sector_batch=0)
        self.assertEqual(result["requests_made"], 1)
        self.assertEqual(call.call_args.args[0], "youtube_stats")
        self.assertEqual(set(call.call_args.args[1].split(",")), set(self.store.config["youtube_video_ids"]))

    def test_no_ids_means_no_request(self):
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture_only"}), patch("ksi_lib.engine.collect") as call:
            result = refresh(self.store, sources=["youtube_stats"], budget=1, sector_batch=0)
        call.assert_not_called()
        self.assertEqual(result["unavailable"][0]["status"], "no_video_ids_yet")

    def test_youtube_empty_watchlist_still_searches_one_radar_field(self):
        self.store.config["watch_topics"] = []
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture_only"}), patch("ksi_lib.engine.collect", return_value=([], {})) as call:
            result = refresh(self.store, sources=["youtube"], sector_batch=6)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result["requests_made"], 1)
        self.assertNotEqual(call.call_args.args[1], "한국 창업")
        self.assertEqual(result["coverage"]["successfully_queried_domains"], 1)

    def test_youtube_explicit_topic_takes_precedence(self):
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture_only"}), patch("ksi_lib.engine.collect", return_value=([], {})) as call:
            refresh(self.store, explicit_topics=["explicit fixture"], sources=["youtube"], sector_batch=6)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[1], "explicit fixture")

    def test_youtube_daily_cap_applies_even_with_force(self):
        self.store.config["youtube_search_daily_limit"] = 1
        with self.store.db:
            self.store.fetch_log("youtube", "previous fixture", "ok", 0, {})
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture_only"}), patch("ksi_lib.engine.collect") as call:
            result = refresh(self.store, explicit_topics=["another fixture"], sources=["youtube"], sector_batch=0, force=True)
        call.assert_not_called()
        self.assertEqual(result["deferred"][0]["status"], "local_daily_search_limit")

    def test_youtube_daily_cap_allows_fresh_cache(self):
        self.store.config["youtube_search_daily_limit"] = 1
        with self.store.db:
            self.store.fetch_log("youtube", "same fixture", "ok", 3, {})
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture_only"}), patch("ksi_lib.engine.collect") as call:
            result = refresh(self.store, explicit_topics=["same fixture"], sources=["youtube"], sector_batch=0)
        call.assert_not_called()
        self.assertEqual(result["sources"][0]["status"], "fresh_cache")

    def test_invalid_youtube_cap_fails_before_network(self):
        self.store.config["youtube_search_daily_limit"] = True
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture_only"}), patch("ksi_lib.engine.collect") as call, self.assertRaises(ValueError):
            refresh(self.store, sources=["youtube"], sector_batch=0)
        call.assert_not_called()


class UpgradeGuardTest(unittest.TestCase):
    setUp = RadarTest.setUp
    tearDown = RadarTest.tearDown
    source = RadarTest.source
    make_dossier = RadarTest.make_dossier
    bound = RadarTest.bound
    card = RadarTest.card

    def test_report_maintenance_is_quiet_and_once_per_bucket(self):
        result = research.maintenance(self.store)
        self.assertEqual(len(result["generated"]), 3)
        self.assertEqual(result["messages_sent"], 0)
        self.assertEqual(research.maintenance(self.store)["generated"], [])

    def test_report_maintenance_regenerates_next_day(self):
        research.maintenance(self.store)
        with patch("ksi_lib.research.now", return_value=now() + timedelta(days=1)):
            result = research.maintenance(self.store)
        self.assertIn("daily", [r["period"] for r in result["generated"]])

    def test_card_feedback_reaches_its_dossier_followup(self):
        cid = radar.publish_card(self.store, self.card())["id"]
        with self.store.db:
            self.store.record("feedback", {"id": "fixture-feedback", "subject_id": cid,
                "outcome": "not_useful", "lesson": "Test-only user note, no real customer", "evidence_ids": []})
        task = research.research_plan(self.store)["tasks"][0]
        self.assertEqual(task["feedback"][0]["subject_id"], cid)

    def test_malformed_dossier_lists_rejected(self):
        for key, value in (("search_audit", ["bad"]), ("competitors", [None]), ("counterarguments", "bad")):
            data = copy.deepcopy(self.dossier_input)
            data[key] = value
            with self.assertRaises(ValueError):
                research.save_dossier(self.store, data)

    def test_export_never_repeats_stale_eligible_flag(self):
        radar.publish_card(self.store, self.card())
        dossier = copy.deepcopy(self.dossier_input)
        dossier["decision"] = "reject"
        research.save_dossier(self.store, dossier)
        radar.render_cards(self.store)
        exported = json.loads((self.workspace / "reports/opportunities.json").read_text())[0]
        self.assertTrue(exported["recorded_notification_eligible"])
        self.assertFalse(exported["notification_eligible"])
        self.assertIn("dossier_decision:reject", exported["quality_gate"]["reasons"])

    def test_fixed_connection_check_idempotent_and_receipted(self):
        self.bound()
        self.assertEqual(telegram.enqueue_connection_check(self.store, self.fake_chat)["queued"], 1)
        self.assertEqual(telegram.enqueue_connection_check(self.store, self.fake_chat)["queued"], 0)
        transport = Mock(return_value={"message_id": 10, "chat": {"id": int(self.fake_chat)}})
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "sent")
        self.assertEqual(transport.call_args.args[2]["text"], telegram.CONNECTION_CHECK)
        self.assertEqual(telegram.status(self.store)["connection_checks_confirmed"], 1)
        self.assertEqual(telegram.status(self.store)["idea_deliveries_confirmed"], 0)

    def test_connection_check_recipient_confirmation_required(self):
        with self.assertRaises(ValueError):
            telegram.enqueue_connection_check(self.store, self.fake_chat)
        self.bound()
        with self.assertRaises(ValueError):
            telegram.enqueue_connection_check(self.store, "wrong")

    def test_connection_check_not_arbitrary_message_escape(self):
        self.bound()
        telegram.enqueue_connection_check(self.store, self.fake_chat)
        with self.store.db:
            self.store.db.execute("UPDATE telegram_outbox SET message='arbitrary fabricated idea'")
        transport = Mock()
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "quality_blocked")
        transport.assert_not_called()

    def test_connection_check_uncertain_not_retried(self):
        self.bound()
        telegram.enqueue_connection_check(self.store, self.fake_chat)
        transport = Mock(side_effect=telegram.TelegramError("network_outcome_unknown"))
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "uncertain")
        self.assertEqual(telegram.enqueue_connection_check(self.store, self.fake_chat)["queued"], 0)
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "cooldown")
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(transport.call_count, 1)


class PartialDeadlineTest(GrantsTest):
    def test_known_past_deadline_with_unknown_opening_is_closed(self):
        notice = self.notice()
        notice["opens_at"] = None
        notice["closes_at"] = stamp(now() - timedelta(days=1))
        notice["coverage_note"] = "Recorded window closed; conditional rolling opening not verified"
        result = self.match(notice)
        self.assertEqual(result["application_phase"], "closed")
        self.assertIn("rolling", result["coverage_note"])
        self.assertFalse(result["actionable_candidate"])


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for cls in (YoutubeStatisticsTest, UpgradeGuardTest, PartialDeadlineTest):
        suite.addTests(cls(n) for n in cls.__dict__ if n.startswith("test_"))
    return suite
