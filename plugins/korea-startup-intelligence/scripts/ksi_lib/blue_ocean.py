"""Blue-ocean discovery and single-founder venture lifecycle management.

The module stores an agent/human assessment. It deliberately does not infer that
an empty competitor search is a market opportunity and never emits a success
probability. Existing evidence, dossier and experiment records remain the source
of truth for stronger claims.
"""
import json
import re
from datetime import timedelta
from pathlib import Path

from .model import assets, atomic_json, atomic_text, digest, now, parse_date, stamp


ASSESSMENTS = {
    "problem": "반복되는 실제 문제와 피해가 확인됐는가?",
    "current_spend": "고객이 현재 시간·돈·인력으로 해결하고 있는가?",
    "supply_gap": "기존 공급과 수작업 대안이 놓치는 구체적 공백은 무엇인가?",
    "timing": "기술·규제·비용·행동 변화 때문에 왜 지금 가능한가?",
    "korea_fit": "한국의 가격·유통·규제·행동 조건에 맞는가?",
    "reachability": "이번 달 접촉 가능한 좁은 초기 고객이 있는가?",
    "switching_reason": "현재 대안에서 옮겨올 충분한 이유가 있는가?",
    "counterevidence": "수요가 없거나 이미 포화됐다는 반대 근거를 찾았는가?",
}

SIGNAL_DIMENSIONS = {
    "velocity": "같은 정의와 모집단에서 변화 속도를 측정했는가?",
    "breadth": "관계없는 사용자·지역·산업으로 신호가 넓어지는가?",
    "persistence": "일회성 사건이 아니라 반복되는가?",
    "cross_channel": "독립된 신호 계열 사이로 이동하는가?",
    "novelty": "기존 주제의 재포장이 아닌 새로운 행동·문제인가?",
    "manipulation_risk": "광고·봇·캠페인·낮은 기저 가능성을 확인했는가?",
}

EPISTEMIC = {"FACT", "INFERENCE", "ASSUMPTION", "UNKNOWN"}
STAGES = ("detected", "watching", "researching", "validating", "building", "launched", "scaling", "parked", "killed")
ACTIVE_STAGES = set(STAGES) - {"parked", "killed"}
TRANSITIONS = {
    "detected": {"watching", "researching", "parked", "killed"},
    "watching": {"researching", "parked", "killed"},
    "researching": {"watching", "validating", "parked", "killed"},
    "validating": {"researching", "building", "parked", "killed"},
    "building": {"validating", "launched", "parked", "killed"},
    "launched": {"building", "scaling", "parked", "killed"},
    "scaling": {"launched", "parked", "killed"},
    "parked": {"watching", "researching", "killed"},
    "killed": {"watching", "researching"},
}


def _text(value, field, maximum=1600):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field}: 비어 있지 않은 {maximum}자 이하 텍스트가 필요합니다.")
    return value.strip()


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,99}", value):
        raise ValueError("key: 영문 소문자·숫자·하이픈으로 된 안정적인 키가 필요합니다.")
    return value


def _string_list(value, field, minimum=0, maximum=12):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field}: {minimum}~{maximum}개 문자열 목록이 필요합니다.")
    result = []
    for item in value:
        result.append(_text(item, field, 800))
    if len(set(result)) != len(result):
        raise ValueError(f"{field}: 중복 항목을 제거하세요.")
    return result


def _evidence(store, value, field="evidence_ids", minimum=0):
    ids = _string_list(value, field, minimum, 40)
    known = {row["id"] for row in store.observations()}
    if set(ids) - known:
        raise ValueError(f"{field}: 현재 접근 가능한 근거 ID만 연결하세요.")
    return ids


def _claim(item, name, candidate_evidence):
    if item is None:
        return {"status": "UNKNOWN", "conclusion": ASSESSMENTS.get(name, SIGNAL_DIMENSIONS.get(name, "미확인")), "evidence_ids": []}
    if not isinstance(item, dict) or item.get("status") not in EPISTEMIC:
        raise ValueError(f"{name}: FACT/INFERENCE/ASSUMPTION/UNKNOWN 상태가 필요합니다.")
    ids = _string_list(item.get("evidence_ids", []), name + ".evidence_ids", 0, 20)
    if set(ids) - set(candidate_evidence):
        raise ValueError(f"{name}: 후보에 연결된 evidence_ids만 사용할 수 있습니다.")
    if item["status"] in ("FACT", "INFERENCE") and not ids:
        raise ValueError(f"{name}: FACT/INFERENCE에는 근거 연결이 필요합니다.")
    return {"status": item["status"], "conclusion": _text(item.get("conclusion"), name + ".conclusion"), "evidence_ids": ids}


