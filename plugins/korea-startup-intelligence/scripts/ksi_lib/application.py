"""API-key-free application workbench; drafting by Codex, checks by local code."""
from copy import deepcopy
import math

from .model import atomic_json, atomic_text, digest, stamp
from .radar import ensure_radar, evidence_signature, valid_reviews
from .research import dossier_quality, id_list, record_key, text
from .grants import match_notice
from .venture import assess as assess_venture, get_dossier

SECTIONS = {
    "problem": ("고객 문제", "problem_severity", "problem_frequency", "current_workaround"),
    "solution": ("해결책·차별성", "differentiation", "technology_leverage", "mvp_feasibility"),
    "market": ("목표 고객·시장", "market_size", "market_growth", "korea_fit"),
    "business_model": ("수익모델·판매", "willingness_to_pay", "distribution", "retention"),
    "competition": ("경쟁·전환 이유", "competition", "differentiation"),
    "execution": ("검증·실행 일정", "mvp_feasibility", "supply_access"),
    "team": ("팀·수행 역량", "team_fit"),
    "funding": ("자금 필요성·집행", "capital_intensity", "support_fit"),
    "risk": ("위험·대응", "regulatory_risk", "supply_access"),
}
FINAL_CHECKS = ("truthfulness", "official_form", "attachments", "length_limits")
BLOCKED_PROFILE_FIELDS = {"resident_registration_number", "bank_account", "phone", "email", "name", "address"}


def paragraphs(data):
    return [p for section in data["sections"].values() for p in section] + [r["answer"] for r in data["pitch"] + data["judge_qa"]]


def content_fingerprint(data):
    # Attestations bind to content AND the exact dossier/notice/source versions.
    # Timestamps and attestation wording cannot cause a self-referential digest.
    return digest({k: v for k, v in data.items() if k not in ("updated_at", "final_checks", "boundary")})


def source_fingerprint(review):
    return digest({"review": {k: v for k, v in review.items() if k not in ("reviewed_at", "observation")},
                   "source": evidence_signature(review["observation"])})


def stored_application(store, application_id):
    ensure_radar(store)
    data = next((a for a in store.records("application") if a["id"] == application_id), None)
    if data is None:
        raise ValueError("Unknown application draft")
    return data


def editable(data):
    return {"key": data["id"].removeprefix("application-"), **{k: deepcopy(v) for k, v in data.items()
            if k not in ("id", "updated_at", "boundary", "dossier_fingerprint", "notice_fingerprint", "source_review_fingerprints")}}


def notice_for(store, grant_id):
    if grant_id is None:
        return None
    notice = next((g for g in store.records("grant") if g["id"] == grant_id), None)
    if notice is None:
        raise ValueError("Unknown official notice")
    return notice


def prepare(store, dossier_id, grant_id=None):
    ensure_radar(store)
    dossier = get_dossier(store, dossier_id)
    notice = notice_for(store, grant_id)
    sections = {}
    for section, (_, *dimensions) in SECTIONS.items():
        sections[section] = [{"text": dossier["findings"][key]["conclusion"],
                              "status": dossier["findings"][key]["status"],
                              "evidence_ids": sorted({l["evidence_id"] for l in dossier["findings"][key]["links"]}),
                              "founder_fact_ids": []} for key in dimensions]
    return {"mode": "no_additional_api_key_required", "status": "research_to_rewrite_not_submission_document",
            "instruction": "Codex must rewrite the evidence into a coherent application, pitch and judge Q&A. This scaffold is not the final deliverable. Do not invent missing customer, team, revenue or notice facts.",
            "source_dossier": dossier, "official_notice": notice,
            "input_template": {"key": dossier["key"], "dossier_id": dossier_id, "grant_id": grant_id,
                "title": dossier["title"], "profile": {}, "founder_facts": {}, "sections": sections,
                "criterion_mapping": [{"criterion": c["criterion"], "section_ids": [], "rationale": "공식 항목에 맞춰 작성 필요"}
                                      for c in notice["evaluation_criteria"]] if notice else [],
                "budget": None, "milestones": [], "pitch": [], "judge_qa": [], "attachments": [],
                "final_checks": {k: {"checked": False, "note": "실제 문서와 공고 대조 전"} for k in FINAL_CHECKS}},
            "boundary": "General planning sections, not an official form or award probability; no network or submission"}


