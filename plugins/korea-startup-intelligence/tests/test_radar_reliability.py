"""Operational regressions exercised without network calls or user state."""
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ksi_lib import radar
from ksi_lib.collectors import FetchError
from ksi_lib.engine import refresh
from ksi_lib.model import Store, init_workspace, now, observation, stamp


class RadarReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "state"
        init_workspace(self.workspace)
        self.store = Store(self.workspace)
        radar.ensure_radar(self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def stats_refresh(self, ids, force=False, response=None):
        self.store.config["youtube_video_ids"] = ids
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture"}), \
                patch("ksi_lib.engine.collect", return_value=response or ([], {})) as collect:
            report = refresh(self.store, sources=["youtube_stats"], budget=1, sector_batch=0, force=force)
        return report, collect

    def topic(self, title, hours=1, source="google_news_rss", url=None):
        row = observation(source, "social_post" if source == "youtube" else "article", title,
                          "Fixture article " + title, url or "https://example.com/" + title,
                          stamp(now() - timedelta(hours=hours)))
        with self.store.db:
            self.store.put_observation(row)
        return row

    def packet(self):
        radar.prepare(self.store, no_refresh=True)
        return json.loads((self.workspace / "reports/radar-packet.json").read_text())

    def test_new_video_does_not_refetch_fresh_batch_members(self):
        self.stats_refresh(["abc123DEF45", "def123ABC45"])
        report, collect = self.stats_refresh(["abc123DEF45", "def123ABC45", "ghi123ABC45"])
        self.assertEqual(collect.call_args.args[1], "ghi123ABC45")
        self.assertEqual(report["requests_made"], 1)
        self.assertEqual(next(x for x in report["sources"] if x["status"] == "fresh_cache")["video_count"], 2)

    def test_missing_videos_are_cached_as_attempts_not_fabricated_metrics(self):
        self.stats_refresh(["abc123DEF45"])
        report, collect = self.stats_refresh(["abc123DEF45"])
        collect.assert_not_called()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(self.store.observations(), [])
        self.assertEqual(report["sources"][0]["status"], "fresh_cache")
        self.assertEqual(report["unavailable"], [])

    def test_changed_batch_cannot_bypass_failed_video_backoff(self):
        self.store.config["youtube_video_ids"] = ["abc123DEF45", "def123ABC45"]
        with patch("ksi_lib.engine.credentials", return_value={"YOUTUBE_API_KEY": "fixture"}), \
                patch("ksi_lib.engine.collect", side_effect=FetchError("http_429")):
            refresh(self.store, sources=["youtube_stats"], sector_batch=0)
        report, collect = self.stats_refresh(["abc123DEF45", "ghi123ABC45"])
        self.assertEqual(collect.call_args.args[1], "ghi123ABC45")
        self.assertEqual(next(x for x in report["sources"] if x["status"] == "error_backoff")["video_count"], 1)

    def test_expired_video_is_fetched_again(self):
        self.stats_refresh(["abc123DEF45"])
        with self.store.db:
            self.store.db.execute("UPDATE fetches SET attempted_at=?", (stamp(now() - timedelta(hours=7)),))
        report, collect = self.stats_refresh(["abc123DEF45"])
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(report["requests_made"], 1)

    def test_batch_limit_progresses_without_resampling_first_twenty(self):
        ids = [str(n).zfill(11) for n in range(21)]
        first, collect = self.stats_refresh(ids)
        self.assertEqual(len(collect.call_args.args[1].split(",")), 20)
        self.assertTrue(any(x["status"] == "video_batch_deferred" for x in first["sources"]))
        _, collect = self.stats_refresh(ids)
        self.assertEqual(collect.call_args.args[1], ids[-1])
        _, collect = self.stats_refresh(ids)
        collect.assert_not_called()

    def test_force_is_explicit_diagnostic_override(self):
        self.stats_refresh(["abc123DEF45"])
        _, collect = self.stats_refresh(["abc123DEF45"], force=True)
        self.assertEqual(collect.call_count, 1)

    def test_per_source_ttl_applies_before_video_selection(self):
        self.stats_refresh(["abc123DEF45"])
        with self.store.db:
            self.store.db.execute("UPDATE fetches SET attempted_at=?", (stamp(now() - timedelta(hours=2)),))
        _, collect = self.stats_refresh(["abc123DEF45"])
        collect.assert_not_called()
        self.store.config["source_freshness_hours"] = {"youtube_stats": 1}
        _, collect = self.stats_refresh(["abc123DEF45"])
        self.assertEqual(collect.call_count, 1)

    def test_invalid_ttl_rejected_even_without_video_ids(self):
        self.store.config["source_freshness_hours"] = {"youtube_stats": True}
        with self.assertRaises(ValueError):
            self.stats_refresh([])

    def test_newest_korean_topic_is_not_stuck_behind_alphabetical_backlog(self):
        for index in range(12):
            self.topic("a-old-" + str(index), hours=24)
        self.topic("한국-새로운-분야", hours=1)
        packet = self.packet()
        self.assertEqual(packet["topics"][0]["topic"], "한국-새로운-분야")
        self.assertEqual(len(packet["topics"]), 4)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM radar_checks").fetchone()[0], 0)

    def test_attention_flood_does_not_exclude_early_or_sector_discovery(self):
        for index in range(15):
            self.topic("급등어-" + str(index), source="google_trends_rss")
        self.topic("초기 기술", hours=48, source="github_new")
        sector = self.topic("제조업 현장", hours=24)
        sector["domain_ids"] = ["KR-001"]
        with self.store.db:
            self.store.put_observation(sector)
        packet = self.packet()
        self.assertEqual(packet["topics"][0]["topic"], "초기 기술")
        self.assertEqual(packet["topics"][2]["topic"], "제조업 현장")
        self.assertEqual(packet["topics"][2]["selection_reason"], "sector_breadth")
        self.assertIn("google_trends_rss", packet["selection_sources"])

    def test_single_available_early_source_does_not_pin_repeated_packets(self):
        for index in range(15):
            self.topic("attention-" + str(index), source="google_trends_rss")
        self.topic("early-tech", source="hackernews")
        first = self.packet()
        second = self.packet()
        self.assertFalse({t["topic"] for t in first["topics"]} & {t["topic"] for t in second["topics"]})

    def test_attention_only_is_explicit_fallback_not_empty_packet(self):
        for index in range(8):
            self.topic("attention-" + str(index), source="google_trends_rss")
        packet = self.packet()
        self.assertEqual(len(packet["topics"]), 4)
        self.assertEqual(packet["selection_sources"], ["google_trends_rss"])

    def test_interrupted_research_rotates_but_remains_pending(self):
        for index in range(12):
            self.topic("topic-" + str(index))
        first = self.packet()
        second = self.packet()
        self.assertFalse({t["topic"] for t in first["topics"]} & {t["topic"] for t in second["topics"]})
        self.assertEqual(second["pending_topic_count"], 12)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM radar_submissions").fetchone()[0], 0)

    def test_waiting_topics_progress_while_new_topics_keep_arriving(self):
        for index in range(12):
            self.topic("z-waiting-" + str(index), hours=48)
        seen_waiting = set()
        for cycle in range(4):
            for index in range(6):
                self.topic(f"a-new-{cycle}-{index}", hours=1)
            packet = self.packet()
            seen_waiting.update(t["topic"] for t in packet["topics"] if t["topic"].startswith("z-waiting"))
        self.assertGreaterEqual(len(seen_waiting), 6)

    def test_video_counters_accompany_search_topic_without_duplicate_topic(self):
        url = "https://www.youtube.com/watch?v=abc123DEF45"
        search = self.topic("한국 농업", source="youtube", url=url)
        metric = observation("youtube_stats", "social_metric", "youtube:abc123DEF45", search["title"], url,
                             search["event_at"], metrics={"likes_snapshot": 12})
        with self.store.db:
            self.store.put_observation(metric)
        packet = self.packet()
        self.assertEqual(packet["pending_topic_count"], 1)
        topic = packet["topics"][0]
        self.assertEqual(topic["topic"], "한국 농업")
        self.assertEqual(topic["total_observations"], 1)
        self.assertEqual(topic["supporting_metric_observations"][0]["id"], metric["id"])
        radar.submit(self.store, {"packet_id": packet["packet_id"], "topic": topic["topic"],
                                 "outcome": "insufficient_evidence", "note": "Fixture metadata only", "cards": []})
        metric["metrics"]["likes_snapshot"] += 1
        with self.store.db:
            self.store.put_observation(metric)
        self.assertEqual(self.packet()["pending_topic_count"], 0)

    def test_explicit_video_without_search_remains_visible(self):
        self.topic("youtube:abc123DEF45", source="youtube_stats", url="https://www.youtube.com/watch?v=abc123DEF45")
        packet = self.packet()
        self.assertEqual(packet["topics"][0]["topic"], "youtube:abc123DEF45")


if __name__ == "__main__":
    unittest.main()
