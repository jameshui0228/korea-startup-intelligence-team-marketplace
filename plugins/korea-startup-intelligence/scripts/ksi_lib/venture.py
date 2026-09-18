"""Persist evidence-linked founder questions and concrete alternatives."""
from copy import deepcopy

from .model import stamp, digest, atomic_json, atomic_text
from .radar import valid_reviews, ensure_radar
from .research import text, id_list

QUESTIONS = ("demand", "workaround", "specific_customer", "smallest_wedge", "observation_surprise", "future_fit")
PROMPTS = (
    "관심·조회가 아닌 실제 사용·지출·손실은 확인했는가?",
    "현재 해결 순서·도구·비용은 무엇인가?",
    "가장 절실한 고객의 역할·상황·구매 권한은 무엇인가?",
    "가장 작은 유료 가치와 반증 가능한 실험은 무엇인가?",
    "실제 사용 관찰에서 예상과 달랐던 점은 무엇인가?",
    "3년 뒤 더 필요하거나 불필요해질 조건은 무엇인가?",
)
STAGE_PRIORITIES = {
    "unknown": QUESTIONS,
    "pre_product": ("demand", "workaround", "specific_customer"),
    "users": ("workaround", "smallest_wedge", "observation_surprise"),
    "paying": ("smallest_wedge", "observation_surprise", "future_fit"),
}


def product_stage(value):
    if not isinstance(value, str) or value not in STAGE_PRIORITIES:
        raise ValueError("Product stage must be unknown/pre_product/users/paying; do not infer it from news")
    return value


def get_dossier(store, dossier_id):
    dossier = next((d for d in store.records("dossier") if d["id"] == dossier_id), None)
    if not dossier:
        raise ValueError("Venture review requires an existing evidence-linked dossier")
    return dossier


def prepare(store, dossier_id, stage=None):
    ensure_radar(store)
    dossier = get_dossier(store, dossier_id)
    prior = next((r for r in store.records("venture_review") if r["dossier_id"] == dossier_id), None)
    prior_assessment = assess(store, prior) if prior else None
    reusable = prior is not None and prior_assessment["current"]
    stage = product_stage(stage if stage is not None else prior.get("product_stage", "unknown") if reusable else "unknown")
    template = {"dossier_id": dossier_id, "mode": "explore", "decision": "research",
                "six_questions": {q: {"status": "UNKNOWN", "conclusion": p, "evidence_ids": []}
                                  for q, p in zip(QUESTIONS, PROMPTS)},
                "alternatives": [{"kind": k, "name": name, "approach": "미검토", "tradeoff": "미검토",
                                  "smallest_test": "미설계", "failure_condition": "미설계"}
                                 for k, name in (("status_quo", "현재 방식 유지"), ("minimal", "최소 서비스"))],
                "failure_modes": [{"risk": "고객 문제와 지불 근거 미확인", "detection": "실제 자료 검토 필요",
                                   "response": "확인 전 개발·집행 보류"}],
                "next_action": "기존 근거와 반례를 읽고 구체적인 다음 조사 하나를 설계"}
    if prior:
        # Never silently resurrect a rejected/parked proposal when evidence goes
        # stale. Retain the decision and alternatives; reopen only the answers.
        template = {key: deepcopy(prior[key]) if reusable or key != "six_questions" else value
                    for key, value in template.items()}
    template["product_stage"] = stage
    priority = list(STAGE_PRIORITIES[stage])
    ordered = priority + [q for q in QUESTIONS if q not in priority]
    unknown = [q for q in ordered if template["six_questions"][q]["status"] in ("UNKNOWN", "ASSUMPTION")]
    return {"status": "draft_questions_not_a_completed_review", "dossier": dossier,
            "input_template": template, "prior_review": prior_assessment,
            "diagnostic": {"product_stage": stage, "stage_basis": "explicit_or_previously_recorded_not_independently_verified",
                "priority_questions": priority, "next_questions": unknown,
                "reused_current_answers": [q for q in QUESTIONS if reusable and q not in unknown],
                "instruction": "Ask only the most decision-relevant unresolved question; do not repeat a current answer or invent observations. Stage is not proof of paying customers."}}


def assess(store, review):
    dossier = next((d for d in store.records("dossier") if d["id"] == review["dossier_id"]), None)
    gaps = []
    if not dossier or digest(dossier) != review.get("dossier_fingerprint"):
        gaps.append("dossier_changed_since_review")
    ids = sorted({i for a in review["six_questions"].values() for i in a["evidence_ids"]})
    try:
        valid_reviews(store, ids)
    except ValueError:
        gaps.append("stale_or_changed_review_evidence")
    unknown = [q for q in QUESTIONS if review["six_questions"][q]["status"] in ("UNKNOWN", "ASSUMPTION")]
    return {"id": review["id"], "dossier_id": review["dossier_id"], "decision": review["decision"],
            "product_stage": review.get("product_stage", "unknown"),
            "current": not gaps, "gaps": gaps, "unverified_questions": unknown,
            "next_action": review["next_action"], "customer_validation": "not_established_by_review"}