def paragraph(value, available_ids, founder_facts):
    if not isinstance(value, dict) or value.get("status") not in ("FACT", "INFERENCE", "ASSUMPTION", "UNKNOWN"):
        raise ValueError("Draft paragraphs need explicit epistemic status")
    ids = id_list(value.get("evidence_ids", []), "draft sources", 20)
    facts = id_list(value.get("founder_fact_ids", []), "founder fact references", 12)
    if set(ids) - available_ids or set(facts) - set(founder_facts):
        raise ValueError("Draft claims must reference available reviewed sources or confirmed founder facts")
    if value["status"] in ("FACT", "INFERENCE") and not (ids or facts):
        raise ValueError("Factual draft claims require evidence; use ASSUMPTION or UNKNOWN instead")
    return {"text": text(value.get("text"), "draft paragraph", 2400), "status": value["status"],
            "evidence_ids": ids, "founder_fact_ids": facts}


def money(value, name):
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError("Use a bounded integer KRW amount: " + name)
    return value


def normalize_budget(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("items"), list) or not 1 <= len(value["items"]) <= 40:
        raise ValueError("Budget requires 1..40 explicit cost items, or null if unknown")
    items = []
    for item in value["items"]:
        if not isinstance(item, dict):
            raise ValueError("Budget item must be an object")
        qty = item.get("quantity")
        if type(qty) is not int or not 1 <= qty <= 1000000:
            raise ValueError("Budget quantity must be a positive bounded integer")
        unit = money(item.get("unit_cost_krw"), "unit cost")
        total = money(item.get("total_krw"), "item total")
        if qty * unit != total:
            raise ValueError("Budget quantity times unit cost does not equal item total")
        items.append({"name": text(item.get("name"), "budget item", 200), "quantity": qty,
                      "unit_cost_krw": unit, "total_krw": total, "basis": text(item.get("basis"), "cost basis")})
    requested, own = money(value.get("requested_krw"), "requested funds"), money(value.get("own_krw"), "own funds")
    total = sum(i["total_krw"] for i in items)
    if requested + own != total:
        raise ValueError("Requested plus own funds must equal the itemized budget")
    return {"items": items, "requested_krw": requested, "own_krw": own, "total_krw": total,
            "basis": text(value.get("basis"), "budget assumptions"),
            "boundary": "Proposed expenditure, not spending authority or confirmation of eligible cost categories"}


