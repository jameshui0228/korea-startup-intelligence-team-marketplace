import hashlib
import json
import math
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_resources import parse_taxonomy
from ksi import doctor, import_evidence, resolve_forecast
from ksi_lib.collectors import (FetchError, decode_json, fetch, google_news, google_trends,
                                hub_headers, naver_search, naver_trend, safe_xml, youtube, bizinfo, github_new, hackernews,
                                kosis_registered_series, crossref_recent)
from ksi_lib.engine import analyze_series, choose_domains, coverage, dedupe, refresh, summarize_topic
from ksi_lib.model import (KST, Store, assets, atomic_json, canonical_url, credentials, init_workspace,
                           now, observation, parse_date, stamp, validate_record)


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name) / "state"
        init_workspace(self.workspace)
        self.store = Store(self.workspace)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def row(self, source="google_news_rss", kind="article", topic="test", suffix="1"):
        return observation(source, kind, topic, "A sufficiently long common test headline " + suffix,
                           "https://example.com/article/" + suffix, stamp(now() - timedelta(days=1)))

    def test_init_idempotent_preserves_founder(self):
        p = self.workspace / "FOUNDER_CONTEXT.md"
        p.write_text("user owned content")
        init_workspace(self.workspace)
        self.assertEqual(p.read_text(), "user owned content")

    def test_workspace_private(self):
        self.assertEqual(self.workspace.stat().st_mode & 0o777, 0o700)

    def test_schema_mismatch_rejected(self):
        self.store.close()
        atomic_json(self.workspace / "config.json", {"schema_version": 900})
        with self.assertRaises(ValueError):
            Store(self.workspace)

    def test_old_workspace_config_gets_safe_product_defaults(self):
        self.store.close()
        atomic_json(self.workspace / "config.json", {"schema_version": 1, "enabled_sources": ["google_news_rss"]})
        self.store = Store(self.workspace)
        self.assertEqual(self.store.config["workspace_profile_version"], 7)
        self.assertEqual(self.store.config["product_focus"], "blue_ocean_discovery_and_personal_founder_operations")
        self.assertEqual(self.store.config["operating_mode"], "on_demand")
        self.assertFalse(self.store.config["scheduler_required"])
        self.assertEqual(self.store.config["enabled_sources"], ["google_news_rss"])
        persisted = json.loads((self.workspace / "config.json").read_text())
        self.assertEqual(persisted["optional_modules"], ["grants", "competitions", "team_workbench"])

    def test_exact_legacy_default_sources_gain_public_crossref_but_custom_sources_do_not(self):
        self.store.close()
        atomic_json(self.workspace / "config.json", {"schema_version": 1, "enabled_sources": [
            "github_new", "hackernews", "google_trends_rss", "google_news_rss"]})
        self.store = Store(self.workspace)
        self.assertIn("crossref_recent", self.store.config["enabled_sources"])
        self.store.close()
        atomic_json(self.workspace / "config.json", {"schema_version": 1,
                    "enabled_sources": ["github_new", "google_news_rss"]})
        self.store = Store(self.workspace)
        self.assertEqual(self.store.config["enabled_sources"], ["github_new", "google_news_rss"])

    def test_legacy_product_focus_upgrades_but_custom_focus_is_preserved(self):
        self.store.close()
        config = {"schema_version": 1, "enabled_sources": [],
                  "product_focus": "blue_ocean_discovery_and_venture_lifecycle"}
        atomic_json(self.workspace / "config.json", config)
        self.store = Store(self.workspace)
        self.assertEqual(self.store.config["product_focus"], "blue_ocean_discovery_and_personal_founder_operations")
        self.store.close()
        config["product_focus"] = "user_custom_focus"
        atomic_json(self.workspace / "config.json", config)
        self.store = Store(self.workspace)
        self.assertEqual(self.store.config["product_focus"], "user_custom_focus")

    def test_missing_credentials_not_queried(self):
        with patch("ksi_lib.engine.credentials", return_value={}), patch("ksi_lib.engine.collect") as call:
            r = refresh(self.store, ["test"], ["naver_news"], sector_batch=0)
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["requests_made"], 0)
        self.assertEqual(r["unavailable"][0]["status"], "credentials_missing")
        call.assert_not_called()

    def test_partial_failure_preserves_good_source(self):
        def collect_stub(source, *args):
            if source == "google_trends_rss":
                raise FetchError("http_429")
            return [self.row()], {"response_sha256": "abc"}
        with patch("ksi_lib.engine.collect", side_effect=collect_stub):
            r = refresh(self.store, ["test"], ["google_news_rss", "google_trends_rss"], sector_batch=0)
        self.assertEqual(r["status"], "partial")
        self.assertEqual(len(self.store.observations()), 1)

    def test_source_write_failure_is_atomic(self):
        rows = [self.row(), {"id": "broken"}]
        with patch("ksi_lib.engine.collect", return_value=(rows, {})):
            result = refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
        self.assertEqual(len(self.store.observations()), 0)
        self.assertEqual(result["new_observations"], 0)

    def test_cache_avoids_second_request(self):
        with patch("ksi_lib.engine.collect", return_value=([self.row()], {})) as call:
            refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
            result = refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result["requests_made"], 0)
        self.assertEqual(result["sources"][0]["status"], "fresh_cache")

    def test_budget_enforced_and_reported(self):
        with patch("ksi_lib.engine.collect", return_value=([], {})) as call:
            r = refresh(self.store, ["one", "two", "three"], ["google_news_rss"], budget=1, sector_batch=0)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(len(r["deferred"]), 2)

    def test_invalid_budget(self):
        with self.assertRaises(ValueError):
            refresh(self.store, budget=0)

    def test_source_not_implemented_reported(self):
        r = refresh(self.store, sources=["instagram"], sector_batch=0)
        self.assertEqual(r["unavailable"][0]["status"], "not_implemented")

    def test_failed_source_backoff(self):
        with patch("ksi_lib.engine.collect", side_effect=FetchError("http_401")) as call:
            refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
            r = refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(r["sources"][0]["status"], "error_backoff")

    def test_arbitrary_exception_body_never_logged(self):
        with patch("ksi_lib.engine.collect", side_effect=RuntimeError("PRIVATE_FAKE_TOKEN")):
            r = refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
        self.assertNotIn("PRIVATE_FAKE_TOKEN", json.dumps(r))
        self.assertNotIn("PRIVATE_FAKE_TOKEN", (self.workspace / "reports/latest.json").read_text())

    def test_round_robin_all_400_without_duplicates(self):
        seen = set()
        for _ in range(50):
            batch = choose_domains(self.store, 8)
            self.assertFalse(seen & {d["domain_id"] for d in batch})
            for d in batch:
                self.store.db.execute("INSERT INTO coverage(domain_id,attempts) VALUES (?,1)", (d["domain_id"],))
                seen.add(d["domain_id"])
        self.assertEqual(len(seen), 400)

    def test_query_success_not_review(self):
        with patch("ksi_lib.engine.collect", return_value=([], {})):
            refresh(self.store, sources=["google_news_rss"], sector_batch=2)
        c = coverage(self.store)
        self.assertEqual(c["successfully_queried_domains"], 2)
        self.assertEqual(c["human_or_agent_reviewed_domains"], 0)

    def test_observation_dedup_on_reimport(self):
        row = self.row()
        self.store.put_observation(row)
        self.store.put_observation(row)
        self.assertEqual(len(self.store.observations()), 1)

    def test_single_star_snapshot_no_growth(self):
        row = self.row("github_new", "repository")
        row["metrics"] = {"stars_snapshot": 100}
        self.store.put_observation(row)
        self.assertIsNone(self.store.snapshot_changes()[0]["change_ratio"])

    def test_star_snapshots_week_comparison(self):
        row = self.row("github_new", "repository")
        row["metrics"] = {"stars_snapshot": 100}
        row["observed_at"] = stamp(now() - timedelta(days=7))
        self.store.put_observation(row)
        row["observed_at"] = stamp()
        row["metrics"] = {"stars_snapshot": 150}
        self.store.put_observation(row)
        self.assertEqual(self.store.snapshot_changes()[0]["change_ratio"], .5)

    def test_star_snapshots_low_base_not_infinite(self):
        row = self.row("github_new", "repository")
        row["metrics"] = {"stars_snapshot": 0}
        row["observed_at"] = stamp(now() - timedelta(days=7))
        self.store.put_observation(row)
        row["observed_at"] = stamp()
        row["metrics"] = {"stars_snapshot": 10}
        self.store.put_observation(row)
        self.assertIsNone(self.store.snapshot_changes()[0]["change_ratio"])

    def test_public_refresh_does_not_read_secrets(self):
        with patch("ksi_lib.engine.credentials") as secret, patch("ksi_lib.engine.collect", return_value=([], {})):
            refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
        secret.assert_not_called()

    def test_record_versions_preserved(self):
        self.store.record("idea", {"id": "abc", "status": "hypothesis"})
        self.store.record("idea", {"id": "abc", "status": "rejected"})
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], 2)

    def test_same_record_no_spurious_revision(self):
        self.store.record("idea", {"id": "abc"})
        self.store.record("idea", {"id": "abc"})
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0], 1)

    def test_fact_requires_verification(self):
        record = {"id": "c1", "claim": "test", "status": "FACT", "evidence_ids": [], "assumptions": [], "next_test": "verify"}
        with self.assertRaises(ValueError):
            validate_record(self.store, "claim", record)

    def test_unknown_evidence_rejected(self):
        record = {"id": "c1", "claim": "test", "status": "ASSUMPTION", "evidence_ids": ["unknown"], "assumptions": [], "next_test": "verify"}
        with self.assertRaises(ValueError):
            validate_record(self.store, "claim", record)

    def test_expired_evidence_not_valid_for_claim(self):
        row = self.row()
        row["expires_at"] = stamp(now() - timedelta(days=1))
        self.store.put_observation(row)
        record = {"id": "c1", "claim": "test", "status": "FACT", "evidence_ids": [row["id"]], "assumptions": [], "next_test": "verify", "verification_note": "read"}
        with self.assertRaises(ValueError):
            validate_record(self.store, "claim", record)

    def test_expiry_purges_provider_data_not_user_feedback(self):
        row = self.row()
        row["expires_at"] = stamp(now() - timedelta(days=1))
        self.store.put_observation(row)
        self.store.record("feedback", {"id": "f1", "lesson": "keep failure"})
        self.assertEqual(self.store.purge_expired(), 1)
        self.assertEqual(len(self.store.records("feedback")), 1)

    def test_forecast_probability_and_deadline_validated(self):
        base = {"id": "f1", "question": "event", "probability": .5, "deadline": stamp(now() + timedelta(days=1)), "resolution_rule": "defined event", "evidence_ids": []}
        for val in (float("nan"), -1, 2, True):
            with self.assertRaises(ValueError):
                validate_record(self.store, "forecast", {**base, "probability": val})
        with self.assertRaises(ValueError):
            validate_record(self.store, "forecast", {**base, "deadline": stamp(now() - timedelta(days=1))})

    def test_forecast_immutable(self):
        data = {"id": "f1", "question": "event", "probability": .5, "deadline": stamp(now() + timedelta(days=1)), "resolution_rule": "defined", "evidence_ids": []}
        self.store.record("forecast", validate_record(self.store, "forecast", data))
        with self.assertRaises(ValueError):
            validate_record(self.store, "forecast", data)

    def test_no_early_resolution(self):
        self.store.record("forecast", {"id": "f1", "probability": .6, "deadline": stamp(now() + timedelta(days=1))})
        with self.assertRaises(ValueError):
            resolve_forecast(self.store, "f1", 1, "x")

    def test_resolve_brier_and_immutable_outcome(self):
        self.store.record("forecast", {"id": "f1", "probability": .6, "deadline": stamp(now() - timedelta(days=2))})
        row = self.row()
        self.store.put_observation(row)
        result = resolve_forecast(self.store, "f1", 1, row["id"])
        self.assertAlmostEqual(result["brier_score"], .16)
        with self.assertRaises(ValueError):
            resolve_forecast(self.store, "f1", 0, row["id"])

    def test_doctor_no_secret_values(self):
        with patch("ksi.credentials", return_value={"NAVER_HUB_CLIENT_ID": "PRIVATE_FAKE_TOKEN"}):
            output = json.dumps(doctor(self.store))
        self.assertNotIn("PRIVATE_FAKE_TOKEN", output)

    def test_world_readable_secrets_refused(self):
        p = self.workspace / ".secrets.env"
        p.write_text("NAVER_HUB_CLIENT_ID=dummy")
        p.chmod(0o644)
        with self.assertRaises(ValueError):
            credentials(self.workspace)

    def test_private_secrets_supported_without_execution(self):
        p = self.workspace / ".secrets.env"
        p.write_text("NAVER_HUB_CLIENT_ID=dummy\nNAVER_HUB_CLIENT_SECRET=$(not_executed)")
        p.chmod(0o600)
        self.assertEqual(credentials(self.workspace)["NAVER_HUB_CLIENT_SECRET"], "$(not_executed)")

    def test_import_is_atomic_on_bad_row(self):
        p = self.workspace / "input.json"
        atomic_json(p, [{"topic": "a", "title": "a", "url": "https://example.com", "event_at": stamp(now() - timedelta(days=1)), "collection_basis": "user_owned"}, {"topic": "bad"}])
        with self.assertRaises(ValueError):
            import_evidence(self.store, p)
        self.assertEqual(len(self.store.observations()), 0)

    def test_repeat_signal_not_real_alert(self):
        with patch("ksi_lib.engine.collect", return_value=([self.row()], {})):
            refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
            result = refresh(self.store, ["test"], ["google_news_rss"], sector_batch=0)
        self.assertEqual(result["trends"][0]["novelty"], "unchanged")
        self.assertEqual(result["review_alerts"], [])


