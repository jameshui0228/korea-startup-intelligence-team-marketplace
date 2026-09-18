"""Personal founder operating system for a constrained, evidence-first portfolio.

This module automates local planning and reversible portfolio state management.
It never contacts customers, spends money, launches campaigns, or fabricates KPI
measurements. Unknown capacity and founder fit remain unknown instead of zero.
"""
import json
import math
import re
from datetime import date, datetime, timedelta

from . import blue_ocean
from .model import KST, atomic_json, atomic_text, digest, now, parse_date, stamp


PROFILE_ID = "founder-operations-profile"
FIT_DIMENSIONS = ("skills", "customer_access", "motivation", "time", "capital", "domain", "regulatory")
FIT_STATES = {"ALIGNED", "PARTIAL", "MISFIT", "UNKNOWN"}
FIT_BASES = {"user_confirmed", "observed", "agent_inference"}
TRACKS = ("interview", "mvp", "pricing", "gtm")
DEFAULT_DEPENDENCIES = {"interview": [], "mvp": ["interview"], "pricing": ["mvp"], "gtm": ["pricing"]}
GROUPS = {
    "discovery": {"detected", "watching", "researching"},
    "validation": {"validating"},
    "build": {"building"},
    "growth": {"launched", "scaling"},
}
GROUP_ORDER = {"growth": 0, "build": 1, "validation": 2, "discovery": 3}


def _text(value, field, maximum=1200):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field}: 비어 있지 않은 {maximum}자 이하 텍스트가 필요합니다.")
    return value.strip()


def _key(value, field="key"):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", value):
        raise ValueError(f"{field}: 영문 소문자·숫자·하이픈으로 된 안정적인 키가 필요합니다.")
    return value


def _number(value, field, low=0, high=10**15):
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{field}: {low}~{high} 범위의 유한한 숫자가 필요합니다.")
    return value


def _integer(value, field, low=0, high=10**12):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{field}: {low}~{high} 범위의 정수가 필요합니다.")
    return value