def status(store, dossier_id=None):
    ensure_radar(store)
    if dossier_id is not None:
        get_dossier(store, dossier_id)
    dossiers = [d for d in store.records("dossier") if dossier_id is None or d["id"] == dossier_id]
    reviews = [r for r in store.records("venture_review") if dossier_id is None or r["dossier_id"] == dossier_id]
    return {"reviews": [assess(store, r) for r in reviews],
            "missing_dossier_ids": [d["id"] for d in dossiers if not any(r["dossier_id"] == d["id"] for r in reviews)],
            "boundary": "Founder review is reasoning, not independent consensus or customer validation"}


def render(store, data):
    lines = ["# 사업 가설 검토", "", data["dossier_id"], "", "판단: " + data["decision"], "",
             "신고된 제품 단계: " + data.get("product_stage", "unknown") + " (고객 검증 증명이 아님)", ""]
    for q in QUESTIONS:
        answer = data["six_questions"][q]
        lines += ["## " + q, "", answer["status"] + " — " + answer["conclusion"], "",
                  "근거: " + (", ".join(answer["evidence_ids"]) or "없음"), ""]
    lines += ["## 대안 비교", ""]
    for a in data["alternatives"]:
        lines += ["### " + a["name"], "", a["approach"], "", "절충: " + a["tradeoff"], "",
                  "최소 실험: " + a["smallest_test"], "", "실패 조건: " + a["failure_condition"], ""]
    lines += ["## 실패 경로", ""]
    for f in data["failure_modes"]:
        lines += ["- " + f["risk"] + " / 관찰: " + f["detection"] + " / 대응: " + f["response"]]
    lines += ["", "다음 행동: " + data["next_action"], "", "고객 검증 결과가 아닙니다. 현재성은 venture-review status로 다시 확인합니다."]
    base = store.workspace / "reports/venture-reviews" / data["id"]
    atomic_json(base.with_suffix(".json"), data)
    atomic_text(base.with_suffix(".md"), "\n".join(lines) + "\n")
    return str(base.with_suffix(".md"))


def save(store, payload):
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError("Venture review must be a JSON object")
    dossier = get_dossier(store, payload.get("dossier_id"))
    if 'expected_revision' in payload:
        store.assert_revision('venture_review', 'venture-' + dossier['key'], payload['expected_revision'])
    if payload.get("mode") not in ("explore", "hold", "narrow") or payload.get("decision") not in ("research", "test", "park", "reject"):
        raise ValueError("Invalid venture review mode or decision")
    questions = payload.get("six_questions")
    if not isinstance(questions, dict) or set(questions) != set(QUESTIONS):
        raise ValueError("Answer all six founder questions; use UNKNOWN where necessary")
    reviews = {r["evidence_id"]: r for r in valid_reviews(store, dossier["evidence_ids"])}
    answers = {}
    for key, answer in questions.items():
        if not isinstance(answer, dict) or answer.get("status") not in ("FACT", "INFERENCE", "ASSUMPTION", "UNKNOWN"):
            raise ValueError("Venture answers require epistemic status")
        ids = id_list(answer.get("evidence_ids"), "venture evidence", 12)
        if set(ids) - set(reviews) or any(reviews[i]["read_scope"] == "metadata_only" for i in ids):
            raise ValueError("Venture evidence must be substantive dossier sources")
        if answer["status"] in ("FACT", "INFERENCE") and not ids:
            raise ValueError("Evidence-backed venture answers require evidence")
        answers[key] = {"status": answer["status"], "conclusion": text(answer.get("conclusion"), key), "evidence_ids": ids}
    data = {"id": "venture-" + dossier["key"], "dossier_id": dossier["id"], "dossier_fingerprint": digest(dossier),
            "mode": payload["mode"], "decision": payload["decision"], "six_questions": answers,
            "next_action": text(payload.get("next_action"), "next action"),
            "reviewed_at": stamp(), "boundary": "Reasoned hypotheses, not customer interviews or independent expert consensus"}
    if "product_stage" in payload:
        data["product_stage"] = product_stage(payload["product_stage"])
    for field, fields, low, high in (
        ("alternatives", ("name", "approach", "tradeoff", "smallest_test", "failure_condition"), 2, 3),
        ("failure_modes", ("risk", "detection", "response"), 1, 8),
    ):
        rows = payload.get(field)
        if not isinstance(rows, list) or not low <= len(rows) <= high or any(not isinstance(x, dict) for x in rows):
            raise ValueError("Invalid bounded venture review list: " + field)
        data[field] = [{k: text(r.get(k), k, 600) for k in fields} for r in rows]
    kinds = [r.get("kind") for r in payload["alternatives"]]
    if any(k not in ("status_quo", "minimal", "expanded") for k in kinds) or len(set(kinds)) != len(kinds) or "status_quo" not in kinds:
        raise ValueError("Compare distinct alternatives including status_quo and minimal or expanded")
    for row, kind in zip(data["alternatives"], kinds):
        row["kind"] = kind
    old = next((r for r in store.records("venture_review") if r["id"] == data["id"]), None)
    if old and {k:v for k,v in old.items() if k != "reviewed_at"} == {k:v for k,v in data.items() if k != "reviewed_at"}:
        return {"status": "unchanged", "id": data["id"], "assessment": assess(store, old), "report_path": render(store, old)}
    with store.db:
        revision = store.record("venture_review", data, payload.get('expected_revision'))
    return {"status": "saved", "id": data["id"], "revision": revision,
            "assessment": assess(store, data), "report_path": render(store, data)}