def save(store, payload):
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError("Application must be a JSON object")
    if 'expected_revision' in payload:
        store.assert_revision('application', 'application-' + record_key(payload.get('key')), payload['expected_revision'])
    dossier = get_dossier(store, payload.get("dossier_id"))
    notice = notice_for(store, payload.get("grant_id"))
    founder_facts = payload.get("founder_facts", {})
    if not isinstance(founder_facts, dict) or len(founder_facts) > 30:
        raise ValueError("Use bounded non-identifying founder facts")
    confirmed = {}
    for key, fact in founder_facts.items():
        if key in BLOCKED_PROFILE_FIELDS or not isinstance(fact, dict) or fact.get("status") != "user_confirmed":
            raise ValueError("Founder facts must be explicitly user-confirmed and non-identifying")
        record_key(key)
        confirmed[key] = {"statement": text(fact.get("statement"), "confirmed founder fact"),
                          "basis": text(fact.get("basis"), "user confirmation basis"), "status": "user_confirmed"}
    profile = payload.get("profile", {})
    if not isinstance(profile, dict) or set(profile) & BLOCKED_PROFILE_FIELDS:
        raise ValueError("Use only non-identifying notice eligibility fields")
    if notice and set(profile) - {r["field"] for r in notice["rules"]}:
        raise ValueError("Keep eligibility profile limited to the selected notice fields")
    if not notice and profile:
        raise ValueError("Eligibility profile needs a selected official notice")
    normalized_profile = {}
    for key, fact in profile.items():
        if not isinstance(fact, dict) or fact.get("status") != "confirmed" or type(fact.get("value")) not in (str, int, float, bool):
            raise ValueError("Eligibility facts require a confirmed scalar and a reference basis; omit unknown fields")
        if type(fact["value"]) is float and not math.isfinite(fact["value"]):
            raise ValueError("Eligibility numbers must be finite")
        if isinstance(fact["value"], str) and len(fact["value"]) > 300:
            raise ValueError("Bound eligibility text values")
        normalized_profile[key] = {"value": fact["value"], "status": "confirmed",
                                   "basis": text(fact.get("basis"), "profile fact basis", 300),
                                   "as_of_basis": text(fact.get("as_of_basis"), "profile reference point", 300)}
    ids = set(dossier["evidence_ids"]) | (set(notice["evidence_ids"]) if notice else set())
    reviews = valid_reviews(store, sorted(ids))
    available = {r["evidence_id"] for r in reviews if r["read_scope"] != "metadata_only"}
    raw_sections = payload.get("sections", {})
    if not isinstance(raw_sections, dict) or set(raw_sections) - set(SECTIONS):
        raise ValueError("Use defined application section keys")
    sections = {}
    for key, rows in raw_sections.items():
        if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
            raise ValueError("Draft sections require 1..12 attributed paragraphs")
        sections[key] = [paragraph(row, available, confirmed) for row in rows]
    data = {"id": "application-" + record_key(payload.get("key")), "dossier_id": dossier["id"],
            "grant_id": notice["id"] if notice else None, "title": text(payload.get("title"), "application title", 200),
            "dossier_fingerprint": digest(dossier), "notice_fingerprint": digest(notice) if notice else None,
            "profile": normalized_profile, "founder_facts": confirmed, "sections": sections,
            "budget": normalize_budget(payload.get("budget")), "criterion_mapping": [], "milestones": [],
            "pitch": [], "judge_qa": [], "attachments": [], "final_checks": {}}
    for field, maximum in (("criterion_mapping", 30), ("milestones", 20), ("pitch", 15), ("judge_qa", 20), ("attachments", 40)):
        rows = payload.get(field, [])
        if not isinstance(rows, list) or len(rows) > maximum or any(not isinstance(r, dict) for r in rows):
            raise ValueError("Use a bounded application list: " + field)
        for row in rows:
            if field == "criterion_mapping":
                if not notice or row.get("criterion") not in [c["criterion"] for c in notice["evaluation_criteria"]]:
                    raise ValueError("Only map criteria actually extracted from the official notice")
                linked = id_list(row.get("section_ids"), "criterion sections", 9)
                if set(linked) - set(sections):
                    raise ValueError("Criterion mapping must link written sections")
                data[field].append({"criterion": row["criterion"], "section_ids": linked,
                                    "rationale": text(row.get("rationale"), "criterion rationale")})
            elif field == "milestones":
                start, end = row.get("start_week"), row.get("end_week")
                if type(start) is not int or type(end) is not int or not 1 <= start <= end <= 260:
                    raise ValueError("Use a planned milestone interval of weeks 1..260")
                data[field].append({"start_week": start, "end_week": end,
                    **{k: text(row.get(k), k) for k in ("deliverable", "measurement", "pass_condition", "stop_condition")}})
            elif field in ("pitch", "judge_qa"):
                label = "title" if field == "pitch" else "question"
                data[field].append({label: text(row.get(label), label, 300), "answer": paragraph(row.get("answer"), available, confirmed)})
            else:
                if row.get("status") not in ("missing", "prepared", "not_applicable"):
                    raise ValueError("Declare actual attachment preparation status")
                data[field].append({"name": text(row.get("name"), "attachment name", 200), "status": row["status"],
                                    "basis": text(row.get("basis"), "attachment check basis")})
    criteria = [m["criterion"] for m in data["criterion_mapping"]]
    if len(criteria) != len(set(criteria)):
        raise ValueError("Map each official evaluation criterion once")
    used_ids = {eid for p in paragraphs(data) for eid in p["evidence_ids"]} | (set(notice["evidence_ids"]) if notice else set())
    data["source_review_fingerprints"] = {r["evidence_id"]: source_fingerprint(r) for r in reviews if r["evidence_id"] in used_ids}
    fingerprint = content_fingerprint(data)
    old = next((a for a in store.records("application") if a["id"] == data["id"]), None)
    checks = payload.get("final_checks", {})
    if not isinstance(checks, dict) or set(checks) - set(FINAL_CHECKS):
        raise ValueError("Use the defined final document checks")
    for key in FINAL_CHECKS:
        check = checks.get(key, {"checked": False, "note": "미검토"})
        if not isinstance(check, dict) or type(check.get("checked")) is not bool:
            raise ValueError("Final document checks require an explicit boolean and verification note")
        previous = old.get("final_checks", {}).get(key, {}) if old else {}
        reusable = previous.get("checked") is True and previous.get("content_fingerprint") == fingerprint
        # Initial explicit declarations remain supported. On an existing draft,
        # old booleans/notes cannot silently certify new content. Use attest with
        # the exact fingerprint returned by check after reviewing the revision.
        checked = check["checked"] and (old is None or reusable or check.get("content_fingerprint") == fingerprint)
        data["final_checks"][key] = {"checked": checked, "note": text(check.get("note"), "final check note"),
                                     "content_fingerprint": fingerprint if checked else None}
    data["boundary"] = "Drafting and consistency workbench; no selection guarantee, official certification or automatic submission"
    if old and {k: v for k, v in old.items() if k != "updated_at"} == data:
        return {"status": "unchanged", "id": old["id"], "audit": audit(store, old), "report_path": render(store, old)}
    data["updated_at"] = stamp()
    with store.db:
        revision = store.record("application", data, payload.get('expected_revision'))
    return {"status": "draft_saved", "id": data["id"], "revision": revision, "audit": audit(store, data), "report_path": render(store, data)}