def _next_action(value, active=True):
    if value is None and not active:
        return None
    if not isinstance(value, dict):
        raise ValueError("next_action: 가설·행동·통과/중단 기준을 구조화하세요.")
    result = {field: _text(value.get(field), "next_action." + field, 1000)
              for field in ("hypothesis", "action", "pass_condition", "stop_condition")}
    due = parse_date(value.get("due_at")) if value.get("due_at") else None
    if not due or due <= now() or due > now() + timedelta(days=365):
        raise ValueError("next_action.due_at: 1년 이내의 미래 시각이 필요합니다.")
    cost = value.get("estimated_cost_krw")
    if type(cost) is not int or not 0 <= cost <= 100_000_000:
        raise ValueError("next_action.estimated_cost_krw: 0~1억원 정수 상한이 필요합니다.")
    external = value.get("external_action_required")
    if type(external) is not bool:
        raise ValueError("next_action.external_action_required: true/false가 필요합니다.")
    result.update({"due_at": stamp(due), "estimated_cost_krw": cost,
                   "external_action_required": external,
                   "execution_authorized": False if external else None})
    return result


def template():
    unknown = lambda question: {"status": "UNKNOWN", "conclusion": question, "evidence_ids": []}
    return {
        "key": None, "title": None, "domain_ids": [], "customer": None, "problem": None,
        "payer": None, "current_workaround": None, "why_now": None, "korea_gap": None,
        "smallest_wedge": None, "business_models": [], "evidence_ids": [], "dossier_id": None,
        "stage": "detected", "assessments": {k: unknown(v) for k, v in ASSESSMENTS.items()},
        "signal_profile": {k: unknown(v) for k, v in SIGNAL_DIMENSIONS.items()},
        "alternatives": [],
        "next_action": {"hypothesis": None, "action": None, "pass_condition": None,
                        "stop_condition": None, "due_at": None, "estimated_cost_krw": 0,
                        "external_action_required": False},
        "stop_condition": None, "reopen_condition": None, "review_after": None,
        "expected_revision": 0,
        "boundary": "초기 후보 입력 양식이며 경쟁사 검색 결과 0건만으로 블루오션이 되지 않습니다.",
    }


def _alternatives(value, candidate_evidence):
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("alternatives: 최대 20개의 실제 대안 목록이 필요합니다.")
    result = []
    for item in value:
        if not isinstance(item, dict) or item.get("kind") not in ("direct", "indirect", "manual", "status_quo"):
            raise ValueError("alternatives.kind: direct/indirect/manual/status_quo 중 하나를 사용하세요.")
        ids = _string_list(item.get("evidence_ids", []), "alternatives.evidence_ids", 0, 12)
        if set(ids) - set(candidate_evidence):
            raise ValueError("alternatives: 후보 근거만 연결하세요.")
        result.append({"kind": item["kind"], "name": _text(item.get("name"), "alternative.name", 300),
                       "gap": _text(item.get("gap"), "alternative.gap", 800), "evidence_ids": ids})
    return result