class PureTest(unittest.TestCase):
    def series(self, recent=30, baseline=20):
        end = now().astimezone(KST).date() - timedelta(days=1)
        return [{"date": str(end - timedelta(days=i)), "value": recent if i < 7 else baseline} for i in range(40)]

    def test_all_user_taxonomy_preserved(self):
        data = assets("taxonomy.json")
        source = (ROOT / "assets/user_inputs/korea_domains.txt").read_text()
        self.assertEqual(parse_taxonomy(source), data)
        self.assertEqual(data["domain_count"], 400)
        self.assertEqual(data["subfield_count"], 3559)
        self.assertEqual(sum(line.startswith("- ") for line in source.splitlines()), 3559)
        self.assertEqual(len(data["compressed_categories"]), 89)
        self.assertTrue(data["domains"][286]["notes"])

    def test_user_inputs_hash_verified(self):
        for name, info in assets("input_manifest.json").items():
            self.assertEqual(hashlib.sha256((ROOT / "assets/user_inputs" / name).read_bytes()).hexdigest(), info["sha256"])
        self.assertEqual(len(assets("input_manifest.json")), 3)

    def test_research_metadata_only_and_unique(self):
        data = assets("research_index.json")
        self.assertEqual(len(data), 177)
        self.assertEqual(len({r["repository"] for r in data}), 177)
        self.assertTrue(all("evidence_scope" in r for r in data))
        self.assertTrue(all("readme" not in r for r in data))

    def test_timezone_korean_midnight(self):
        self.assertEqual(parse_date("2026-09-17").isoformat(), "2026-09-16T15:00:00+00:00")
        self.assertEqual(parse_date("bad"), None)

    def test_canonical_tracking_removed(self):
        self.assertEqual(canonical_url("https://example.com/a?utm_source=x&id=1#part"), "https://example.com/a?id=1")

    def test_bad_url_or_secret_refused(self):
        for url in ("file:///etc/passwd", "https://u:p@example.com", "https://example.com?api_key=private", "javascript:alert(1)"):
            with self.assertRaises(ValueError):
                canonical_url(url)

    def test_network_host_whitelist(self):
        for url in ("http://example.com", "https://localhost", "https://naverapihub.apigw.ntruss.com.evil.test"):
            with self.assertRaises(FetchError):
                fetch(url)

    def test_naver_hub_correct_headers(self):
        data = hub_headers({"NAVER_HUB_CLIENT_ID": "dummy", "NAVER_HUB_CLIENT_SECRET": "fake"})
        self.assertIn("X-NCP-APIGW-API-KEY", data)
        self.assertNotIn("X-Naver-Client-Secret", data)

    def test_xml_entity_rejected(self):
        with self.assertRaises(FetchError):
            safe_xml(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss/>')

    def test_json_provider_error_not_empty_success(self):
        for val in ({"error": {"message": "bad"}}, {"errorCode": "403"}, []):
            with self.assertRaises(FetchError):
                decode_json(json.dumps(val))

    def test_same_window_growth(self):
        r = analyze_series(self.series())
        self.assertEqual(r["growth_ratio"], .5)
        self.assertEqual(r["direction"], "rising")
        self.assertIsNone(r["predictive_accuracy"])

    def test_negative_growth_kept(self):
        self.assertEqual(analyze_series(self.series(10, 30))["direction"], "falling")

    def test_low_baseline_no_exploding_growth(self):
        result = analyze_series(self.series(30, .1))
        self.assertEqual(result["status"], "low_baseline")
        self.assertIsNone(result["growth_ratio"])

    def test_history_needed(self):
        self.assertEqual(analyze_series(self.series()[:14])["status"], "insufficient_history")

    def test_missing_day_rejected(self):
        points = self.series()
        points.pop(10)
        self.assertEqual(analyze_series(points)["status"], "missing_days")

    def test_invalid_numbers_rejected(self):
        for val in (float("nan"), float("inf"), -1, 101, True):
            points = self.series()
            points[0]["value"] = val
            self.assertEqual(analyze_series(points)["status"], "invalid_series")

    def test_today_incomplete_rejected(self):
        points = self.series()
        points[0]["date"] = str(now().astimezone(KST).date())
        self.assertEqual(analyze_series(points)["status"], "duplicate_or_incomplete_day")

    def test_duplicate_day_rejected(self):
        points = self.series()
        points[0]["date"] = points[1]["date"]
        self.assertEqual(analyze_series(points)["status"], "duplicate_or_incomplete_day")

    def test_stale_series_rejected(self):
        later = now() + timedelta(days=5)
        self.assertEqual(analyze_series(self.series(), later)["status"], "stale_series")

    def test_two_news_aggregators_one_family(self):
        a = observation("naver_news", "article", "t", "A sufficiently long identical title", "https://a.example/1", stamp(now()))
        b = observation("google_news_rss", "article", "t", "A sufficiently long identical title - Publisher", "https://b.example/2", stamp(now()))
        r = summarize_topic("t", [a, b])
        self.assertEqual(r["deduped_observations"], 1)
        self.assertEqual(r["signal_families"], ["news"])
        self.assertEqual(r["candidate_stage"], "Weak_signal")

    def test_future_and_undated_not_growth_evidence(self):
        a = observation("naver_cafe", "community_post", "t", "a", "https://a.example/1")
        b = observation("naver_news", "article", "t", "b", "https://b.example/2", stamp(now() + timedelta(days=10)))
        r = summarize_topic("t", [a, b])
        self.assertEqual(r["dated_recent_observations"], 0)
        self.assertEqual(r["candidate_stage"], "insufficient_evidence")

    def test_single_source_spike_not_proven_trend(self):
        a = observation("google_trends_rss", "search_spike", "t", "t", "https://trends.google.com", stamp(now()), metrics={"traffic_bucket": "1000000+"})
        r = summarize_topic("t", [a])
        self.assertEqual(r["candidate_stage"], "Weak_signal")
        self.assertEqual(r["stage"], "unreviewed")
        self.assertFalse(r["independence_verified"])

    def test_naver_fixture_no_snippet_or_author_retention(self):
        payload = {"total": 90000, "items": [{"title": "<b>Test</b>", "originallink": "https://example.com/a", "pubDate": "Wed, 16 Sep 2026 10:00:00 +0900", "description": "Private-looking full text", "author": "a person"}]}
        with patch("ksi_lib.collectors.fetch", return_value=(json.dumps(payload).encode(), {})):
            rows, receipt = naver_search("naver_news", "test", {"NAVER_HUB_CLIENT_ID": "x", "NAVER_HUB_CLIENT_SECRET": "y"}, 5)
        self.assertEqual(rows[0]["title"], "Test")
        self.assertNotIn("Private-looking", json.dumps(rows))
        self.assertNotIn("a person", json.dumps(rows))
        self.assertEqual(receipt["provider_total_not_search_volume"], 90000)

    def test_naver_trend_fixture_request_window(self):
        payload = {"results": [{"data": [{"period": "2026-09-16", "ratio": 20.5}]}]}
        with patch("ksi_lib.collectors.fetch", return_value=(json.dumps(payload).encode(), {})) as call:
            rows, _ = naver_trend("돌봄", {"NAVER_HUB_CLIENT_ID": "x", "NAVER_HUB_CLIENT_SECRET": "y"}, 5)
        self.assertTrue(call.call_args.args[0].endswith("/search-trend/v1/search"))
        self.assertEqual(rows[0]["metrics"]["unit"], "relative_index_0_100")
        self.assertEqual(len(call.call_args.args[2]["keywordGroups"]), 1)

    def test_google_rss_fixture(self):
        payload = b'<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item><title>topic</title><pubDate>Wed, 16 Sep 2026 10:00:00 +0900</pubDate><ht:approx_traffic>500+</ht:approx_traffic></item></channel></rss>'
        with patch("ksi_lib.collectors.fetch", return_value=(payload, {})):
            rows, _ = google_trends("KR", 5)
        self.assertEqual(rows[0]["metrics"]["traffic_bucket"], "500+")
        self.assertEqual(rows[0]["geography"], "KR")

    def test_country_not_silently_changed(self):
        with self.assertRaises(FetchError), patch("ksi_lib.collectors.fetch") as call:
            google_trends("XX", 5)
        call.assert_not_called()

    def test_youtube_fixture_no_audience_assumption(self):
        payload = {"items": [{"id": {"videoId": "v1"}, "snippet": {"title": "Example", "publishedAt": stamp(now())}}]}
        with patch("ksi_lib.collectors.fetch", return_value=(json.dumps(payload).encode(), {})):
            rows, _ = youtube("topic", {"YOUTUBE_API_KEY": "test"}, 5)
        self.assertEqual(rows[0]["geography"], "KR_query_not_audience")
        self.assertNotIn("viewCount", rows[0]["metrics"])

    def test_bizinfo_fixture_eligibility_unknown(self):
        payload = {"jsonArray": {"item": [{"title": "공고", "link": "/notice/1", "reqstBeginEndDe": "20260901~20261001"}]}}
        with patch("ksi_lib.collectors.fetch", return_value=(json.dumps(payload).encode(), {})):
            rows, receipt = bizinfo({"BIZINFO_API_KEY": "test"}, 5)
        self.assertEqual(rows[0]["url"], "https://www.bizinfo.go.kr/notice/1")
        self.assertTrue(rows[0]["metrics"]["eligibility"].startswith("UNKNOWN"))

    def test_kosis_registered_series_keeps_measurement_definition(self):
        payload = [{"ORG_ID": "101", "TBL_ID": "DT_TEST", "TBL_NM": "시험 통계",
                    "ITM_NM": "사업체 수", "UNIT_NM": "개", "PRD_DE": "2025", "DT": "1,234",
                    "LST_CHN_DE": "20260901"}]
        config = json.dumps({"label": "한국 사업체", "userStatsId": "tester/DT_TEST",
                             "prdSe": "Y", "latest_periods": 3, "definition": "연간 사업체 수",
                             "population": "대한민국 등록 사업체", "normalization": "원자료"})
        with patch("ksi_lib.collectors.fetch", return_value=(json.dumps(payload).encode(), {})) as call:
            rows, receipt = kosis_registered_series(config, {"KOSIS_API_KEY": "test"}, 5)
        self.assertIn("statisticsData.do", call.call_args.args[0])
        self.assertNotIn("test", rows[0]["url"])
        self.assertEqual(rows[0]["metrics"]["value"], 1234.0)
        self.assertEqual(rows[0]["measurement"]["unit"], "개")
        self.assertEqual(rows[0]["measurement"]["population"], "대한민국 등록 사업체")
        self.assertEqual(receipt["numeric_rows_saved"], 1)

    def test_crossref_uses_deposit_date_without_claiming_adoption(self):
        payload = {"status": "ok", "message": {"total-results": 50, "items": [{
            "DOI": "10.1234/example", "title": ["New sensing method"],
            "created": {"date-time": "2026-09-17T10:00:00Z"}, "published": {"date-parts": [[2026, 8]]},
            "publisher": "Example Society", "type": "journal-article", "is-referenced-by-count": 2,
        }]}}
        with patch("ksi_lib.collectors.fetch", return_value=(json.dumps(payload).encode(), {})) as call:
            rows, receipt = crossref_recent("sensing", 5)
        self.assertIn("from-created-date", call.call_args.args[0])
        self.assertEqual(rows[0]["deposited_at"], "2026-09-17T10:00:00Z")
        self.assertIn("deposit_date_not_publication_date", rows[0]["limitations"])
        self.assertEqual(rows[0]["geography"], "global_metadata")
        self.assertEqual(receipt["saved_items"], 1)

    def test_github_snapshot_not_growth(self):
        payload = {"items": [{"full_name": "x/y", "html_url": "https://github.com/x/y", "created_at": stamp(now()), "stargazers_count": 100}]}
        with patch("ksi_lib.collectors.fetch", return_value=(json.dumps(payload).encode(), {})):
            rows, _ = github_new("topic", 5)
        self.assertIsNone(rows[0]["metrics"]["star_growth"])


if __name__ == "__main__":
    unittest.main()
