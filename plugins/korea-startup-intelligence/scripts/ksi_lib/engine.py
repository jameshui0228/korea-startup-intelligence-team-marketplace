import json
import math
import statistics
import re
from urllib.parse import parse_qs, urlsplit
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from .collectors import FetchError, collect
from .model import (KST, Store, assets, atomic_json, atomic_text, credentials, digest,
                    normalize_title, now, parse_date, stamp)


def analyze_series(points, as_of=None):
    """Descriptive same-window week comparison; never a calibrated forecast."""
    as_of = (as_of or now()).astimezone(KST).date()
    if not isinstance(points, list):
        return {"status": "invalid_series"}
    values = {}
    for p in points:
        dt = parse_date(p.get("date"))
        val = p.get("value")
        if not dt or isinstance(val, bool) or not isinstance(val, (float, int)) or not math.isfinite(val) or not 0 <= val <= 100:
            return {"status": "invalid_series"}
        day = dt.astimezone(KST).date()
        if day >= as_of or day in values:
            return {"status": "duplicate_or_incomplete_day"}
        values[day] = val
    if len(values) < 28:
        return {"status": "insufficient_history", "days": len(values), "required_days": 28}
    last = max(values)
    if (as_of - last).days > 3:
        return {"status": "stale_series", "last_date": str(last)}
    dates = [last - timedelta(days=i) for i in range(28)]
    if any(d not in values for d in dates):
        return {"status": "missing_days", "required_contiguous_days": 28}
    recent = statistics.mean(values[d] for d in dates[:7])
    baseline = statistics.mean(values[d] for d in dates[7:14])
    preceding = statistics.mean(values[d] for d in dates[14:21])
    if baseline < 1:
        return {"status": "low_baseline", "recent_mean": recent, "baseline_mean": baseline,
                "growth_ratio": None, "note": "Relative index baseline below 1; avoid huge percent claims"}
    growth = recent / baseline - 1
    previous_growth = baseline / preceding - 1 if preceding >= 1 else None
    return {"status": "descriptive_only", "recent_mean": round(recent, 4), "baseline_mean": round(baseline, 4),
            "growth_ratio": round(growth, 4), "acceleration_pp": round((growth - previous_growth) * 100, 2) if previous_growth is not None else None,
            "direction": "rising" if growth >= .3 else "falling" if growth <= -.3 else "flat_or_small_change",
            "last_date": str(last), "days": len(values), "seasonality_adjusted": False,
            "threshold_basis": "uncalibrated_triage_heuristic_not_significance", "predictive_accuracy": None}


def dedupe(rows):
    """Collapse identical URLs, origins and title syndication conservatively."""
    used_url, used_origin, used_title, kept = set(), set(), set(), []
    for row in sorted(rows, key=lambda r: r["observed_at"], reverse=True):
        url = row["url"]
        origin = row.get("origin_key", url)
        title = normalize_title(row["title"])
        # Series and search-spike observations share portal URLs but refer to distinct terms.
        key = url if row["kind"] not in ("series", "search_spike") else origin
        if key in used_url or origin in used_origin or (len(title) > 12 and title in used_title):
            continue
        used_url.add(key)
        used_origin.add(origin)
        used_title.add(title)
        kept.append(row)
    return kept


def summarize_topic(topic, observations, registry=None):
    registry = registry or {s["id"]: s for s in assets("sources.json")}
    # A news item's publication date is not its event date. Unknown dates don't substantiate recent change.
    rows = dedupe(observations)
    fresh = [r for r in rows if parse_date(r.get("event_at")) and
             now() - timedelta(days=14) <= parse_date(r["event_at"]) <= now() + timedelta(hours=1)]
    families = sorted({registry.get(r["source"], {}).get("family", "import") for r in fresh})
    series = [r for r in fresh if r["kind"] == "series"]
    growth = analyze_series(series[0]["series"]) if series else {"status": "no_comparable_series"}
    candidate = growth.get("direction") == "rising" and len(families) >= 2
    down = growth.get("direction") == "falling"
    return {"id": "trend-" + digest(topic)[:16], "topic": topic, "updated_at": stamp(),
            "evidence_ids": [r["id"] for r in rows], "evidence_urls": [r["url"] for r in rows[:12]],
            "raw_observations": len(observations), "deduped_observations": len(rows), "dated_recent_observations": len(fresh),
            "signal_families": families, "independence_verified": False,
            "stage": "unreviewed", "candidate_stage": "Emerging_candidate" if candidate else "Weak_signal" if fresh else "insufficient_evidence",
            "confidence": "limited", "growth": growth, "negative_signal": down,
            "commerce_evidence_present_unverified": any(r["kind"] == "transaction" for r in fresh),
            "korea_relevance": "needs_review" if any(r.get("geography") != "KR" for r in rows) else "KR_query_scope_not_representative",
            "caveats": ["Source-family diversity does not prove independent observations.",
                        "Search spikes and media attention are not demand, payment, market size or success probabilities.",
                        "Accelerating/Mainstream/Saturated require manual evidence review; automatic thresholds are not validated.",
                        "Negative signals are also candidates, not automatic no-go decisions."]}


