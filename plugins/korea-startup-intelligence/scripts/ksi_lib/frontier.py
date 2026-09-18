"""Divergent frontier discovery and novelty tournament.

This module deliberately runs *before* the conservative blue-ocean evidence
gates.  It helps Codex generate structurally different hypotheses without
pretending that novelty is customer demand or startup success.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import timedelta

from .engine import choose_domains
from .model import assets, clean, digest, now, parse_date, stamp
from .venture_intelligence import SOURCE_LANES


ARCHETYPES = (
    {
        "id": "constraint_flip",
        "label": "제약 반전",
        "question": "최근의 기술·비용·규제 변화로 예전에는 불가능했던 고객 행동이 가능해졌는가?",
    },
    {
        "id": "second_order_infrastructure",
        "label": "인프라의 2차 효과",
        "question": "새 인프라·표준·플랫폼이 만드는 보이지 않는 후속 작업은 무엇인가?",
    },
    {
        "id": "nonconsumption",
        "label": "비소비자 진입",
        "question": "현재 대안이 비싸거나 복잡해 아예 사용하지 않는 고객은 누구인가?",
    },
    {
        "id": "workflow_unbundling",
        "label": "가장 비싼 한 순간 분리",
        "question": "큰 솔루션 전체가 아니라 결과를 망치는 오직 한 순간은 무엇인가?",
    },
    {
        "id": "trust_and_verification",
        "label": "신뢰·검증 계층",
        "question": "생성·유통은 쉬워졌지만 진위·책임·품질 확인이 새 병목이 된 지점은 어디인가?",
    },
    {
        "id": "capacity_market",
        "label": "유휴 역량 재편",
        "question": "잘게 나뉘어져 거래되지 못하는 시간·장비·공간·전문성은 무엇인가?",
    },
    {
        "id": "reverse_trend",
        "label": "소멸 트렌드의 반대편",
        "question": "서비스·인력·제품이 사라지면 누가 전환·이전·유지보수 비용을 내게 되는가?",
    },
    {
        "id": "overseas_korea_lag",
        "label": "해외→한국 시차",
        "question": "해외의 새 행동이 한국에서는 가격·규제·유통·문화 때문에 어떤 다른 형태로 들어오는가?",
    },
    {
        "id": "cross_industry_transfer",
        "label": "산업 간 원리 이식",
        "question": "한 산업의 검증된 작동 원리를 다른 산업의 구매·규제·유통 제약에 맞게 옮길 수 있는가?",
    },
    {
        "id": "coordination_failure",
        "label": "조정 실패",
        "question": "기술이 아니라 서로 다른 이해관계자의 순서·책임·정보 불일치가 핵심 비용인가?",
    },
)

BUSINESS_STRUCTURES = (
    "managed_service", "workflow_tool", "verification_service", "distribution",
    "outcome_pricing", "shared_infrastructure", "physical_or_hybrid", "marketplace",
)

MECHANISM_BY_KIND = {
    "regulation": "규칙·책임 변경", "standard": "표준·호환성 변경", "patent": "기술 공급 변화",
    "job": "업무·역할 수요 변화", "procurement": "기관 구매 요구 변화", "procurement_award": "실제 조달 거래",
    "price_change": "원가·공급 제약 변화", "crowdfunding": "새 제품 선결제 신호",
    "review": "사용 후 반복 마찰", "comment": "고객 언어의 초기 문제", "customer_observation": "관찰된 고객 행동",
    "transaction": "거래·지불 행동", "aggregate_metric": "반복 이용 집계", "search_spike": "탐색 관심 변화",
    "repository": "개발 가능성·공급 확대", "paper": "연구 가능성 변화", "product": "새 공급 출현",
    "app": "새 디지털 공급", "article": "신호 후보; 원 사건 재확인 필요",
}
MECHANISM_KINDS = {"regulation", "standard", "job", "procurement_award", "price_change",
                   "crowdfunding", "review", "comment", "customer_observation", "transaction",
                   "aggregate_metric", "patent", "paper"}

GENERIC_PATTERNS = (
    r"\bAI\s*(기반|활용)?\s*(통합)?\s*(플랫폼|앱|서비스|솔루션)\b",
    r"맞춤형\s*(플랫폼|앱|서비스|솔루션)",
    r"(원스톱|올인원|혁신적인)\s*(플랫폼|앱|서비스|솔루션)?",
    r"스마트\s*(플랫폼|관리|솔루션)",
    r"통합\s*관리\s*(플랫폼|앱|서비스|솔루션)",
)

REQUIRED_FIELDS = (
    "title", "customer", "trigger_moment", "structural_change", "non_obvious_insight",
    "solution", "business_structure", "business_model", "incumbent_disadvantage",
    "korea_wedge", "why_now", "horizon_months", "archetype", "domain_ids", "evidence_ids",
    "counterevidence_ids", "assumptions", "leading_indicator", "falsifier",
    "low_cost_probe", "first_users",
)


def _tokens(value):
    value = unicodedata.normalize("NFKC", str(value or "")).lower()
    return set(re.findall(r"[a-z0-9가-힣]{2,}", value))


def _ngrams(value, size=3):
    value = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).lower())
    return {value[index:index + size] for index in range(max(0, len(value) - size + 1))}


def _jaccard(left, right):
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _similarity(left, right):
    return max(_jaccard(_tokens(left), _tokens(right)), _jaccard(_ngrams(left), _ngrams(right)))


def _reviewed(store):
    exists = store.db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_reviews'"
    ).fetchone()
    if not exists:
        return {}
    from .radar import evidence_signature
    observations = {row["id"]: row for row in store.observations()}
    current = now()
    output = {}
    for row in store.db.execute("SELECT evidence_id,evidence_hash,reviewed_at,data FROM source_reviews"):
        source = observations.get(row["evidence_id"])
        review_date = parse_date(row["reviewed_at"])
        if not source or row["evidence_hash"] != evidence_signature(source) or not review_date or \
                not timedelta(0) <= current - review_date <= timedelta(days=14):
            continue
        try:
            data = json.loads(row["data"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if data.get("read_scope") != "metadata_only":
            output[row["evidence_id"]] = data
    return output


def _lane(row):
    return SOURCE_LANES.get(row.get("source"), row.get("source") or "unknown")


def _mechanism(row):
    return MECHANISM_BY_KIND.get(row.get("kind"), "변화 원인 재확인 필요")


def _domain_pool(store, observations, count=16):
    taxonomy = assets("taxonomy.json")["domains"]
    lookup = {item["id"]: item for item in taxonomy}
    ids = []
    for row in observations:
        for domain_id in row.get("domain_ids", []):
            if domain_id in lookup and domain_id not in ids:
                ids.append(domain_id)
    for item in choose_domains(store, count):
        if item["domain_id"] not in ids:
            ids.append(item["domain_id"])
    output = []
    for domain_id in ids[:count]:
        domain = lookup[domain_id]
        attempt = store.db.execute("SELECT attempts FROM coverage WHERE domain_id=?", (domain_id,)).fetchone()
        subfield = domain["subfields"][(attempt[0] if attempt else 0) % len(domain["subfields"])]
        output.append({"domain_id": domain_id, "domain": domain["name"],
                       "subfield_id": subfield["id"], "subfield": subfield["name"]})
    return output


def frontier_packet(store, topic=None, limit=30):
    """Build a deterministic divergence packet; never call prompts ideas or evidence."""
    if type(limit) is not int or not 12 <= limit <= 60:
        raise ValueError("frontier limit은 12~60이며 30을 권장합니다.")
    topic = clean(topic, 160) if topic else None
    rows = store.observations()
    if topic:
        wanted = _tokens(topic)
        matches = [row for row in rows if wanted & _tokens(" ".join(
            str(row.get(field, "")) for field in ("topic", "title", "kind")))]
    else:
        matches = rows
    reviews = _reviewed(store)
    current = now()
    def priority(row):
        event_date = parse_date(row.get("event_at"))
        recent = event_date is not None and timedelta(0) <= current - event_date <= timedelta(days=120)
        reviewed = row["id"] in reviews
        return (0 if reviewed and recent else 1 if recent else 2 if reviewed else 3,
                -(event_date.timestamp() if event_date else 0), row["id"])
    matches.sort(key=priority)
    atoms = []
    seen_origins = set()
    for row in matches:
        origin = row.get("origin_key") or row.get("publisher") or row.get("url")
        # Preserve cross-lane diversity before repeating one publisher.
        if origin in seen_origins and len(atoms) < 12:
            continue
        seen_origins.add(origin)
        review = reviews.get(row["id"])
        event_date = parse_date(row.get("event_at"))
        recent = event_date is not None and timedelta(0) <= current - event_date <= timedelta(days=120)
        atoms.append({
            "evidence_id": row["id"], "topic": row.get("topic"), "title": row.get("title"),
            "event_at": row.get("event_at"), "geography": row.get("geography"),
            "kind": row.get("kind"),
            "domain_ids": row.get("domain_ids", []),
            "lane": _lane(row), "mechanism": _mechanism(row),
            "read_scope": review.get("read_scope") if review else "metadata_only_or_unreviewed",
            "reviewed_summary": review.get("summary") if review else None,
            "reviewed_recent_event_120d": bool(review and recent),
            "use": "source_atom" if review else "lead_only_open_original_before_claiming",
        })
        if len(atoms) >= 18:
            break
    domains = _domain_pool(store, matches or rows, 16)
    if len(domains) < 2:
        raise ValueError("산업 조합을 만들 분류 정보가 부족합니다.")
    domain_lookup = {item["domain_id"]: item for item in domains}
    anchored = [atom for atom in atoms if atom["reviewed_recent_event_120d"] and
                atom["kind"] in MECHANISM_KINDS]
    prompts = []
    for index in range(limit):
        archetype = ARCHETYPES[index % len(ARCHETYPES)]
        structure = BUSINESS_STRUCTURES[(index * 3) % len(BUSINESS_STRUCTURES)]
        atom = anchored[index % len(anchored)] if anchored else None
        mapped_id = next((domain_id for domain_id in atom["domain_ids"]
                          if domain_id in domain_lookup), None) if atom else None
        source_domain = (domain_lookup[mapped_id] if mapped_id else
                         {"domain_id": None, "domain": atom.get("topic") or "미분류 신호",
                          "subfield_id": None, "subfield": "원문에서 분야 확인 필요"} if atom else
                         domains[index % len(domains)])
        destination = domains[(index * 7 + 5) % len(domains)]
        if destination["domain_id"] == source_domain["domain_id"]:
            destination = domains[(index + 1) % len(domains)]
        anchor_context = (f"원문 신호 '{atom['title']}' ({atom['event_at']}; {atom['mechanism']})가 "
                          f"{source_domain['domain']}의 행동·비용을 실제 바꾸는지 먼저 확인하라. "
                          if atom else "현재 검토된 최근 원문·분야 연결이 없어 트렌드 가설로 주장하지 말고 조사 리드로만 사용하라. ")
        prompts.append({
            "prompt_id": "frontier-prompt-" + digest([topic, index, archetype["id"], source_domain, destination])[:16],
            "archetype": archetype,
            "business_structure": structure,
            "source_domain": source_domain,
            "destination_domain": destination,
            "signal_atom": atom,
            "trend_anchor_status": ("reviewed_recent_original" if mapped_id else
                                    "reviewed_recent_needs_domain_classification") if atom else "unanchored_research_prompt",
            "challenge": (
                f"{anchor_context}{archetype['question']} "
                f"{source_domain['domain']}/{source_domain['subfield']}의 작동 원리와 "
                f"{destination['domain']}/{destination['subfield']}의 구매·규제·유통 제약을 충돌시켜라."
            ),
            "anti_obviousness_gate": [
                "일반 AI에게 산업명만 넣어도 나올 제안인가? 그렇다면 탈락.",
                "단순 AI·플랫폼·매칭·추천을 제거해도 구조적 통찰이 남는가?",
                "새로 바뀐 메커니즘과 고객의 특정 순간을 한 문장으로 설명할 수 있는가?",
                "기존 대기업·플랫폼이 바로 복제하지 못하는 구조적 이유가 있는가?",
                "한국에서만 다른 가격·규제·유통·행동 제약이 구체적인가?",
                "틀렸음을 빨리 보여 줄 다음 관측과 폐기 조건이 있는가?",
            ],
        })
    lanes = sorted({_lane(row) for row in matches})
    recent_reviewed = [atom for atom in atoms if atom["reviewed_recent_event_120d"]]
    research_topics = list(dict.fromkeys([topic] if topic else
                     [atom["topic"] for atom in recent_reviewed if atom.get("topic")]))[:3]
    if not research_topics:
        research_topics = ["한국 현장 고객 문제"]
    research_routes = []
    for subject in research_topics:
        research_routes.extend([
            {"lane": "structural_change", "query": f"{subject} {current.year} 시행 규제 조달 발주 원문",
             "question": "무엇이 언제 바뀌어 비용·책임·구매를 바꾸는가?"},
            {"lane": "customer_pain", "query": f"{subject} 반복 불편 수작업 비용 후기 질문 {current.year}",
             "question": "실제 고객이 어떤 순간에 우회·지출하는가?"},
            {"lane": "early_supply", "query": f"{subject} 신규 제품 채용 특허 가격 변화 {current.year}",
             "question": "새 공급과 기존 대안 사이에 남는 공백은 무엇인가?"},
            {"lane": "public_social", "query": f"{subject} site:youtube.com OR site:instagram.com OR site:x.com {current.year}",
             "question": "공개 게시물의 실제 사용자 발화·광고·재인용을 구별할 수 있는가?"},
        ])
    return {
        "mode": "frontier_divergence_before_validation",
        "topic": topic,
        "signal_atoms": atoms,
        "generation_prompts": prompts,
        "tournament_target": {"raw": limit, "semifinal": 10, "shortlist": 3},
        "diversity_quotas": {
            "minimum_domain_count": 8, "minimum_archetype_count": 6,
            "minimum_business_structure_count": 5, "minimum_non_software_or_hybrid": 5,
        },
        "coverage": {
            "stored_observations": len(rows), "topic_matches": len(matches),
            "reviewed_atoms": sum(atom["read_scope"] != "metadata_only_or_unreviewed" for atom in atoms),
            "reviewed_recent_atoms_120d": len(recent_reviewed),
            "reviewed_recent_mechanism_anchors_120d": len(anchored),
            "mapped_mechanism_anchors_120d": sum(any(domain_id in domain_lookup for domain_id in atom["domain_ids"])
                                                  for atom in anchored),
            "signal_lanes": lanes, "domain_pool": len(domains),
        },
        "freshness_research_routes": research_routes,
        "instruction": (
            "Codex는 이 조합을 그대로 답으로 내지 말고 원문을 열어 변화 메커니즘을 재확인한다. "
            "최근 사건·행동 신호의 날짜와 생산자, 오래된 재인용·광고 가능성을 대조한다. "
            "그 뒤 평범한 재포장을 제거하고 30→10→3 tournament template으로 후보를 평가한다."
        ),
        "trend_boundary": ("최근 원문에서 행동·비용·제도 변화 메커니즘이 확인되지 않아 현재 유행·선행성을 주장할 수 없습니다."
                           if not anchored else
                           "최근 원문 신호가 있어도 반복·독립성·대중 보도 대비 선행성은 별도 검증이 필요합니다."),
        "boundary": "발산용 조합과 조사 리드입니다. 검증된 아이디어·수요·성공확률이 아닙니다.",
    }


def tournament_template():
    return {
        "batch_key": "founder-chosen-stable-key",
        "topic": "이번 탐색의 고객 변화 또는 시장 주제",
        "candidates": [{
            "key": "stable-candidate-key", "title": "구체적 고객·순간·결과가 보이는 이름",
            "customer": "특정 역할의 초기 고객", "trigger_moment": "문제가 발생하는 특정 순간",
            "structural_change": "언제 무엇이 바뀌어 예전과 다른 행동이 가능해졌는지",
            "non_obvious_insight": "주류 설명과 다른 인과 메커니즘",
            "solution": "핵심 결과를 바꾸는 최소 제안", "business_structure": BUSINESS_STRUCTURES[0],
            "business_model": "누가 무엇을 기준으로 지불하는지",
            "incumbent_disadvantage": "기존 대기업·대안이 이 진입점을 회피하는 구조적 이유",
            "korea_wedge": "한국의 가격·규제·유통·행동 제약을 이용한 첫 진입점",
            "why_now": "날짜가 있는 최근 사건이 어떤 행동·비용을 언제부터 바꾸는지",
            "horizon_months": 12, "archetype": ARCHETYPES[0]["id"], "domain_ids": ["KR-001"],
            "evidence_ids": [], "counterevidence_ids": [], "assumptions": ["가장 위험한 가정"],
            "leading_indicator": "다음에 관측되어야 할 선행 행동",
            "falsifier": "무엇이 관측되면 틀렸다고 판정할지",
            "low_cost_probe": "제품 개발 전 가장 싼 관측·수동 실험",
            "first_users": "이번 달 접근 경로를 조사할 초기 고객",
        }],
        "note": "3~60개를 미리보기할 수 있지만 완전한 30→10→3 토너먼트는 최소 30개가 필요",
    }


def _text(value, field, minimum=8, maximum=700):
    if not isinstance(value, str):
        raise ValueError(f"{field}: 문자열이 필요합니다.")
    value = clean(value, maximum)
    if len(value) < minimum:
        raise ValueError(f"{field}: 더 구체적인 내용이 필요합니다.")
    return value


def _string_list(value, field, minimum=0, maximum=12):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum or any(
            not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field}: {minimum}~{maximum}개의 문자열 목록이 필요합니다.")
    return list(dict.fromkeys(item.strip() for item in value))


def _generic_hits(value):
    return [pattern for pattern in GENERIC_PATTERNS if re.search(pattern, value, re.IGNORECASE)]


def _concept(candidate):
    return " ".join(str(value) for value in (
        candidate.get("customer", ""), candidate.get("trigger_moment") or candidate.get("problem", ""),
        candidate.get("structural_change") or candidate.get("why_now", ""),
        candidate.get("non_obvious_insight") or candidate.get("korea_gap", ""),
        candidate.get("solution") or candidate.get("smallest_wedge", ""),
        candidate.get("korea_wedge") or candidate.get("korea_gap", ""),
    ))


def _normalize_candidate(store, raw, known_observations, known_domains):
    if not isinstance(raw, dict) or any(field not in raw for field in REQUIRED_FIELDS):
        missing = [field for field in REQUIRED_FIELDS if not isinstance(raw, dict) or field not in raw]
        raise ValueError("프런티어 후보 필드 누락: " + ", ".join(missing))
    candidate = {field: raw[field] for field in REQUIRED_FIELDS}
    candidate["title"] = _text(candidate["title"], "title", 8, 120)
    for field in ("customer", "trigger_moment", "solution", "business_model", "leading_indicator",
                  "falsifier", "low_cost_probe", "first_users"):
        candidate[field] = _text(candidate[field], field, 10)
    for field in ("structural_change", "non_obvious_insight", "incumbent_disadvantage", "korea_wedge", "why_now"):
        candidate[field] = _text(candidate[field], field, 20)
    if candidate["business_structure"] not in BUSINESS_STRUCTURES:
        raise ValueError("business_structure: 지원되는 사업 구조를 사용하세요.")
    if candidate["archetype"] not in {item["id"] for item in ARCHETYPES}:
        raise ValueError("archetype: 지원되는 프런티어 원리를 사용하세요.")
    if type(candidate["horizon_months"]) is not int or not 1 <= candidate["horizon_months"] <= 60:
        raise ValueError("horizon_months: 1~60 정수가 필요합니다.")
    candidate["domain_ids"] = _string_list(candidate["domain_ids"], "domain_ids", 1, 5)
    if set(candidate["domain_ids"]) - known_domains:
        raise ValueError("알 수 없는 domain_ids가 있습니다.")
    for field in ("evidence_ids", "counterevidence_ids"):
        candidate[field] = _string_list(candidate[field], field, 0, 20)
        if set(candidate[field]) - set(known_observations):
            raise ValueError(f"{field}: 현재 유효한 근거 ID만 연결하세요.")
    candidate["assumptions"] = _string_list(candidate["assumptions"], "assumptions", 1, 8)
    key = raw.get("key")
    if key is not None and (not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", key)):
        raise ValueError("key: 영문 소문자·숫자·하이픈 3~80자가 필요합니다.")
    candidate["key"] = key or "hypothesis-" + digest(candidate["title"])[:16]
    candidate["id"] = "frontier-" + candidate["key"]
    return candidate


def _evaluate_one(candidate, observations, reviewed, comparison_texts):
    concept = _concept(candidate)
    similarities = [(_similarity(concept, text), record_id) for record_id, text in comparison_texts if text]
    max_similarity, nearest = max(similarities, default=(0.0, None))
    hits = _generic_hits(" ".join([candidate["title"], candidate["solution"], candidate["non_obvious_insight"]]))
    causal = bool(re.search(r"(때문|반대로|하지만|결과|인해|변하|어려운|회피|유인)", candidate["non_obvious_insight"]))
    korea_specific = bool(re.search(r"(규제|인허|유통|조달|가격|노동|지역|결제|플랫폼|언어|문화|책임)", candidate["korea_wedge"]))
    model_specific = bool(re.search(r"(건당|월|연간|성과|수수료|구독|계약|납품|검증|대행|유통|절감|이용료)", candidate["business_model"]))
    novelty = {
        "specific_structural_change": len(candidate["structural_change"]) >= 30,
        "specific_customer_moment": len(candidate["trigger_moment"]) >= 18,
        "non_obvious_causal_mechanism": len(candidate["non_obvious_insight"]) >= 28 and causal,
        "conceptual_distance_from_saved_candidates": max_similarity < 0.62,
        "incumbent_structural_disadvantage": len(candidate["incumbent_disadvantage"]) >= 28,
        "korea_specific_wedge": korea_specific,
        "specific_value_capture": model_specific,
    }
    linked = [observations[evidence_id] for evidence_id in candidate["evidence_ids"]]
    substantive = [row for row in linked if row["id"] in reviewed]
    origins = {reviewed[row["id"]].get("origin_group") or row.get("publisher") or row.get("url")
               for row in substantive}
    lanes = {_lane(row) for row in substantive}
    evidence = {
        "has_source": bool(linked),
        "has_reviewed_original": bool(substantive),
        "independent_origins": len(origins) >= 2,
        "cross_lane": len(lanes) >= 2,
        "counterevidence_linked": bool(candidate["counterevidence_ids"]),
    }
    current = now()
    dated = [(row, parse_date(row.get("event_at"))) for row in linked]
    recent = [row for row, date in dated if date is not None
              and timedelta(0) <= current - date <= timedelta(days=120)]
    reviewed_recent = [row for row in recent if row["id"] in reviewed]
    recent_origins = {reviewed[row["id"]].get("origin_group") or row.get("publisher") or row.get("url")
                      for row in reviewed_recent}
    recent_lanes = {_lane(row) for row in reviewed_recent}
    trend = {
        "specific_why_now": len(candidate["why_now"]) >= 30,
        "dated_linked_signal": any(date is not None for _, date in dated),
        "recent_signal_120d": bool(recent),
        "reviewed_recent_original_120d": bool(reviewed_recent),
        "independent_recent_origins": len(recent_origins) >= 2,
        "cross_lane_recent": len(recent_lanes) >= 2,
        "recent_mechanism_signal": any(row.get("kind") in MECHANISM_KINDS for row in reviewed_recent),
    }
    execution = {
        "leading_indicator_prespecified": len(candidate["leading_indicator"]) >= 18,
        "falsifier_prespecified": len(candidate["falsifier"]) >= 18,
        "cheap_probe_prespecified": len(candidate["low_cost_probe"]) >= 18,
        "first_users_specific": len(candidate["first_users"]) >= 18,
        "time_horizon_prespecified": 1 <= candidate["horizon_months"] <= 60,
    }
    novelty_strength = sum(novelty.values())
    evidence_strength = sum(evidence.values())
    trend_relevance = sum(trend.values())
    execution_clarity = sum(execution.values())
    hard_generic = len(hits) >= 2 or max_similarity >= 0.86
    if hard_generic:
        tier = "reject_generic"
    elif hits:
        tier = "needs_rework"
    elif novelty_strength < 4:
        tier = "needs_rework"
    elif (novelty_strength >= 5 and evidence_strength >= 4 and trend_relevance >= 5
          and execution_clarity >= 4):
        tier = "executable_candidate"
    elif novelty_strength >= 4 and evidence_strength >= 2 and trend["reviewed_recent_original_120d"]:
        tier = "emerging_candidate"
    else:
        tier = "frontier_hypothesis"
    warnings = []
    if hits:
        warnings.append("generic_solution_language:" + str(len(hits)))
    if max_similarity >= 0.62:
        warnings.append("conceptually_close_to:" + str(nearest))
    if not linked:
        warnings.append("no_source_evidence_frontier_only")
    if linked and not evidence["has_reviewed_original"]:
        warnings.append("linked_sources_not_original_text_reviewed")
    if linked and not trend["reviewed_recent_original_120d"]:
        warnings.append("no_reviewed_recent_original_120d")
    if reviewed_recent and len(recent_origins) < 2:
        warnings.append("recent_signal_single_origin")
    warnings.append("mainstream_lead_time_not_measured")
    if not candidate["counterevidence_ids"]:
        warnings.append("counterevidence_missing")
    return {
        "candidate_id": candidate["id"], "title": candidate["title"], "tier": tier,
        "decision_vector": {
            "novelty_strength": novelty_strength,
            "evidence_strength": evidence_strength,
            "trend_relevance": trend_relevance,
            "execution_clarity": execution_clarity,
        },
        "novelty_dimensions": novelty, "evidence_dimensions": evidence,
        "trend_dimensions": trend,
        "latest_linked_event_at": max((stamp(date) for _, date in dated if date is not None), default=None),
        "execution_dimensions": execution, "max_similarity": round(max_similarity, 3),
        "nearest_candidate_id": nearest, "generic_phrase_hits": len(hits), "warnings": warnings,
        "boundary": "참신성·시의성·근거·실행 명확성 비교이며 성공확률이나 트렌드 선행성 증명이 아닙니다.",
    }


def _pareto(evaluations):
    dimensions = ("novelty_strength", "trend_relevance", "evidence_strength", "execution_clarity")
    for row in evaluations:
        row["dominated_by"] = []
        if row["tier"] == "reject_generic":
            continue
        for other in evaluations:
            if other is row or other["tier"] == "reject_generic":
                continue
            left, right = other["decision_vector"], row["decision_vector"]
            if all(left[key] >= right[key] for key in dimensions) and any(left[key] > right[key] for key in dimensions):
                row["dominated_by"].append(other["candidate_id"])


def evaluate_tournament(store, payload, apply=False):
    if not isinstance(payload, dict) or not isinstance(payload.get("candidates"), list):
        raise ValueError("tournament에는 candidates 목록이 필요합니다.")
    if not 3 <= len(payload["candidates"]) <= 60:
        raise ValueError("tournament 후보는 3~60개이어야 합니다.")
    known_observations = {row["id"]: row for row in store.observations()}
    known_domains = {row["id"] for row in assets("taxonomy.json")["domains"]}
    candidates = [_normalize_candidate(store, row, known_observations, known_domains)
                  for row in payload["candidates"]]
    ids = [row["id"] for row in candidates]
    if len(ids) != len(set(ids)):
        raise ValueError("한 토너먼트 안에 중복 candidate key가 있습니다.")
    comparison = [(row["id"], _concept(row)) for row in
                  store.records("blue_ocean") + store.records("frontier_hypothesis")]
    reviewed = _reviewed(store)
    evaluations = []
    for candidate in candidates:
        peers = [(record_id, text) for record_id, text in comparison if record_id != candidate["id"]]
        peers += [(row["id"], _concept(row)) for row in candidates if row["id"] != candidate["id"]]
        evaluations.append(_evaluate_one(candidate, known_observations, reviewed, peers))
    _pareto(evaluations)
    evaluation_by_id = {row["candidate_id"]: row for row in evaluations}
    tier_order = {"executable_candidate": 0, "emerging_candidate": 1, "frontier_hypothesis": 2,
                  "needs_rework": 3, "reject_generic": 4}
    ranked = sorted(candidates, key=lambda row: (
        tier_order[evaluation_by_id[row["id"]]["tier"]],
        bool(evaluation_by_id[row["id"]]["dominated_by"]),
        -evaluation_by_id[row["id"]]["decision_vector"]["novelty_strength"],
        -evaluation_by_id[row["id"]]["decision_vector"]["trend_relevance"],
        -evaluation_by_id[row["id"]]["decision_vector"]["evidence_strength"],
        -evaluation_by_id[row["id"]]["decision_vector"]["execution_clarity"], row["id"],
    ))
    shortlist, domains_used, archetypes_used = [], set(), set()
    for candidate in ranked:
        evaluation = evaluation_by_id[candidate["id"]]
        if evaluation["tier"] in ("reject_generic", "needs_rework"):
            continue
        primary = candidate["domain_ids"][0]
        if primary in domains_used or candidate["archetype"] in archetypes_used:
            continue
        shortlist.append(candidate["id"])
        domains_used.add(primary)
        archetypes_used.add(candidate["archetype"])
        if len(shortlist) == 3:
            break
    if len(shortlist) < 3:
        shortlist.extend(row["id"] for row in ranked
                         if row["id"] not in shortlist and
                         evaluation_by_id[row["id"]]["tier"] not in ("reject_generic", "needs_rework"))
        shortlist = shortlist[:3]
    structures = Counter(row["business_structure"] for row in candidates)
    domain_count = len({domain_id for row in candidates for domain_id in row["domain_ids"]})
    archetype_count = len({row["archetype"] for row in candidates})
    non_software = sum(row["business_structure"] in {
        "managed_service", "verification_service", "distribution", "shared_infrastructure", "physical_or_hybrid"
    } for row in candidates)
    quality_gaps = []
    if len(candidates) < 30:
        quality_gaps.append("raw_pool_below_30")
    if domain_count < 8:
        quality_gaps.append("fewer_than_8_domains")
    if archetype_count < 6:
        quality_gaps.append("fewer_than_6_archetypes")
    if len(structures) < 5:
        quality_gaps.append("fewer_than_5_business_structures")
    if non_software < 5:
        quality_gaps.append("fewer_than_5_non_software_or_hybrid")
    result = {
        "evaluations": evaluations,
        "shortlist": shortlist,
        "semifinal": [row["id"] for row in ranked
                      if evaluation_by_id[row["id"]]["tier"] not in ("reject_generic",)][:10],
        "tier_counts": dict(Counter(row["tier"] for row in evaluations)),
        "diversity": {"candidate_count": len(candidates), "domain_count": domain_count,
                      "archetype_count": archetype_count, "business_structures": dict(structures),
                      "non_software_or_hybrid": non_software, "quality_gaps": quality_gaps,
                      "full_tournament": not quality_gaps},
        "saved": False,
        "boundary": "30→10→3 참신성·시의성 토너먼트이며 시장 검증·선행성·성공확률이 아닙니다.",
    }
    if apply:
        batch_key = payload.get("batch_key")
        if not isinstance(batch_key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", batch_key):
            raise ValueError("--apply에는 영문 소문자·숫자·하이픈 batch_key가 필요합니다.")
        batch_id = "frontier-batch-" + batch_key + "-" + digest({
            "candidates": candidates, "topic": payload.get("topic")
        })[:12]
        recorded_at = stamp()
        batch = {"id": batch_id, "batch_key": batch_key, "topic": clean(payload.get("topic"), 200),
                 "candidate_ids": ids, "shortlist": shortlist, "evaluations": evaluations,
                 "diversity": result["diversity"], "recorded_at": recorded_at,
                 "boundary": result["boundary"]}
        with store.db:
            store.record("frontier_batch", batch)
            for candidate in candidates:
                store.record("frontier_hypothesis", {
                    **candidate, "evaluation": evaluation_by_id[candidate["id"]],
                    "source_batch_id": batch_id, "recorded_at": recorded_at,
                    "status": "exploration_not_validated",
                })
        result["saved"] = True
        result["batch_id"] = batch_id
        result["saved_hypotheses"] = len(candidates)
    return result


def saved_hypotheses(store):
    rows = store.records("frontier_hypothesis")
    return {
        "items": rows,
        "count": len(rows),
        "boundary": "저장된 탐색 가설이며 blue-ocean 후보·고객 수요·사업 검증이 아닙니다.",
    }