def save(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("블루오션 후보는 JSON 객체여야 합니다.")
    key = _key(payload.get("key"))
    record_id = "blue-ocean-" + key
    expected = payload.get("expected_revision")
    exists = store.db.execute("SELECT revision FROM records WHERE kind='blue_ocean' AND id=?", (record_id,)).fetchone()
    old = next((r for r in store.records("blue_ocean") if r["id"] == record_id), None)
    if exists or expected is not None:
        store.assert_revision("blue_ocean", record_id, expected)
    stage = payload.get("stage", "detected")
    if stage not in STAGES:
        raise ValueError("stage: " + ", ".join(STAGES) + " 중 하나를 사용하세요.")
    if old and stage != old["stage"]:
        raise ValueError("기존 후보의 stage는 blue-ocean transition으로 변경하세요.")
    if not old and stage not in ("detected", "watching", "researching", "parked", "killed"):
        raise ValueError("새 후보는 탐지·관찰·조사·보류·폐기 상태에서 시작하세요. 검증 이후 단계는 transition 게이트를 사용합니다.")
    ids = _evidence(store, payload.get("evidence_ids"), minimum=1)
    domains = _string_list(payload.get("domain_ids"), "domain_ids", 1, 6)
    if set(domains) - {d["id"] for d in assets("taxonomy.json")["domains"]}:
        raise ValueError("domain_ids: domains 명령의 한국 시장 분류 ID를 사용하세요.")
    dossier_id = payload.get("dossier_id")
    if dossier_id is not None:
        if not isinstance(dossier_id, str) or not any(d["id"] == dossier_id for d in store.records("dossier")):
            raise ValueError("dossier_id: 기존 근거 연결형 조사 ID 또는 null이 필요합니다.")
    data = {"id": record_id, "key": key, "stage": stage, "domain_ids": domains,
            "evidence_ids": ids, "dossier_id": dossier_id}
    for field in ("title", "customer", "problem", "payer", "current_workaround", "why_now", "korea_gap", "smallest_wedge", "stop_condition", "reopen_condition"):
        data[field] = _text(payload.get(field), field)
    data["business_models"] = _string_list(payload.get("business_models"), "business_models", 1, 10)
    assessment_input = payload.get("assessments", {})
    signal_input = payload.get("signal_profile", {})
    if not isinstance(assessment_input, dict) or set(assessment_input) - set(ASSESSMENTS):
        raise ValueError("assessments: 정의된 시장공백 항목만 사용하세요.")
    if not isinstance(signal_input, dict) or set(signal_input) - set(SIGNAL_DIMENSIONS):
        raise ValueError("signal_profile: 정의된 신호 항목만 사용하세요.")
    data["assessments"] = {k: _claim(assessment_input.get(k), k, ids) for k in ASSESSMENTS}
    data["signal_profile"] = {k: _claim(signal_input.get(k), k, ids) for k in SIGNAL_DIMENSIONS}
    data["alternatives"] = _alternatives(payload.get("alternatives", []), ids)
    data["next_action"] = _next_action(payload.get("next_action"), stage in ACTIVE_STAGES)
    review_after = parse_date(payload.get("review_after")) if payload.get("review_after") else None
    if stage in ACTIVE_STAGES and (not review_after or review_after <= now() or review_after > now() + timedelta(days=365)):
        raise ValueError("review_after: 활성 후보에는 1년 이내 미래 재검토 시각이 필요합니다.")
    data["review_after"] = stamp(review_after) if review_after else None
    data["updated_at"] = stamp()
    data["boundary"] = "시장공백 가설. 경쟁 부재·트렌드·사업 성공을 자동 입증하지 않음."
    comparable = {k: v for k, v in data.items() if k != "updated_at"}
    if old and {k: v for k, v in old.items() if k != "updated_at"} == comparable:
        return {"status": "unchanged", "id": record_id, "assessment": assess(store, old)}
    with store.db:
        revision = store.record("blue_ocean", data, expected)
    return {"status": "saved", "id": record_id, "revision": revision, "assessment": assess(store, data)}


def _source_diversity(store, ids):
    observations = {o["id"]: o for o in store.observations() if o["id"] in ids}
    reviews = []
    has_reviews = store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_reviews'").fetchone()
    if has_reviews:
        from .radar import valid_reviews
        for evidence_id in ids:
            try:
                reviews.extend(r for r in valid_reviews(store, [evidence_id]) if r["read_scope"] != "metadata_only")
            except ValueError:
                continue
    reviewed_ids = {r["evidence_id"] for r in reviews}
    # User-owned measured results can be substantive without a public-page review.
    direct = [o for i, o in observations.items() if i not in reviewed_ids and
              o.get("collection_basis") in ("user_owned", "authorized_export") and
              o.get("kind") in ("interview", "transaction", "aggregate_metric")]
    origins = {r["origin_group"] for r in reviews} | {o.get("origin_key", o["id"]) for o in direct}
    families = {r["family"] for r in reviews} | {"customer" for _ in direct}
    return {"substantive_evidence_ids": sorted(reviewed_ids | {o["id"] for o in direct}),
            "independent_origin_count": len(origins), "signal_family_count": len(families),
            "origin_groups": sorted(origins), "families": sorted(families)}


def assess(store, candidate):
    ids = set(candidate.get("evidence_ids", []))
    current = {o["id"] for o in store.observations()}
    stale_ids = sorted(ids - current)
    diversity = _source_diversity(store, sorted(ids & current))
    substantive = set(diversity["substantive_evidence_ids"])
    backed = [k for k, item in candidate.get("assessments", {}).items()
              if item.get("status") in ("FACT", "INFERENCE") and set(item.get("evidence_ids", [])) & substantive
              and not set(item["evidence_ids"]) - current]
    signal_backed = [k for k, item in candidate.get("signal_profile", {}).items()
                     if item.get("status") in ("FACT", "INFERENCE") and set(item.get("evidence_ids", [])) & substantive
                     and not set(item["evidence_ids"]) - current]
    core = {"problem", "current_spend", "supply_gap", "timing", "korea_fit", "reachability", "switching_reason"}
    missing_core = sorted(core - set(backed))
    reasons = ["missing_evidence:" + key for key in missing_core]
    if "counterevidence" not in backed:
        reasons.append("counterevidence_not_investigated")
    if diversity["independent_origin_count"] < 2:
        reasons.append("fewer_than_two_independent_origins")
    if diversity["signal_family_count"] < 2:
        reasons.append("fewer_than_two_signal_families")
    if not any(a["kind"] in ("manual", "status_quo") for a in candidate.get("alternatives", [])):
        reasons.append("current_workaround_not_compared")
    if stale_ids:
        reasons.append("expired_or_missing_evidence")
    dossier_quality = None
    if candidate.get("dossier_id"):
        dossier = next((d for d in store.records("dossier") if d["id"] == candidate["dossier_id"]), None)
        if dossier:
            from .research import dossier_quality as quality
            dossier_quality = quality(store, dossier)
            if not dossier_quality["ready_for_opportunity_alert"]:
                reasons.append("dossier_has_blocking_gaps")
        else:
            reasons.append("missing_dossier")
    else:
        reasons.append("missing_dossier")
    validated_results = []
    if candidate.get("dossier_id"):
        plans = {p["id"] for p in store.records("validation_plan") if p.get("dossier_id") == candidate["dossier_id"]}
        validated_results = [r for r in store.records("validation_result") if r.get("plan_id") in plans]
    if not {"problem", "current_spend", "supply_gap"} <= set(backed):
        whitespace = "unproven"
    elif not missing_core and diversity["independent_origin_count"] >= 2 and diversity["signal_family_count"] >= 2:
        whitespace = "investigated" if dossier_quality and dossier_quality["ready_for_opportunity_alert"] and "counterevidence" in backed else "plausible"
    else:
        whitespace = "plausible"
    review_after = parse_date(candidate.get("review_after"))
    overdue = candidate.get("stage") in ACTIVE_STAGES and (not review_after or review_after <= now())
    return {
        "candidate_id": candidate["id"], "stage": candidate["stage"], "whitespace_state": whitespace,
        "blue_ocean_proven": False, "evidence_backed_assessments": backed,
        "assessment_denominator": len(ASSESSMENTS), "evidence_backed_signal_dimensions": signal_backed,
        "signal_dimension_denominator": len(SIGNAL_DIMENSIONS), "source_diversity": diversity,
        "blocking_gaps": list(dict.fromkeys(reasons)), "validation_ready": whitespace == "investigated",
        "passing_validation_results": sum(r.get("outcome") == "criterion_met" for r in validated_results),
        "recorded_validation_results": len(validated_results), "review_overdue": overdue,
        "next_action": candidate.get("next_action"),
        "boundary": "설명 가능한 시장공백 검토 상태이며 성공확률·경쟁 부재 증명이 아닙니다.",
    }


def status(store, candidate_id=None):
    candidates = store.records("blue_ocean")
    if candidate_id:
        candidates = [c for c in candidates if c["id"] == candidate_id or c["key"] == candidate_id]
        if not candidates:
            raise ValueError("블루오션 후보를 찾을 수 없습니다.")
    rows = [{"candidate": c, "assessment": assess(store, c)} for c in candidates]
    counts = {stage: sum(c["candidate"]["stage"] == stage for c in rows) for stage in STAGES}
    return {"candidates": rows, "counts": counts,
            "due": [c["candidate"]["id"] for c in rows if c["assessment"]["review_overdue"]],
            "portfolio_size": len(rows), "automatic_external_actions": False}


def next_actions(store, limit=10):
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit: 1~50 범위가 필요합니다.")
    rows = status(store)["candidates"]
    rows = [r for r in rows if r["candidate"]["stage"] in ACTIVE_STAGES]
    rows.sort(key=lambda r: (not r["assessment"]["review_overdue"],
                             parse_date(r["candidate"]["next_action"]["due_at"]),
                             len(r["assessment"]["blocking_gaps"])))
    return {"items": [{"candidate_id": r["candidate"]["id"], "title": r["candidate"]["title"],
                        "stage": r["candidate"]["stage"], "whitespace_state": r["assessment"]["whitespace_state"],
                        "next_action": r["candidate"]["next_action"],
                        "blocking_gaps": r["assessment"]["blocking_gaps"][:5]}
                       for r in rows[:limit]],
            "ordering": "기한 초과→가까운 기한→근거 공백 수. 성공 가능성 순위가 아닙니다."}


def transition(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("상태 변경 입력은 JSON 객체여야 합니다.")
    candidate_id = payload.get("candidate_id")
    current = next((c for c in store.records("blue_ocean") if c["id"] == candidate_id or c["key"] == candidate_id), None)
    if not current:
        raise ValueError("상태를 변경할 후보를 찾을 수 없습니다.")
    target = payload.get("to_stage")
    if target not in TRANSITIONS[current["stage"]]:
        raise ValueError(f"허용되지 않은 상태 이동: {current['stage']} → {target}")
    reason = _text(payload.get("reason"), "reason")
    ids = _evidence(store, payload.get("evidence_ids", []), minimum=0)
    assessment = assess(store, current)
    if target == "validating" and not assessment["validation_ready"]:
        raise ValueError("검증 단계로 이동하기 전에 시장공백 핵심 근거·독립 출처·dossier 공백을 보완하세요.")
    if target == "building" and assessment["passing_validation_results"] < 1:
        raise ValueError("구축 단계에는 사전 기준을 통과한 실제 validation 결과가 최소 1건 필요합니다.")
    if target in ("launched", "scaling") and not ids:
        raise ValueError("출시·확장 상태에는 실제 관측 결과 근거가 필요합니다.")
    if current["stage"] == "killed" and not ids:
        raise ValueError("폐기 후보를 다시 열려면 reopen_condition에 해당하는 새 근거가 필요합니다.")
    updated = dict(current)
    updated["stage"] = target
    updated["updated_at"] = stamp()
    if target in ACTIVE_STAGES:
        updated["next_action"] = _next_action(payload.get("next_action") or current.get("next_action"), True)
        review_after = parse_date(payload.get("review_after")) if payload.get("review_after") else parse_date(updated["next_action"]["due_at"])
        if not review_after or review_after <= now():
            raise ValueError("활성 상태에는 미래 review_after가 필요합니다.")
        updated["review_after"] = stamp(review_after)
    else:
        updated["next_action"] = None
        updated["review_after"] = stamp(parse_date(payload["review_after"])) if payload.get("review_after") else None
    expected = payload.get("expected_revision")
    store.assert_revision("blue_ocean", current["id"], expected)
    event_time = stamp()
    event = {"id": "blue-ocean-event-" + digest([current["id"], current["stage"], target, reason, event_time])[:24],
             "candidate_id": current["id"], "from_stage": current["stage"], "to_stage": target,
             "reason": reason, "evidence_ids": ids, "recorded_at": event_time,
             "external_action_executed": False}
    with store.db:
        revision = store.record("blue_ocean", updated, expected)
        store.record("blue_ocean_event", event)
    return {"status": "transitioned", "revision": revision, "event": event,
            "assessment": assess(store, updated)}


def prepare(store, limit=6):
    if type(limit) is not int or not 1 <= limit <= 12:
        raise ValueError("limit: 1~12 범위가 필요합니다.")
    from .research import research_plan
    plan = research_plan(store, limit)
    managed_keys = {c["key"] for c in store.records("blue_ocean")}
    unmanaged = [{"id": c["id"], "opportunity_key": c.get("opportunity_key"), "title": c.get("title"),
                  "dossier_id": c.get("dossier_id"), "next_action": "새 근거를 재검토한 뒤 blue-ocean 후보로 채택하거나 제외"}
                 for c in store.records("opportunity") if c.get("opportunity_key") not in managed_keys]
    return {"mode": "blue_ocean_discovery", "api_key_required": False,
            "existing_portfolio": status(store), "unmanaged_opportunities": unmanaged[:12],
            "research_tasks": plan.get("tasks", []),
            "search_lanes": [
                "고객 행동·반복 수작업·현재 지출", "검색·커뮤니티·리뷰의 약한 신호",
                "채용·조달·특허·규제·기술 가격 변화", "해외 선행 사례와 한국 대체재",
                "직접 경쟁·간접 경쟁·현 상태 유지", "광고·봇·계절성·일회성 사건 반증",
            ],
            "decision_order": ["문제", "현재 지출", "공급 공백", "왜 지금", "한국 적합성", "초기 고객 접근", "전환 이유", "반대 근거"],
            "instruction": "실제 원문을 읽고 근거를 저장한 뒤 후보를 작성하세요. 검색 결과 부재를 시장 공백으로 확정하지 마세요."}


def brief(store):
    portfolio = status(store)
    next_work = next_actions(store, 10)
    buckets = {name: [] for name in ("new_signals", "investigated", "validation_or_execution", "parked_or_killed")}
    for row in portfolio["candidates"]:
        candidate, assessment = row["candidate"], row["assessment"]
        item = {"id": candidate["id"], "title": candidate["title"], "stage": candidate["stage"],
                "whitespace_state": assessment["whitespace_state"], "blocking_gaps": assessment["blocking_gaps"][:5],
                "next_action": candidate.get("next_action")}
        if candidate["stage"] in ("detected", "watching"):
            buckets["new_signals"].append(item)
        elif candidate["stage"] in ("validating", "building", "launched", "scaling"):
            buckets["validation_or_execution"].append(item)
        elif candidate["stage"] in ("parked", "killed"):
            buckets["parked_or_killed"].append(item)
        else:
            buckets["investigated"].append(item)
    data = {"generated_at": stamp(), "portfolio_size": portfolio["portfolio_size"], "sections": buckets,
            "next_actions": next_work["items"], "boundary": "근거 기반 개인 창업 포트폴리오 브리핑. 성공확률·실시간 완전 수집 보장 아님."}
    report_dir = store.workspace / "reports"
    atomic_json(report_dir / "blue-ocean-latest.json", data)
    lines = ["# 허구김 블루오션 브리핑", "", data["generated_at"], "",
             f"관리 후보 {data['portfolio_size']}개. 경쟁사가 없다는 이유만으로 블루오션으로 분류하지 않습니다.", ""]
    labels = {"new_signals": "새 신호", "investigated": "조사 중", "validation_or_execution": "검증·실행",
              "parked_or_killed": "보류·폐기"}
    for key, label in labels.items():
        lines += ["## " + label, ""]
        lines += [f"- {item['title']} · {item['stage']} · {item['whitespace_state']}" for item in buckets[key]] or ["해당 후보 없음"]
        lines.append("")
    lines += ["## 지금 할 일", ""]
    lines += [f"- {item['title']}: {item['next_action']['action']} ({item['next_action']['due_at']})" for item in next_work["items"]] or ["등록된 다음 행동 없음"]
    lines += ["", data["boundary"]]
    atomic_text(report_dir / "blue-ocean-latest.md", "\n".join(lines) + "\n")
    return {"report_path": str(report_dir / "blue-ocean-latest.md"), **data}