def revision_tasks(gaps, business_gaps):
    """Deterministic editing guidance, never invented customer answers."""
    tasks = []
    for gap in dict.fromkeys(gaps):
        kind, _, detail = gap.partition(":")
        priority, target = 2, "application"
        action = "점검 항목의 실제 자료와 현재 문서를 대조해 수정한다."
        if kind in ("no_target_notice", "notice_changed", "eligibility_or_application_window_unresolved", "official_evaluation_criteria_missing"):
            priority, target = 0, "official_notice"
            action = "현재 공식 공고·정정·첨부와 사용자 확인 정보를 대조한다. 공고가 없으면 범용 초안을 유지한다."
        elif kind in ("dossier_decision", "venture_decision"):
            priority, target = 0, "venture_review"
            action = "기존 보류·기각 이유를 먼저 검토한다. 새로운 반증 없이 결정을 해제하거나 제출 준비로 승격하지 않는다."
        elif kind in ("dossier_changed", "stale_venture_review", "stale_or_changed_draft_evidence", "source_interpretation_changed_or_unbound"):
            priority, target = 0, "evidence"
            action = "바뀐 조사·원문 해석을 기존 문장과 대조하고 필요한 문장을 고친 뒤 저장한다. 단순 재저장으로 사실을 재확인했다고 하지 않는다."
        elif kind in ("missing_section", "unresolved_section"):
            priority, target = 1, "sections." + detail
            action = "이 문항을 실제 근거 또는 명시된 계획으로 작성한다. 고객·팀·매출 등 모르는 사실은 창업자 확인이나 조사 과제로 남긴다."
        elif kind == "unmapped_criterion":
            priority, target = 1, "criterion_mapping"
            action = "공식 평가항목 '" + detail + "'에 답하는 실제 본문 위치와 근거를 연결한다."
        elif kind == "budget_not_defined":
            priority, target = 1, "budget"
            action = "수량·단가·견적/가정·신청/자체자금을 작성하고 공고의 비목·세금·자부담 인정 조건을 대조한다. 비용을 집행하지 않는다."
        elif kind == "measurable_execution_plan_missing":
            priority, target = 1, "milestones"
            action = "기간·산출물·측정 방법·통과/중단 기준이 있는 실행 계획을 작성한다. 계획과 관측 결과를 구분한다."
        elif kind in ("pitch_outline_incomplete", "judge_rehearsal_incomplete", "unresolved_pitch_or_judge_answer"):
            target = "pitch_and_judge_qa"
            action = "발표 또는 까다로운 심사 질문에 근거가 연결된 답변을 작성한다. 실제 시간·장수는 공고에 맞추고 모르는 실적을 만들지 않는다."
        elif kind == "missing_attachments":
            target = "attachments"
            action = "필수 첨부와 실제 보유 파일을 대조하고 누락을 표시한다. 파일이 없는데 준비 완료로 바꾸지 않는다."
        elif kind in ("manual_check_pending", "manual_check_revision_mismatch"):
            priority, target = 3, "final_checks." + detail
            action = "현재 보고서를 실제로 검토한 뒤 application check의 버전 식별값으로 해당 항목만 attest한다. 자동으로 true를 채우지 않는다."
        tasks.append({"code": gap, "priority": priority, "target": target, "action": action,
                      "kind": "document_review", "external_action_authorized": False})
    for gap in dict.fromkeys(business_gaps):
        tasks.append({"code": gap, "priority": 1, "target": "dossier", "kind": "business_evidence",
                      "action": "사업 가설의 근거 공백을 조사하거나 사전 기준이 있는 실험으로 설계한다. 문서 완성도를 고객 검증으로 대체하지 않는다.",
                      "external_action_authorized": False})
    return sorted(tasks, key=lambda item: item["priority"])


