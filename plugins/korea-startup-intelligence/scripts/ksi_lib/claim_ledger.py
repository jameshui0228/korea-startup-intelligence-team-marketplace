"""Claim-scoped evidence checks, not automated verification of semantic truth."""
from __future__ import annotations

import json
import re
from datetime import timedelta

from .model import digest, now, parse_date


RELATIONS = {"supports", "contradicts", "context"}
STATUSES = {"FACT", "INFERENCE", "ASSUMPTION", "UNKNOWN"}
BASES = {
    "direct_customer", "observed_behavior", "official_research", "official_rule",
    "provider_claim", "analyst_inference", "measured_series", "transaction", "aggregate_measurement",
}
CORE_FIELDS = ("customer", "problem", "payer", "current_alternative",
               "structural_change", "why_now", "korea_wedge")
CHANGE_FIELDS = ("structural_change", "why_now")
CLAIM_FIELDS = CORE_FIELDS + ("current_spend", "supply_gap", "non_obvious_insight",
                              "incumbent_disadvantage", "business_model", "first_users")
CUSTOMER_BASES = {"direct_customer", "observed_behavior", "official_research",
                  "transaction", "aggregate_measurement"}
SUPPORT_BASES = {
    "customer": CUSTOMER_BASES,
    "problem": CUSTOMER_BASES,
    "payer": {"direct_customer", "transaction", "aggregate_measurement"},
    "current_alternative": CUSTOMER_BASES,
    "current_spend": {"direct_customer", "transaction", "aggregate_measurement", "official_research"},
    "supply_gap": CUSTOMER_BASES | {"official_rule"},
    "structural_change": BASES - {"provider_claim", "analyst_inference"},
    "why_now": BASES - {"provider_claim", "analyst_inference"},
    "korea_wedge": CUSTOMER_BASES | {"official_rule", "measured_series"},
}
NEXT_CHECKS = {
    "customer": "초기 고객의 실제 역할·행동을 보여 주는 원문 확인",
    "problem": "고객이 반복해서 겪는 순간과 현재 우회 행동 확인",
    "payer": "현재 돈·예산을 쓰는 주체와 지불 단위 확인; 구매 의향과 거래 구분",
    "current_alternative": "한국의 직접·간접·수작업 대안과 실제 이용 방식 확인",
    "structural_change": "무엇이 언제 바뀌었는지 원 생산자 자료 확인",
    "why_now": "최근 변화가 이 고객의 비용·행동에 연결되는지 확인",
    "korea_wedge": "한국에 적용되는 규칙·가격·유통·고객 제약 확인",
}
SUPPORTED = {"SUPPORTED", "INFERRED"}
BINDING_FIELDS = ("source_signature", "review_signature", "claim_signature")


def _text(value, field, maximum=700, *, optional=False):
    if optional and value in (None, ""):
        return ""
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(f"{field}: 비어 있지 않은 {maximum}자 이내 문자열이 필요합니다.")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError(f"{field}: 제어 문자를 사용할 수 없습니다.")
    return " ".join(value.split())


def source_signature(row):
    # Measurement definitions, speaker identity and ad flags affect meaning;
    # retrieval/expiry timestamps do not.
    return digest({key: row.get(key) for key in (
        "id", "source", "kind", "topic", "title", "url", "event_at", "geography",
        "content_scope", "metrics", "series", "measurement", "domain_ids", "publisher", "origin_key",
        "collection_basis", "speaker_role", "change_kind", "limitations", "demand_or_supply",
        "promotion_or_ad", "seasonal_event", "bot_or_coordinated", "comparison_key",
    )})


def review_signature(review):
    return digest({key: value for key, value in review.items() if key != "reviewed_at"})


