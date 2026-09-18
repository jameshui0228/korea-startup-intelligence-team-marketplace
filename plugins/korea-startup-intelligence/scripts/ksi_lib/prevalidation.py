"""Zero-result bootstrap for evidence-first venture work.

This module helps a founder make progress before any customer experiment has
produced data.  It ranks *learning work*, not startup attractiveness, and never
turns public signals, scenarios, or synthetic examples into validation results.
"""
from __future__ import annotations

import json
from datetime import timedelta

from . import blue_ocean, venture_intelligence, venture_ops
from .model import digest, now, stamp


CUSTOMER_RESULT_KINDS = {"interview", "transaction", "customer_observation", "aggregate_metric"}
PUBLIC_CUSTOMER_KINDS = {"review", "comment"}
SUPPLY_KINDS = {"product", "app", "procurement_award", "crowdfunding", "repository"}
ATTENTION_KINDS = {"article", "post", "search_spike", "paper", "job", "patent", "standard", "regulation"}
CUSTOMER_ONLY_CLAIMS = {"problem", "current_spend", "reachability", "switching_reason"}
DESK_RESEARCHABLE_CLAIMS = {"supply_gap", "timing", "korea_fit", "counterevidence"}


def _candidate(store, value):
    row = next((item for item in store.records("blue_ocean")
                if item["id"] == value or item["key"] == value), None)
    if not row:
        raise ValueError("블루오션 후보를 찾을 수 없습니다.")
    return row


