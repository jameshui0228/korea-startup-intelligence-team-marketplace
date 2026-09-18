"""Authorized, source-scoped intake for signal families without live adapters.

Importing a review records what the operator actually read. It does not assert
platform-wide coverage, authentic customer demand, or trend acceleration.
"""
import json
import math
import re
from datetime import timedelta

from . import blue_ocean, radar, social, venture_intelligence
from .model import assets, canonical_url, now, observation, parse_date, stamp


KINDS = {"article", "post", "comment", "job", "patent", "standard", "paper",
         "price_change", "procurement", "procurement_award", "app", "review",
         "product", "crowdfunding", "regulation", "aggregate_metric",
         "search_spike", "customer_observation", "manual_evidence", "transaction"}
FAMILIES = {"jobs": "market", "patents": "technology", "standards": "technology",
            "papers": "technology", "technology_cost": "technology_cost", "procurement": "market",
            "app_store": "product", "commerce": "product", "crowdfunding": "product",
            "regulation": "policy", "kosis": "market", "ecos": "market",
            "instagram": "community", "tiktok": "community", "x": "community",
            "threads": "community", "reddit": "community", "youtube": "community"}
FAMILIES["technology_cost"] = "technology"


def template():
    return {"source": "jobs", "kind": "job", "topic": None, "title": None,
            "url": None, "event_at": None, "geography": "KR", "domain_ids": [],
            "read_scope": "relevant_sections", "summary": None,
            "origin_group": None, "origin_note": None, "reviewer": None,
            "collection_basis": "public_source_verified", "limitations": [],
            "metrics": {}, "measurement": None, "demand_or_supply": "context",
            "comparison_key": None, "speaker_role": "unknown",
            "promotion_or_ad": False, "seasonal_event": False, "bot_or_coordinated": False,
            "force_recheck": False,
            "warning": "원문을 실제 읽은 후 자기 말로 요약; 접근 제한 우회·개인정보·키 저장 금지"}