def choose_domains(store, count):
    domains = assets("taxonomy.json")["domains"]
    history = {r["domain_id"]: dict(r) for r in store.db.execute("SELECT * FROM coverage")}
    # Coprime permutation spreads first-run sampling across the whole 400-domain list.
    ranked = sorted(domains, key=lambda d: (history.get(d["id"], {}).get("attempts", 0), (d["number"] * 137) % 401))
    output = []
    for d in ranked[:count]:
        attempts = history.get(d["id"], {}).get("attempts", 0)
        subfield = d["subfields"][attempts % len(d["subfields"])]
        output.append({"domain_id": d["id"], "domain": d["name"], "subfield_id": subfield["id"],
                       "subfield": subfield["name"], "query": f"{d['name']} {subfield['name']}"})
    return output


def coverage(store):
    taxonomy = assets("taxonomy.json")
    history = {r["domain_id"]: dict(r) for r in store.db.execute("SELECT * FROM coverage")}
    receipts = store.records("research_receipt")
    return {"taxonomy_domains": taxonomy["domain_count"], "taxonomy_subfields": taxonomy["subfield_count"],
            "attempted_domains": len(history), "successfully_queried_domains": sum(bool(r["last_success"]) for r in history.values()),
            "human_or_agent_reviewed_domains": sum(bool(r["reviewed_at"]) for r in history.values()),
            "domains_with_investigation_receipts": len({d for r in receipts if r["outcome"] == "investigated" for d in r["domain_ids"]}),
            "research_outcomes_recorded": len(receipts),
            "unqueried_domains": [d["id"] for d in taxonomy["domains"] if d["id"] not in history],
            "boundary": "A successful query does not mean the field was deeply researched, validated or fully covered."}


def source_freshness(cfg, source, spec):
    ttl = (spec["ttl_hours"] if source == "naver_trend" else
           cfg.get("source_freshness_hours", {}).get(source, min(float(cfg["freshness_hours"]), spec["ttl_hours"])))
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or not 0.25 <= ttl <= 168:
        raise ValueError("Source freshness must be 0.25..168 hours")
    return ttl


def youtube_stats_due(store, pool_ids, ttl, force=False):
    """Cache/backoff belong to each requested video, including missing results.

    A new batch composition must not bypass either limit. Reuse the fetch log so
    workspaces created before this rule also retain their successful attempts.
    """
    sampled = {}
    for row in store.observations():
        if row["source"] == "youtube_stats":
            video = parse_qs(urlsplit(row["url"]).query).get("v", [""])[0]
            sampled[video] = max(sampled.get(video, ""), row["observed_at"])
    recent = store.db.execute(
        "SELECT query,attempted_at,status FROM fetches WHERE source='youtube_stats' AND attempted_at>=? ORDER BY id",
        (stamp(now() - timedelta(hours=max(ttl, 1))),))
    attempted = {}
    for row in recent:
        for video in row["query"].split(","):
            attempted[video] = (row["attempted_at"], row["status"])
            if row["status"] == "ok":
                sampled[video] = max(sampled.get(video, ""), row["attempted_at"])
    due, fresh, backoff = [], 0, 0
    for video in pool_ids:
        last = attempted.get(video)
        if not force and last and last[1] != "ok" and parse_date(last[0]) > now() - timedelta(hours=1):
            backoff += 1
        elif not force and video in sampled and parse_date(sampled[video]) > now() - timedelta(hours=ttl):
            fresh += 1
        else:
            due.append(video)
    due.sort(key=lambda video: (sampled.get(video, ""), video))
    return due[:20], fresh, backoff, max(0, len(due) - 20)


