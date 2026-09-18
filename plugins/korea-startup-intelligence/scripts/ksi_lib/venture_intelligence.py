"""Cross-source signal intelligence and portfolio decision support.

The functions in this module are deliberately descriptive.  They connect
observed evidence, dossiers and founder constraints, but never turn a score
into a probability of startup success.  Missing inputs remain visible.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta

from .model import assets, credentials, digest, now, parse_date, stamp


DEMAND_KINDS = {"interview", "transaction", "aggregate_metric", "search_spike", "customer_observation"}
SUPPLY_KINDS = {"repository", "product", "app", "patent", "standard", "procurement_award", "crowdfunding"}
BEHAVIOR_KINDS = {"interview", "transaction", "customer_observation"}
PUBLIC_BEHAVIOR_KINDS = {"review", "comment"}
MARKET_SUPPLY_KINDS = {"product", "app", "procurement_award", "crowdfunding"}
EARLY_LANES = {
    "jobs", "patents", "standards", "papers", "technology_cost", "procurement",
    "app_store", "commerce", "crowdfunding", "regulation", "official_statistics",
}
SOURCE_LANES = {
    "github_new": "technology", "hackernews": "technology",
    "crossref_recent": "papers",
    "google_trends_rss": "search", "google_news_rss": "news",
    "naver_news": "news", "naver_blog": "community", "naver_cafe": "community",
    "naver_trend": "search", "youtube": "social", "youtube_uploads": "social",
    "youtube_stats": "social", "instagram": "social", "tiktok": "social",
    "x": "social", "threads": "social", "reddit": "community",
    "jobs": "jobs", "patents": "patents", "standards": "standards",
    "papers": "papers", "technology_cost": "technology_cost",
    "procurement": "procurement", "app_store": "app_store", "commerce": "commerce",
    "crowdfunding": "crowdfunding", "regulation": "regulation",
    "kosis": "official_statistics", "ecos": "official_statistics",
}


def _tokens(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return set(re.findall(r"[a-z0-9가-힣]{2,}", value))


def _token_list(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.findall(r"[a-z0-9가-힣]{2,}", value)


def _ngrams(value, size=3):
    value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).lower())
    return {value[i:i + size] for i in range(max(0, len(value) - size + 1))}


def _jaccard(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def glossary(store):
    """Return alias -> canonical term without claiming semantic completeness."""
    output = {}
    for row in store.records("wb_glossary"):
        canonical = str(row.get("term", "")).strip().lower()
        if not canonical:
            continue
        output[canonical] = canonical
        for alias in row.get("aliases", []):
            if isinstance(alias, str) and alias.strip():
                output[alias.strip().lower()] = canonical
    return output


def canonical_tokens(store, value):
    aliases = glossary(store)
    raw = _token_list(value)
    phrases = []
    for alias, canonical in aliases.items():
        source, target = tuple(_token_list(alias)), tuple(_token_list(canonical))
        if source and target:
            phrases.append((source, target))
    phrases.sort(key=lambda pair: (-len(pair[0]), pair[0]))
    output, index = [], 0
    while index < len(raw):
        match = next(((source, target) for source, target in phrases
                      if tuple(raw[index:index + len(source)]) == source), None)
        if match:
            output.extend(match[1])
            index += len(match[0])
        else:
            output.append(raw[index])
            index += 1
    return set(output)


def semantic_duplicate_warnings(store, candidates=None):
    """Hybrid customer/problem similarity, stronger than whole-text token overlap.

    This remains a review warning: Korean morphology and business semantics need
    a human/agent decision before records are merged.
    """
    candidates = candidates or store.records("blue_ocean")
    warnings = []
    for index, left in enumerate(candidates):
        left_customer = canonical_tokens(store, left.get("customer"))
        left_problem = canonical_tokens(store, left.get("problem"))
        for right in candidates[index + 1:]:
            customer = _jaccard(left_customer, canonical_tokens(store, right.get("customer")))
            problem_tokens = _jaccard(left_problem, canonical_tokens(store, right.get("problem")))
            problem_chars = _jaccard(_ngrams(left.get("problem")), _ngrams(right.get("problem")))
            problem = max(problem_tokens, problem_chars)
            shared_dossier = bool(left.get("dossier_id") and left.get("dossier_id") == right.get("dossier_id"))
            same_source = bool(left.get("source_opportunity_id") and
                               left.get("source_opportunity_id") == right.get("source_opportunity_id"))
            likely = shared_dossier or same_source or (customer >= .45 and problem >= .55)
            if likely:
                warnings.append({
                    "candidate_ids": [left["id"], right["id"]],
                    "customer_similarity": round(customer, 3),
                    "problem_similarity": round(problem, 3),
                    "shared_dossier": shared_dossier,
                    "same_source_opportunity": same_source,
                    "status": "semantic_review_required",
                    "action": "고객·상황·문제·현재 대안이 같은지 확인한 뒤 명시적으로 병합하거나 별도 유지",
                })
    return warnings


def _revision(store, kind, record_id):
    row = store.db.execute("SELECT revision FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
    return row[0] if row else 0


def _founder_file_fit(store, candidate):
    path = store.workspace / "FOUNDER_CONTEXT.md"
    if not path.exists():
        return None, "founder_context_missing", []
    values = {}
    for line in path.read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip("# ")] = value.strip()
    exclusions = values.get("제외 산업", "")
    excluded = [part.strip() for part in re.split(r"[,，/;]", exclusions)
                if part.strip() and part.strip() != "미확인"]
    domains = {row["id"]: row for row in assets("taxonomy.json")["domains"]}
    domain_text = " ".join(str(domains.get(did, {})) for did in candidate.get("domain_ids", []))
    candidate_text = " ".join(str(candidate.get(field, "")) for field in ("title", "customer", "problem")) + " " + domain_text
    matched_exclusions = [name for name in excluded if name in candidate_text]
    if matched_exclusions:
        return 0, "explicit_founder_context_exclusion", matched_exclusions
    accessible = values.get("접근 가능한 고객", "")
    if accessible and accessible != "미확인":
        shared = canonical_tokens(store, accessible) & canonical_tokens(store, candidate.get("customer"))
        if shared:
            return 2, "founder_context_customer_access_overlap_unconfirmed", sorted(shared)
    return None, "founder_fit_not_confirmed", []


def _fit_value(store, candidate):
    candidate_id = candidate["id"]
    fit = next((r for r in store.records("founder_fit") if r.get("candidate_id") == candidate_id), None)
    profile = next(iter(store.records("founder_profile")), None)
    if fit and (not profile or fit.get("profile_revision") == _revision(store, "founder_profile", profile["id"])):
        return ({"aligned": 3, "conditional": 2, "unknown": 1, "misaligned": 0}.get(fit.get("decision")),
                "structured_founder_fit", [])
    return _founder_file_fit(store, candidate)


def _pareto(rows):
    dimensions = ("business_value", "founder_fit", "option_value", "reachability")
    for row in rows:
        row["dominated_by"] = []
        row["unknown_dimensions"] = [k for k in dimensions if row["decision_vector"].get(k) is None]
        row["comparison_status"] = "incomplete" if row["unknown_dimensions"] else "comparable"
        if row["unknown_dimensions"]:
            continue
        for other in rows:
            if other is row or any(other["decision_vector"].get(k) is None for k in dimensions):
                continue
            a, b = other["decision_vector"], row["decision_vector"]
            if all(a[k] >= b[k] for k in dimensions) and any(a[k] > b[k] for k in dimensions):
                row["dominated_by"].append(other["candidate_id"])
    return rows


def portfolio_decisions(store, assessment_fn):
    """Build an explainable non-probabilistic comparison for all candidates."""
    rows = []
    for candidate in store.records("blue_ocean"):
        assessment = assessment_fn(store, candidate)
        backed = set(assessment["evidence_backed_assessments"])
        business_value = sum(name in backed for name in ("problem", "current_spend", "supply_gap", "timing"))
        reachability = 1 if "reachability" in backed else 0
        action = candidate.get("next_action") or {}
        cost = action.get("estimated_cost_krw")
        if type(cost) is int:
            option_value = 3 if cost == 0 else 2 if cost <= 100_000 else 1 if cost <= 1_000_000 else 0
            if action.get("external_action_required") is False:
                option_value = min(3, option_value + 1)
        else:
            option_value = None
        fit, fit_basis, fit_notes = _fit_value(store, candidate)
        rows.append({
            "candidate_id": candidate["id"], "title": candidate["title"], "stage": candidate["stage"],
            "decision_vector": {"business_value": business_value, "founder_fit": fit,
                                "option_value": option_value, "reachability": reachability},
            "validation_cost_krw": cost, "review_overdue": assessment["review_overdue"],
            "founder_fit_basis": fit_basis, "founder_fit_notes": fit_notes,
            "blocking_gap_count": len(assessment["blocking_gaps"]),
            "boundary": "비교 가능한 의사결정 차원이며 성공확률이나 시장점수가 아닙니다.",
        })
    _pareto(rows)
    stage_order = {"scaling": 0, "launched": 1, "building": 2, "validating": 3,
                   "researching": 4, "watching": 5, "detected": 6, "parked": 7, "killed": 8}
    rows.sort(key=lambda row: (row["comparison_status"] != "comparable", bool(row["dominated_by"]),
                               not row["review_overdue"],
                               -sum(v for v in row["decision_vector"].values() if v is not None),
                               stage_order.get(row["stage"], 99), row["candidate_id"]))
    return {"items": rows, "pareto_frontier": [r["candidate_id"] for r in rows
                                                  if r["comparison_status"] == "comparable" and not r["dominated_by"]],
            "comparison_pending": [r["candidate_id"] for r in rows if r["comparison_status"] == "incomplete"],
            "ordering": "비교값 완비→비지배 후보→재검토 기한→확인된 사업가치·적합성·선택가치·접근성. 미확인은 우수 후보로 간주하지 않음. 성공확률 아님."}


def _event_time(row):
    return parse_date(row.get("event_at")) or parse_date(row.get("observed_at"))


def _comparison_series(rows, reviewed_body):
    """Return only explicitly keyed, same-basis demand/supply observations."""
    grouped = defaultdict(lambda: defaultdict(lambda: {"demand": [], "supply": []}))
    definitions = defaultdict(lambda: {"demand": set(), "supply": set()})
    for row in rows:
        key, role, measurement = row.get("comparison_key"), row.get("demand_or_supply"), row.get("measurement")
        value = row.get("metrics", {}).get("value")
        if not key or role not in ("demand", "supply") or not isinstance(measurement, dict) or \
                isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
            continue
        if row.get("collection_basis") not in ("user_owned", "authorized_export") and not reviewed_body(row):
            continue
        required = ("definition", "unit", "population", "period", "normalization", "vintage")
        if any(not isinstance(measurement.get(field), str) or not measurement[field].strip() for field in required):
            continue
        basis = (measurement["unit"], measurement["population"], measurement["normalization"], measurement["vintage"])
        group_key = (key, basis)
        grouped[group_key][measurement["period"]][role].append((row, value))
        definitions[group_key][role].add(measurement.get("definition"))
    output = []
    for (key, basis), periods in grouped.items():
        points = []
        for period, roles in sorted(periods.items()):
            if len(roles["demand"]) != 1 or len(roles["supply"]) != 1:
                continue
            demand_row, demand_value = roles["demand"][0]
            supply_row, supply_value = roles["supply"][0]
            if (demand_row.get("origin_key") or demand_row["url"]) == (supply_row.get("origin_key") or supply_row["url"]):
                continue
            points.append({"period": period, "demand": demand_value, "supply": supply_value,
                           "difference": demand_value - supply_value,
                           "demand_evidence_id": demand_row["id"], "supply_evidence_id": supply_row["id"]})
        if points:
            change = points[-1]["difference"] - points[0]["difference"] if len(points) >= 3 else None
            output.append({"comparison_key": key, "unit": basis[0], "population": basis[1],
                           "normalization": basis[2], "vintage": basis[3],
                           "demand_definitions": sorted(definitions[(key, basis)]["demand"]),
                           "supply_definitions": sorted(definitions[(key, basis)]["supply"]), "points": points,
                           "status": "three_or_more_completed_periods" if len(points) >= 3 else "insufficient_periods",
                           "difference_change": change,
                           "boundary": "명시된 동일 비교 기준의 기술 차이입니다. 시장 전체 수요·공급 또는 인과적 기회 증명이 아닙니다."})
    return sorted(output, key=lambda row: row["comparison_key"])


def signal_graph(store):
    observations = store.observations()
    from .radar import evidence_signature
    reviews = {}
    if store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_reviews'").fetchone():
        reviews = {row["evidence_id"]: row for row in store.db.execute(
            "SELECT evidence_id,reviewed_at,evidence_hash,data FROM source_reviews")}

    def reviewed_body(row):
        review = reviews.get(row["id"])
        return bool(review and review["evidence_hash"] == evidence_signature(row) and
                    parse_date(review["reviewed_at"]) and
                    parse_date(review["reviewed_at"]) >= now() - timedelta(days=14) and
                    json.loads(review["data"]).get("read_scope") != "metadata_only")

    def origin(row):
        return row.get("origin_key") or row.get("publisher") or row["url"]

    groups = defaultdict(list)
    for row in observations:
        concept = " ".join(sorted(canonical_tokens(store, row.get("topic") or row.get("title"))))
        if not concept:
            concept = row["id"]
        groups[digest(concept)[:16]].append(row)
    clusters = []
    for key, rows in groups.items():
        rows.sort(key=lambda row: _event_time(row) or now())
        origins = {origin(row) for row in rows}
        lanes = {SOURCE_LANES.get(row.get("source"), row.get("source", "unknown")) for row in rows}
        geographies = {row.get("geography", "unknown") for row in rows}
        dates = {_event_time(row).date().isoformat() for row in rows if _event_time(row)}
        first_by_lane = {}
        for row in rows:
            lane = SOURCE_LANES.get(row.get("source"), row.get("source", "unknown"))
            when = _event_time(row)
            if when and (lane not in first_by_lane or when < parse_date(first_by_lane[lane])):
                first_by_lane[lane] = stamp(when)
        ordered = sorted(first_by_lane.items(), key=lambda pair: pair[1])
        lead_lag = []
        for (left, left_at), (right, right_at) in zip(ordered, ordered[1:]):
            lead_lag.append({"from": left, "to": right,
                             "seconds": (parse_date(right_at) - parse_date(left_at)).total_seconds()})
        demand = [row for row in rows if row.get("kind") in DEMAND_KINDS or
                  row.get("demand_or_supply") == "demand"]
        supply = [row for row in rows if row.get("kind") in SUPPLY_KINDS or
                  row.get("demand_or_supply") == "supply"]
        behavior = [row for row in rows if (row.get("kind") in BEHAVIOR_KINDS or
                                             (row.get("kind") in PUBLIC_BEHAVIOR_KINDS and
                                              row.get("speaker_role") == "customer")) and
                    not row.get("promotion_or_ad") and
                    (row.get("collection_basis") in ("user_owned", "authorized_export") or reviewed_body(row))]
        behavior_origins = {origin(row) for row in behavior}
        behavior_days = {_event_time(row).date().isoformat() for row in behavior if _event_time(row)}
        market_supply_origins = {origin(row) for row in rows if row.get("kind") in MARKET_SUPPLY_KINDS}
        comparisons = _comparison_series(rows, reviewed_body)
        low_base = any(type(value) in (int, float) and 0 <= value < 10 and
                       (metric.endswith("_count") or metric.endswith("_views") or metric in ("views", "transactions"))
                       for row in rows for metric, value in row.get("metrics", {}).items())
        risks = []
        if len(origins) < 2:
            risks.append("single_origin")
        if len(lanes) < 2:
            risks.append("single_signal_lane")
        if low_base:
            risks.append("low_baseline")
        if not behavior and all(lane in {"news", "social"} for lane in lanes):
            risks.append("attention_only_no_behavioral_demand")
        if demand and not behavior:
            risks.append("demand_proxy_without_customer_behavior")
        if behavior and not market_supply_origins:
            risks.append("market_supply_not_sampled")
        if behavior and market_supply_origins and not comparisons:
            risks.append("demand_supply_sampling_not_comparable")
        if any(row.get("promotion_or_ad") for row in rows):
            risks.append("promotion_or_ad")
        if any(row.get("seasonal_event") for row in rows):
            risks.append("possible_seasonality")
        if any(row.get("bot_or_coordinated") for row in rows):
            risks.append("possible_coordination")
        clusters.append({
            "cluster_id": "signal-cluster-" + key,
            "topics": sorted({row.get("topic") for row in rows if row.get("topic")}),
            "evidence_ids": [row["id"] for row in rows], "origins": len(origins),
            "lanes": sorted(lanes), "geographies": sorted(geographies),
            "velocity": _cluster_velocity(store, rows), "breadth": len(lanes) + len(geographies),
            "persistence_days": len(dates), "novelty": _cluster_novelty(rows),
            "manipulation_risks": risks, "first_by_lane": first_by_lane, "lead_lag": lead_lag,
            "demand_signals": len(demand), "supply_signals": len(supply),
            "behavioral_demand_origins": len(behavior_origins), "behavioral_demand_days": len(behavior_days),
            "market_supply_origins": len(market_supply_origins),
            "explicit_comparisons": comparisons,
            "raw_observation_count_difference": len(demand) - len(supply),
            "comparison_basis": "unmatched_raw_observation_counts_not_market_gap",
            "gap_status": "comparable_series_observed" if any(c["status"] == "three_or_more_completed_periods" for c in comparisons) else
                          "comparable_points_insufficient" if comparisons else
                          "comparison_design_needed" if behavior_origins and market_supply_origins else
                          "supply_audit_needed" if behavior_origins and not market_supply_origins else
                          "proxy_only" if demand and not behavior else "unresolved",
        })
    clusters.sort(key=lambda row: (-row["behavioral_demand_origins"], -row["persistence_days"], row["cluster_id"]))
    return {"clusters": clusters, "observation_count": len(observations),
            "boundary": "동일 개념 후보를 묶은 기술통계입니다. 동일 사건·인과·수요는 원문 검토로 확인해야 합니다."}


def _cluster_velocity(store, rows):
    ids = {row["url"] for row in rows}
    samples = [dict(row) for row in store.db.execute(
        "SELECT source,url,metric,observed_at,value FROM metric_samples ORDER BY observed_at") if row["url"] in ids]
    changes = []
    grouped = defaultdict(list)
    for row in samples:
        grouped[(row["source"], row["url"], row["metric"])].append(row)
    for key, values in grouped.items():
        if len(values) < 2:
            continue
        first, last = values[0], values[-1]
        seconds = (parse_date(last["observed_at"]) - parse_date(first["observed_at"])).total_seconds()
        if seconds > 0:
            changes.append({"source": key[0], "metric": key[2],
                            "change_per_day": (last["value"] - first["value"]) / seconds * 86400,
                            "samples": len(values), "elapsed_seconds": seconds})
    return changes


def _cluster_novelty(rows):
    dated = sorted((_event_time(row) for row in rows if _event_time(row)))
    if not dated:
        return {"status": "unknown", "age_days": None}
    age = (now() - dated[0]).total_seconds() / 86400
    return {"status": "new" if age <= 30 else "established" if age <= 365 else "long_running",
            "age_days": round(age, 2)}


def opportunity_patterns(store):
    graph = signal_graph(store)
    reverse = []
    evergreen = []
    for cluster in graph["clusters"]:
        falling = any(change["change_per_day"] < 0 for change in cluster["velocity"])
        if falling:
            reverse.append({"cluster_id": cluster["cluster_id"], "topics": cluster["topics"],
                            "hypothesis": "감소·퇴출·공급 축소가 남긴 전환·이전·유지보수 문제를 조사",
                            "status": "research_prompt_not_opportunity"})
        if cluster["behavioral_demand_days"] >= 3 and cluster["behavioral_demand_origins"] >= 2:
            evergreen.append({"cluster_id": cluster["cluster_id"], "topics": cluster["topics"],
                              "persistence_days": cluster["persistence_days"],
                              "status": "persistent_problem_candidate"})
    measured = [comparison for row in graph["clusters"] for comparison in row["explicit_comparisons"]]
    return {"demand_supply_gaps": [],
            "measured_comparisons": measured,
            "gap_investigations": [row for row in graph["clusters"]
                                   if row["gap_status"] in ("supply_audit_needed", "comparison_design_needed")],
            "reverse_opportunities": reverse, "evergreen_pains": evergreen}


def overseas_korea_lag(store):
    rows = []
    for cluster in signal_graph(store)["clusters"]:
        evidence = {row["id"]: row for row in store.observations()}
        foreign = [_event_time(evidence[eid]) for eid in cluster["evidence_ids"]
                   if evidence[eid].get("geography") not in (None, "KR", "unknown") and _event_time(evidence[eid])]
        korea = [_event_time(evidence[eid]) for eid in cluster["evidence_ids"]
                 if evidence[eid].get("geography") == "KR" and _event_time(evidence[eid])]
        if foreign:
            first_foreign = min(foreign)
            first_korea = min(korea) if korea else None
            rows.append({"cluster_id": cluster["cluster_id"], "topics": cluster["topics"],
                         "foreign_first_at": stamp(first_foreign),
                         "korea_first_at": stamp(first_korea) if first_korea else None,
                         "lag_days": round((first_korea - first_foreign).total_seconds() / 86400, 2)
                                     if first_korea and first_korea >= first_foreign else None,
                         "status": "measured" if first_korea else "korea_signal_not_observed"})
    return rows


def cross_industry_transfers(store):
    by_problem = defaultdict(list)
    for candidate in store.records("blue_ocean"):
        signature = " ".join(sorted(canonical_tokens(store, candidate.get("problem"))))
        if signature:
            by_problem[signature].append(candidate)
    output = []
    for signature, rows in by_problem.items():
        domains = sorted({domain for row in rows for domain in row.get("domain_ids", [])})
        if len(domains) >= 2:
            output.append({"problem_signature": signature, "domain_ids": domains,
                           "candidate_ids": [row["id"] for row in rows],
                           "transfer_questions": ["원래 산업의 작동 원리는 무엇인가?", "새 산업의 구매·규제·유통 차이는 무엇인가?",
                                                  "이전이 실패할 조건은 무엇인가?"],
                           "status": "comparison_required"})
    return output


def business_structures(candidate):
    return [
        {"model": "managed_service", "wedge": "먼저 사람이 수동으로 결과를 제공", "risk": "반복 수요와 인력 한계"},
        {"model": "workflow_tool", "wedge": "가장 비싼 한 작업만 도구화", "risk": "기존 도구 전환 비용"},
        {"model": "distribution", "wedge": "검증된 공급을 좁은 고객에게 연결", "risk": "마진·반품·채널 의존"},
        {"model": "marketplace", "wedge": "한쪽 공급을 먼저 확보", "risk": "양면 초기 유동성"},
        {"model": "physical_or_hybrid", "wedge": "현장 작업과 소프트웨어를 함께 설계", "risk": "재고·인증·운영 자본"},
    ]


def channel_map(store, candidate):
    profile = next(iter(store.records("founder_profile")), {})
    access = profile.get("customer_access", [])
    dossier = next((d for d in store.records("dossier") if d["id"] == candidate.get("dossier_id")), {})
    distribution = dossier.get("findings", {}).get("distribution", {})
    channels = [{"channel": item, "basis": "founder_confirmed_access", "verified": True} for item in access]
    if distribution.get("conclusion"):
        channels.append({"channel": distribution["conclusion"], "basis": "dossier_finding",
                         "verified": False,
                         "research_status": distribution.get("status")})
    return {"candidate_id": candidate["id"], "channels": channels,
            "reachable": any(item["verified"] for item in channels),
            "boundary": "접근 경로 지도이며 고객의 응답·구매 승인이 아닙니다."}


def saturation(store, candidate):
    competitors = []
    dossier = next((d for d in store.records("dossier") if d["id"] == candidate.get("dossier_id")), None)
    if dossier:
        competitors = dossier.get("competitors", [])
    events = [e for e in store.records("blue_ocean_event") if e.get("candidate_id") == candidate["id"]]
    entries = [e for e in events if "major_company" in e.get("reason", "") or
               e.get("change_kind") == "major_company_entry"]
    price_pressure = [o for o in store.observations() if o.get("kind") == "price_change" and
                      canonical_tokens(store, o.get("topic")) & canonical_tokens(store, candidate.get("problem"))]
    status = "review_required"
    if len(competitors) >= 5 or len(entries) >= 2:
        status = "saturation_risk"
    elif competitors:
        status = "competition_observed"
    return {"candidate_id": candidate["id"], "status": status, "competitor_count": len(competitors),
            "major_company_entries": len(entries), "price_pressure_signals": len(price_pressure),
            "measured_at": stamp(), "boundary": "관측된 대안과 진입 신호의 추적이며 전체 시장점유율이 아닙니다."}


def entry_dynamics(store, candidate):
    """Contrast an accessible narrow wedge with large-company response risk."""
    channels = channel_map(store, candidate)
    competition = saturation(store, candidate)
    dossier = next((row for row in store.records("dossier") if row["id"] == candidate.get("dossier_id")), None)
    capital = (dossier or {}).get("findings", {}).get("capital_intensity", {})
    cost = (candidate.get("next_action") or {}).get("estimated_cost_krw")
    risks = []
    if not channels["reachable"]:
        risks.append("initial_customer_channel_unconfirmed")
    if competition["status"] == "saturation_risk":
        risks.append("observed_competitor_saturation")
    if competition["major_company_entries"]:
        risks.append("large_company_entry_observed")
    if capital.get("status") not in ("FACT", "INFERENCE"):
        risks.append("capital_requirement_unknown")
    if cost is None:
        risks.append("initial_validation_cost_unknown")
    return {"candidate_id": candidate["id"], "smallest_wedge": candidate["smallest_wedge"],
            "business_structures": business_structures(candidate), "channel_map": channels,
            "saturation": competition, "capital_intensity_finding": capital,
            "validation_cost_krw": cost, "risks": risks,
            "decision": "narrow_entry_experiment_available" if not risks else "entry_hypothesis_needs_review",
            "boundary": "좁은 진입점과 대기업 진입 위험의 검토 틀이지 방어 가능한 해자나 독점 증명이 아닙니다."}


RULE_FIELDS = {
    "validation_outcome", "evidence_count", "customer_evidence_count", "transaction_count",
    "active_users", "retention_rate", "repeat_purchase_rate", "gross_margin", "cac_krw",
    "competitor_count",
}
RULE_EVIDENCE_KINDS = {
    "article", "post", "comment", "job", "patent", "standard", "paper", "price_change",
    "procurement", "procurement_award", "app", "review", "product", "crowdfunding",
    "regulation", "aggregate_metric", "search_spike", "customer_observation", "manual_evidence",
    "interview", "transaction", "repository",
}
SCOPED_RULE_FIELDS = {
    "evidence_count", "customer_evidence_count", "transaction_count", "active_users",
    "retention_rate", "repeat_purchase_rate", "gross_margin", "cac_krw",
}


def validate_condition_set(value, name):
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > 12:
        raise ValueError(f"{name}: 최대 12개 구조화 조건이 필요합니다.")
    output = []
    for row in value:
        if not isinstance(row, dict) or row.get("field") not in RULE_FIELDS or row.get("operator") not in ("gte", "lte", "eq", "in"):
            raise ValueError(f"{name}: 지원 field와 gte/lte/eq/in 연산자를 사용하세요.")
        if "value" not in row:
            raise ValueError(f"{name}: 비교 value가 필요합니다.")
        window = row.get("window_days")
        if window is not None and (type(window) is not int or not 1 <= window <= 3650):
            raise ValueError(f"{name}: window_days는 1~3650 정수입니다.")
        evidence_kinds = row.get("evidence_kinds", [])
        if not isinstance(evidence_kinds, list) or len(evidence_kinds) > 12 or \
                any(not isinstance(item, str) or item not in RULE_EVIDENCE_KINDS for item in evidence_kinds):
            raise ValueError(f"{name}: evidence_kinds는 지원되는 근거 종류 최대 12개입니다.")
        if (window is not None or evidence_kinds) and row["field"] not in SCOPED_RULE_FIELDS:
            raise ValueError(f"{name}: {row['field']}에는 기간·근거 종류 필터를 적용할 수 없습니다.")
        output.append({"field": row["field"], "operator": row["operator"], "value": row["value"],
                       "window_days": window, "evidence_kinds": evidence_kinds})
    return output


def condition_facts(store, candidate, window_days=None, evidence_kinds=None):
    ids = set(candidate.get("evidence_ids", []))
    observations = [o for o in store.observations() if o["id"] in ids]
    if evidence_kinds:
        observations = [o for o in observations if o.get("kind") in set(evidence_kinds)]
    if window_days is not None:
        threshold = now() - timedelta(days=window_days)
        observations = [o for o in observations if _event_time(o) and _event_time(o) >= threshold]
    observations.sort(key=lambda row: _event_time(row) or now())
    facts = {
        "evidence_count": len(observations),
        "customer_evidence_count": sum((o.get("kind") in
                                        ("interview", "transaction", "customer_observation", "aggregate_metric")) and
                                       o.get("collection_basis") in ("user_owned", "authorized_export")
                                       for o in observations),
        "transaction_count": sum(o.get("kind") == "transaction" for o in observations),
        "competitor_count": saturation(store, candidate)["competitor_count"],
        "evaluated_evidence_ids": [o["id"] for o in observations],
    }
    metrics = {}
    for observation in observations:
        metrics.update({k: v for k, v in observation.get("metrics", {}).items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)})
    for field in ("active_users", "retention_rate", "repeat_purchase_rate", "gross_margin", "cac_krw"):
        facts[field] = metrics.get(field)
    if candidate.get("dossier_id"):
        plan_ids = {p["id"] for p in store.records("validation_plan") if p.get("dossier_id") == candidate["dossier_id"]}
        outcomes = [r.get("outcome") for r in store.records("validation_result") if r.get("plan_id") in plan_ids]
        facts["validation_outcome"] = outcomes[-1] if outcomes else None
    else:
        facts["validation_outcome"] = None
    return facts


def evaluate_conditions(store, candidate, rules):
    facts = condition_facts(store, candidate)
    results = []
    for rule in rules:
        scoped = condition_facts(store, candidate, rule.get("window_days"), rule.get("evidence_kinds")) \
                 if rule["field"] in SCOPED_RULE_FIELDS else facts
        actual, expected, operator = scoped.get(rule["field"]), rule["value"], rule["operator"]
        matched = False
        if actual is not None:
            try:
                matched = ((operator == "gte" and actual >= expected) or
                           (operator == "lte" and actual <= expected) or
                           (operator == "eq" and actual == expected) or
                           (operator == "in" and actual in expected))
            except (TypeError, ValueError):
                matched = False
        results.append({"rule": rule, "actual": actual, "matched": matched,
                        "evaluated_evidence_ids": scoped["evaluated_evidence_ids"]})
    return {"matched": bool(results) and all(row["matched"] for row in results), "results": results, "facts": facts}


def source_capabilities(store):
    registered = {row["id"]: row for row in assets("sources.json")}
    available_keys = credentials(store.workspace)
    enabled = set(store.config.get("enabled_sources", []))
    lanes = defaultdict(lambda: {"live_sources": [], "available_import": True, "status": "import_or_browser_review"})
    for source, lane in SOURCE_LANES.items():
        spec = registered.get(source)
        if spec and spec.get("adapter"):
            lanes[lane]["live_sources"].append(source)
            if source in enabled:
                lanes[lane]["status"] = "enabled_connector"
    for lane in EARLY_LANES:
        lanes[lane]
    details = []
    for source, spec in registered.items():
        latest = store.db.execute("SELECT status,attempted_at FROM fetches WHERE source=? ORDER BY id DESC LIMIT 1", (source,)).fetchone()
        missing = [key for key in spec.get("credentials", []) if key not in available_keys]
        details.append({"source": source, "adapter": bool(spec.get("adapter")),
                        "enabled": source in enabled, "credential_ready": not missing,
                        "missing_key_names": missing, "last_attempt": dict(latest) if latest else None,
                        "live_verified_in_this_workspace": bool(latest and latest["status"] == "ok"),
                        "fallback": "reviewed_public_page_or_authorized_export" if not spec.get("adapter") else None})
    return {"lanes": dict(lanes), "source_details": details,
            "boundary": "enabled_connector만 자동 수집 대상입니다. 나머지는 Codex 공개 웹 검토 또는 허용 export 접수 경로입니다."}


def source_yield(store):
    opportunities = store.records("opportunity")
    observations = {row["id"]: row for row in store.observations()}
    denominator = Counter(row["source"] for row in observations.values())
    useful = Counter()
    for card in opportunities:
        for source in {observations[eid]["source"] for eid in card.get("evidence_ids", []) if eid in observations}:
            useful[source] += 1
    return [{"source": source, "observations": count, "opportunities": useful[source],
             "opportunities_per_observation": useful[source] / count if count else None}
            for source, count in sorted(denominator.items())]


def performance_metrics(store):
    from . import blue_ocean
    forecasts = store.records("trend_forecast")
    forecast_results = store.records("trend_forecast_result")
    result_map = {row["forecast_id"]: row for row in forecast_results}
    leads = [row.get("lead_seconds") for row in forecast_results if row.get("lead_seconds") is not None]
    candidates = store.records("blue_ocean")
    confirmed = 0
    for candidate in candidates:
        if "problem" in blue_ocean.assess(store, candidate)["evidence_backed_assessments"]:
            confirmed += 1
    validations = store.records("validation_result")
    stopped = sum(row.get("outcome") == "stop_criterion_met" for row in validations)
    observations = {o["id"]: o for o in store.observations()}
    paid_candidates = {candidate["id"] for candidate in candidates
                       if any(observations.get(eid, {}).get("kind") == "transaction" and
                              observations[eid].get("collection_basis") in ("user_owned", "authorized_export")
                              for eid in candidate.get("evidence_ids", []))}
    evaluated = [row for row in forecasts if type(result_map.get(row["id"], {}).get("truth")) is bool]
    detected_positive = sum(bool(row.get("detected")) for row in evaluated)
    false_positive = sum(result_map.get(row["id"], {}).get("truth") is False and row.get("detected") is True for row in forecasts)
    false_negative = sum(result_map.get(row["id"], {}).get("truth") is True and row.get("detected") is not True for row in forecasts)
    actual_positive = sum(result_map.get(row["id"], {}).get("truth") is True for row in forecasts)
    decision_durations = []
    for candidate in candidates:
        events = sorted((e for e in store.records("blue_ocean_event") if e.get("candidate_id") == candidate["id"]),
                        key=lambda row: row.get("recorded_at", ""))
        terminal = next((e for e in events if e.get("to_stage") in ("parked", "killed", "launched", "scaling")), None)
        if events and terminal:
            decision_durations.append((parse_date(terminal["recorded_at"]) - parse_date(events[0]["recorded_at"])).total_seconds())
    usability = store.records("wb_usability")
    manual = [r for r in usability if r.get("condition") == "manual" and r.get("completed")]
    plugin = [r for r in usability if r.get("condition") == "plugin" and r.get("completed")]
    avg = lambda rows: sum(r.get("minutes", 0) for r in rows) / len(rows) if rows else None
    manual_avg, plugin_avg = avg(manual), avg(plugin)
    return {
        "lead_time_to_baseline": {"mean_seconds": sum(leads) / len(leads) if leads else None, "n": len(leads)},
        "problem_confirmation_rate": confirmed / len(candidates) if candidates else None,
        "problem_confirmation_denominator": len(candidates),
        "validation_stop_rate": stopped / len(validations) if validations else None,
        "validation_denominator": len(validations),
        "paid_experiment_reach_rate": len(paid_candidates) / len(candidates) if candidates else None,
        "paid_candidate_count": len(paid_candidates),
        "paid_candidate_denominator": len(candidates),
        "false_positive_rate": false_positive / detected_positive if detected_positive else None,
        "false_positive_denominator": detected_positive,
        "miss_rate_within_registered_truth_set": false_negative / actual_positive if actual_positive else None,
        "miss_denominator_registered_actual_positive": actual_positive,
        "source_yield": source_yield(store),
        "mean_seconds_to_decision": sum(decision_durations) / len(decision_durations) if decision_durations else None,
        "decision_n": len(decision_durations),
        "time_saved_minutes": manual_avg - plugin_avg if manual_avg is not None and plugin_avg is not None else None,
        "usability_manual_n": len(manual), "usability_plugin_n": len(plugin),
        "boundary": "등록·관측된 분모에 한한 기술통계입니다. 전체 시장 성과나 플러그인 인과효과가 아닙니다.",
    }


def filter_candidates(store, query=None, domains=None, stages=None, max_budget=None, due_before=None):
    domains, stages = set(domains or []), set(stages or [])
    deadline = parse_date(due_before) if due_before else None
    rows = []
    for candidate in store.records("blue_ocean"):
        action = candidate.get("next_action") or {}
        if query and query.lower() not in (candidate.get("title", "") + " " + candidate.get("customer", "") + " " + candidate.get("problem", "")).lower():
            continue
        if domains and not domains.intersection(candidate.get("domain_ids", [])):
            continue
        if stages and candidate.get("stage") not in stages:
            continue
        if max_budget is not None and (type(action.get("estimated_cost_krw")) is not int or action["estimated_cost_krw"] > max_budget):
            continue
        if deadline and (not parse_date(action.get("due_at")) or parse_date(action["due_at"]) > deadline):
            continue
        rows.append(candidate)
    return rows


def catch_up(store, since):
    since_at = parse_date(since)
    if not since_at or since_at > now():
        raise ValueError("catch-up 기준 시각은 현재보다 이전인 ISO 시각이어야 합니다.")
    events = [e for e in store.records("blue_ocean_event") if parse_date(e.get("recorded_at")) and parse_date(e["recorded_at"]) >= since_at]
    new_observations = [o for o in store.observations() if parse_date(o.get("observed_at")) >= since_at]
    due = [c["id"] for c in store.records("blue_ocean") if c.get("review_after") and parse_date(c["review_after"]) <= now()]
    return {"since": stamp(since_at), "generated_at": stamp(), "events": events,
            "new_observation_ids": [o["id"] for o in new_observations], "overdue_candidate_ids": due,
            "source_changes": [r for r in store.records("wb_source_change")
                               if parse_date(r.get("recorded_at") or r.get("updated_at")) and
                               parse_date(r.get("recorded_at") or r.get("updated_at")) >= since_at],
            "boundary": "저장된 기간의 따라잡기이며 앱이 꺼진 동안 수집되지 않은 자료의 완전 복원은 아닙니다."}