def audit(store, data):
    gaps = []
    dossier = get_dossier(store, data["dossier_id"])
    notice = notice_for(store, data["grant_id"])
    match = match_notice(store, notice["id"], data["profile"]) if notice else None
    if digest(dossier) != data["dossier_fingerprint"]:
        gaps.append("dossier_changed")
    if dossier["decision"] in ("park", "reject"):
        gaps.append("dossier_decision:" + dossier["decision"])
    review = next((r for r in store.records("venture_review") if r["dossier_id"] == dossier["id"]), None)
    if review and review["decision"] in ("park", "reject"):
        gaps.append("venture_decision:" + review["decision"])
    if review and not assess_venture(store, review)["current"]:
        gaps.append("stale_venture_review")
    if not notice:
        gaps.append("no_target_notice")
    elif digest(notice) != data["notice_fingerprint"]:
        gaps.append("notice_changed")
    if match and not match["actionable_candidate"]:
        gaps.append("eligibility_or_application_window_unresolved")
    if notice and not notice["evaluation_criteria"]:
        gaps.append("official_evaluation_criteria_missing")
    all_paragraphs = paragraphs(data)
    try:
        linked_ids = {i for p in all_paragraphs for i in p["evidence_ids"]} | (set(notice["evidence_ids"]) if notice else set())
        reviews = valid_reviews(store, sorted(linked_ids))
        if any(data.get("source_review_fingerprints", {}).get(r["evidence_id"]) != source_fingerprint(r) for r in reviews):
            gaps.append("source_interpretation_changed_or_unbound")
    except ValueError:
        gaps.append("stale_or_changed_draft_evidence")
    for section in SECTIONS:
        if section not in data["sections"]:
            gaps.append("missing_section:" + section)
        elif any(p["status"] == "UNKNOWN" for p in data["sections"][section]):
            gaps.append("unresolved_section:" + section)
    if any(r["answer"]["status"] == "UNKNOWN" for r in data["pitch"] + data["judge_qa"]):
        gaps.append("unresolved_pitch_or_judge_answer")
    mapped = {m["criterion"] for m in data["criterion_mapping"] if m["section_ids"]}
    if notice:
        gaps += ["unmapped_criterion:" + c["criterion"] for c in notice["evaluation_criteria"] if c["criterion"] not in mapped]
    if data["budget"] is None:
        gaps.append("budget_not_defined")
    if not data["milestones"]:
        gaps.append("measurable_execution_plan_missing")
    # A workbench preference of five slides is not an official program rule.
    # Actual length/time limits are verified in the declared manual checks.
    if not data["pitch"]:
        gaps.append("pitch_outline_incomplete")
    if not data["judge_qa"]:
        gaps.append("judge_rehearsal_incomplete")
    if any(a["status"] == "missing" for a in data["attachments"]):
        gaps.append("missing_attachments")
    gaps += ["manual_check_pending:" + key for key, c in data["final_checks"].items() if not c["checked"]]
    fingerprint = content_fingerprint(data)
    gaps += ["manual_check_revision_mismatch:" + key for key, c in data["final_checks"].items()
             if c["checked"] and c.get("content_fingerprint") != fingerprint]
    business_gaps = dossier_quality(store, dossier)["blocking_gaps"]
    return {"id": data["id"], "readiness": "ready_for_human_submission_review" if not gaps else "working_draft",
            "gaps": gaps, "eligibility": match, "selection_probability": None, "automatic_submission": False,
            "content_fingerprint": fingerprint, "business_evidence_gaps": business_gaps,
            "revision_tasks": revision_tasks(gaps, business_gaps),
            "claim_status_counts": {s: sum(p["status"] == s for p in all_paragraphs) for s in ("FACT", "INFERENCE", "ASSUMPTION", "UNKNOWN")},
            "boundary": "Structural and arithmetic checks plus declared manual review; not semantic truth or award prediction"}