def current_reviews(store):
    exists = store.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_reviews'"
    ).fetchone()
    if not exists:
        return {}
    from .radar import evidence_signature
    observations = {row["id"]: row for row in store.observations()}
    current, output = now(), {}
    for row in store.db.execute("SELECT evidence_id,evidence_hash,reviewed_at,data FROM source_reviews"):
        source = observations.get(row["evidence_id"])
        date = parse_date(row["reviewed_at"])
        if not source or row["evidence_hash"] != evidence_signature(source) or not date or \
                not timedelta(0) <= current - date <= timedelta(days=14):
            continue
        try:
            data = json.loads(row["data"])
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("read_scope") in {"relevant_sections", "full_text"}:
            output[row["evidence_id"]] = data
    return output


def _claim_signature(field, statement, link):
    return digest([field, statement, *[link.get(key) for key in
                                      ("evidence_id", "relation", "basis", "locator", "note")]])


def normalize_claims(raw_claims, candidate, observations, reviewed, previous=None):
    """Bind new links; preserve old bindings on resubmission until explicit recheck."""
    if raw_claims is None:
        if (previous or {}).get("claims"):
            raise ValueError("기존 claims를 생략할 수 없습니다. frontier-claims의 후보를 이어서 수정하세요.")
        return {}
    if not isinstance(raw_claims, dict) or set(raw_claims) - set(CLAIM_FIELDS):
        raise ValueError("claims: 지원되는 주장 필드만 포함한 객체가 필요합니다.")
    previous_claims = (previous or {}).get("claims") or {}
    # Never silently drop a counterargument; keep it with an explicitly
    # rechecked relation and note when a new reading changes its relevance.
    for field, old_claim in previous_claims.items():
        old_counters = {link["evidence_id"] for link in old_claim.get("links", [])
                        if link.get("relation") == "contradicts"}
        value = raw_claims.get(field)
        new_links = value.get("links", []) if isinstance(value, dict) else []
        new_ids = {link.get("evidence_id") for link in new_links if isinstance(link, dict)} if isinstance(new_links, list) else set()
        if old_counters - new_ids:
            raise ValueError(f"claims.{field}: 기존 반례를 삭제하지 말고 재검토 관계·이유를 기록하세요.")
    allowed_ids = set(candidate.get("evidence_ids", [])) | set(candidate.get("counterevidence_ids", []))
    output = {}
    for field, value in raw_claims.items():
        if not isinstance(value, dict):
            raise ValueError(f"claims.{field}: 객체가 필요합니다.")
        statement = _text(value.get("statement", candidate.get(field)), f"claims.{field}.statement")
        if candidate.get(field) and statement != " ".join(candidate[field].split()):
            raise ValueError(f"claims.{field}.statement가 후보의 {field}와 일치하지 않습니다.")
        status = value.get("status", "UNKNOWN")
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError(f"claims.{field}.status: FACT/INFERENCE/ASSUMPTION/UNKNOWN을 사용하세요.")
        links = value.get("links", [])
        if not isinstance(links, list) or len(links) > 12:
            raise ValueError(f"claims.{field}.links: 최대 12개의 목록이 필요합니다.")
        old_links = {link["evidence_id"]: link for link in previous_claims.get(field, {}).get("links", [])}
        normalized, seen = [], set()
        for link in links:
            if not isinstance(link, dict):
                raise ValueError(f"claims.{field}.links: 객체가 필요합니다.")
            evidence_id = link.get("evidence_id")
            prior = old_links.get(evidence_id) if isinstance(evidence_id, str) else None
            if not isinstance(evidence_id, str) or evidence_id not in allowed_ids or \
                    (evidence_id not in observations and not prior):
                raise ValueError(f"claims.{field}: 새 연결에는 현재 유효한 근거 ID가 필요합니다.")
            if evidence_id in seen:
                raise ValueError(f"claims.{field}: 같은 근거를 중복 연결할 수 없습니다.")
            seen.add(evidence_id)
            if not isinstance(link.get("relation"), str) or link["relation"] not in RELATIONS or \
                    not isinstance(link.get("basis"), str) or link["basis"] not in BASES:
                raise ValueError(f"claims.{field}: relation과 basis를 명시하세요.")
            if link["relation"] == "contradicts" and evidence_id not in set(candidate.get("counterevidence_ids", [])):
                raise ValueError(f"claims.{field}: contradicts 근거는 counterevidence_ids에도 있어야 합니다.")
            if type(link.get("rechecked", False)) is not bool:
                raise ValueError(f"claims.{field}.rechecked: true/false가 필요합니다.")
            item = {"evidence_id": evidence_id, "relation": link["relation"], "basis": link["basis"],
                    "locator": _text(link.get("locator"), f"claims.{field}.locator", 400),
                    "note": _text(link.get("note"), f"claims.{field}.note", 600)}
            if link.get("rechecked"):
                if not prior or evidence_id not in reviewed:
                    raise ValueError(f"claims.{field}: 현재 원문을 검토한 후 rechecked를 기록하세요.")
                binding = None
            else:
                if not prior and any(key in link for key in BINDING_FIELDS):
                    raise ValueError(f"claims.{field}: 새 근거 서명은 시스템이 생성합니다.")
                binding = prior
            if binding is not None:
                for name in BINDING_FIELDS:
                    value_hash = binding.get(name)
                    if value_hash is not None and (not isinstance(value_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", value_hash)):
                        raise ValueError(f"claims.{field}: 손상된 근거 서명입니다.")
                    item[name] = value_hash
            else:
                item.update(source_signature=source_signature(observations[evidence_id]),
                            review_signature=review_signature(reviewed[evidence_id]) if evidence_id in reviewed else None,
                            claim_signature=_claim_signature(field, statement, item))
            normalized.append(item)
        output[field] = {"statement": statement, "status": status, "links": normalized,
                         "uncertainty": _text(value.get("uncertainty"), f"claims.{field}.uncertainty", 600, optional=True),
                         "next_check": _text(value.get("next_check"), f"claims.{field}.next_check", 600, optional=True)}
    return output


def _link_issue(field, claim, link, observations, reviewed):
    row, review = observations.get(link["evidence_id"]), reviewed.get(link["evidence_id"])
    if not row:
        return "evidence_missing_or_expired"
    if link.get("claim_signature") != _claim_signature(field, claim.get("statement"), link):
        return "claim_or_interpretation_changed"
    if link.get("source_signature") != source_signature(row):
        return "source_changed"
    if not review:
        return "review_changed_or_expired" if link.get("review_signature") else "original_not_reviewed"
    if link.get("review_signature") != review_signature(review):
        return "review_changed_or_expired"
    return None


def _basis_issue(field, claim, link, row, review):
    basis, kind = link["basis"], row.get("kind")
    if basis not in SUPPORT_BASES.get(field, BASES):
        return "basis_not_fit"
    if claim.get("status") == "FACT" and basis == "analyst_inference":
        return "inference_not_fact"
    if field == "korea_wedge" and row.get("geography") != "KR":
        return "korea_applicability_unconfirmed"
    if basis in {"direct_customer", "observed_behavior"}:
        if row.get("promotion_or_ad") or row.get("bot_or_coordinated") or row.get("speaker_role") in {"provider", "advertiser"}:
            return "provider_or_promotional_not_customer"
        if kind not in {"interview", "customer_observation", "transaction", "review", "comment", "post"}:
            return "customer_observation_unconfirmed"
        if kind in {"review", "comment", "post"} and row.get("speaker_role") != "customer":
            return "customer_role_unconfirmed"
    if basis == "transaction" and kind not in {"transaction", "procurement_award"}:
        return "transaction_unconfirmed"
    if basis in {"measured_series", "aggregate_measurement"}:
        measurement = row.get("measurement")
        if not (row.get("metrics") or row.get("series")) or not isinstance(measurement, dict) or any(
                not measurement.get(key) for key in ("definition", "unit", "population", "period", "normalization", "vintage")):
            return "measurement_definition_missing"
    if basis == "official_rule" and kind not in {"regulation", "standard"} and \
            (review or {}).get("family") != "policy":
        return "official_rule_unconfirmed"
    if basis == "official_research" and kind not in {"paper", "aggregate_metric", "series"} and \
            (review or {}).get("family") not in {"technology", "market"}:
        return "research_source_unconfirmed"
    return None


def assess_claims(candidate, observations, reviewed):
    claims = candidate.get("claims") or {}
    report, supported, blocking, stale, basis_gaps, next_checks = {}, [], [], [], [], []
    for field in CLAIM_FIELDS:
        claim = claims.get(field)
        if not claim:
            if field in CORE_FIELDS:
                next_checks.append({"claim": field, "status": "MISSING", "action": NEXT_CHECKS[field]})
            continue
        links = []
        for link in claim.get("links", []):
            issue = _link_issue(field, claim, link, observations, reviewed)
            basis_issue = _basis_issue(field, claim, link, observations.get(link["evidence_id"], {}),
                                       reviewed.get(link["evidence_id"]))
            links.append({**{key: link.get(key) for key in ("evidence_id", "relation", "basis", "locator", "note")},
                          "valid": issue is None, "stale": issue is not None,
                          "reason": issue, "eligible_support_basis": basis_issue is None,
                          "basis_issue": basis_issue})
        supports = [link for link in links if link["relation"] == "supports" and link["valid"] and link["eligible_support_basis"]]
        counters = [link for link in links if link["relation"] == "contradicts" and link["valid"]]
        stale_links = [link for link in links if link["stale"] and link["relation"] != "context"]
        # Editing an old contradiction to context needs a new reading; otherwise
        # its bound interpretation no longer matches and it remains a blocker.
        stale_links += [link for link in links if link["relation"] == "context" and
                        link["reason"] == "claim_or_interpretation_changed"]
        mismatch = candidate.get(field) and " ".join(candidate[field].split()) != claim.get("statement")
        if mismatch:
            stale.append(field + ":statement_changed")
        stale.extend(f"{field}:{link['evidence_id']}:{link['reason']}" for link in stale_links)
        if any(link["relation"] == "supports" and link["basis_issue"] for link in links):
            basis_gaps.append(field)
        if counters:
            derived = "CONTESTED" if supports else "CONTRADICTED"
        elif stale_links or mismatch:
            derived = "RECHECK"
        elif claim.get("status") in {"UNKNOWN", "ASSUMPTION"}:
            derived = "UNTESTED"
        elif supports and claim.get("status") in {"FACT", "INFERENCE"}:
            derived = "SUPPORTED" if claim["status"] == "FACT" else "INFERRED"
        else:
            derived = "UNSUPPORTED"
        if counters or stale_links or mismatch:
            blocking.append(field)
        if derived in SUPPORTED and field in CORE_FIELDS:
            supported.append(field)
        report[field] = {"statement": claim.get("statement"), "declared_status": claim.get("status"),
                         "derived_status": derived, "links": links,
                         "eligible_support_count": len(supports), "contradiction_count": len(counters),
                         "uncertainty": claim.get("uncertainty", ""), "next_check": claim.get("next_check", "")}
        if derived not in SUPPORTED:
            next_checks.append({"claim": field, "status": derived,
                                "action": claim.get("next_check") or NEXT_CHECKS.get(field, "주장과 반례의 원문 위치·해석 재확인")})
    return {"configured": bool(claims), "claims": report, "supported_core": supported,
            "blocking": sorted(set(blocking)), "stale": sorted(set(stale)),
            "basis_gaps": sorted(set(basis_gaps)), "next_checks": next_checks,
            "boundary": "검토자가 기록한 주장별 근거 구조를 점검합니다. 문장의 참·거짓 자동 검증이나 구매·수요·성공확률의 증명이 아닙니다."}


def claim_evidence_ids(report, fields=None, relation="supports"):
    ids = []
    for field in (report.get("claims", {}) if fields is None else fields):
        claim = report.get("claims", {}).get(field, {})
        if relation == "supports" and claim.get("derived_status") not in SUPPORTED:
            continue
        for link in claim.get("links", []):
            if link["relation"] == relation and link["valid"] and (relation != "supports" or link["eligible_support_basis"]):
                ids.append(link["evidence_id"])
    return sorted(set(ids))