def refresh(store, explicit_topics=None, sources=None, budget=None, sector_batch=None, force=False):
    cfg = store.config
    registry = {s["id"]: s for s in assets("sources.json")}
    selected = sources or cfg["enabled_sources"]
    if set(selected) - set(registry):
        raise ValueError("Unknown sources in config")
    keys = credentials(store.workspace) if any(registry[s]["credentials"] for s in selected) else {}
    budget = int(budget if budget is not None else cfg["max_requests"])
    count = int(sector_batch if sector_batch is not None else cfg["sector_batch"])
    if not 1 <= budget <= 60 or not 0 <= count <= 40:
        raise ValueError("Request budget 1..60 and sector batch 0..40 required")
    timeout = max(2, min(20, int(cfg["timeout_seconds"])))
    sectors = choose_domains(store, count)
    watch = list(dict.fromkeys((explicit_topics or []) + cfg.get("watch_topics", [])))[:12]
    if not watch and not sectors:
        watch = ["한국 창업"]
    if any(not isinstance(t, str) or not 1 <= len(t) <= 120 for t in watch):
        raise ValueError("Topics must be nonempty strings under 120 characters")
    plan, unavailable, statuses = [], [], []
    sector_by_query = {d["query"]: d for d in sectors}
    for source in selected:
        spec = registry[source]
        missing = [k for k in spec["credentials"] if not keys.get(k)]
        if not spec["adapter"] or missing:
            unavailable.append({"source": source, "status": "not_implemented" if not spec["adapter"] else "credentials_missing", "missing_keys": missing})
            continue
        ttl = source_freshness(cfg, source, spec)
        if source == "google_trends_rss":
            topics = cfg.get("countries", ["KR"])[:3]
        elif source in ("github_new", "hackernews"):
            globals_ = cfg.get("global_queries", ["robotics", "healthcare"])
            offset = store.db.execute("SELECT COUNT(*) FROM fetches WHERE source=?", (source,)).fetchone()[0] % max(len(globals_), 1)
            topics = (globals_[offset:] + globals_[:offset])[:2]
        elif source == "bizinfo":
            topics = ["지원사업"]
        elif source == "youtube":
            # An empty watchlist must not silently disable YouTube in radar mode.
            # One bounded search rotates across this cycle's actual field queries.
            candidates = list(dict.fromkeys(watch + list(sector_by_query)))
            total_searches = store.db.execute("SELECT COUNT(*) FROM fetches WHERE source='youtube'").fetchone()[0]
            topics = [watch[0]] if explicit_topics else [candidates[total_searches % len(candidates)]] if candidates else []
        elif source == 'youtube_uploads':
            playlists = cfg.get('youtube_upload_playlists', [])
            if not isinstance(playlists, list) or len(playlists) > 20 or any(not isinstance(p, str) or not re.fullmatch(r'UU[A-Za-z0-9_-]{22}', p) for p in playlists):
                raise ValueError('youtube_upload_playlists: 최대 20개 공개 업로드 목록 ID를 지정하세요.')
            offset = store.db.execute("SELECT COUNT(*) FROM fetches WHERE source='youtube_uploads'").fetchone()[0] % max(1, len(playlists))
            topics = (playlists[offset:] + playlists[:offset])[:2]
            if not topics:
                unavailable.append({'source': source, 'status': 'no_upload_playlists_configured', 'missing_keys': []})
        elif source == "youtube_stats":
            ids = cfg.get("youtube_video_ids", [])
            if not isinstance(ids, list) or any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", i) for i in ids):
                raise ValueError("youtube_video_ids must contain valid public video IDs")
            discovered = [parse_qs(urlsplit(r["url"]).query).get("v", [""])[0]
                          for r in store.observations() if r["source"] in ("youtube", "youtube_uploads")]
            pool_ids = sorted(set(ids + discovered))
            selected_ids, fresh, backoff, waiting = youtube_stats_due(store, pool_ids, ttl, force)
            topics = [",".join(selected_ids)] if selected_ids else []
            for status, amount in (("fresh_cache", fresh), ("error_backoff", backoff), ("video_batch_deferred", waiting)):
                if amount:
                    statuses.append({"source": source, "query": "per_video", "status": status,
                                     "video_count": amount, "boundary": "Requested IDs, not confirmed available videos"})
            if not pool_ids:
                unavailable.append({"source": source, "status": "no_video_ids_yet", "missing_keys": []})
        elif source in ("naver_news", "google_news_rss"):
            topics = watch + list(sector_by_query)
        else:
            # Narrow search terms, not an accidental AND of an entire industry name and subtype.
            topics = watch
        for topic in topics:
            plan.append((source, topic, spec))
    # Round robin source requests to avoid spending the whole budget on the first provider.
    buckets = defaultdict(list)
    for item in plan:
        buckets[item[0]].append(item)
    plan = []
    while any(buckets.values()):
        for source in selected:
            if buckets[source]:
                plan.append(buckets[source].pop(0))
    jobs, deferred = [], []
    for source, topic, spec in plan:
        last = store.latest_fetch(source, topic)
        last_ok = store.latest_fetch(source, topic, success=True)
        ttl = source_freshness(cfg, source, spec)
        if not force and last and last["status"] != "ok" and parse_date(last["attempted_at"]) > now() - timedelta(hours=1):
            statuses.append({"source": source, "query": topic, "status": "error_backoff"})
        elif not force and last_ok and parse_date(last_ok["attempted_at"]) > now() - timedelta(hours=ttl):
            statuses.append({"source": source, "query": topic, "status": "fresh_cache", "items": last_ok["item_count"]})
        elif source == "youtube" and youtube_search_cap_reached(store):
            deferred.append({"source": source, "query": topic, "status": "local_daily_search_limit",
                             "boundary": "Workspace KST-day guard, not the Google project quota or its reset time"})
        elif len(jobs) >= budget:
            deferred.append({"source": source, "query": topic, "status": "budget_deferred"})
        else:
            jobs.append((source, topic, spec))
    new_rows, sector_outcomes = [], defaultdict(list)
    # Bounded read-only network work. Each result settles independently; writes remain serial below.
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(collect, s, t, keys, timeout): (s, t, spec) for s, t, spec in jobs}
        for future in as_completed(pending):
            source, topic, spec = pending[future]
            try:
                rows, receipt = future.result()
                with store.db:
                    for row in rows:
                        if topic in sector_by_query:
                            row["domain_ids"] = [sector_by_query[topic]["domain_id"]]
                            row["domain_assignment"] = "query_hint_not_content_verified"
                        store.put_observation(row)
                    store.fetch_log(source, topic, "ok", len(rows), receipt)
                new_rows.extend(rows)
                statuses.append({"source": source, "query": topic, "status": "ok", "items": len(rows)})
                if topic in sector_by_query:
                    sector_outcomes[sector_by_query[topic]["domain_id"]].append(True)
            except (FetchError, ValueError, KeyError, TypeError, OverflowError) as exc:
                # Never serialize exception bodies or URL-bearing stack traces.
                error = str(exc) if isinstance(exc, FetchError) else "invalid_provider_payload"
                with store.db:
                    store.fetch_log(source, topic, error, 0, {"error": error})
                statuses.append({"source": source, "query": topic, "status": error, "items": 0})
                if topic in sector_by_query:
                    sector_outcomes[sector_by_query[topic]["domain_id"]].append(False)
            except Exception:
                with store.db:
                    store.fetch_log(source, topic, "adapter_failure", 0, {"error": "adapter_failure"})
                statuses.append({"source": source, "query": topic, "status": "adapter_failure", "items": 0})
    for domain_id, successes in sector_outcomes.items():
        ts = stamp()
        store.db.execute("""INSERT INTO coverage(domain_id,attempts,last_attempt,last_success) VALUES (?,1,?,?)
                         ON CONFLICT(domain_id) DO UPDATE SET attempts=attempts+1,last_attempt=excluded.last_attempt,
                         last_success=COALESCE(excluded.last_success,coverage.last_success)""",
                         (domain_id, ts, ts if any(successes) else None))
    store.db.commit()
    purged = store.purge_expired()
    rows_by_topic = defaultdict(list)
    for row in store.observations():
        rows_by_topic[row["topic"]].append(row)
    trends = [summarize_topic(topic, rows, registry) for topic, rows in rows_by_topic.items()]
    previous_trends = {t["id"]: t for t in store.records("trend")}
    alerts = []
    for trend in trends:
        previous = previous_trends.get(trend["id"])
        trend["first_detected"] = previous.get("first_detected", previous["updated_at"]) if previous else trend["updated_at"]
        signature = [trend["candidate_stage"], trend["negative_signal"], trend["signal_families"], trend["growth"].get("direction")]
        prior_signature = [previous["candidate_stage"], previous["negative_signal"], previous["signal_families"], previous["growth"].get("direction")] if previous else None
        trend["novelty"] = "new" if not previous else "meaningful_candidate_change" if signature != prior_signature else "unchanged"
        if trend["novelty"] != "unchanged" and (trend["candidate_stage"] == "Emerging_candidate" or trend["negative_signal"]):
            alerts.append({"trend_id": trend["id"], "topic": trend["topic"], "reason": trend["novelty"], "human_review_required": True})
        store.record("trend", trend)
    store.db.commit()
    ok = sum(s["status"] in ("ok", "fresh_cache") for s in statuses)
    bad = sum(s["status"] not in ("ok", "fresh_cache") for s in statuses)
    state = "partial" if ok and (bad or unavailable or deferred) else "ok" if ok else "unavailable"
    report = {"schema_version": 1, "generated_at": stamp(), "status": state, "requests_made": len(jobs),
              "request_budget": budget, "new_observations": len(new_rows), "sources": sorted(statuses, key=lambda x: (x["source"], x["query"])),
              "unavailable": unavailable, "deferred": deferred, "coverage": coverage(store),
              "trends": trends, "review_alerts": alerts, "snapshot_changes": store.snapshot_changes(), "expired_metadata_removed": purged,
              "not_connected": [s["id"] for s in registry.values() if not s["adapter"]],
              "disabled_sources": [s["id"] for s in registry.values() if s["adapter"] and s["id"] not in selected],
              "boundary": "Metadata collection and candidate triage only. Not all content read, all fields surveyed, or trends/business demand validated."}
    atomic_json(store.workspace / "reports/latest.json", report)
    atomic_text(store.workspace / "reports/latest.md", render_report(report))
    return report