def check(store, application_id):
    data = stored_application(store, application_id)
    return {**audit(store, data), "report_path": render(store, data),
            "attestation_template": {"application_id": application_id, "content_fingerprint": content_fingerprint(data),
                "checks": {k: {"checked": False, "note": "이 버전의 실제 검토 결과를 작성"} for k in FINAL_CHECKS}}}


def resume(store, application_id):
    data = stored_application(store, application_id)
    return {"status": "existing_draft_to_edit_not_regenerated", "input_template": {**editable(data),
            "expected_revision": store.checkout('application', application_id)['expected_revision']}, "audit": audit(store, data)}


def attest(store, payload):
    if not isinstance(payload, dict):
        raise ValueError("Application attestation must be an object")
    data = stored_application(store, payload.get("application_id"))
    fingerprint = content_fingerprint(data)
    if payload.get("content_fingerprint") != fingerprint:
        raise ValueError("Draft changed since review; check and inspect the current version before attesting")
    if set(audit(store, data)["gaps"]) & {"dossier_changed", "notice_changed", "source_interpretation_changed_or_unbound", "stale_or_changed_draft_evidence"}:
        raise ValueError("Sources or research changed; review and save the revised content before attesting")
    checks = payload.get("checks")
    if not isinstance(checks, dict) or not checks or set(checks) - set(FINAL_CHECKS):
        raise ValueError("Attest one or more defined checks with actual verification notes")
    draft = editable(data)
    for key, value in checks.items():
        if not isinstance(value, dict) or type(value.get("checked")) is not bool:
            raise ValueError("Each attestation needs checked and note")
        draft["final_checks"][key] = {"checked": value["checked"], "note": text(value.get("note"), "review note"),
                                      "content_fingerprint": fingerprint}
    return save(store, draft)


def source_appendix(store, data):
    notice = notice_for(store, data["grant_id"])
    ids = {i for p in paragraphs(data) for i in p["evidence_ids"]} | (set(notice["evidence_ids"]) if notice else set())
    observations = {o["id"]: o for o in store.observations()}
    result = []
    for eid in sorted(ids):
        row = {"evidence_id": eid, "status": "unavailable_or_needs_review"}
        obs = observations.get(eid)
        if obs:
            row.update({k: obs.get(k) for k in ("title", "url", "event_at")})
        try:
            review = valid_reviews(store, [eid])[0]
            matches = data.get("source_review_fingerprints", {}).get(eid) == source_fingerprint(review)
            row.update({"status": "current" if matches else "interpretation_changed_or_unbound",
                        **{k: review.get(k) for k in ("read_scope", "reviewed_at", "limitations")}})
        except ValueError:
            pass
        result.append(row)
    return result


def reference_line(paragraph):
    return "근거: " + (", ".join(paragraph["evidence_ids"] + paragraph["founder_fact_ids"]) or "계획·가설 또는 미확인")


