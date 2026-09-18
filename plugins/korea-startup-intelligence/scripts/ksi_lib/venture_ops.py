"""Task, execution and monthly operating layer for a solo founder."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import blue_ocean, venture_intelligence
from .model import digest, now, parse_date, stamp


TASK_STATES = {"todo", "in_progress", "blocked", "done", "cancelled"}
ACTION_TRANSITIONS = {
    "planned": {"approved", "cancelled"},
    "approved": {"executing", "cancelled"},
    "executing": {"completed", "failed", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}
TRACKS = ("interview", "mvp", "pricing", "gtm")


def _text(value, field, maximum=1600):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field}: 비어 있지 않은 {maximum}자 이하 텍스트가 필요합니다.")
    return value.strip()


def _strings(value, field, minimum=0, maximum=30):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field}: {minimum}~{maximum}개 문자열 목록이 필요합니다.")
    result = [_text(item, field, 600) for item in value]
    if len(result) != len(set(result)):
        raise ValueError(f"{field}: 중복을 제거하세요.")
    return result


def _number(value, field, maximum=10**12):
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(f"{field}: 0~{maximum} 숫자가 필요합니다.")
    return value


def _candidate(store, value):
    candidate = next((row for row in store.records("blue_ocean") if row["id"] == value or row["key"] == value), None)
    if not candidate:
        raise ValueError("후보를 찾을 수 없습니다.")
    return candidate


def _revision(store, kind, record_id):
    row = store.db.execute("SELECT revision FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
    return row[0] if row else 0


def template(kind):
    templates = {
        "task": {"key": None, "candidate_id": None, "title": None, "track": "interview", "status": "todo",
                 "due_at": None, "estimated_hours": None, "budget_krw": 0, "dependencies": [],
                 "definition_of_done": None, "external_action_required": False, "expected_revision": 0},
        "task-result": {"task_id": None, "status": "done", "outcome": None, "summary": None,
                        "actual_hours": None, "actual_cost_krw": 0, "evidence_ids": [], "limitations": []},
        "action": {"key": None, "candidate_id": None, "title": None, "state": "planned",
                   "external_action": True, "authorization_scope": None, "budget_cap_krw": 0,
                   "due_at": None, "expected_revision": 0},
        "action-transition": {"action_id": None, "to_state": None, "reason": None,
                              "user_confirmed": False, "evidence_ids": [], "result_summary": None},
    }
    if kind not in templates:
        raise ValueError("venture-ops template: task/task-result/action/action-transition 중 하나가 필요합니다.")
    return templates[kind]


def save_task(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("task 입력은 객체여야 합니다.")
    candidate = _candidate(store, payload.get("candidate_id"))
    key = payload.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", key):
        raise ValueError("task key는 영문 소문자·숫자·하이픈이어야 합니다.")
    record_id = "founder-task-" + candidate["key"] + "-" + key
    old = next((row for row in store.records("founder_task") if row["id"] == record_id), None)
    expected = payload.get("expected_revision", 0)
    store.assert_revision("founder_task", record_id, expected)
    status = payload.get("status", "todo")
    if status not in TASK_STATES:
        raise ValueError("task status: todo/in_progress/blocked/done/cancelled")
    track = payload.get("track")
    if track not in TRACKS and track not in ("research", "build", "operations", "growth"):
        raise ValueError("task track이 유효하지 않습니다.")
    due = parse_date(payload.get("due_at"))
    if not due:
        raise ValueError("task due_at은 시간대가 있는 ISO 시각이어야 합니다.")
    dependencies = _strings(payload.get("dependencies", []), "dependencies", 0, 20)
    known = {row["id"] for row in store.records("founder_task")}
    if set(dependencies) - known:
        raise ValueError("dependencies에는 기존 task ID만 넣으세요.")
    data = {"id": record_id, "key": key, "candidate_id": candidate["id"],
            "title": _text(payload.get("title"), "title"), "track": track, "status": status,
            "due_at": stamp(due), "estimated_hours": _number(payload.get("estimated_hours"), "estimated_hours", 1000),
            "budget_krw": int(_number(payload.get("budget_krw", 0), "budget_krw")),
            "dependencies": dependencies,
            "definition_of_done": _text(payload.get("definition_of_done"), "definition_of_done"),
            "external_action_required": bool(payload.get("external_action_required", False)),
            "created_at": old["created_at"] if old else stamp(), "updated_at": stamp(),
            "boundary": "로컬 작업 계획이며 외부 행동을 실행하거나 승인하지 않습니다."}
    with store.db:
        revision = store.record("founder_task", data, expected)
    return {"status": "saved", "id": record_id, "revision": revision, "task": data}


def record_task_result(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("task-result 입력은 객체여야 합니다.")
    task = next((row for row in store.records("founder_task") if row["id"] == payload.get("task_id")), None)
    if not task:
        raise ValueError("task를 찾을 수 없습니다.")
    status = payload.get("status")
    if status not in ("done", "blocked", "cancelled"):
        raise ValueError("결과 status는 done/blocked/cancelled입니다.")
    evidence_ids = _strings(payload.get("evidence_ids", []), "evidence_ids", 0, 20)
    known = {row["id"] for row in store.observations()}
    if set(evidence_ids) - known:
        raise ValueError("현재 유효한 evidence ID만 연결하세요.")
    record_id = "founder-task-result-" + digest([task["id"], status, evidence_ids])[:24]
    if _revision(store, "founder_task_result", record_id):
        return {"status": "unchanged", "id": record_id}
    result = {"id": record_id, "task_id": task["id"], "candidate_id": task["candidate_id"],
              "status": status, "outcome": _text(payload.get("outcome"), "outcome"),
              "summary": _text(payload.get("summary"), "summary"),
              "actual_hours": _number(payload.get("actual_hours"), "actual_hours", 1000),
              "actual_cost_krw": int(_number(payload.get("actual_cost_krw", 0), "actual_cost_krw")),
              "evidence_ids": evidence_ids,
              "limitations": _strings(payload.get("limitations", []), "limitations", 0, 20),
              "recorded_at": stamp(), "boundary": "실행 결과 기록이며 고객 수요는 연결된 근거 범위에서만 판단합니다."}
    updated = dict(task); updated["status"] = status; updated["updated_at"] = result["recorded_at"]
    with store.db:
        store.record("founder_task_result", result)
        store.record("founder_task", updated, _revision(store, "founder_task", task["id"]))
        store.record("blue_ocean_event", {
            "id": "blue-ocean-event-" + digest([record_id, "task_result"])[:24],
            "event_type": "task_result", "candidate_id": task["candidate_id"],
            "from_stage": None, "to_stage": None,
            "reason": "작업 결과: " + result["outcome"], "evidence_ids": evidence_ids,
            "task_id": task["id"], "result_id": record_id, "recorded_at": result["recorded_at"],
            "external_action_executed": False})
    related = [event for evidence_id in evidence_ids
               for event in blue_ocean.note_evidence_change(store, evidence_id)]
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="task_result")
    return {"status": "recorded", "id": record_id, "result": result,
            "related_evidence_events": related, "portfolio_reassessment": reassessment}


def task_board(store, candidate_id=None):
    rows = [row for row in store.records("founder_task") if not candidate_id or row["candidate_id"] == _candidate(store, candidate_id)["id"]]
    results = {row["task_id"]: row for row in store.records("founder_task_result")}
    rows.sort(key=lambda row: (row["status"] in ("done", "cancelled"), parse_date(row["due_at"]), row["id"]))
    return {"tasks": [{**row, "result": results.get(row["id"]),
                        "overdue": row["status"] not in ("done", "cancelled") and parse_date(row["due_at"]) < now()}
                       for row in rows],
            "counts": {state: sum(row["status"] == state for row in rows) for state in TASK_STATES}}


def save_action(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("action 입력은 객체여야 합니다.")
    candidate = _candidate(store, payload.get("candidate_id"))
    key = payload.get("key")
    if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", key):
        raise ValueError("action key가 유효하지 않습니다.")
    record_id = "founder-action-" + candidate["key"] + "-" + key
    expected = payload.get("expected_revision", 0)
    store.assert_revision("founder_action", record_id, expected)
    due = parse_date(payload.get("due_at"))
    if not due:
        raise ValueError("action due_at이 필요합니다.")
    data = {"id": record_id, "candidate_id": candidate["id"], "key": key,
            "title": _text(payload.get("title"), "title"), "state": "planned",
            "external_action": bool(payload.get("external_action", True)),
            "authorization_scope": _text(payload.get("authorization_scope"), "authorization_scope"),
            "budget_cap_krw": int(_number(payload.get("budget_cap_krw", 0), "budget_cap_krw")),
            "due_at": stamp(due), "created_at": stamp(), "updated_at": stamp(),
            "external_action_executed_by_plugin": False}
    with store.db:
        revision = store.record("founder_action", data, expected)
    return {"status": "saved", "id": record_id, "revision": revision, "action": data}


def transition_action(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("action-transition 입력은 객체여야 합니다.")
    action = next((row for row in store.records("founder_action") if row["id"] == payload.get("action_id")), None)
    if not action:
        raise ValueError("action을 찾을 수 없습니다.")
    target = payload.get("to_state")
    if target not in ACTION_TRANSITIONS[action["state"]]:
        raise ValueError(f"허용되지 않은 action 이동: {action['state']} → {target}")
    if target == "approved" and action["external_action"] and payload.get("user_confirmed") is not True:
        raise ValueError("외부 행동 승인은 사용자의 명시적 확인이 필요합니다.")
    ids = _strings(payload.get("evidence_ids", []), "evidence_ids", 0, 20)
    if set(ids) - {row["id"] for row in store.observations()}:
        raise ValueError("현재 유효한 evidence ID만 연결하세요.")
    if target in ("completed", "failed") and not ids:
        raise ValueError("완료/실패에는 실제 결과 근거가 필요합니다.")
    updated = dict(action); updated["state"] = target; updated["updated_at"] = stamp()
    event = {"id": "founder-action-event-" + digest([action["id"], action["state"], target, updated["updated_at"]])[:24],
             "action_id": action["id"], "candidate_id": action["candidate_id"], "from_state": action["state"],
             "to_state": target, "reason": _text(payload.get("reason"), "reason"), "evidence_ids": ids,
             "result_summary": payload.get("result_summary"), "recorded_at": updated["updated_at"],
             "external_action_executed_by_plugin": False}
    if target in ("completed", "failed"):
        event["result_summary"] = _text(payload.get("result_summary"), "result_summary")
    with store.db:
        revision = store.record("founder_action", updated, _revision(store, "founder_action", action["id"]))
        store.record("founder_action_event", event)
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="action_result") if target in ("completed", "failed") else None
    return {"status": "transitioned", "revision": revision, "event": event,
            "portfolio_reassessment": reassessment}


def execution_package(store, candidate_id, apply=False):
    candidate = _candidate(store, candidate_id)
    due = now() + timedelta(days=14)
    package = {
        "id": "founder-package-" + candidate["key"], "candidate_id": candidate["id"],
        "generated_at": stamp(),
        "interview": {"goal": candidate["problem"], "sample": "접근 가능한 실제 역할 5명부터",
                      "questions": ["최근 이 문제를 겪은 실제 사례를 시간 순서대로 설명해 주세요.",
                                    "어떤 도구·사람·비용이 들었나요?", "현재 대안을 계속 쓰는 이유와 바꿀 조건은 무엇인가요?",
                                    "문제가 발생하지 않았던 경우는 언제였나요?", "구매 결정자는 누구이며 실제 예산은 어디서 나오나요?",
                                    "다음 수동 시험에 자기 자료로 참여할 이유가 있나요?"],
                      "pass_condition": "사전 적격 5명 중 3명 이상이 최근 반복 사례와 현재 비용을 제시",
                      "stop_condition": "반복 사례 2명 이하 또는 기존 무료 대안으로 충분"},
        "mvp": {"method": candidate["smallest_wedge"], "build_rule": "개발 전 수동·기존 도구 조합으로 핵심 결과 제공",
                "pass_condition": "실제 고객 자료로 반복 사용 또는 명시적 후속 요청 확인",
                "stop_condition": candidate["stop_condition"]},
        "pricing": {"tests": ["현재 지출·승인 단위 확인", "무료가 아닌 보증금/유료 수동 서비스 제안", "가격별 실제 선택 기록"],
                    "pass_condition": "말뿐인 의향이 아니라 계약 의향·보증금·거래 중 하나의 사용자 소유 근거",
                    "stop_condition": "지불자·예산·구매 절차를 확인하지 못함"},
        "gtm": {"beachhead": candidate["customer"], "channels": venture_intelligence.channel_map(store, candidate),
                "message": candidate["problem"] + "을 현재 방식보다 좁고 측정 가능하게 줄이는 수동 시험",
                "conversion_definition": "적격 고객이 자기 사례/자료로 다음 검증을 예약",
                "stop_condition": "접근 채널에서 적격 응답을 확보하지 못함"},
        "recommended_kpis": standard_kpis(), "external_actions_executed": False,
        "boundary": "실행 준비안이며 인터뷰·개발·가격 제안·연락을 자동 수행하지 않습니다.",
    }
    tasks = []
    if apply:
        existing = _revision(store, "founder_execution_package", package["id"])
        with store.db:
            store.record("founder_execution_package", package, existing)
        for index, track in enumerate(TRACKS):
            task_id = "founder-task-" + candidate["key"] + "-" + track
            if _revision(store, "founder_task", task_id):
                tasks.append({"id": task_id, "status": "existing"})
                continue
            task = save_task(store, {"key": track, "candidate_id": candidate["id"], "title": track + " 검증 준비",
                "track": track, "status": "todo", "due_at": stamp(due + timedelta(days=index * 7)),
                "estimated_hours": 2, "budget_krw": 0,
                "dependencies": ["founder-task-" + candidate["key"] + "-" + TRACKS[index - 1]] if index else [],
                "definition_of_done": "사전 통과·중단 기준과 실제 결과 기록", "external_action_required": track != "mvp",
                "expected_revision": 0})
            tasks.append({"id": task["id"], "status": "created"})
    return {"package": package, "applied": apply, "tasks": tasks}


def standard_kpis():
    return [
        {"key": "activation_rate", "definition": "적격 신규 사용자 중 핵심가치를 처음 완료한 비율", "unit": "fraction"},
        {"key": "retention_rate", "definition": "사전 정의한 기간 뒤 다시 핵심행동을 한 활성 코호트 비율", "unit": "fraction"},
        {"key": "gross_margin", "definition": "매출에서 변동원가·서비스 직접원가를 뺀 비율", "unit": "fraction"},
        {"key": "cac_krw", "definition": "같은 기간 신규 유료고객당 획득 지출", "unit": "KRW/customer"},
        {"key": "repeat_purchase_rate", "definition": "구매 가능 코호트 중 정의한 기간 내 재구매한 비율", "unit": "fraction"},
    ]


def monthly_plan(store, month=None):
    profile = next(iter(store.records("founder_profile")), None)
    if not profile:
        return {"status": "setup_required", "missing": ["founder_profile"]}
    try:
        month = month or now().date().strftime("%Y-%m")
        start = date.fromisoformat(month + "-01")
    except (TypeError, ValueError):
        raise ValueError("month는 YYYY-MM이어야 합니다.") from None
    monthly_hours = profile.get("monthly_hours_available")
    monthly_budget = profile.get("monthly_budget_krw")
    if monthly_hours is None or monthly_budget is None:
        return {"status": "setup_required", "month": month,
                "missing": [name for name, value in (("monthly_hours_available", monthly_hours),
                                                       ("monthly_budget_krw", monthly_budget)) if value is None],
                "boundary": "주간 한도를 임의로 월간 한도로 환산하지 않습니다."}
    ranking = venture_intelligence.portfolio_decisions(store, blue_ocean.assess)
    focus = []
    hours_left, budget_left = monthly_hours, monthly_budget
    pipelines = {row["candidate_id"]: row for row in store.records("founder_pipeline")}
    for row in ranking["items"]:
        candidate = _candidate(store, row["candidate_id"])
        if candidate["stage"] not in blue_ocean.ACTIVE_STAGES or row["dominated_by"]:
            continue
        pipeline = pipelines.get(candidate["id"])
        hours = pipeline.get("weekly_hours_estimate") * 4 if pipeline else None
        budget = pipeline.get("weekly_budget_krw") * 4 if pipeline else None
        if hours is None or budget is None:
            focus.append({"candidate_id": candidate["id"], "status": "needs_estimate"})
        elif hours <= hours_left and budget <= budget_left:
            focus.append({"candidate_id": candidate["id"], "status": "allocated",
                          "hours": hours, "budget_krw": budget})
            hours_left -= hours; budget_left -= budget
    return {"status": "planned", "month": month, "focus": focus,
            "hours": {"available": monthly_hours, "remaining": hours_left},
            "budget": {"available_krw": monthly_budget, "remaining_krw": budget_left},
            "boundary": "사용자가 확인한 월간 한도와 파이프라인 추정치의 배분이며 실제 지출 승인이 아닙니다."}


def weekly_variance(store, week_start=None):
    if week_start is None:
        current = now().date() - timedelta(days=now().date().weekday())
        week_start = current.isoformat()
    checkin = next((row for row in store.records("founder_checkin") if row["week_start"] == week_start), None)
    pipelines = {row["candidate_id"]: row for row in store.records("founder_pipeline")}
    actual = {item["candidate_id"]: item for item in (checkin or {}).get("items", [])}
    rows = []
    for candidate_id in sorted(set(pipelines) | set(actual)):
        plan = pipelines.get(candidate_id, {})
        observed = actual.get(candidate_id, {})
        rows.append({"candidate_id": candidate_id,
                     "weekly_goal": plan.get("weekly_goal"), "decision_due_at": plan.get("decision_due_at"),
                     "planned_bottlenecks": plan.get("bottlenecks", []),
                     "planned_hours": plan.get("weekly_hours_estimate"), "actual_hours": observed.get("hours_spent"),
                     "hours_variance": observed.get("hours_spent") - plan.get("weekly_hours_estimate")
                                       if observed.get("hours_spent") is not None and plan.get("weekly_hours_estimate") is not None else None,
                     "planned_budget_krw": plan.get("weekly_budget_krw"), "actual_spend_krw": observed.get("spend_krw"),
                     "budget_variance_krw": observed.get("spend_krw") - plan.get("weekly_budget_krw")
                                            if observed.get("spend_krw") is not None and plan.get("weekly_budget_krw") is not None else None,
                     "blockers": observed.get("blockers", []), "decision": observed.get("decision")})
    return {"week_start": week_start, "items": rows, "checkin_missing": checkin is None}


def failure_patterns(store):
    candidates = {row["id"]: row for row in store.records("blue_ocean")}
    killed = [event for event in store.records("blue_ocean_event") if event.get("to_stage") == "killed"]
    reasons = Counter()
    source_candidates = defaultdict(set)
    for event in killed:
        reason = event.get("reason", "unknown")
        code = reason.split(":", 1)[-1].split(",", 1)[0]
        reasons[code] += 1
        source_candidates[code].add(event.get("candidate_id"))
    for result in store.records("validation_result"):
        if result.get("outcome") == "stop_criterion_met":
            reasons["validation_stop_criterion"] += 1
    patterns = [{"code": code, "count": count, "candidate_ids": sorted(source_candidates[code])}
                for code, count in reasons.most_common()]
    warnings = []
    failed_terms = set()
    for event in killed:
        candidate = candidates.get(event.get("candidate_id"), {})
        failed_terms |= venture_intelligence.canonical_tokens(store, candidate.get("problem"))
    for candidate in candidates.values():
        if candidate["stage"] not in ("killed", "parked"):
            overlap = sorted(failed_terms & venture_intelligence.canonical_tokens(store, candidate.get("problem")))
            if overlap:
                warnings.append({"candidate_id": candidate["id"], "shared_failure_terms": overlap,
                                 "action": "기존 폐기 후보의 실패 원인이 반복되는지 확인"})
    return {"patterns": patterns, "active_candidate_warnings": warnings,
            "boundary": "저장된 실패의 반복 패턴이며 새 후보의 실패를 예측하지 않습니다."}


def status(store):
    return {"task_board": task_board(store), "actions": store.records("founder_action"),
            "monthly": monthly_plan(store), "weekly_variance": weekly_variance(store),
            "failure_learning": failure_patterns(store), "standard_kpis": standard_kpis()}