def _revision(store, kind, record_id):
    row = store.db.execute("SELECT revision FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
    return row[0] if row else 0


def _validation_state(store, candidate):
    dossier_id = candidate.get("dossier_id")
    plans = [row for row in store.records("validation_plan") if dossier_id and row.get("dossier_id") == dossier_id]
    plan_ids = {row["id"] for row in plans}
    results = [row for row in store.records("validation_result") if row.get("plan_id") in plan_ids]
    if results:
        state = "observed_results_available"
    elif plans:
        state = "prespecified_plan_only"
    else:
        state = "no_experiment_data"
    return {"state": state, "plan_ids": sorted(plan_ids),
            "result_ids": sorted(row["id"] for row in results),
            "passing_result_ids": sorted(row["id"] for row in results if row.get("outcome") == "criterion_met")}


def _evidence_inventory(store, candidate):
    linked = set(candidate.get("evidence_ids", []))
    rows = [row for row in store.observations() if row["id"] in linked]
    owned_customer = [row for row in rows
                      if row.get("kind") in CUSTOMER_RESULT_KINDS and
                      row.get("collection_basis") in ("user_owned", "authorized_export")]
    public_customer = [row for row in rows
                       if row.get("kind") in PUBLIC_CUSTOMER_KINDS and
                       row.get("speaker_role") == "customer" and not row.get("promotion_or_ad")]
    supply = [row for row in rows if row.get("kind") in SUPPLY_KINDS]
    attention = [row for row in rows if row.get("kind") in ATTENTION_KINDS]
    return {
        "linked_evidence_count": len(rows),
        "missing_or_expired_evidence_ids": sorted(linked - {row["id"] for row in rows}),
        "user_owned_customer_observations": len(owned_customer),
        "public_customer_voice_observations": len(public_customer),
        "supply_observations": len(supply),
        "attention_or_context_observations": len(attention),
        "transaction_observations": sum(row.get("kind") == "transaction" for row in owned_customer),
        "boundary": "공개 고객 발언과 관심 신호는 실제 모집 고객의 실험 결과가 아닙니다.",
    }


def _assumption_envelope(candidate):
    return {
        "status": "requires_founder_assumptions",
        "inputs": {
            "price_krw": None, "variable_cost_krw": None, "service_cost_krw": None,
            "orders_per_customer": None, "cac_krw": None, "fixed_cost_krw": None,
            "working_capital_buffer_krw": None,
        },
        "formulas": {
            "unit_contribution_krw": "price_krw - variable_cost_krw - service_cost_krw",
            "customer_contribution_krw": "unit_contribution_krw * orders_per_customer - cac_krw",
            "break_even_customers": "(fixed_cost_krw + working_capital_buffer_krw) / customer_contribution_krw",
        },
        "sensitivity_questions": [
            "어느 입력 하나가 20% 나빠지면 고객당 공헌이익이 음수가 되는가?",
            "반복 구매를 1회로 두어도 손익 구조가 성립하는가?",
            "수동 서비스 시간까지 직접원가에 포함했는가?",
        ],
        "boundary": "숫자가 없으면 계산하지 않습니다. 예시·합성값·업계 평균을 관측값으로 채우지 않습니다.",
    }


def _desk_tasks(candidate, assessment, validation):
    gaps = set(assessment["blocking_gaps"])
    missing = {item.split(":", 1)[1] for item in gaps if item.startswith("missing_evidence:")}
    base = now()
    common = {"candidate_id": candidate["id"], "track": "research", "status": "todo",
              "budget_krw": 0, "external_action_required": False}
    tasks = [
        {**common, "key": "bootstrap-claim-ledger", "title": "핵심 주장·반례 근거표 만들기",
         "due_at": stamp(base + timedelta(days=3)), "estimated_hours": 2,
         "definition_of_done": "문제·현재 지출·공급 공백·반례를 FACT/INFERENCE/ASSUMPTION/UNKNOWN으로 나누고 원문 위치와 한계를 연결"},
        {**common, "key": "bootstrap-alternative-audit", "title": "직접·간접·수작업·현상유지 대안과 공개 가격 조사",
         "due_at": stamp(base + timedelta(days=5)), "estimated_hours": 2,
         "definition_of_done": "대안별 고객·가격 단위·전환 마찰·놓치는 작업을 실제 공개 원문 범위에서 비교"},
        {**common, "key": "bootstrap-channel-map", "title": "접촉 전 초기 고객 채널 지도 작성",
         "due_at": stamp(base + timedelta(days=7)), "estimated_hours": 1,
         "definition_of_done": "창업자가 접근 가능한 역할·장소·커뮤니티·소개 경로와 접근 불가 조건을 구분하되 실제 연락은 하지 않음"},
        {**common, "key": "bootstrap-economics-bounds", "title": "단위경제 가정 범위와 손익분기 민감도 작성",
         "due_at": stamp(base + timedelta(days=10)), "estimated_hours": 2,
         "definition_of_done": "가격·직접원가·서비스 시간·반복 구매·CAC의 보수/기준/상한 가정을 출처 또는 창업자 가정으로 표시"},
        {**common, "key": "bootstrap-experiment-spec", "title": "첫 실제 검증의 사전 기준만 작성",
         "due_at": stamp(base + timedelta(days=14)), "estimated_hours": 2,
         "definition_of_done": "표본·모집·측정·통과·중단·안전·예산 기준을 고정한 계획 초안 작성. 실행·응답·결과는 생성하지 않음"},
    ]
    if not missing:
        tasks[0]["title"] = "확인된 주장과 남은 반례의 근거표 갱신"
    if validation["state"] == "prespecified_plan_only":
        tasks[-1]["title"] = "등록된 실험 계획의 실행 준비도 점검"
        tasks[-1]["definition_of_done"] = "기존 계획의 모집·측정·안전·권한·원자료 보관 준비를 점검하되 결과를 미리 만들지 않음"
    return tasks


def build(store, candidate):
    assessment = blue_ocean.assess(store, candidate)
    validation = _validation_state(store, candidate)
    inventory = _evidence_inventory(store, candidate)
    backed = set(assessment["evidence_backed_assessments"])
    customer_unknowns = sorted(CUSTOMER_ONLY_CLAIMS - backed)
    desk_unknowns = sorted(DESK_RESEARCHABLE_CLAIMS - backed)
    fit = next((row for row in venture_intelligence.portfolio_decisions(store, blue_ocean.assess)["items"]
                if row["candidate_id"] == candidate["id"]), None)
    if validation["state"] == "observed_results_available":
        lane = "use_observed_results"
    elif assessment["validation_ready"]:
        lane = "prespecify_first_experiment"
    elif customer_unknowns:
        lane = "reduce_customer_unknowns_without_claiming_validation"
    else:
        lane = "complete_desk_research"
    decision_ceiling = "validating" if assessment["validation_ready"] else "researching"
    if candidate["stage"] in ("parked", "killed"):
        decision_ceiling = candidate["stage"]
    fingerprint_input = {
        "candidate_id": candidate["id"], "candidate_updated_at": candidate.get("updated_at"),
        "assessment": {key: assessment.get(key) for key in (
            "whitespace_state", "blocking_gaps", "evidence_backed_assessments", "validation_ready")},
        "validation": validation, "inventory": inventory,
        "founder_fit": (fit or {}).get("decision_vector", {}).get("founder_fit"),
    }
    package = {
        "id": "prevalidation-bootstrap-" + candidate["key"], "candidate_id": candidate["id"],
        "candidate_stage": candidate["stage"], "mode": "zero_experiment_data_bootstrap",
        "generated_at": stamp(), "fingerprint": digest(fingerprint_input),
        "experiment_data": validation, "evidence_inventory": inventory,
        "claim_ceiling": {
            "customer_validation_required": customer_unknowns,
            "desk_research_can_reduce_uncertainty": desk_unknowns,
            "decision_ceiling_without_results": decision_ceiling,
            "stage_transition_performed": False,
        },
        "learning_lane": lane,
        "learning_priority_basis": {
            "blocking_gap_count": len(assessment["blocking_gaps"]),
            "customer_unknown_count": len(customer_unknowns),
            "desk_research_unknown_count": len(desk_unknowns),
            "founder_fit": (fit or {}).get("decision_vector", {}).get("founder_fit"),
            "next_learning_cost_krw": 0,
            "meaning": "의사결정에 중요한 미확인을 낮은 비용으로 줄이는 순서이며 사업 성공 순위가 아님",
        },
        "desk_research_tasks": _desk_tasks(candidate, assessment, validation),
        "assumption_envelope": _assumption_envelope(candidate),
        "handoff": {
            "when_ready": "실제 고객/거래 자료를 얻기 전에 validation plan 또는 qualitative-plan으로 기준을 고정",
            "never_auto_create": ["고객 응답", "구매 의향", "매출", "전환율", "실험 성공", "시장 규모 관측값"],
        },
        "boundary": "실험 데이터가 없어도 조사·비교·실험 준비는 진행합니다. 공개 근거·가정·시나리오는 실제 고객 검증이 아닙니다.",
    }
    return package


def _apply(store, package):
    previous = next((row for row in store.records("prevalidation_bootstrap") if row["id"] == package["id"]), None)
    if previous and previous.get("fingerprint") == package["fingerprint"]:
        record_status = "unchanged"
        saved = previous
    else:
        with store.db:
            revision = store.record("prevalidation_bootstrap", package,
                                    _revision(store, "prevalidation_bootstrap", package["id"]))
        saved = package
        record_status = "saved_revision_" + str(revision)
    task_results = []
    for task in package["desk_research_tasks"]:
        task_id = "founder-task-" + package["candidate_id"].removeprefix("blue-ocean-") + "-" + task["key"]
        if _revision(store, "founder_task", task_id):
            task_results.append({"id": task_id, "status": "existing_preserved"})
            continue
        result = venture_ops.save_task(store, {**task, "dependencies": [], "expected_revision": 0})
        task_results.append({"id": result["id"], "status": "created"})
    return {"record_status": record_status, "record": saved, "tasks": task_results,
            "candidate_stage_changed": False, "external_action_executed": False}


def bootstrap(store, candidate_id=None, limit=5, apply=False):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("limit: 1~20 범위가 필요합니다.")
    candidates = [_candidate(store, candidate_id)] if candidate_id else store.records("blue_ocean")
    if not candidates:
        return {"status": "candidate_required", "items": [],
                "next_step": "blue-ocean run 또는 sync --apply로 공개 근거가 연결된 첫 후보를 만든 뒤 다시 실행",
                "boundary": "실험 데이터는 필요 없지만 구체 고객·문제와 최소 한 개의 실제 출처는 필요합니다."}
    packages = [build(store, row) for row in candidates]
    lane_order = {"prespecify_first_experiment": 0,
                  "reduce_customer_unknowns_without_claiming_validation": 1,
                  "complete_desk_research": 2, "use_observed_results": 3}
    packages.sort(key=lambda row: (lane_order.get(row["learning_lane"], 9),
                                   -row["learning_priority_basis"]["blocking_gap_count"], row["candidate_id"]))
    packages = packages[:limit]
    applied = [_apply(store, package) for package in packages] if apply else []
    return {"status": "bootstrap_saved" if apply else "bootstrap_preview",
            "mode": "works_without_experiment_results", "items": packages, "applied": applied,
            "ranking": "학습 우선순위. 사업 매력도·성공확률 순위가 아님.",
            "external_actions_executed": False,
            "boundary": "실험 결과가 없어도 공개자료 검토와 실행 준비를 계속하지만 검증 완료로 승격하지 않습니다."}