def youtube_search_cap_reached(store):
    limit = store.config.get("youtube_search_daily_limit", 48)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("youtube_search_daily_limit must be an integer 1..100")
    start = stamp(now().astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0))
    attempted = store.db.execute("SELECT COUNT(*) FROM fetches WHERE source='youtube' AND attempted_at>=?", (start,)).fetchone()[0]
    return attempted >= limit


def md(text):
    return str(text).replace("|", "\\|").replace("\n", " ").replace("[", "\\[").replace("]", "\\]")


def render_report(report):
    c = report["coverage"]
    lines = ["# 허구김 · 한국 창업 인텔리전스 수집 상태", "", f"생성: {report['generated_at']}",
             f"상태: {report['status']} · 요청 {report['requests_made']}/{report['request_budget']} · 이번 수집 {report['new_observations']}건", "",
             "이 보고서는 제목·링크·검색지수 수집 및 검토 후보 목록이다. 기사 본문 완독, 한국 전체 조사, 사업성 검증을 뜻하지 않는다.", "",
             f"분류표: {c['taxonomy_domains']}개 분야 / {c['taxonomy_subfields']}개 세부항목. 실제 조회 성공 {c['successfully_queried_domains']}개 분야; 심층 검토 {c['human_or_agent_reviewed_domains']}개.", "",
             "## 연결 결과", "", "| 출처 | 검색어 | 상태 | 건수 |", "|---|---|---|---|"]
    for s in report["sources"]:
        lines.append(f"| {md(s['source'])} | {md(s['query'])} | {s['status']} | {s.get('items', 0)} |")
    for s in report["unavailable"]:
        lines.append(f"| {s['source']} | — | {s['status']} | — |")
    lines += ["", "미구현/별도 승인 필요: " + ", ".join(report["not_connected"]),
              "", "이번 실행에서 비활성인 구현 소스: " + (", ".join(report.get("disabled_sources", [])) or "없음"),
              f"요청 예산으로 다음 실행에 미룬 조회: {len(report['deferred'])}개", "",
              "## 후속 검토 후보", "", "아래는 검증된 사업기회가 아니다. 중복 기사·광고·일회성 사건·계절성을 확인한 뒤 고객의 반복 문제와 지불 행동을 조사한다.", ""]
    ranked = sorted(report["trends"], key=lambda t: (t["candidate_stage"] != "Emerging_candidate", not t["negative_signal"], -t["dated_recent_observations"]))
    for t in ranked[:20]:
        lines += [f"### {md(t['topic'])}", "", f"후보: {t['candidate_stage']} / 단계 미검토 / 신뢰도 제한적", "",
                  f"중복 정리 {t['deduped_observations']}건 · 출처 계열 {', '.join(t['signal_families']) or '없음'} · 검색 시계열 {t['growth']['status']}"]
        for i, url in enumerate(t["evidence_urls"][:3], 1):
            lines.append(f"- [출처 {i}]({url})")
        lines.append("")
    return "\n".join(lines)