def import_signal(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("signal 입력은 JSON 객체여야 합니다.")
    source = payload.get("source")
    if source not in FAMILIES:
        raise ValueError("허용된 산업/SNS 신호 source를 사용하세요.")
    kind = payload.get("kind")
    if kind not in KINDS:
        raise ValueError("허용된 관측 kind를 사용하세요.")
    for name in ("topic", "title", "summary", "origin_group", "origin_note", "reviewer"):
        radar.bounded_text(payload.get(name), name, 1500 if name == "summary" else 240)
    if re.search(r"(?i)(bearer\s|api[_ -]?key|client[_ -]?secret|[\w.+-]+@[\w.-]+\.[a-z]{2,}|01[016789][- ]?\d{3,4}[- ]?\d{4})", payload["summary"]):
        raise ValueError("요약에 인증정보·개인정보 패턴이 있습니다. 비식별 자기말 요약만 저장하세요.")
    url = canonical_url(payload.get("url"))
    if source in social.HOSTS:
        social.public_post(source, url)
    event = parse_date(payload.get("event_at"))
    if not event or event > now():
        raise ValueError("실제 게시·관측 시각인 event_at이 필요합니다.")
    scope = payload.get("read_scope")
    if scope not in ("relevant_sections", "full_text", "metadata_only"):
        raise ValueError("read_scope는 실제 읽은 범위를 표시하세요.")
    basis = payload.get("collection_basis")
    if basis not in ("public_source_verified", "user_owned", "authorized_export"):
        raise ValueError("공개 검토·소유·허용 내보내기 자료만 접수합니다.")
    limitations = radar.text_list(payload.get("limitations", []), "limitations", minimum=0)
    domains = payload.get("domain_ids", [])
    valid_domains = {row["id"] for row in assets("taxonomy.json")["domains"]}
    if not isinstance(domains, list) or len(domains) > 8 or set(domains) - valid_domains:
        raise ValueError("domain_ids는 알려진 분야 ID 최대 8개입니다.")
    metrics = payload.get("metrics", {})
    if not isinstance(metrics, dict) or len(metrics) > 12 or any(
            not isinstance(key, str) or isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value)
            for key, value in metrics.items()):
        raise ValueError("metrics는 최대 12개의 수치 관측입니다.")
    measurement = payload.get("measurement")
    if metrics or source in ("kosis", "ecos", "technology_cost"):
        if not isinstance(measurement, dict) or any(
                not isinstance(measurement.get(field), str) or not measurement[field].strip()
                for field in ("definition", "unit", "population", "period", "normalization", "vintage")):
            raise ValueError("수치 신호는 정의·단위·모집단·기간·정규화·공표판본을 모두 기록하세요.")
    for flag in ("promotion_or_ad", "seasonal_event", "bot_or_coordinated"):
        if type(payload.get(flag, False)) is not bool:
            raise ValueError(flag + "는 true/false로 기록하세요.")
    if type(payload.get("force_recheck", False)) is not bool:
        raise ValueError("force_recheck는 true/false입니다.")
    role = payload.get("demand_or_supply", "context")
    if role not in ("demand", "supply", "context"):
        raise ValueError("demand_or_supply를 구분하세요.")
    comparison_key = payload.get("comparison_key")
    if comparison_key is not None:
        if not isinstance(comparison_key, str) or not re.fullmatch(r"[a-zA-Z0-9가-힣_.:-]{1,120}", comparison_key):
            raise ValueError("comparison_key는 영문·숫자·한글과 ._:- 조합 1~120자입니다.")
        if role not in ("demand", "supply") or not measurement or type(metrics.get("value")) not in (int, float):
            raise ValueError("comparison_key에는 수요/공급 역할과 measurement 및 숫자 metrics.value가 필요합니다.")
    speaker_role = payload.get("speaker_role", "unknown")
    if speaker_role not in ("customer", "provider", "advertiser", "expert", "unknown"):
        raise ValueError("speaker_role은 customer/provider/advertiser/expert/unknown 중 하나입니다.")
    radar.ensure_radar(store)
    row = observation(source, kind, payload["topic"], payload["title"], url, stamp(event),
                      geography=payload.get("geography", "unknown"), domain_ids=domains,
                      content_scope="reviewed_" + scope, collection_basis=basis,
                      metrics=metrics, measurement=measurement, demand_or_supply=role,
                      comparison_key=comparison_key, speaker_role=speaker_role,
                      promotion_or_ad=payload.get("promotion_or_ad", False),
                      seasonal_event=payload.get("seasonal_event", False),
                      bot_or_coordinated=payload.get("bot_or_coordinated", False),
                      origin_key=payload["origin_group"],
                      limitations=limitations + ["reviewer_attested_not_independently_audited"],
                      expires_at=stamp(now() + timedelta(days=28)))
    review = {"evidence_id": row["id"], "read_scope": scope, "family": FAMILIES[source],
              "summary": payload["summary"], "origin_group": payload["origin_group"],
              "origin_note": payload["origin_note"], "reviewer": payload["reviewer"],
              "collection_basis": basis, "reviewed_at": stamp(), "url": row["url"],
              "event_at": row["event_at"], "limitations": limitations,
              "date_basis": "source_publication_or_event", "verification": "reviewer_attestation_not_independent_audit"}
    previous_row = next((item for item in store.observations() if item["id"] == row["id"]), None)
    previous_review_row = store.db.execute("SELECT data FROM source_reviews WHERE evidence_id=?", (row["id"],)).fetchone()
    previous_review = json.loads(previous_review_row["data"]) if previous_review_row else None
    stable_fields = ("kind", "topic", "title", "url", "event_at", "geography", "domain_ids", "metrics",
                     "measurement", "demand_or_supply", "comparison_key", "speaker_role", "promotion_or_ad", "seasonal_event",
                     "bot_or_coordinated")
    review_fields = ("read_scope", "family", "summary", "origin_group", "origin_note", "reviewer",
                     "collection_basis", "limitations")
    if not payload.get("force_recheck", False) and previous_row and previous_review and \
            all(previous_row.get(field) == row.get(field) for field in stable_fields) and \
            all(previous_review.get(field) == review.get(field) for field in review_fields):
        return {"status": "unchanged", "evidence_id": row["id"], "direct_api_collected": False,
                "portfolio_reassessment": None}
    with store.db:
        store.put_observation(row)
        store.db.execute("INSERT OR REPLACE INTO source_reviews VALUES (?,?,?,?)",
                         (row["id"], review["reviewed_at"], radar.evidence_signature(row),
                          json.dumps(review, ensure_ascii=False)))
    events = blue_ocean.note_evidence_change(store, row["id"])
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="signal_intake")
    return {"status": "reviewed_signal_saved", "evidence_id": row["id"], "source": source,
            "read_scope": scope, "blue_ocean_events": events, "reassessment": reassessment,
            "direct_api_collected": False, "platform_census": False}


def capabilities(store):
    return {"input_template": template(), "sources": sorted(FAMILIES),
            "live_and_import_lanes": venture_intelligence.source_capabilities(store),
            "boundary": "직접 API가 없는 곳은 공개 원문 또는 권한 있는 export를 실제 검토한 뒤 접수합니다."}
