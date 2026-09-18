"""Delivery, recovery and interrupted-cycle behavior in isolated synthetic state."""
import json
import io
import unittest
import urllib.error
from datetime import timedelta
from unittest.mock import Mock, patch
import test_radar as fixtures
from ksi_lib import operations, radar, telegram
from ksi_lib.model import atomic_json, atomic_text, now, stamp


class TelegramOperationsTest(unittest.TestCase):
    setUp = fixtures.RadarTest.setUp
    tearDown = fixtures.RadarTest.tearDown
    source = fixtures.RadarTest.source
    make_dossier = fixtures.RadarTest.make_dossier
    card = fixtures.RadarTest.card
    bound = fixtures.RadarTest.bound
    queued = fixtures.RadarTest.queued

    def outbox(self):
        return self.store.db.execute("SELECT * FROM telegram_outbox ORDER BY created_at,id LIMIT 1").fetchone()

    def success(self):
        return Mock(return_value={"message_id": 12, "chat": {"id": int(self.fake_chat)}})

    def uncertain(self):
        self.queued()
        return telegram.deliver(self.store, True, Mock(side_effect=telegram.TelegramError("network_outcome_unknown")))

    def finish_topics(self, packet_id):
        packet = operations.load_packet(self.store, packet_id)
        for topic in packet["topics"]:
            radar.submit(self.store, {"packet_id": packet_id, "topic": topic["topic"],
                                     "outcome": "insufficient_evidence", "note": "Synthetic fixture, not market evidence", "cards": []})

    def test_success_has_durable_attempt_and_redacted_history(self):
        self.queued()
        telegram.deliver(self.store, True, self.success())
        log = telegram.history(self.store)
        self.assertEqual(log["attempts"][0]["outcome"], "sent")
        self.assertEqual(log["attempts"][0]["message_id"], 12)
        self.assertEqual(log["deliveries"][0]["attempts"], 1)
        self.assertNotIn(self.fake_token, json.dumps(log))
        self.assertNotIn(self.fake_chat, json.dumps(log))
        self.assertNotIn("text", log["deliveries"][0])

    def test_tampered_ordinary_message_never_sent_or_previewed(self):
        self.queued()
        with self.store.db:
            self.store.db.execute("UPDATE telegram_outbox SET message='Unreviewed altered text'")
        self.assertEqual(telegram.deliver(self.store)["messages"], [])
        transport = self.success()
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "quality_blocked")
        transport.assert_not_called()

    def test_other_provider_key_not_exposed_in_preview(self):
        self.queued()
        other_key = "fixture_private_youtube_key_12345"
        atomic_text(self.workspace / ".secrets.env", "YOUTUBE_API_KEY=" + other_key + "\n")
        with patch("ksi_lib.telegram.render_message", return_value=other_key), self.store.db:
            self.store.db.execute("UPDATE telegram_outbox SET message=?", (other_key,))
            preview = telegram.deliver(self.store)
        self.assertNotIn(other_key, json.dumps(preview))
        self.assertEqual(preview["messages"], [])

    def test_other_provider_key_blocked_before_enqueue(self):
        self.bound()
        other_key = "fixture_private_youtube_key_12345"
        atomic_text(self.workspace / ".secrets.env", "YOUTUBE_API_KEY=" + other_key + "\n")
        radar.publish_card(self.store, self.card())
        with patch("ksi_lib.telegram.render_message", return_value=other_key), self.assertRaises(ValueError):
            telegram.enqueue(self.store)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM telegram_outbox").fetchone()[0], 0)

    def test_invalid_head_is_skipped_and_only_one_valid_message_sent(self):
        self.queued()
        first = self.outbox()["id"]
        second_card = self.card("second-fixture")
        second_card["evidence_ids"] += [self.source("second-fixture-source", "policy")]
        second = radar.publish_card(self.store, second_card)
        telegram.enqueue(self.store)
        with self.store.db:
            self.store.db.execute("UPDATE telegram_outbox SET message='Tampered',created_at=? WHERE id=?", (stamp(now() - timedelta(minutes=5)), first))
        transport = self.success()
        result = telegram.deliver(self.store, True, transport)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(self.store.db.execute("SELECT card_id FROM telegram_outbox WHERE status='sent'").fetchone()[0], second["id"])

    def test_card_age_is_rechecked_independently_of_queue_age(self):
        self.queued()
        row = self.store.db.execute("SELECT * FROM records WHERE kind='opportunity'").fetchone()
        card = json.loads(row["data"])
        card["reviewed_at"] = stamp(now() - timedelta(hours=25))
        with self.store.db:
            self.store.db.execute("UPDATE records SET data=? WHERE kind='opportunity'", (json.dumps(card),))
        transport = self.success()
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "expired")
        transport.assert_not_called()

    def test_unknown_delivery_shows_attention_and_cools_down_other_cards(self):
        result = self.uncertain()
        radar.publish_card(self.store, self.card("another-fixture"))
        telegram.enqueue(self.store)
        transport = self.success()
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "cooldown")
        transport.assert_not_called()
        status = telegram.status(self.store)
        self.assertEqual(status["queue_counts"]["uncertain"], 1)
        self.assertEqual(status["needs_attention"][0]["id"], result["alert_id"])

    def test_new_revision_of_uncertain_idea_is_not_rebroadcast(self):
        self.uncertain()
        row = self.store.db.execute("SELECT * FROM records WHERE kind='opportunity'").fetchone()
        data = json.loads(row["data"])
        data["summary"] = "Changed synthetic summary"
        with self.store.db:
            self.store.record("opportunity", data)
        queued = telegram.enqueue(self.store)
        self.assertEqual(queued["queued"], 0)
        self.assertEqual(queued["skipped_reasons"]["prior_delivery_unresolved"], 1)

    def test_crash_preserves_unknown_attempt_and_prevents_retry(self):
        self.queued()
        with self.assertRaises(KeyboardInterrupt):
            telegram.deliver(self.store, True, Mock(side_effect=KeyboardInterrupt()))
        self.assertEqual(self.outbox()["status"], "sending")
        transport = self.success()
        telegram.deliver(self.store, True, transport)
        transport.assert_not_called()
        self.assertEqual(self.outbox()["status"], "uncertain")
        self.assertEqual(telegram.history(self.store)["attempts"][0]["outcome"], "uncertain")

    def test_success_on_wrong_recipient_is_uncertain(self):
        self.queued()
        result = telegram.deliver(self.store, True, Mock(return_value={"message_id": 12, "chat": {"id": 999}}))
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(telegram.status(self.store)["live_deliveries_confirmed"], 0)

    def test_mismatched_returned_text_is_not_confirmed(self):
        self.queued()
        result = telegram.deliver(self.store, True, Mock(return_value={"message_id": 12, "chat": {"id": int(self.fake_chat)}, "text": "Other message"}))
        self.assertEqual(result["status"], "uncertain")

    def test_server_retry_after_is_never_shortened(self):
        self.queued()
        delay = 8 * 86400
        result = telegram.deliver(self.store, True, Mock(side_effect=telegram.TelegramError("http_429", delay)))
        self.assertGreaterEqual(telegram.parse_date(result["retry_after_at"]), now() + timedelta(seconds=delay - 2))
        self.assertEqual(telegram.status(self.store)["delivery_window"]["reason"], "rate_limit_backoff")

    def test_long_retry_overflow_blocks_without_unsafe_retry(self):
        self.queued()
        result = telegram.deliver(self.store, True, Mock(side_effect=telegram.TelegramError("http_429", 10**30)))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(telegram.status(self.store)["blocked_reason"], "unrepresentable_retry_after")

    def test_429_retry_creates_second_attempt_only_after_due(self):
        self.queued()
        telegram.deliver(self.store, True, Mock(side_effect=telegram.TelegramError("http_429", 60)))
        later = now() + timedelta(seconds=61)
        with patch("ksi_lib.telegram.now", return_value=later), patch("ksi_lib.model.now", return_value=later):
            self.assertEqual(telegram.deliver(self.store, True, self.success())["status"], "sent")
        attempts = telegram.history(self.store)["attempts"]
        self.assertEqual(len(attempts), 2)
        self.assertEqual({r["attempt_no"] for r in attempts}, {1, 2})

    def test_manual_delivered_confirmation_does_not_fabricate_api_success(self):
        result = self.uncertain()
        with patch("ksi_lib.telegram.api") as api:
            resolved = telegram.resolve_delivery(self.store, result["alert_id"], "delivered", self.fake_chat, "User checked their chat")
        api.assert_not_called()
        self.assertEqual(resolved["status"], "confirmed_delivered")
        status = telegram.status(self.store)
        self.assertEqual(status["live_deliveries_confirmed"], 0)
        self.assertEqual(status["user_confirmed_deliveries"], 1)
        self.assertEqual(status["needs_attention"], [])
        self.assertEqual(status["delivery_window"]["reason"], "cooldown")

    def test_manual_retry_requires_exact_chat_and_not_delivered(self):
        result = self.uncertain()
        for outcome, chat in (("delivered", self.fake_chat), ("not_delivered", "999999")):
            with self.assertRaises(ValueError):
                telegram.resolve_delivery(self.store, result["alert_id"], outcome, chat, "User checked", retry=True)
        self.assertEqual(self.outbox()["status"], "uncertain")

    def test_manual_not_delivered_does_not_retry_unless_explicit(self):
        result = self.uncertain()
        telegram.resolve_delivery(self.store, result["alert_id"], "not_delivered", self.fake_chat, "User checked", retry=False)
        self.assertEqual(self.outbox()["status"], "confirmed_not_delivered")
        transport = self.success()
        telegram.deliver(self.store, True, transport)
        transport.assert_not_called()

    def test_explicit_manual_retry_keeps_both_attempts(self):
        result = self.uncertain()
        telegram.resolve_delivery(self.store, result["alert_id"], "not_delivered", self.fake_chat, "User explicitly requested retry", retry=True)
        self.assertEqual(telegram.deliver(self.store, True, self.success())["status"], "sent")
        self.assertEqual(len(telegram.history(self.store)["attempts"]), 2)
        with self.assertRaises(ValueError):
            telegram.resolve_delivery(self.store, result["alert_id"], "not_delivered", self.fake_chat, "Duplicate retry", retry=True)

    def test_discard_does_not_reset_daily_possible_delivery_cap(self):
        result = self.uncertain()
        cfg = radar.ensure_radar(self.store)
        cfg["telegram_daily_limit"] = 1
        atomic_json(self.workspace / "radar.json", cfg)
        telegram.resolve_delivery(self.store, result["alert_id"], "discard", self.fake_chat, "Stop checking this item")
        self.assertEqual(telegram.status(self.store)["delivery_window"]["reason"], "daily_limit")

    def test_legacy_uncertain_discard_preserves_possible_delivery_cap(self):
        result = self.uncertain()
        with self.store.db:
            self.store.db.execute("DELETE FROM telegram_attempts")
        cfg = radar.ensure_radar(self.store)
        cfg["telegram_daily_limit"] = 1
        atomic_json(self.workspace / "radar.json", cfg)
        telegram.resolve_delivery(self.store, result["alert_id"], "discard", self.fake_chat, "User leaves this unresolved")
        self.assertEqual(telegram.status(self.store)["delivery_window"]["reason"], "daily_limit")
        self.assertEqual(telegram.history(self.store)["attempts"][0]["error"], "legacy_outbox_last_known_attempt")

    def test_release_self_test_is_fixed_once_per_version_and_separate(self):
        self.bound()
        self.assertEqual(telegram.enqueue_self_test(self.store)["queued"], 1)
        self.assertEqual(telegram.enqueue_self_test(self.store)["queued"], 0)
        transport = self.success()
        telegram.deliver(self.store, True, transport)
        self.assertEqual(transport.call_args.args[2]["text"], telegram.DELIVERY_CHECK)
        self.assertEqual(telegram.status(self.store)["release_checks_confirmed"], 1)
        self.assertEqual(telegram.status(self.store)["idea_deliveries_confirmed"], 0)

    def test_tampered_self_test_is_never_sent(self):
        self.bound()
        telegram.enqueue_self_test(self.store)
        with self.store.db:
            self.store.db.execute("UPDATE telegram_outbox SET message='Arbitrary message'")
        transport = self.success()
        self.assertEqual(telegram.deliver(self.store, True, transport)["status"], "quality_blocked")
        transport.assert_not_called()

    def test_cycle_resume_avoids_repeat_fetch_and_preserves_progress(self):
        first = radar.prepare(self.store, no_refresh=True)
        with patch("ksi_lib.radar.refresh") as refresh:
            resumed = radar.prepare(self.store, resume=True)
        refresh.assert_not_called()
        self.assertEqual(first["packet_id"], resumed["packet_id"])
        self.assertEqual(len(operations.runs(self.store)), 1)

    def test_new_packet_does_not_invalidate_pending_packet_submission(self):
        first = radar.prepare(self.store, no_refresh=True)
        second = radar.prepare(self.store, no_refresh=True)
        self.assertNotEqual(first["packet_id"], second["packet_id"])
        self.finish_topics(first["packet_id"])
        self.assertEqual(operations.runs(self.store)[1]["state"], "reviewing")

    def test_older_packet_cannot_overwrite_newer_judgement(self):
        first = radar.prepare(self.store, no_refresh=True)
        self.source("new-evidence", "policy")
        second = radar.prepare(self.store, no_refresh=True)
        self.finish_topics(second["packet_id"])
        newer_signature = self.store.db.execute("SELECT signature FROM radar_checks").fetchone()[0]
        self.finish_topics(first["packet_id"])
        self.assertEqual(self.store.db.execute("SELECT signature FROM radar_checks").fetchone()[0], newer_signature)
        outcome = json.loads(self.store.db.execute("SELECT result FROM radar_submissions WHERE packet_id=?", (first["packet_id"],)).fetchone()[0])
        self.assertEqual(outcome["outcome"], "superseded_review")

    def test_malformed_rate_limit_response_is_sanitized(self):
        error = urllib.error.HTTPError("https://api.telegram.org/bot" + self.fake_token, 429, "Too many", {}, io.BytesIO(b'{"parameters": []}'))
        opener = Mock()
        opener.open.side_effect = error
        with patch("ksi_lib.telegram.urllib.request.build_opener", return_value=opener), self.assertRaises(telegram.TelegramError) as caught:
            telegram.api(self.fake_token, "sendMessage", {})
        self.assertEqual(caught.exception.code, "http_429")
        self.assertNotIn(self.fake_token, str(caught.exception))

    def test_unknown_error_text_is_never_recorded(self):
        self.queued()
        result = telegram.deliver(self.store, True, Mock(side_effect=telegram.TelegramError("raw_secret_fixture_value")))
        self.assertEqual(result["error"], "delivery_outcome_unknown")
        self.assertNotIn("raw_secret_fixture_value", json.dumps(telegram.history(self.store)))

    def test_on_demand_mode_rejects_new_heartbeat_cycles(self):
        first = radar.prepare(self.store, no_refresh=True)
        with self.assertRaisesRegex(ValueError, "on_demand"):
            radar.prepare(self.store, no_refresh=True, trigger="heartbeat", automation_id="fixture")
        resumed = radar.prepare(self.store, trigger="manual", resume=True)
        self.assertEqual(resumed["packet_id"], first["packet_id"])

    def test_finish_refuses_unreviewed_topics(self):
        first = radar.prepare(self.store, no_refresh=True)
        with patch("ksi_lib.telegram.api") as api:
            result = operations.finish(self.store, first["packet_id"], send=True)
        api.assert_not_called()
        self.assertEqual(result["status"], "review_incomplete")

    def test_cycle_finish_receipt_is_idempotent_even_with_send(self):
        self.bound()
        telegram.enqueue_self_test(self.store)
        first = radar.prepare(self.store, no_refresh=True)
        self.finish_topics(first["packet_id"])
        with patch("ksi_lib.telegram.api", self.success()) as api:
            result = operations.finish(self.store, first["packet_id"], send=True)
            replay = operations.finish(self.store, first["packet_id"], send=True)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(result["delivery"]["sent"], 1)
        self.assertTrue(replay["replayed_receipt"])

    def test_crash_after_send_before_cycle_completion_cannot_send_second_message(self):
        self.bound()
        telegram.enqueue_self_test(self.store)
        telegram.enqueue_connection_check(self.store, self.fake_chat)
        first = radar.prepare(self.store, no_refresh=True)
        self.finish_topics(first["packet_id"])
        transport = self.success()
        with patch("ksi_lib.telegram.api", transport), patch("ksi_lib.operations.research.maintenance", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                operations.finish(self.store, first["packet_id"], send=True)
        # Even beyond the cooldown, this cycle already used its one send attempt.
        with self.store.db:
            earlier = stamp(now() - timedelta(hours=2))
            self.store.db.execute("UPDATE telegram_attempts SET started_at=?", (earlier,))
            self.store.db.execute("UPDATE telegram_outbox SET sent_at=? WHERE status='sent'", (earlier,))
        with patch("ksi_lib.telegram.api", transport):
            result = operations.finish(self.store, first["packet_id"], send=True)
        self.assertEqual(transport.call_count, 1)
        self.assertTrue(result["delivery"]["replayed_attempt_receipt"])
        self.assertEqual(telegram.status(self.store)["queue_counts"]["pending"], 1)

    def test_cycle_preview_does_not_complete_or_consume_send(self):
        self.bound()
        first = radar.prepare(self.store, no_refresh=True)
        self.finish_topics(first["packet_id"])
        result = operations.finish(self.store, first["packet_id"])
        self.assertEqual(result["status"], "ready_to_finish")
        self.assertIsNone(self.store.db.execute("SELECT completed_at FROM radar_runs").fetchone()[0])

    def test_failed_cycle_cannot_accept_more_reviews(self):
        first = radar.prepare(self.store, no_refresh=True)
        operations.fail(self.store, first["packet_id"], "source_unavailable")
        with self.assertRaises(ValueError):
            self.finish_topics(first["packet_id"])

    def test_failure_after_send_preserves_delivery_receipt(self):
        self.bound()
        telegram.enqueue_self_test(self.store)
        first = radar.prepare(self.store, no_refresh=True)
        self.finish_topics(first["packet_id"])
        with patch("ksi_lib.telegram.api", self.success()), patch("ksi_lib.operations.research.maintenance", side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                operations.finish(self.store, first["packet_id"], send=True)
        result = operations.fail(self.store, first["packet_id"], "research_interrupted")
        self.assertEqual(result["confirmed_api_sends"], 1)
        self.assertEqual(result["delivery_attempts"][0]["message_id"], 12)
        replay = operations.fail(self.store, first["packet_id"], "local_error")
        self.assertEqual(replay["reason"], "research_interrupted")
        self.assertTrue(replay["replayed_receipt"])

    def test_expired_unfinished_cycle_closes_without_faking_completion(self):
        first = radar.prepare(self.store, no_refresh=True)
        with self.store.db:
            self.store.db.execute("UPDATE radar_runs SET started_at=? WHERE packet_id=?",
                                  (stamp(now() - timedelta(days=2)), first["packet_id"]))
        new = radar.prepare(self.store, no_refresh=True, resume=True)
        self.assertNotEqual(new["packet_id"], first["packet_id"])
        closed = self.store.db.execute("SELECT state,result FROM radar_runs WHERE packet_id=?", (first["packet_id"],)).fetchone()
        self.assertEqual(closed["state"], "failed")
        self.assertEqual(json.loads(closed["result"])["reason"], "research_window_expired")
        self.assertNotIn("unfinished_research_cycle", operations.health(self.store)["issues"])

    def test_stale_or_path_like_packet_rejected(self):
        first = radar.prepare(self.store, no_refresh=True)
        for value in ("../../private", "", None):
            with self.assertRaises(ValueError):
                operations.load_packet(self.store, value)
        with patch("ksi_lib.operations.now", return_value=now() + timedelta(days=2)):
            with self.assertRaises(ValueError):
                operations.load_packet(self.store, first["packet_id"])

    def test_trigger_label_requires_automation_id(self):
        for trigger, aid in (("heartbeat", None), ("heartbeat", "fixture"), ("manual", "fixture"), ("other", None)):
            with patch("ksi_lib.radar.refresh") as refresh, self.assertRaises(ValueError):
                radar.prepare(self.store, trigger=trigger, automation_id=aid)
            refresh.assert_not_called()

    def test_health_does_not_repeatedly_notify_unchanged_issue(self):
        cfg = radar.ensure_radar(self.store)
        cfg["telegram_enabled"] = True
        atomic_json(self.workspace / "radar.json", cfg)
        self.assertTrue(operations.health(self.store)["notification_needed"])
        operations.health(self.store, acknowledge=True)
        self.assertFalse(operations.health(self.store)["notification_needed"])
        self.bound()
        self.assertTrue(operations.health(self.store)["notification_needed"])

    def test_on_demand_runs_do_not_require_scheduler_proof(self):
        cfg = radar.ensure_radar(self.store)
        cfg["scheduler"] = {"status": "ACTIVE", "automation_id": "fixture"}
        atomic_json(self.workspace / "radar.json", cfg)
        radar.prepare(self.store, no_refresh=True)
        health = operations.health(self.store)
        self.assertNotIn("no_recorded_heartbeat_run", health["issues"])
        self.assertFalse(health["scheduler_required"])
        self.assertEqual(health["scheduler_registration"]["status"], "not_required")
        self.assertIsNone(health["latest_recorded_heartbeat"])

    def test_stale_missing_scheduler_is_not_an_on_demand_error(self):
        cfg = radar.ensure_radar(self.store)
        cfg["scheduler"] = {"status": "MISSING", "automation_id": "deleted-fixture"}
        atomic_json(self.workspace / "radar.json", cfg)
        health = operations.health(self.store)
        self.assertEqual(health["status"], "ok")
        self.assertNotIn("scheduler_not_active:missing", health["issues"])
        self.assertNotIn("no_recorded_heartbeat_run", health["issues"])


if __name__ == "__main__":
    unittest.main()