def _strings(value, field, minimum=0, maximum=30):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field}: {minimum}~{maximum}개 문자열 목록이 필요합니다.")
    result = [_text(item, field, 500) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{field}: 중복 항목을 제거하세요.")
    return result


def _candidate(store, value):
    row = next((item for item in store.records("blue_ocean") if item["id"] == value or item["key"] == value), None)
    if not row:
        raise ValueError("운영할 블루오션 후보를 찾을 수 없습니다.")
    return row


def _revision(store, kind, record_id):
    row = store.db.execute("SELECT revision FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
    return row[0] if row else 0


def _profile(store, required=True):
    profile = next((row for row in store.records("founder_profile") if row["id"] == PROFILE_ID), None)
    if required and not profile:
        raise ValueError("개인 운영 프로필이 없습니다. operator template profile을 채워 operator configure로 저장하세요.")
    return profile


def _week_start(value=None):
    if value is None:
        current = now().astimezone(KST).date()
        current = current - timedelta(days=current.weekday())
    else:
        try:
            current = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise ValueError("week_start: YYYY-MM-DD 날짜가 필요합니다.") from None
    if current.weekday() != 0:
        raise ValueError("week_start: 한국시간 기준 월요일 날짜가 필요합니다.")
    return current.isoformat()


def template(kind):
    templates = {
        "profile": {
            "weekly_hours_available": None, "weekly_budget_krw": None,
            "cash_budget_krw": None, "protected_reserve_krw": None,
            "wip_limits": {"discovery": 2, "validation": 1, "build": 1, "growth": 1},
            "max_total_active": 3, "stale_after_days": 21,
            "policies": {"auto_park_overflow": True, "auto_park_stale": True,
                         "auto_park_founder_misfit": True, "auto_kill_on_stop": True,
                         "auto_reopen_wip": True, "auto_reopen_on_evidence": True,
                         "auto_advance_gated_stages": True},
            "priority_order": [], "skills": [], "customer_access": [], "constraints": [],
            "excluded_industries": [], "risk_boundary": None, "expected_revision": 0,
        },
        "fit": {
            "candidate_id": None,
            "dimensions": {name: {"status": "UNKNOWN", "rationale": None, "basis": "user_confirmed"}
                           for name in FIT_DIMENSIONS},
            "weekly_hours_required": None, "weekly_budget_required_krw": None,
            "initial_budget_required_krw": None, "constraints": [], "expected_revision": 0,
        },
        "pipeline": {
            "candidate_id": None, "weekly_hours_estimate": None, "weekly_budget_krw": None,
            "tracks": {name: {"plan_ids": [], "depends_on": DEFAULT_DEPENDENCIES[name]} for name in TRACKS},
            "expected_revision": 0,
        },
        "kpi-plan": {
            "key": None, "candidate_id": None, "cadence": "weekly",
            "metrics": [{"key": None, "name": None, "definition": None, "unit": None,
                         "direction": "higher", "target": None, "floor": None}],
        },
        "kpi-snapshot": {
            "plan_id": None, "week_start": None, "values": {}, "evidence_ids": [],
            "summary": None, "limitations": [],
        },
        "checkin": {
            "week_start": None, "summary": None,
            "items": [{"candidate_id": None, "hours_spent": 0, "spend_krw": 0,
                       "accomplishments": [], "blockers": [], "decision": "none",
                       "evidence_ids": [], "note": None}],
        },
        "reopen-signal": {
            "candidate_id": None, "evidence_ids": [], "matched_condition": None,
            "confirmed_by_founder": False,
        },
    }
    if kind not in templates:
        raise ValueError("operator template: profile/fit/pipeline/kpi-plan/kpi-snapshot/checkin/reopen-signal 중 하나가 필요합니다.")
    return templates[kind]


def configure(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("개인 운영 프로필은 JSON 객체여야 합니다.")
    expected = payload.get("expected_revision", 0)
    store.assert_revision("founder_profile", PROFILE_ID, expected)
    hours = _number(payload.get("weekly_hours_available"), "weekly_hours_available", 1, 168)
    weekly_budget = _integer(payload.get("weekly_budget_krw"), "weekly_budget_krw", 0, 10**12)
    cash = _integer(payload.get("cash_budget_krw"), "cash_budget_krw", 0, 10**13)
    reserve = _integer(payload.get("protected_reserve_krw"), "protected_reserve_krw", 0, 10**13)
    if reserve > cash:
        raise ValueError("protected_reserve_krw는 cash_budget_krw를 초과할 수 없습니다.")
    limits = payload.get("wip_limits")
    if not isinstance(limits, dict) or set(limits) != set(GROUPS):
        raise ValueError("wip_limits는 discovery/validation/build/growth를 모두 포함해야 합니다.")
    limits = {name: _integer(limits[name], "wip_limits." + name, 0, 20) for name in GROUPS}
    maximum = _integer(payload.get("max_total_active"), "max_total_active", 1, 20)
    policies = payload.get("policies")
    required_policies = {"auto_park_overflow", "auto_park_stale", "auto_park_founder_misfit",
                         "auto_kill_on_stop", "auto_reopen_wip", "auto_reopen_on_evidence",
                         "auto_advance_gated_stages"}
    if not isinstance(policies, dict) or set(policies) != required_policies or any(type(v) is not bool for v in policies.values()):
        raise ValueError("policies의 모든 자동 운영 스위치를 true/false로 명시하세요.")
    priorities = _strings(payload.get("priority_order", []), "priority_order", 0, 20)
    known = {c["id"] for c in store.records("blue_ocean")}
    if set(priorities) - known:
        raise ValueError("priority_order에는 현재 후보 ID만 사용할 수 있습니다.")
    data = {
        "id": PROFILE_ID, "timezone": "Asia/Seoul", "weekly_hours_available": hours,
        "weekly_budget_krw": weekly_budget, "cash_budget_krw": cash,
        "protected_reserve_krw": reserve, "deployable_cash_krw": cash - reserve,
        "wip_limits": limits, "max_total_active": maximum,
        "stale_after_days": _integer(payload.get("stale_after_days"), "stale_after_days", 7, 365),
        "policies": policies, "priority_order": priorities,
        "skills": _strings(payload.get("skills", []), "skills", 0, 30),
        "customer_access": _strings(payload.get("customer_access", []), "customer_access", 0, 30),
        "constraints": _strings(payload.get("constraints", []), "constraints", 0, 30),
        "excluded_industries": _strings(payload.get("excluded_industries", []), "excluded_industries", 0, 30),
        "risk_boundary": _text(payload.get("risk_boundary"), "risk_boundary"),
        "confirmed_at": stamp(),
        "boundary": "사용자가 확인한 개인 운영 한도이며 사업 성공확률이나 지출 승인이 아닙니다.",
    }
    with store.db:
        revision = store.record("founder_profile", data, expected)
    return {"status": "configured", "id": PROFILE_ID, "revision": revision, "profile": data}


def save_fit(store, payload):
    profile = _profile(store)
    if not isinstance(payload, dict):
        raise ValueError("창업자 적합성 평가는 JSON 객체여야 합니다.")
    candidate = _candidate(store, payload.get("candidate_id"))
    record_id = "founder-fit-" + candidate["key"]
    expected = payload.get("expected_revision", 0)
    store.assert_revision("founder_fit", record_id, expected)
    dimensions = payload.get("dimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != set(FIT_DIMENSIONS):
        raise ValueError("dimensions는 skills/customer_access/motivation/time/capital/domain/regulatory를 모두 포함해야 합니다.")
    normalized = {}
    for name in FIT_DIMENSIONS:
        row = dimensions[name]
        if not isinstance(row, dict) or row.get("status") not in FIT_STATES or row.get("basis") not in FIT_BASES:
            raise ValueError(name + ": 상태와 근거 성격을 명시하세요.")
        normalized[name] = {"status": row["status"], "rationale": _text(row.get("rationale"), name + ".rationale"),
                            "basis": row["basis"]}
    hours = _number(payload.get("weekly_hours_required"), "weekly_hours_required", 0, 168)
    weekly = _integer(payload.get("weekly_budget_required_krw"), "weekly_budget_required_krw", 0, 10**12)
    initial = _integer(payload.get("initial_budget_required_krw"), "initial_budget_required_krw", 0, 10**13)
    conflicts = []
    if hours > profile["weekly_hours_available"]:
        conflicts.append("weekly_hours_exceed_founder_capacity")
    if weekly > profile["weekly_budget_krw"]:
        conflicts.append("weekly_budget_exceeds_limit")
    if initial > profile["deployable_cash_krw"]:
        conflicts.append("initial_budget_invades_protected_reserve")
    states = {row["status"] for row in normalized.values()}
    if "MISFIT" in states or conflicts:
        decision = "misaligned"
    elif "UNKNOWN" in states or any(row["basis"] == "agent_inference" for row in normalized.values()):
        decision = "unknown"
    elif "PARTIAL" in states:
        decision = "conditional"
    else:
        decision = "aligned"
    data = {"id": record_id, "candidate_id": candidate["id"], "candidate_revision": _revision(store, "blue_ocean", candidate["id"]),
            "profile_revision": _revision(store, "founder_profile", PROFILE_ID), "dimensions": normalized,
            "weekly_hours_required": hours, "weekly_budget_required_krw": weekly,
            "initial_budget_required_krw": initial,
            "constraints": _strings(payload.get("constraints", []), "constraints", 0, 20),
            "capacity_conflicts": conflicts, "decision": decision, "assessed_at": stamp(),
            "boundary": "창업자-후보 적합성 설명이며 후보 성공확률 점수가 아닙니다."}
    with store.db:
        revision = store.record("founder_fit", data, expected)
    return {"status": "saved", "id": record_id, "revision": revision, "assessment": data}


def _validate_dependencies(tracks):
    for name, row in tracks.items():
        if name in row["depends_on"] or set(row["depends_on"]) - set(TRACKS):
            raise ValueError("pipeline depends_on에는 다른 유효 단계만 사용할 수 있습니다.")
    visiting, visited = set(), set()
    def visit(name):
        if name in visiting:
            raise ValueError("pipeline 단계 의존성에 순환이 있습니다.")
        if name in visited:
            return
        visiting.add(name)
        for parent in tracks[name]["depends_on"]:
            visit(parent)
        visiting.remove(name)
        visited.add(name)
    for name in TRACKS:
        visit(name)


def save_pipeline(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("실험 파이프라인은 JSON 객체여야 합니다.")
    candidate = _candidate(store, payload.get("candidate_id"))
    record_id = "founder-pipeline-" + candidate["key"]
    expected = payload.get("expected_revision", 0)
    store.assert_revision("founder_pipeline", record_id, expected)
    tracks = payload.get("tracks")
    if not isinstance(tracks, dict) or set(tracks) != set(TRACKS):
        raise ValueError("tracks는 interview/mvp/pricing/gtm을 모두 포함해야 합니다.")
    plans = {p["id"]: p for p in store.records("validation_plan")}
    normalized, used = {}, set()
    for name in TRACKS:
        row = tracks[name]
        if not isinstance(row, dict):
            raise ValueError("각 pipeline 단계는 객체여야 합니다.")
        ids = _strings(row.get("plan_ids", []), name + ".plan_ids", 0, 12)
        if used & set(ids):
            raise ValueError("하나의 validation plan을 여러 pipeline 단계에 중복 연결할 수 없습니다.")
        for plan_id in ids:
            plan = plans.get(plan_id)
            if not plan or not candidate.get("dossier_id") or plan.get("dossier_id") != candidate.get("dossier_id"):
                raise ValueError("pipeline에는 같은 후보 dossier의 validation plan만 연결하세요.")
        used.update(ids)
        normalized[name] = {"plan_ids": ids,
                            "depends_on": _strings(row.get("depends_on", DEFAULT_DEPENDENCIES[name]), name + ".depends_on", 0, 3)}
    _validate_dependencies(normalized)
    data = {"id": record_id, "candidate_id": candidate["id"],
            "candidate_revision": _revision(store, "blue_ocean", candidate["id"]),
            "weekly_hours_estimate": _number(payload.get("weekly_hours_estimate"), "weekly_hours_estimate", 0, 168),
            "weekly_budget_krw": _integer(payload.get("weekly_budget_krw"), "weekly_budget_krw", 0, 10**12),
            "tracks": normalized, "updated_at": stamp(),
            "boundary": "실험 의존성과 자원 계획이며 고객 연락·MVP 제작·광고 집행을 실행하지 않습니다."}
    with store.db:
        revision = store.record("founder_pipeline", data, expected)
    return {"status": "saved", "id": record_id, "revision": revision,
            "pipeline": pipeline_status(store, data)}


def pipeline_status(store, pipeline):
    plans = {p["id"]: p for p in store.records("validation_plan")}
    results = {r["plan_id"]: r for r in store.records("validation_result")}
    states = {}
    for name in TRACKS:
        row = pipeline["tracks"][name]
        linked = [plans[i] for i in row["plan_ids"] if i in plans]
        linked_results = [results[i] for i in row["plan_ids"] if i in results]
        outcomes = [item["outcome"] for item in linked_results]
        dependencies_met = all(states.get(parent, {}).get("state") == "passed" for parent in row["depends_on"])
        if "stop_criterion_met" in outcomes:
            state = "stopped"
        elif "criterion_met" in outcomes:
            state = "passed"
        elif linked_results:
            state = "inconclusive"
        elif linked:
            current = now()
            state = "awaiting_result" if any(current >= parse_date(p["ends_at"]) for p in linked) else \
                    "running" if any(parse_date(p["starts_at"]) <= current for p in linked) else "planned"
        elif dependencies_met:
            state = "ready"
        else:
            state = "blocked"
        states[name] = {"state": state, "plan_ids": row["plan_ids"], "depends_on": row["depends_on"],
                        "outcomes": outcomes, "dependencies_met": dependencies_met}
    next_track = next((name for name in TRACKS if states[name]["state"] not in ("passed", "blocked")), None)
    if next_track is None:
        next_track = next((name for name in TRACKS if states[name]["state"] == "blocked"), None)
    return {"candidate_id": pipeline["candidate_id"], "tracks": states, "next_track": next_track,
            "stopped_tracks": [name for name in TRACKS if states[name]["state"] == "stopped"],
            "complete": all(states[name]["state"] == "passed" for name in TRACKS)}


def save_kpi_plan(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("KPI plan은 JSON 객체여야 합니다.")
    key = _key(payload.get("key"), "key")
    record_id = "founder-kpi-plan-" + key
    if _revision(store, "founder_kpi_plan", record_id):
        raise ValueError("KPI plan은 불변입니다. 정의를 바꾸려면 새 key를 사용하세요.")
    candidate = _candidate(store, payload.get("candidate_id"))
    if candidate["stage"] not in ("building", "launched", "scaling"):
        raise ValueError("KPI plan은 구축·출시·확장 후보에만 사전 등록하세요.")
    metrics = payload.get("metrics")
    if not isinstance(metrics, list) or not 1 <= len(metrics) <= 20:
        raise ValueError("metrics: 1~20개 KPI 정의가 필요합니다.")
    normalized, keys = [], set()
    for item in metrics:
        if not isinstance(item, dict):
            raise ValueError("각 KPI는 객체여야 합니다.")
        metric_key = _key(item.get("key"), "metric.key")
        if metric_key in keys:
            raise ValueError("metric.key는 중복될 수 없습니다.")
        keys.add(metric_key)
        if item.get("direction") not in ("higher", "lower"):
            raise ValueError("metric.direction은 higher/lower 중 하나입니다.")
        target = item.get("target")
        floor = item.get("floor")
        if target is not None:
            target = _number(target, "metric.target", -10**15, 10**15)
        if floor is not None:
            floor = _number(floor, "metric.floor", -10**15, 10**15)
        if target is not None and floor is not None:
            if item["direction"] == "higher" and target <= floor:
                raise ValueError("higher KPI는 target이 floor보다 커야 합니다.")
            if item["direction"] == "lower" and target >= floor:
                raise ValueError("lower KPI는 target이 floor보다 작아야 합니다.")
        normalized.append({"key": metric_key, "name": _text(item.get("name"), "metric.name", 120),
                           "definition": _text(item.get("definition"), "metric.definition", 500),
                           "unit": _text(item.get("unit"), "metric.unit", 80),
                           "direction": item["direction"], "target": target, "floor": floor})
    if payload.get("cadence") != "weekly":
        raise ValueError("v0.4.0 KPI cadence는 weekly만 지원합니다.")
    data = {"id": record_id, "candidate_id": candidate["id"], "cadence": "weekly", "metrics": normalized,
            "registered_at": stamp(), "boundary": "KPI 정의이며 실제 측정·인과·성장 증명이 아닙니다."}
    with store.db:
        store.record("founder_kpi_plan", data)
    return {"status": "registered", "id": record_id, "record": data}


def _kpi_judgement(metric, value):
    target, floor = metric["target"], metric["floor"]
    if target is None and floor is None:
        return "observed_no_threshold"
    if metric["direction"] == "higher":
        if target is not None and value >= target:
            return "on_target"
        if floor is not None and value <= floor:
            return "below_floor"
    else:
        if target is not None and value <= target:
            return "on_target"
        if floor is not None and value >= floor:
            return "below_floor"
    return "attention"


def save_kpi_snapshot(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("KPI snapshot은 JSON 객체여야 합니다.")
    plan = next((p for p in store.records("founder_kpi_plan") if p["id"] == payload.get("plan_id")), None)
    if not plan:
        raise ValueError("등록된 KPI plan이 필요합니다.")
    candidate = _candidate(store, plan["candidate_id"])
    if candidate["stage"] not in ("launched", "scaling"):
        raise ValueError("실제 KPI snapshot은 launched/scaling 후보에만 기록합니다.")
    week = _week_start(payload.get("week_start"))
    current_monday = now().astimezone(KST).date() - timedelta(days=now().astimezone(KST).date().weekday())
    if date.fromisoformat(week) > current_monday:
        raise ValueError("미래 주차의 KPI snapshot을 기록할 수 없습니다.")
    record_id = plan["id"] + "-" + week
    values = payload.get("values")
    metric_map = {m["key"]: m for m in plan["metrics"]}
    if not isinstance(values, dict) or set(values) != set(metric_map):
        raise ValueError("values는 KPI plan의 모든 metric key를 정확히 포함해야 합니다.")
    normalized_values = {key: _number(value, "values." + key, -10**15, 10**15) for key, value in values.items()}
    ids = _strings(payload.get("evidence_ids"), "evidence_ids", 1, 30)
    observations = {o["id"]: o for o in store.observations()}
    period_start = parse_date(week + "T00:00:00+09:00")
    period_end = period_start + timedelta(days=7)
    for evidence_id in ids:
        row = observations.get(evidence_id)
        if not row or row.get("collection_basis") not in ("user_owned", "authorized_export") or \
                row.get("kind") not in ("transaction", "aggregate_metric"):
            raise ValueError("KPI는 사용자 소유/허용 거래 또는 집계 측정 근거가 필요합니다.")
        measured_at = parse_date(row.get("event_at"))
        if not measured_at or measured_at > now() or not period_start <= measured_at < period_end:
            raise ValueError("KPI 근거의 측정일은 해당 KST 주차 안에 있어야 합니다.")
    data = {"id": record_id, "plan_id": plan["id"], "candidate_id": candidate["id"], "week_start": week,
            "values": normalized_values, "judgements": {key: _kpi_judgement(metric_map[key], value)
                                                         for key, value in normalized_values.items()},
            "evidence_ids": ids, "summary": _text(payload.get("summary"), "summary"),
            "limitations": _strings(payload.get("limitations", []), "limitations", 0, 20),
            "recorded_at": stamp(), "boundary": "사용자 제공 운영 측정의 주간 스냅샷이며 독립 회계감사나 인과 증명이 아닙니다."}
    old = next((r for r in store.records("founder_kpi_snapshot") if r["id"] == record_id), None)
    if old:
        if {k: v for k, v in old.items() if k != "recorded_at"} != {k: v for k, v in data.items() if k != "recorded_at"}:
            raise ValueError("같은 주차 KPI snapshot은 덮어쓸 수 없습니다. 정정 사유를 다음 주 보고서에 남기세요.")
        return {"status": "unchanged", "id": record_id, "record": old}
    with store.db:
        store.record("founder_kpi_snapshot", data)
    return {"status": "recorded", "id": record_id, "record": data}


def save_checkin(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("주간 check-in은 JSON 객체여야 합니다.")
    week = _week_start(payload.get("week_start"))
    current_monday = now().astimezone(KST).date() - timedelta(days=now().astimezone(KST).date().weekday())
    if date.fromisoformat(week) > current_monday:
        raise ValueError("미래 주차의 실제 check-in을 기록할 수 없습니다.")
    record_id = "founder-checkin-" + week
    if _revision(store, "founder_checkin", record_id):
        raise ValueError("같은 주차 check-in은 불변입니다. 누락은 다음 check-in에서 명시하세요.")
    items = payload.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise ValueError("items: 1~20개 후보 실행 기록이 필요합니다.")
    normalized, seen = [], set()
    known_evidence = {o["id"] for o in store.observations()}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("check-in item은 객체여야 합니다.")
        candidate = _candidate(store, item.get("candidate_id"))
        if candidate["id"] in seen:
            raise ValueError("한 check-in에서 후보를 중복 기록할 수 없습니다.")
        seen.add(candidate["id"])
        decision = item.get("decision")
        if decision not in ("none", "continue", "park", "kill", "reopen"):
            raise ValueError("decision은 none/continue/park/kill/reopen 중 하나입니다.")
        ids = _strings(item.get("evidence_ids", []), "evidence_ids", 0, 20)
        if set(ids) - known_evidence:
            raise ValueError("check-in에는 현재 접근 가능한 근거 ID만 연결하세요.")
        normalized.append({"candidate_id": candidate["id"],
                           "hours_spent": _number(item.get("hours_spent"), "hours_spent", 0, 168),
                           "spend_krw": _integer(item.get("spend_krw"), "spend_krw", 0, 10**12),
                           "accomplishments": _strings(item.get("accomplishments", []), "accomplishments", 0, 20),
                           "blockers": _strings(item.get("blockers", []), "blockers", 0, 20),
                           "decision": decision, "evidence_ids": ids,
                           "note": _text(item.get("note"), "note")})
    data = {"id": record_id, "week_start": week, "summary": _text(payload.get("summary"), "summary"),
            "items": normalized, "total_hours": sum(item["hours_spent"] for item in normalized),
            "total_spend_krw": sum(item["spend_krw"] for item in normalized), "recorded_at": stamp(),
            "boundary": "창업자 자기보고 운영 기록이며 고객 수요나 회계감사를 대신하지 않습니다."}
    with store.db:
        store.record("founder_checkin", data)
    return {"status": "recorded", "id": record_id, "record": data}


def save_reopen_signal(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("재개 신호는 JSON 객체여야 합니다.")
    candidate = _candidate(store, payload.get("candidate_id"))
    if candidate["stage"] != "killed":
        raise ValueError("폐기된 후보에만 재개 신호를 등록할 수 있습니다.")
    if payload.get("confirmed_by_founder") is not True:
        raise ValueError("reopen_condition 충족 여부는 창업자가 명시적으로 확인해야 합니다.")
    ids = _strings(payload.get("evidence_ids"), "evidence_ids", 1, 20)
    observations = {o["id"]: o for o in store.observations()}
    if set(ids) - set(observations):
        raise ValueError("현재 접근 가능한 새 근거만 연결하세요.")
    killed_events = [e for e in store.records("blue_ocean_event") if e.get("candidate_id") == candidate["id"] and e.get("to_stage") == "killed"]
    killed_at = max((parse_date(e["recorded_at"]) for e in killed_events), default=None)
    if not killed_at or any(parse_date(observations[i]["observed_at"]) <= killed_at for i in ids):
        raise ValueError("폐기 이후 관측된 새 근거가 필요합니다.")
    condition = _text(payload.get("matched_condition"), "matched_condition")
    record_id = "founder-reopen-" + digest([candidate["id"], ids, condition])[:24]
    data = {"id": record_id, "candidate_id": candidate["id"], "evidence_ids": ids,
            "matched_condition": condition, "candidate_reopen_condition": candidate["reopen_condition"],
            "confirmed_by_founder": True, "recorded_at": stamp(), "consumed_at": None,
            "boundary": "재개 조건 일치에 대한 창업자 확인이며 새 시장성 증명이 아닙니다."}
    with store.db:
        store.record("founder_reopen_signal", data)
    return {"status": "recorded", "id": record_id, "record": data}


def _group(stage):
    return next((name for name, stages in GROUPS.items() if stage in stages), None)


def _fit_map(store):
    return {row["candidate_id"]: row for row in store.records("founder_fit")}


def _pipeline_map(store):
    return {row["candidate_id"]: row for row in store.records("founder_pipeline")}


def capacity_plan(store):
    profile = _profile(store, required=False)
    if not profile:
        return {"status": "setup_required", "template": template("profile"), "focus": [], "overflow": [],
                "boundary": "확인된 시간·예산·WIP 한도 없이는 자원을 자동 배분하지 않습니다."}
    candidates = [c for c in store.records("blue_ocean") if c["stage"] in blue_ocean.ACTIVE_STAGES]
    fits, pipelines = _fit_map(store), _pipeline_map(store)
    profile_revision = _revision(store, "founder_profile", PROFILE_ID)
    actual_spend = sum(row.get("total_spend_krw", 0) for row in store.records("founder_checkin"))
    remaining_cash = max(0, profile["deployable_cash_krw"] - actual_spend)
    spendable_this_week = min(profile["weekly_budget_krw"], remaining_cash)
    priorities = {candidate_id: index for index, candidate_id in enumerate(profile["priority_order"])}
    distant = datetime.max.replace(tzinfo=KST)
    candidates.sort(key=lambda c: (priorities.get(c["id"], 10**6), GROUP_ORDER[_group(c["stage"])],
                                   parse_date((c.get("next_action") or {}).get("due_at")) or distant, c["id"]))
    group_counts = {name: 0 for name in GROUPS}
    hours_used = 0.0
    budget_used = 0
    focus, overflow, needs_setup, misfit = [], [], [], []
    for candidate in candidates:
        fit, pipeline = fits.get(candidate["id"]), pipelines.get(candidate["id"])
        fit_current = fit and fit.get("profile_revision") == profile_revision
        if fit_current and fit["decision"] == "misaligned":
            misfit.append({"candidate_id": candidate["id"], "reasons": fit["capacity_conflicts"] or
                           [name for name, item in fit["dimensions"].items() if item["status"] == "MISFIT"]})
        group = _group(candidate["stage"])
        hours = pipeline["weekly_hours_estimate"] if pipeline else (fit["weekly_hours_required"] if fit else None)
        budget = pipeline["weekly_budget_krw"] if pipeline else (fit["weekly_budget_required_krw"] if fit else None)
        missing = [name for name, value in (("founder_fit", fit), ("pipeline", pipeline),
                                             ("weekly_hours", hours), ("weekly_budget", budget)) if value is None]
        if fit and not fit_current:
            missing.append("founder_fit_profile_changed")
        if missing:
            needs_setup.append({"candidate_id": candidate["id"], "missing": missing})
        reasons = []
        if group_counts[group] >= profile["wip_limits"][group]:
            reasons.append("group_wip_limit")
        if len(focus) >= profile["max_total_active"]:
            reasons.append("total_wip_limit")
        if hours is not None and hours_used + hours > profile["weekly_hours_available"]:
            reasons.append("weekly_hours_limit")
        if budget is not None and budget_used + budget > spendable_this_week:
            reasons.append("weekly_budget_limit")
        row = {"candidate_id": candidate["id"], "title": candidate["title"], "stage": candidate["stage"],
               "group": group, "weekly_hours": hours, "weekly_budget_krw": budget,
               "next_action": candidate.get("next_action")}
        if reasons:
            overflow.append({**row, "reasons": reasons})
        else:
            focus.append(row)
            group_counts[group] += 1
            hours_used += hours or 0
            budget_used += budget or 0
    return {"status": "planned", "focus": focus, "overflow": overflow, "needs_setup": needs_setup,
            "founder_misfit": misfit, "allocation": {"hours_planned": hours_used,
            "hours_available": profile["weekly_hours_available"], "budget_planned_krw": budget_used,
            "weekly_budget_krw": profile["weekly_budget_krw"], "spendable_this_week_krw": spendable_this_week,
            "actual_spend_to_date_krw": actual_spend, "deployable_cash_krw": profile["deployable_cash_krw"],
            "remaining_deployable_cash_krw": remaining_cash},
            "wip": {"used": group_counts, "limits": profile["wip_limits"], "total_limit": profile["max_total_active"]},
            "ordering": "창업자 명시 우선순위→출시/구축/검증/탐색→마감. 성공확률 점수는 사용하지 않습니다.",
            "boundary": "확인된 자원 요구만 배분하며 누락값을 0으로 간주하지 않습니다."}


def _latest_checkin(store):
    rows = sorted(store.records("founder_checkin"), key=lambda row: row["week_start"], reverse=True)
    return rows[0] if rows else None


def _lifecycle_map(store):
    return {row["candidate_id"]: row for row in store.records("founder_lifecycle")}


def _save_lifecycle(store, candidate, state, reason, evidence_ids=None, trigger_record_ids=None):
    record_id = "founder-lifecycle-" + candidate["key"]
    old = next((row for row in store.records("founder_lifecycle") if row["id"] == record_id), None)
    resume_evidence = list(evidence_ids or [])
    if not resume_evidence and candidate["stage"] in ("launched", "scaling"):
        stage_events = [event for event in store.records("blue_ocean_event")
                        if event.get("candidate_id") == candidate["id"] and event.get("to_stage") == candidate["stage"]]
        if stage_events:
            resume_evidence = stage_events[0].get("evidence_ids", [])
    data = {"id": record_id, "candidate_id": candidate["id"], "state": state,
            "previous_stage": candidate["stage"] if candidate["stage"] in blue_ocean.ACTIVE_STAGES else
                              (old.get("previous_stage") if old else "researching"),
            "saved_next_action": candidate.get("next_action") or (old.get("saved_next_action") if old else None),
            "saved_review_after": candidate.get("review_after") or (old.get("saved_review_after") if old else None),
            "reason": reason, "evidence_ids": resume_evidence,
            "trigger_record_ids": trigger_record_ids or [], "updated_at": stamp()}
    store.record("founder_lifecycle", data, _revision(store, "founder_lifecycle", record_id))
    return data


def _pipeline_action(store, candidate, pipeline):
    status = pipeline_status(store, pipeline)
    track = status["next_track"]
    if not track:
        return None
    row = status["tracks"][track]
    plans = {p["id"]: p for p in store.records("validation_plan")}
    linked = [plans[i] for i in row["plan_ids"] if i in plans]
    if linked:
        plan = sorted(linked, key=lambda p: p["ends_at"])[0]
        due = parse_date(plan["ends_at"])
        if due <= now():
            due = now() + timedelta(days=1)
        action = {
            "hypothesis": plan["hypothesis"], "action": f"{track} 검증 결과를 수집·기록한다: {plan['method']}",
            "pass_condition": "사전 등록 기준 criterion_met", "stop_condition": "사전 등록 기준 stop_criterion_met",
            "due_at": stamp(due), "estimated_cost_krw": plan.get("budget_krw", 0),
            "external_action_required": True, "execution_authorized": False,
        }
    else:
        action = {
            "hypothesis": f"{track} 단계의 가장 위험한 가설을 사전 등록한다",
            "action": f"{track} validation plan을 작성하고 통과·중단 기준을 고정한다",
            "pass_condition": "불변 validation plan 등록", "stop_condition": "안전·예산·접근 조건을 충족하지 못함",
            "due_at": stamp(now() + timedelta(days=7)), "estimated_cost_krw": 0,
            "external_action_required": False, "execution_authorized": None,
        }
    current = candidate.get("next_action") or {}
    comparable = {key: action[key] for key in ("hypothesis", "action", "pass_condition", "stop_condition", "due_at", "estimated_cost_krw", "external_action_required")}
    if all(current.get(key) == value for key, value in comparable.items()):
        return None
    return {"type": "sync_pipeline_action", "candidate_id": candidate["id"], "track": track,
            "next_action": action, "reason": "pipeline_next_track:" + track}


def reconcile(store, apply=False):
    profile = _profile(store, required=False)
    if not profile:
        return {"status": "setup_required", "applied": False, "actions": [], "template": template("profile")}
    candidates = {c["id"]: c for c in store.records("blue_ocean")}
    fits, pipelines = _fit_map(store), _pipeline_map(store)
    plan = capacity_plan(store)
    checkin = _latest_checkin(store)
    decisions = {item["candidate_id"]: item for item in (checkin or {}).get("items", []) if item["decision"] != "none"}
    actions, decided = [], set()

    def add(candidate_id, action_type, reason, evidence_ids=None):
        if candidate_id not in decided:
            actions.append({"type": action_type, "candidate_id": candidate_id, "reason": reason,
                            "evidence_ids": evidence_ids or []})
            decided.add(candidate_id)

    # Explicit weekly founder decisions are highest priority.
    for candidate_id, item in decisions.items():
        candidate = candidates[candidate_id]
        if item["decision"] == "kill" and candidate["stage"] != "killed":
            add(candidate_id, "kill", "weekly_checkin_decision", item["evidence_ids"])
        elif item["decision"] == "park" and candidate["stage"] in blue_ocean.ACTIVE_STAGES:
            add(candidate_id, "park", "weekly_checkin_decision", item["evidence_ids"])
        elif item["decision"] == "reopen" and candidate["stage"] in ("parked", "killed"):
            add(candidate_id, "reopen", "weekly_checkin_decision", item["evidence_ids"])

    if profile["policies"]["auto_kill_on_stop"]:
        for candidate_id, pipeline in pipelines.items():
            if candidate_id in candidates and candidates[candidate_id]["stage"] in blue_ocean.ACTIVE_STAGES:
                stopped = pipeline_status(store, pipeline)["stopped_tracks"]
                if stopped and candidate_id not in decided:
                    stopped_results = [r for r in store.records("validation_result")
                                       if r.get("plan_id") in sum((pipeline["tracks"][name]["plan_ids"] for name in stopped), []) and
                                       r.get("outcome") == "stop_criterion_met"]
                    measured_evidence = list(dict.fromkeys(link["evidence_id"] for result in stopped_results
                                                           for link in result.get("evidence_links", [])))
                    add(candidate_id, "kill", "prespecified_stop_criterion:" + ",".join(stopped), measured_evidence)
                    actions[-1]["trigger_result_ids"] = [result["id"] for result in stopped_results]
    if profile["policies"]["auto_park_founder_misfit"]:
        for candidate_id, fit in fits.items():
            if candidate_id in candidates and candidates[candidate_id]["stage"] in blue_ocean.ACTIVE_STAGES and \
                    fit.get("profile_revision") == _revision(store, "founder_profile", PROFILE_ID) and fit["decision"] == "misaligned":
                add(candidate_id, "park", "founder_fit_misaligned")
    if profile["policies"]["auto_park_overflow"]:
        for item in plan["overflow"]:
            add(item["candidate_id"], "park", "capacity:" + ",".join(item["reasons"]))
    if profile["policies"]["auto_park_stale"]:
        cutoff = now() - timedelta(days=profile["stale_after_days"])
        for candidate in candidates.values():
            updated = parse_date(candidate.get("updated_at"))
            review = parse_date(candidate.get("review_after"))
            if candidate["stage"] in blue_ocean.ACTIVE_STAGES and updated and updated <= cutoff and review and review <= now():
                add(candidate["id"], "park", "stale_overdue_review")
    if profile["policies"]["auto_advance_gated_stages"]:
        for candidate in candidates.values():
            if candidate["id"] in decided or candidate["stage"] not in ("researching", "validating"):
                continue
            assessment = blue_ocean.assess(store, candidate)
            if assessment["recommended_transition"]:
                add(candidate["id"], "advance", "evidence_gate_met:" + assessment["recommended_transition"])
                actions[-1]["to_stage"] = assessment["recommended_transition"]
    # Pipeline synchronization is local planning; it does not execute the experiment.
    for candidate_id, pipeline in pipelines.items():
        candidate = candidates.get(candidate_id)
        if candidate and candidate_id not in decided and candidate["stage"] in blue_ocean.ACTIVE_STAGES:
            action = _pipeline_action(store, candidate, pipeline)
            if action:
                actions.append(action)
                decided.add(candidate_id)

    lifecycles = _lifecycle_map(store)
    if profile["policies"]["auto_reopen_wip"]:
        used = dict(plan["wip"]["used"])
        total_used = len(plan["focus"])
        hours_used = plan["allocation"]["hours_planned"]
        budget_used = plan["allocation"]["budget_planned_krw"]
        for candidate_id, lifecycle in lifecycles.items():
            candidate = candidates.get(candidate_id)
            if candidate and candidate["stage"] == "parked" and lifecycle["state"] == "parked" and \
                    lifecycle["reason"].startswith(("capacity:", "stale_")):
                target_group = _group(lifecycle.get("previous_stage"))
                pipeline = pipelines.get(candidate_id)
                fit = fits.get(candidate_id)
                hours = pipeline["weekly_hours_estimate"] if pipeline else (fit["weekly_hours_required"] if fit else None)
                budget = pipeline["weekly_budget_krw"] if pipeline else (fit["weekly_budget_required_krw"] if fit else None)
                has_slot = target_group and used[target_group] < profile["wip_limits"][target_group] and \
                           total_used < profile["max_total_active"]
                has_time = hours is not None and hours_used + hours <= profile["weekly_hours_available"]
                has_budget = budget is not None and budget_used + budget <= plan["allocation"]["spendable_this_week_krw"]
                if has_slot and has_time and has_budget:
                    add(candidate_id, "reopen", "capacity_slot_available")
                    used[target_group] += 1
                    total_used += 1
                    hours_used += hours
                    budget_used += budget
    if profile["policies"]["auto_reopen_on_evidence"]:
        signals = sorted(store.records("founder_reopen_signal"), key=lambda r: r["recorded_at"], reverse=True)
        for signal in signals:
            candidate = candidates.get(signal["candidate_id"])
            if candidate and candidate["stage"] == "killed" and not signal.get("consumed_at"):
                add(candidate["id"], "reopen", "confirmed_reopen_signal", signal["evidence_ids"])

    preview = {"status": "preview" if not apply else "applied", "applied": apply, "actions": actions,
               "capacity_plan": plan, "external_actions_executed": False,
               "boundary": "로컬 상태·계획만 자동 관리하며 고객 연락·지출·게시·출시는 실행하지 않습니다."}
    if not apply:
        return preview
    results = []
    for action in actions:
        candidate = _candidate(store, action["candidate_id"])
        try:
            if action["type"] in ("park", "kill"):
                _save_lifecycle(store, candidate, "parked" if action["type"] == "park" else "killed",
                                action["reason"], action.get("evidence_ids"), action.get("trigger_result_ids"))
                target = "parked" if action["type"] == "park" else "killed"
                result = blue_ocean.transition(store, {"candidate_id": candidate["id"], "to_stage": target,
                    "reason": "founder_ops:" + action["reason"], "evidence_ids": action.get("evidence_ids", []),
                    "expected_revision": _revision(store, "blue_ocean", candidate["id"])})
            elif action["type"] == "reopen":
                lifecycle = _lifecycle_map(store).get(candidate["id"])
                target = "researching" if candidate["stage"] == "killed" else (lifecycle or {}).get("previous_stage", "researching")
                transition_evidence = action.get("evidence_ids", []) or ((lifecycle or {}).get("evidence_ids", []) if candidate["stage"] == "parked" else [])
                saved = (lifecycle or {}).get("saved_next_action")
                next_action = dict(saved) if saved else {"hypothesis": candidate["reopen_condition"],
                    "action": "새 근거로 문제·지불·공급 공백을 다시 검토한다", "pass_condition": "재개 조건을 뒷받침하는 원문과 고객 근거 확인",
                    "stop_condition": "새 근거가 기존 반증을 뒤집지 못함", "estimated_cost_krw": 0,
                    "external_action_required": False}
                next_action["due_at"] = stamp(now() + timedelta(days=7))
                next_action.pop("execution_authorized", None)
                result = blue_ocean.transition(store, {"candidate_id": candidate["id"], "to_stage": target,
                    "reason": "founder_ops:" + action["reason"], "evidence_ids": transition_evidence,
                    "next_action": next_action, "review_after": stamp(now() + timedelta(days=7)),
                    "expected_revision": _revision(store, "blue_ocean", candidate["id"])})
                with store.db:
                    _save_lifecycle(store, _candidate(store, candidate["id"]), "active", action["reason"], action.get("evidence_ids"))
                    for signal in store.records("founder_reopen_signal"):
                        if signal["candidate_id"] == candidate["id"] and not signal.get("consumed_at"):
                            updated = dict(signal); updated["consumed_at"] = stamp()
                            store.record("founder_reopen_signal", updated, _revision(store, "founder_reopen_signal", signal["id"]))
            elif action["type"] == "advance":
                result = blue_ocean.transition(store, {"candidate_id": candidate["id"], "to_stage": action["to_stage"],
                    "reason": "founder_ops:" + action["reason"], "evidence_ids": [],
                    "expected_revision": _revision(store, "blue_ocean", candidate["id"])})
            else:  # sync_pipeline_action
                updated = dict(candidate)
                updated["next_action"] = action["next_action"]
                updated["review_after"] = action["next_action"]["due_at"]
                updated["updated_at"] = stamp()
                with store.db:
                    revision = store.record("blue_ocean", updated, _revision(store, "blue_ocean", candidate["id"]))
                    event = {"id": "blue-ocean-event-" + digest([candidate["id"], revision, action["reason"], updated["updated_at"]])[:24],
                             "event_type": "operator_next_action", "candidate_id": candidate["id"],
                             "from_stage": candidate["stage"], "to_stage": candidate["stage"],
                             "reason": action["reason"], "evidence_ids": [], "recorded_at": updated["updated_at"],
                             "external_action_executed": False}
                    store.record("blue_ocean_event", event)
                result = {"status": "next_action_synced", "revision": revision}
            results.append({"candidate_id": candidate["id"], "type": action["type"], "status": "applied", "result": result})
        except ValueError as exc:
            results.append({"candidate_id": candidate["id"], "type": action["type"], "status": "blocked", "reason": str(exc)})
    preview["results"] = results
    preview["capacity_after"] = capacity_plan(store)
    return preview


def status(store):
    profile = _profile(store, required=False)
    fits = _fit_map(store)
    pipelines = _pipeline_map(store)
    candidates = store.records("blue_ocean")
    return {"configured": profile is not None, "profile": profile,
            "capacity_plan": capacity_plan(store),
            "candidate_operations": [{"candidate_id": c["id"], "title": c["title"], "stage": c["stage"],
                                      "founder_fit": fits.get(c["id"]),
                                      "pipeline": pipeline_status(store, pipelines[c["id"]]) if c["id"] in pipelines else None}
                                     for c in candidates],
            "kpi_plans": len(store.records("founder_kpi_plan")),
            "kpi_snapshots": len(store.records("founder_kpi_snapshot")),
            "checkins": len(store.records("founder_checkin")),
            "automatic_external_actions": False,
            "boundary": "개인 창업 운영 상태이며 시장 성공·회계 정확성·자동 외부 실행을 보장하지 않습니다."}


def _kpi_section(store):
    plans = {p["id"]: p for p in store.records("founder_kpi_plan")}
    snapshots = sorted(store.records("founder_kpi_snapshot"), key=lambda r: (r["plan_id"], r["week_start"]), reverse=True)
    grouped = {}
    for row in snapshots:
        grouped.setdefault(row["plan_id"], []).append(row)
    output = []
    for plan_id, rows in grouped.items():
        current, previous = rows[0], rows[1] if len(rows) > 1 else None
        changes = {key: current["values"][key] - previous["values"][key] for key in current["values"]} if previous else None
        output.append({"plan_id": plan_id, "candidate_id": plans.get(plan_id, {}).get("candidate_id"),
                       "week_start": current["week_start"], "values": current["values"],
                       "judgements": current["judgements"], "changes_from_previous": changes})
    return output


def weekly_brief(store, week_start=None, apply=False):
    week = _week_start(week_start)
    reconciliation = reconcile(store, apply=apply)
    current_status = status(store)
    checkin = next((r for r in store.records("founder_checkin") if r["week_start"] == week), None)
    kpis = _kpi_section(store)
    data = {"generated_at": stamp(), "week_start": week, "reconciliation": reconciliation,
            "capacity": current_status["capacity_plan"], "checkin": checkin,
            "candidate_operations": current_status["candidate_operations"], "kpis": kpis,
            "decisions_needed": [], "boundary": "CEO 운영 브리핑이며 고객 행동·지출·출시를 대신 실행하지 않습니다."}
    if not current_status["configured"]:
        data["decisions_needed"].append("개인 시간·예산·WIP 운영 프로필 확인")
    for item in current_status["capacity_plan"].get("needs_setup", []):
        data["decisions_needed"].append(item["candidate_id"] + ": " + ", ".join(item["missing"]))
    for operation in current_status["candidate_operations"]:
        pipeline = operation["pipeline"]
        if pipeline and pipeline["stopped_tracks"]:
            data["decisions_needed"].append(operation["candidate_id"] + ": 중단 기준 충족 " + ",".join(pipeline["stopped_tracks"]))
    report_dir = store.workspace / "reports"
    atomic_json(report_dir / "founder-ceo-weekly.json", data)
    lines = ["# 허구김 주간 CEO 브리핑", "", f"주차: {week}", f"생성: {data['generated_at']}", "",
             "## 이번 주 집중", ""]
    focus = data["capacity"].get("focus", [])
    lines += [f"- {item['title']} · {item['stage']} · {item['weekly_hours']}시간 · {item['weekly_budget_krw']}원"
              for item in focus] or ["- 운영 프로필 또는 집중 후보 설정 필요"]
    lines += ["", "## 자원", ""]
    allocation = data["capacity"].get("allocation")
    if allocation:
        lines += [f"- 시간: {allocation['hours_planned']} / {allocation['hours_available']}시간",
                  f"- 주간 예산: {allocation['budget_planned_krw']} / {allocation['weekly_budget_krw']}원",
                  f"- 누적 실제 지출: {allocation['actual_spend_to_date_krw']}원",
                  f"- 보호예비금 제외 잔여 현금: {allocation['remaining_deployable_cash_krw']}원"]
    else:
        lines += ["- 확인된 자원 한도 없음"]
    lines += ["", "## KPI", ""]
    lines += [f"- {item['candidate_id']} ({item['week_start']}): " + ", ".join(f"{k}={v}" for k, v in item["values"].items())
              for item in kpis] or ["- 출시 이후 KPI 기록 없음"]
    lines += ["", "## 자동 운영", ""]
    lines += [f"- {item['type']}: {item['candidate_id']} · {item['reason']}" for item in reconciliation.get("actions", [])] or ["- 변경 없음"]
    lines += ["", "## CEO 결정 필요", ""]
    lines += ["- " + item for item in data["decisions_needed"]] or ["- 즉시 필요한 결정 없음"]
    lines += ["", data["boundary"]]
    atomic_text(report_dir / "founder-ceo-weekly.md", "\n".join(lines) + "\n")
    return {"report_path": str(report_dir / "founder-ceo-weekly.md"), **data}
