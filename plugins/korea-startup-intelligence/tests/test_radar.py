import copy
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ksi_lib.model import Store, assets, atomic_json, atomic_text, init_workspace, now, observation, stamp
from ksi_lib.engine import refresh
from ksi_lib import radar, telegram, research


class RadarTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "state"
        init_workspace(self.workspace)
        self.store = Store(self.workspace)
        radar.ensure_radar(self.store)
        self.eids = [self.source("one", "technology"), self.source("two", "consumer")]
        self.domain = assets("taxonomy.json")["domains"][0]["id"]
        self.make_dossier()
        self.fake_token = "12345678:" + "fixture_not_a_real_credential_" * 2
        self.fake_chat = "123456789"

    def make_dossier(self):
        findings = {key: {"status": "INFERENCE", "conclusion": "Fictional test finding; no actual customers",
            "links": [{"evidence_id": self.eids[1], "relation": "supports", "basis": "official_research",
                       "locator": "Fixture section", "note": "Synthetic evidence solely for behavior tests"}]}
            for key in ("problem_severity", "current_workaround", "willingness_to_pay", "korea_fit", "differentiation")}
        self.dossier_input = {"key": "fixture-workflow", "title": "Test-only dossier", "topic": "water test",
            "target": "Test-only original hypothesis text for target", "problem": "Test-only original hypothesis text for problem",
            "decision": "research", "decision_reason": "Test-only reasoning", "domain_ids": [self.domain],
            "evidence_ids": self.eids, "findings": findings,
            "search_audit": [{"query": "Test fictional Korean alternatives", "market": "KR", "channel": "fixture",
                "checked_at": stamp(), "limitations": "Not a real search", "read_evidence_ids": self.eids}],
            "competitors": [{"name": "Fictional substitute", "market": "KR", "kind": "manual",
                "advantage": "Test-only existing workflow", "switching_barrier": "Test fixture", "evidence_ids": self.eids}],
            "counterarguments": ["Entire fixture is synthetic and is never imported into user state"]}
        self.dossier_id = research.save_dossier(self.store, self.dossier_input)["id"]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def source(self, suffix, family="technology", days=1, scope="relevant_sections", origin=None):
        return radar.review_source(self.store, {"topic": "water test", "title": "Distinct source " + suffix,
            "url": "https://example.com/" + suffix, "event_at": stamp(now() - timedelta(days=days)),
            "read_scope": scope, "family": family, "summary": "Original paraphrase from test-only source " + suffix,
            "origin_group": origin or suffix, "origin_note": "Identified original producer, fixture only",
            "reviewer": "unit-test", "collection_basis": "public_source_verified", "limitations": ["fictional fixture"]})["evidence_id"]

    def card(self, key="water-workflow-test"):
        card = {k: "Test-only original hypothesis text for " + k for k in radar.TEXT_FIELDS}
        card.update({"opportunity_key": key, "stage": "Weak Signal", "confidence": "limited",
                     "dossier_id": self.dossier_id,
                     "evidence_ids": self.eids, "domain_ids": [self.domain],
                     "next_experiment": {"hypothesis": "Test only assumption", "method": "Local fixture review, no contact",
                         "pass_condition": "Prespecified fixture succeeds", "stop_condition": "Fixture fails",
                         "timebox_days": 7, "budget_krw": 0},
                     "claims": [{"text": "A fixture observation exists", "status": "FACT", "evidence_ids": [self.eids[0]]},
                                {"text": "Demand is untested", "status": "UNKNOWN", "evidence_ids": []}],
                     "score_components": {k: {"value": None, "reason": "Unknown measured data"} for k in radar.WEIGHTS},
                     "korea_opportunity": "Unknown",
                     "change": {"kind": "new", "reason": "Test-only dated change", "evidence_ids": self.eids}})
        for k in ("business_models", "global_players", "korea_players", "contrarian", "watch_signals", "unknowns"):
            card[k] = ["Unknown or fixture-only " + k]
        return card

    def bound(self):
        atomic_text(self.workspace / ".telegram.env", "TELEGRAM_BOT_TOKEN=" + self.fake_token + "\nTELEGRAM_CHAT_ID=" + self.fake_chat + "\n")
        results = [{"id": 12345678, "is_bot": True, "username": "fixture_bot"},
                   {"id": int(self.fake_chat), "type": "private", "first_name": "Test"}]
        with patch("ksi_lib.telegram.api", side_effect=results):
            verified = telegram.verify(self.store)
        self.assertFalse(verified["message_sent"])
        telegram.enable(self.store, self.fake_chat)

    def queued(self):
        self.bound()
        result = radar.publish_card(self.store, self.card())
        self.assertEqual(result["status"], "saved_hypothesis")
        self.assertEqual(telegram.enqueue(self.store)["queued"], 1)

    def test_settings_do_not_replace_user_config(self):
        cfg = radar.ensure_radar(self.store)
        cfg["telegram_daily_limit"] = 4
        atomic_json(self.workspace / "radar.json", cfg)
        self.assertEqual(radar.ensure_radar(self.store)["telegram_daily_limit"], 4)

    def test_telegram_private_file_and_idempotent_init(self):
        telegram.init_telegram(self.store)
        p = self.workspace / ".telegram.env"
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.bound()
        before = p.read_bytes()
        telegram.init_telegram(self.store)
        self.assertEqual(p.read_bytes(), before)

    def test_insecure_telegram_file_not_read(self):
        telegram.init_telegram(self.store)
        (self.workspace / ".telegram.env").chmod(0o644)
        with self.assertRaises(ValueError):
            telegram.telegram_keys(self.workspace)

    def test_telegram_symlink_refused(self):
        target = self.workspace / "target.env"
        atomic_text(target, "TELEGRAM_BOT_TOKEN=\n")
        (self.workspace / ".telegram.env").symlink_to(target)
        with self.assertRaises(ValueError):
            telegram.telegram_keys(self.workspace)

    def test_missing_keys_are_not_network_calls(self):
        with patch("ksi_lib.telegram.api") as call:
            self.assertEqual(telegram.verify(self.store)["status"], "credentials_missing")
            self.assertEqual(telegram.discover(self.store)["status"], "token_missing")
        call.assert_not_called()

    def test_verify_needs_explicit_matching_recipient_enable(self):
        self.bound()
        with self.assertRaises(ValueError):
            telegram.enable(self.store, "999999999")

    def test_verify_disables_prior_delivery_permission(self):
        self.bound()
        results = [{"id": 12345678, "is_bot": True}, {"id": int(self.fake_chat), "type": "private"}]
        with patch("ksi_lib.telegram.api", side_effect=results):
            telegram.verify(self.store)
        self.assertFalse(radar.ensure_radar(self.store)["telegram_enabled"])

    def test_verify_rejects_another_chat(self):
        self.bound()
        with patch("ksi_lib.telegram.api", side_effect=[{"id": 1, "is_bot": True}, {"id": 99999999, "type": "private"}]):
            with self.assertRaises(telegram.TelegramError):
                telegram.verify(self.store)

    def test_discovery_does_not_log_messages_or_ack_updates(self):
        self.bound()
        data = [{"update_id": 100, "message": {"text": "sensitive message body", "chat": {"id": 100, "type": "private", "first_name": "Test"}}}]
        with patch("ksi_lib.telegram.api", return_value=data) as call:
            result = telegram.discover(self.store)
        self.assertNotIn("sensitive", json.dumps(result))
        self.assertNotIn("offset", call.call_args.args[2])
        self.assertFalse(result["destination_selected"])

    def test_good_card_saved_as_hypothesis_not_supported(self):
        result = radar.publish_card(self.store, self.card())
        self.assertTrue(result["notification_eligible"])
        self.assertEqual(result["blue_ocean"]["status"], "synced")
        self.assertEqual(self.store.records("idea")[0]["status"], "hypothesis")
        self.assertIsNone(self.store.records("opportunity")[0]["trend_score"])
        self.assertEqual(self.store.records("blue_ocean")[0]["managed_by"], "radar_bridge")

    def test_missing_payer_rejected(self):
        card = self.card()
        card.pop("payer")
        with self.assertRaises(ValueError):
            radar.publish_card(self.store, card)
        self.assertEqual(self.store.records("idea"), [])

    def test_no_original_read_rejected(self):
        card = self.card()
        card["evidence_ids"] = [self.source("meta", scope="metadata_only")]
        with self.assertRaises(ValueError):
            radar.validate_card(self.store, card)

    def test_expired_or_changed_source_requires_review(self):
        row = self.store.observations()[0]
        row["title"] = "A materially changed source title"
        with self.store.db:
            self.store.put_observation(row)
        with self.assertRaises(ValueError):
            radar.validate_card(self.store, self.card())

    def test_unknown_evidence_id_refused(self):
        with self.assertRaises(ValueError):
            radar.review_source(self.store, {"evidence_id": "nonexistent", "read_scope": "full_text", "family": "policy",
                "summary": "Summary", "origin_group": "source", "origin_note": "known", "reviewer": "test", "collection_basis": "public_source_verified"})

    def test_undated_source_can_be_background_not_new_change(self):
        item = {"topic": "undated", "title": "An undated product page", "url": "https://example.com/undated",
                "event_at": None, "date_basis": "unknown", "read_scope": "full_text", "family": "product",
                "summary": "Background only", "origin_group": "product", "origin_note": "Original producer",
                "reviewer": "test", "collection_basis": "public_source_verified"}
        result = radar.review_source(self.store, item)
        card = self.card()
        card["evidence_ids"] = self.eids + [result["evidence_id"]]
        self.assertTrue(radar.validate_card(self.store, card)["notification_eligible"])
        card["change"]["evidence_ids"] = [result["evidence_id"]]
        with self.assertRaises(ValueError):
            radar.validate_card(self.store, card)

    def test_metadata_date_alone_cannot_pass_recent_change_gate(self):
        eid = self.source("recent-title", scope="metadata_only")
        card = self.card()
        card["evidence_ids"] = self.eids + [eid]
        card["change"]["evidence_ids"] = [eid]
        with self.assertRaises(ValueError):
            radar.validate_card(self.store, card)

    def test_one_producer_cannot_be_two_independent_sources(self):
        self.eids = [self.source("three", "technology", origin="same"), self.source("four", "consumer", origin="same")]
        card = self.card()
        card["stage"] = "Emerging"
        with self.assertRaises(ValueError):
            radar.validate_card(self.store, card)
        card["stage"] = "Weak Signal"
        self.assertFalse(radar.validate_card(self.store, card)["notification_eligible"])

    def test_old_retrieved_today_is_not_recent_change(self):
        self.eids = [self.source("old-one", days=60), self.source("old-two", "consumer", days=60)]
        with self.assertRaises(ValueError):
            radar.validate_card(self.store, self.card())

    def test_accelerating_cannot_come_from_current_counts(self):
        card = self.card()
        card["stage"] = "Accelerating"
        with self.assertRaises(ValueError):
            radar.validate_card(self.store, card)

    def test_fact_needs_evidence(self):
        card = self.card()
        card["claims"][0]["evidence_ids"] = []
        with self.assertRaises(ValueError):
            radar.validate_card(self.store, card)

    def test_scores_require_complete_defined_criteria(self):
        scores = self.card()["score_components"]
        self.assertIsNone(radar.score_components(scores, self.eids))
        for c in scores.values():
            c.update({"value": .5, "scale": "Explicit test scale", "evidence_ids": self.eids})
        self.assertEqual(radar.score_components(scores, self.eids), 50)
        scores["growth"]["value"] = float("nan")
        with self.assertRaises(ValueError):
            radar.score_components(scores, self.eids)

    def test_same_sources_rephrasing_does_not_create_alert(self):
        card = self.card()
        radar.publish_card(self.store, card)
        card["title"] = "A new wording is not a new opportunity"
        self.assertEqual(radar.publish_card(self.store, card)["status"], "unchanged_evidence")

    def test_new_sources_same_idea_needs_meaningful_change_type(self):
        card = self.card()
        radar.publish_card(self.store, card)
        card["evidence_ids"] = self.eids + [self.source("five", "policy")]
        with self.assertRaises(ValueError):
            radar.publish_card(self.store, card)
        card["change"] = {"kind": "regulation", "reason": "Test only new policy evidence", "evidence_ids": card["evidence_ids"][-1:]}
        self.assertEqual(radar.publish_card(self.store, card)["revision"], 2)

    def test_no_result_is_valid_and_not_repeated(self):
        result = radar.prepare(self.store, no_refresh=True)
        payload = {"packet_id": result["packet_id"], "topic": "water test", "outcome": "no_opportunity", "note": "No supported customer problem", "cards": []}
        radar.submit(self.store, payload)
        radar.submit(self.store, payload)
        self.assertEqual(radar.prepare(self.store, no_refresh=True)["pending_topic_count"], 0)

    def test_new_source_reopens_previously_reviewed_topic(self):
        packet = radar.prepare(self.store, no_refresh=True)
        radar.submit(self.store, {"packet_id": packet["packet_id"], "topic": "water test", "outcome": "insufficient_evidence", "note": "Need evidence", "cards": []})
        self.source("six", "policy")
        self.assertEqual(radar.prepare(self.store, no_refresh=True)["pending_topic_count"], 1)

    def test_invalid_submit_does_not_finalize_topic(self):
        packet = radar.prepare(self.store, no_refresh=True)
        bad = self.card()
        bad.pop("problem")
        with self.assertRaises(ValueError):
            radar.submit(self.store, {"packet_id": packet["packet_id"], "topic": "water test", "outcome": "hypothesis", "note": "Test", "cards": [bad]})
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM radar_checks").fetchone()[0], 0)

    def test_deliver_dry_run_has_no_side_effect(self):
        self.queued()
        with patch("ksi_lib.telegram.api") as call:
            result = telegram.deliver(self.store)
        call.assert_not_called()
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(self.store.db.execute("SELECT status FROM telegram_outbox").fetchone()[0], "pending")

    def test_delivery_success_has_receipt_and_no_duplicate(self):
        self.queued()
        call = Mock(return_value={"message_id": 11, "chat": {"id": int(self.fake_chat)}})
        self.assertEqual(telegram.deliver(self.store, send=True, transport=call)["status"], "sent")
        telegram.enqueue(self.store)
        telegram.deliver(self.store, send=True, transport=call)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(telegram.status(self.store)["live_deliveries_confirmed"], 1)

    def test_ambiguous_delivery_not_retried(self):
        self.queued()
        call = Mock(side_effect=telegram.TelegramError("network_outcome_unknown"))
        result = telegram.deliver(self.store, send=True, transport=call)
        self.assertEqual(result["status"], "uncertain")
        telegram.deliver(self.store, send=True, transport=call)
        self.assertEqual(call.call_count, 1)

    def test_unexpected_exception_never_logs_auth(self):
        self.queued()
        call = Mock(side_effect=RuntimeError("https://api.telegram.org/bot" + self.fake_token))
        result = telegram.deliver(self.store, send=True, transport=call)
        self.assertNotIn(self.fake_token, json.dumps(result))
        self.assertEqual(result["status"], "uncertain")

    def test_crashed_send_becomes_uncertain_not_resent(self):
        self.queued()
        with self.store.db:
            self.store.db.execute("UPDATE telegram_outbox SET status='sending',attempts=1")
        call = Mock()
        telegram.deliver(self.store, send=True, transport=call)
        call.assert_not_called()
        self.assertEqual(self.store.db.execute("SELECT status FROM telegram_outbox").fetchone()[0], "uncertain")

    def test_401_stops_auth_retries(self):
        self.queued()
        call = Mock(side_effect=telegram.TelegramError("http_401"))
        self.assertEqual(telegram.deliver(self.store, send=True, transport=call)["status"], "blocked")
        telegram.deliver(self.store, send=True, transport=call)
        self.assertEqual(call.call_count, 1)

    def test_429_respects_retry_after_without_sleep(self):
        self.queued()
        call = Mock(side_effect=telegram.TelegramError("http_429", 1800))
        result = telegram.deliver(self.store, send=True, transport=call)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(telegram.deliver(self.store, send=True, transport=call)["status"], "rate_limit_backoff")
        self.assertEqual(call.call_count, 1)

    def test_new_token_cannot_change_destination_silently(self):
        self.queued()
        atomic_text(self.workspace / ".telegram.env", "TELEGRAM_BOT_TOKEN=" + self.fake_token + "\nTELEGRAM_CHAT_ID=987654321\n")
        call = Mock()
        self.assertEqual(telegram.deliver(self.store, send=True, transport=call)["status"], "blocked_not_enabled_or_verified")
        call.assert_not_called()

    def test_expired_source_blocks_delivery(self):
        self.queued()
        with self.store.db:
            self.store.db.execute("UPDATE observations SET expires_at=?", (stamp(now() - timedelta(days=1)),))
        call = Mock()
        self.assertEqual(telegram.deliver(self.store, send=True, transport=call)["status"], "stale_evidence")
        call.assert_not_called()

    def test_utf16_message_limit_with_emoji(self):
        card = radar.validate_card(self.store, self.card())
        for field in radar.TEXT_FIELDS:
            card[field] = "🧪" * 1200
        message = telegram.render_message(card)
        self.assertLessEqual(len(message.encode("utf-16-le")) // 2, 4096)
        self.assertIn("KST", message)
        self.assertIn("근거 신뢰도: 제한적", message)

    def test_daily_limit_includes_ambiguous_delivery(self):
        self.queued()
        cfg = radar.ensure_radar(self.store)
        cfg["telegram_daily_limit"] = 1
        atomic_json(self.workspace / "radar.json", cfg)
        telegram.deliver(self.store, send=True, transport=Mock(side_effect=telegram.TelegramError("network_outcome_unknown")))
        self.assertEqual(telegram.deliver(self.store, send=True, transport=Mock())["status"], "daily_limit")

    def test_source_specific_ttl_does_not_force_naver(self):
        with patch("ksi_lib.engine.collect", return_value=([], {})) as call:
            self.store.config["source_freshness_hours"] = {"google_news_rss": .5}
            refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
            refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
        self.assertEqual(call.call_count, 1)
        self.assertFalse(any(x.startswith("naver_") for x in self.store.config["enabled_sources"]))

    def test_api_refuses_arbitrary_methods_and_redirects(self):
        with self.assertRaises(telegram.TelegramError):
            telegram.api(self.fake_token, "setWebhook", {})
        with self.assertRaises(telegram.TelegramError):
            telegram.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")


if __name__ == "__main__":
    unittest.main()