def render(store, data):
    checked = audit(store, data)
    lines = ["# " + data["title"], "", "상태: " + checked["readiness"], "",
             "지원사업 선정·제출 완료를 의미하지 않습니다. 수정/제출 전 application check로 재점검합니다.", "",
             "문서 버전: " + checked["content_fingerprint"], ""]
    for section, (label, *_) in SECTIONS.items():
        lines += ["## " + label, ""]
        for p in data["sections"].get(section, []):
            lines += ["[" + p["status"] + "] " + p["text"], "",
                      reference_line(p), ""]
    lines += ["## 공식 평가항목 대응", ""]
    lines += ["- " + m["criterion"] + ": " + ", ".join(m["section_ids"]) + " — " + m["rationale"] for m in data["criterion_mapping"]]
    if data["budget"]:
        b = data["budget"]
        lines += ["", "## 계획 예산", "", f"요청 {b['requested_krw']:,}원 + 자체 {b['own_krw']:,}원 = {b['total_krw']:,}원", ""]
        lines += [f"- {i['name']}: {i['quantity']} × {i['unit_cost_krw']:,}원 = {i['total_krw']:,}원 ({i['basis']})" for i in b["items"]]
    lines += ["", "## 실행 일정", ""]
    lines += [f"- {m['start_week']}~{m['end_week']}주: {m['deliverable']} / 측정: {m['measurement']} / 통과: {m['pass_condition']} / 중단: {m['stop_condition']}" for m in data["milestones"]]
    for field, label, title in (("pitch", "title", "발표 구성"), ("judge_qa", "question", "심사 질문과 답변")):
        lines += ["", "## " + title, ""]
        for index, row in enumerate(data[field], 1):
            answer = row["answer"]
            lines += [f"### {index}. {row[label]}", "", "[" + answer["status"] + "] " + answer["text"], "", reference_line(answer), ""]
    lines += ["## 첨부 준비", ""] + ["- " + a["name"] + ": " + a["status"] + " — " + a["basis"] for a in data["attachments"]]
    lines += ["", "## 제출 전 남은 점검", ""] + ["- " + gap for gap in checked["gaps"]]
    lines += ["", "## 사업성 근거의 미확인 부분", ""] + ["- " + gap for gap in checked["business_evidence_gaps"]]
    lines += ["", "## 다음 수정 작업", ""]
    for task in checked["revision_tasks"]:
        lines += [f"- P{task['priority']} · {task['target']} · {task['code']}: {task['action']}"]
    lines += ["", "## 문서 버전별 수동 검토 기록", ""]
    for key, check in data["final_checks"].items():
        current = check["checked"] and check.get("content_fingerprint") == checked["content_fingerprint"]
        lines += [f"- {key}: {'현재 버전 검토 선언' if current else '현재 버전 미검토'} — {check['note']}"]
    appendix = source_appendix(store, data)
    lines += ["", "## 출처 색인", "", "ID는 본문·발표·심사 답변의 연결 표식입니다. 원문 검토 상태와 주장 진실성은 별도입니다.", ""]
    for source in appendix:
        lines += ["### " + source["evidence_id"], "", source.get("title", "원자료 보관 범위 밖 또는 현재 접근 불가"), "",
                  source.get("url", "현재 보유 URL 없음"), "",
                  f"사건/발행일: {source.get('event_at') or '미확인'} · 검토일: {source.get('reviewed_at') or '현재 유효 검토 없음'}", "",
                  "상태: " + source["status"] + " · 읽기 범위: " + (source.get("read_scope") or "재확인 필요"), "",
                  "한계: " + "; ".join(source.get("limitations", [])), ""]
    referenced_facts = {i for p in paragraphs(data) for i in p["founder_fact_ids"]}
    if referenced_facts:
        lines += ["## 사용자 확인 사실", "", "사용자 진술/제공 자료 기반이며 독립 감사 결과가 아닙니다.", ""]
        for key in sorted(referenced_facts):
            fact = data["founder_facts"][key]
            lines += ["- " + key + ": " + fact["statement"] + " / 확인 근거: " + fact["basis"]]
    base = store.workspace / "reports/applications" / data["id"]
    atomic_json(base.with_suffix(".json"), {"draft": data, "audit": checked, "source_appendix": appendix})
    atomic_text(base.with_suffix(".md"), "\n".join(lines) + "\n")
    return str(base.with_suffix(".md"))
