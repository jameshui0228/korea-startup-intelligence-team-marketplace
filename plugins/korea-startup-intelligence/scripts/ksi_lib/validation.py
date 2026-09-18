"""Prespecified local experiments. No recruitment, spending or synthetic results."""
import math

from .model import now, stamp, parse_date, digest
from .radar import ensure_radar, valid_reviews, text_list
from .research import text, id_list, record_key
from .venture import get_dossier


def number(value, field):
    if type(value) not in (int, float) or not 0 <= value <= 10**18 or not math.isfinite(value):
        raise ValueError("Use a finite nonnegative number: " + field)
    return value


def integer(value, field, low=0, high=10**12):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Use a bounded integer: " + field)
    return value


def dated(value, field):
    # Deadlines must be precise; avoid silently interpreting a local date as UTC.
    if not isinstance(value, str) or "T" not in value or not (value.endswith("Z") or "+" in value[10:] or "-" in value[10:]):
        raise ValueError("Use a timezone-qualified ISO timestamp: " + field)
    dt = parse_date(value)
    if not dt:
        raise ValueError("Invalid experiment timestamp: " + field)
    return dt


def immutable(store, kind, data, timestamp):
    old = next((r for r in store.records(kind) if r["id"] == data["id"]), None)
    if old:
        if {k: v for k, v in old.items() if k != timestamp} != data:
            raise ValueError("Prespecified plans and results are immutable; use a new linked plan for a new experiment")
        return {"status": "unchanged", "id": old["id"], "record": old}
    return None


def plan(store, payload):
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError("Experiment plan must be a JSON object")
    dossier = get_dossier(store, payload.get("dossier_id"))
    key = record_key(payload.get("key"))
    metric = payload.get("metric")
    if not isinstance(metric, dict) or metric.get("aggregation") not in ("rate", "mean") or metric.get("direction") not in ("higher", "lower"):
        raise ValueError("Metric requires rate or mean aggregation and higher or lower direction")
    normalized = {"aggregation": metric["aggregation"], "direction": metric["direction"],
                  "definition": text(metric.get("definition"), "metric definition"),
                  "unit": text(metric.get("unit"), "metric unit", 80),
                  "min_sample": integer(metric.get("min_sample"), "minimum sample", 1, 1000000),
                  "pass_threshold": number(metric.get("pass_threshold"), "pass threshold"),
                  "stop_threshold": number(metric.get("stop_threshold"), "stop threshold")}
    passed, stopped = normalized["pass_threshold"], normalized["stop_threshold"]
    if (normalized["direction"] == "higher" and passed <= stopped) or (normalized["direction"] == "lower" and passed >= stopped):
        raise ValueError("Pass and stop thresholds must be ordered and non-overlapping")
    if normalized["aggregation"] == "rate" and (normalized["unit"] != "fraction" or max(passed, stopped) > 1):
        raise ValueError("Rate thresholds use fractions from 0 to 1, not percentages")
    start, end = dated(payload.get("starts_at"), "start"), dated(payload.get("ends_at"), "end")
    if start >= end:
        raise ValueError("Experiment end must be after start")
    ids = id_list(payload.get("evidence_ids", []), "plan evidence", 12)
    if set(ids) - set(dossier["evidence_ids"]):
        raise ValueError("Plan context must refer to its dossier evidence")
    parent = payload.get("replaces_plan_id")
    if parent is not None and not any(p["id"] == parent and p["dossier_id"] == dossier["id"] for p in store.records("validation_plan")):
        raise ValueError("Replacement must link an existing plan for the same dossier")
    data = {"id": "validation-" + key, "dossier_id": dossier["id"], "method_type": "quantitative",
            "metric": normalized,
            "starts_at": stamp(start), "ends_at": stamp(end), "evidence_ids": ids,
            "budget_krw": integer(payload.get("budget_krw"), "planned budget"), "replaces_plan_id": parent}
    for field in ("hypothesis", "method", "population", "recruitment", "collection_plan", "safety_stop"):
        data[field] = text(payload.get(field), field)
    existing = immutable(store, "validation_plan", data, "registered_at")
    if existing:
        return existing
    if start < now():
        raise ValueError("Register before data collection begins; retrospective evidence belongs in a dossier")
    valid_reviews(store, ids)
    data["registered_at"] = stamp()
    with store.db:
        store.record("validation_plan", data)
        from . import blue_ocean
        portfolio_events = blue_ocean.note_dependency_change(store, data["dossier_id"], "validation_plan", data["id"])
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="validation_plan")
    return {"status": "registered_not_executed", "id": data["id"], "record": data,
            "blue_ocean_events": portfolio_events, "portfolio_reassessment": reassessment,
            "boundary": "Budget is a plan, not spending authority; registration does not contact customers"}


def _patterns(value, field):
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise ValueError(field + " requires 1..12 prespecified patterns")
    rows, codes = [], set()
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("code"), str) or not item["code"]:
            raise ValueError(field + " patterns need stable codes")
        code = item["code"]
        if not all(ch.islower() or ch.isdigit() or ch == "-" for ch in code) or code in codes:
            raise ValueError(field + " pattern codes use unique lowercase letters, digits and hyphens")
        codes.add(code)
        rows.append({"code": code, "description": text(item.get("description"), field + " description", 600),
                     "minimum_cases": integer(item.get("minimum_cases"), field + " minimum cases", 1, 1000)})
    return rows


def qualitative_plan(store, payload):
    """Prespecify coded qualitative evidence without converting it to a fake survey rate."""
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError("Qualitative experiment plan must be a JSON object")
    dossier = get_dossier(store, payload.get("dossier_id"))
    key = record_key(payload.get("key"))
    rule = payload.get("decision_rule")
    if not isinstance(rule, dict):
        raise ValueError("Qualitative plan needs a prespecified decision_rule")
    passed = _patterns(rule.get("pass_patterns"), "pass_patterns")
    stopped = _patterns(rule.get("stop_patterns"), "stop_patterns")
    if {p["code"] for p in passed} & {p["code"] for p in stopped}:
        raise ValueError("Pass and stop pattern codes must not overlap")
    require_negative = rule.get("require_negative_case")
    if type(require_negative) is not bool:
        raise ValueError("require_negative_case must be true or false")
    normalized = {"unit_of_analysis": text(rule.get("unit_of_analysis"), "unit of analysis", 300),
                  "minimum_eligible_cases": integer(rule.get("minimum_eligible_cases"), "minimum eligible cases", 1, 1000),
                  "pass_patterns": passed, "stop_patterns": stopped,
                  "coding_protocol": text(rule.get("coding_protocol"), "coding protocol", 1200),
                  "require_negative_case": require_negative}
    start, end = dated(payload.get("starts_at"), "start"), dated(payload.get("ends_at"), "end")
    if start >= end or start < now():
        raise ValueError("Register a future qualitative collection window with end after start")
    ids = id_list(payload.get("evidence_ids", []), "plan evidence", 12)
    if set(ids) - set(dossier["evidence_ids"]):
        raise ValueError("Plan context must refer to its dossier evidence")
    parent = payload.get("replaces_plan_id")
    if parent is not None and not any(p["id"] == parent and p["dossier_id"] == dossier["id"]
                                      for p in store.records("validation_plan")):
        raise ValueError("Replacement must link an existing plan for the same dossier")
    data = {"id": "validation-" + key, "dossier_id": dossier["id"], "method_type": "qualitative",
            "decision_rule": normalized, "metric": None, "starts_at": stamp(start), "ends_at": stamp(end),
            "evidence_ids": ids, "budget_krw": integer(payload.get("budget_krw"), "planned budget"),
            "replaces_plan_id": parent}
    for field in ("hypothesis", "method", "population", "recruitment", "collection_plan", "safety_stop"):
        data[field] = text(payload.get(field), field)
    existing = immutable(store, "validation_plan", data, "registered_at")
    if existing:
        return existing
    valid_reviews(store, ids)
    data["registered_at"] = stamp()
    with store.db:
        store.record("validation_plan", data)
        from . import blue_ocean
        portfolio_events = blue_ocean.note_dependency_change(store, data["dossier_id"], "validation_plan", data["id"])
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="qualitative_validation_plan")
    return {"status": "registered_not_executed", "id": data["id"], "record": data,
            "blue_ocean_events": portfolio_events, "portfolio_reassessment": reassessment,
            "boundary": "사전 코딩 규칙이며 인터뷰 실행·대표성·통계적 유의성을 뜻하지 않습니다."}


def qualitative_result(store, payload):
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError("Qualitative result must be a JSON object")
    original = next((p for p in store.records("validation_plan") if p["id"] == payload.get("plan_id")), None)
    if not original or original.get("method_type") != "qualitative":
        raise ValueError("Result requires a prespecified qualitative plan")
    if payload.get("execution_status") not in ("completed", "not_run"):
        raise ValueError("Result execution_status must be completed or not_run")
    data = {"id": original["id"], "plan_id": original["id"], "dossier_id": original["dossier_id"],
            "plan_fingerprint": digest(original), "method_type": "qualitative",
            "execution_status": payload["execution_status"], "summary": text(payload.get("summary"), "result summary"),
            "counterevidence": text(payload.get("counterevidence"), "counterevidence or its absence"),
            "limitations": text_list(payload.get("limitations"), "result limitations"),
            "data_quality_issues": text_list(payload.get("data_quality_issues", []), "data quality issues", minimum=0),
            "cost_krw": integer(payload.get("cost_krw"), "actual reported cost"),
            "measurement": None, "evidence_links": [], "cases": [], "outcome": "not_run",
            "boundary": "사전 코딩한 정성 관측의 의사결정 기록이며 대표 수요·인과·성공 확률이 아닙니다."}
    evidence_ids, case_ids = [], set()
    if data["execution_status"] == "completed":
        cases = payload.get("cases")
        if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
            raise ValueError("Completed qualitative results need 1..200 bounded cases")
        allowed = {p["code"] for p in original["decision_rule"]["pass_patterns"] + original["decision_rule"]["stop_patterns"]}
        for item in cases:
            case_id = item.get("case_id") if isinstance(item, dict) else None
            if not isinstance(case_id, str) or not case_id or len(case_id) > 100 or case_id in case_ids or \
                    not all(ch.isalnum() or ch in "-_" for ch in case_id):
                raise ValueError("Cases need unique non-identifying case_id values")
            case_ids.add(case_id)
            if type(item.get("eligible")) is not bool or type(item.get("negative_case")) is not bool:
                raise ValueError("Each case must state eligibility and whether it is a searched negative case")
            codes = item.get("observed_codes")
            if not isinstance(codes, list) or len(codes) != len(set(codes)) or set(codes) - allowed:
                raise ValueError("Observed codes must be unique and prespecified")
            links = item.get("evidence_links")
            if not isinstance(links, list) or not 1 <= len(links) <= 12:
                raise ValueError("Each qualitative case needs measured evidence links")
            normalized_links = []
            for link in links:
                if not isinstance(link, dict) or link.get("basis") not in ("direct_customer", "observed_behavior"):
                    raise ValueError("Qualitative cases require direct-customer or observed-behavior evidence")
                evidence_id = link.get("evidence_id")
                if not isinstance(evidence_id, str) or evidence_id in evidence_ids:
                    raise ValueError("Do not reuse one evidence item as multiple qualitative cases")
                evidence_ids.append(evidence_id)
                normalized = {"evidence_id": evidence_id, "basis": link["basis"],
                              "locator": text(link.get("locator"), "case evidence locator", 300),
                              "note": text(link.get("note"), "case evidence note", 600)}
                normalized_links.append(normalized)
                data["evidence_links"].append({**normalized, "case_id": case_id})
            data["cases"].append({"case_id": case_id, "eligible": item["eligible"],
                                  "negative_case": item["negative_case"],
                                  "observed_codes": codes, "evidence_links": normalized_links})
        eligible = [case for case in data["cases"] if case["eligible"]]
        counts = {code: sum(code in case["observed_codes"] for case in eligible) for code in allowed}
        rule = original["decision_rule"]
        data["measurement"] = {"eligible_cases": len(eligible), "total_cases": len(data["cases"]),
                               "pattern_case_counts": counts, "unit": rule["unit_of_analysis"]}
        if data["data_quality_issues"] or len(eligible) < rule["minimum_eligible_cases"]:
            data["outcome"] = "inconclusive"
        elif any(counts[p["code"]] >= p["minimum_cases"] for p in rule["stop_patterns"]):
            data["outcome"] = "stop_criterion_met"
        elif all(counts[p["code"]] >= p["minimum_cases"] for p in rule["pass_patterns"]) and \
                (not rule["require_negative_case"] or any(c["negative_case"] for c in eligible)):
            data["outcome"] = "criterion_met"
        else:
            data["outcome"] = "inconclusive"
    elif payload.get("cases") is not None or payload.get("evidence_links"):
        raise ValueError("A not-run qualitative experiment cannot contain cases")
    existing = immutable(store, "validation_result", data, "recorded_at")
    if existing:
        return existing
    if now() < parse_date(original["ends_at"]):
        raise ValueError("Record final outcomes only after the prespecified end")
    if data["execution_status"] == "completed":
        start, end = parse_date(original["starts_at"]), parse_date(original["ends_at"])
        for review in valid_reviews(store, evidence_ids):
            event = parse_date(review["observation"].get("event_at"))
            if review["read_scope"] == "metadata_only" or review["collection_basis"] not in ("user_owned", "authorized_export"):
                raise ValueError("Qualitative outcomes need reviewed user-owned or authorized records")
            if not event or not start <= event <= end:
                raise ValueError("Qualitative evidence must be dated inside the collection window")
    data["recorded_at"] = stamp()
    with store.db:
        store.record("validation_result", data)
        from . import blue_ocean
        portfolio_events = blue_ocean.note_dependency_change(store, data["dossier_id"], "validation_result", data["id"])
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="qualitative_validation_result")
    return {"status": "recorded", "id": data["id"], "record": data,
            "blue_ocean_events": portfolio_events, "portfolio_reassessment": reassessment}


def outcome(metric, numerator, denominator, issues):
    value = numerator / denominator
    if not math.isfinite(value):
        raise ValueError("Computed metric must be finite")
    if denominator < metric["min_sample"] or issues:
        return "inconclusive", value
    if metric["direction"] == "higher":
        passed, stopped = value >= metric["pass_threshold"], value <= metric["stop_threshold"]
    else:
        passed, stopped = value <= metric["pass_threshold"], value >= metric["stop_threshold"]
    return "criterion_met" if passed else "stop_criterion_met" if stopped else "inconclusive", value


def result(store, payload):
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError("Experiment result must be a JSON object")
    original = next((p for p in store.records("validation_plan") if p["id"] == payload.get("plan_id")), None)
    if not original:
        raise ValueError("Result requires a prespecified experiment plan")
    if original.get("method_type", "quantitative") != "quantitative":
        raise ValueError("Use validation qualitative-result for a qualitative plan")
    if payload.get("execution_status") not in ("completed", "not_run"):
        raise ValueError("Result execution_status must be completed or not_run")
    data = {"id": original["id"], "plan_id": original["id"], "dossier_id": original["dossier_id"],
            "plan_fingerprint": digest(original), "execution_status": payload["execution_status"],
            "summary": text(payload.get("summary"), "result summary"),
            "counterevidence": text(payload.get("counterevidence"), "counterevidence or its absence"),
            "limitations": text_list(payload.get("limitations"), "result limitations"),
            "data_quality_issues": text_list(payload.get("data_quality_issues", []), "data quality issues", minimum=0),
            "cost_krw": integer(payload.get("cost_krw"), "actual reported cost"),
            "measurement": None, "evidence_links": [], "outcome": "not_run",
            "boundary": "Reported measurements checked against a prespecified rule; not independently audited or general market validation"}
    if data["execution_status"] == "completed":
        measurement = payload.get("measurement")
        if not isinstance(measurement, dict) or measurement.get("unit") != original["metric"]["unit"]:
            raise ValueError("Measurement unit must match the prespecified metric")
        start = dated(measurement.get("collected_from"), "collection start")
        end = dated(measurement.get("collected_to"), "collection end")
        if not parse_date(original["starts_at"]) <= start <= end <= parse_date(original["ends_at"]):
            raise ValueError("Measurements must fall inside the prespecified collection window")
        if start != parse_date(original["starts_at"]) or end != parse_date(original["ends_at"]):
            data["data_quality_issues"] = list(dict.fromkeys(data["data_quality_issues"] + ["partial_collection_window"]))
        numerator = number(measurement.get("numerator"), "measurement numerator")
        denominator = integer(measurement.get("denominator"), "observed sample count", 1, 1000000)
        if original["metric"]["aggregation"] == "rate" and (type(numerator) is not int or numerator > denominator):
            raise ValueError("Rate numerator must be an integer success count not exceeding the denominator")
        decision, value = outcome(original["metric"], numerator, denominator, data["data_quality_issues"])
        data["outcome"] = decision
        data["measurement"] = {"numerator": numerator, "denominator": denominator,
                               "value": value, "unit": measurement["unit"],
                               "collected_from": stamp(start), "collected_to": stamp(end)}
        links = payload.get("evidence_links")
        if not isinstance(links, list) or not 1 <= len(links) <= 12 or any(not isinstance(x, dict) for x in links):
            raise ValueError("Completed experiments require bounded measured-data evidence links")
        ids = id_list([r.get("evidence_id") for r in links], "result evidence", 12, empty=False)
        # First normalize the receipt; identical replay remains possible even if
        # underlying provider observations have since expired.
        for link in links:
            if link.get("basis") not in ("direct_customer", "observed_behavior", "transaction", "aggregate_measurement"):
                raise ValueError("Result evidence must concern actual measurements, not a provider claim")
            data["evidence_links"].append({"evidence_id": link["evidence_id"], "basis": link["basis"],
                "locator": text(link.get("locator"), "measurement locator", 300),
                "note": text(link.get("note"), "measurement evidence note", 600)})
    elif payload.get("measurement") is not None or payload.get("evidence_links"):
        raise ValueError("A not-run experiment cannot contain a completed measurement")
    existing = immutable(store, "validation_result", data, "recorded_at")
    if existing:
        return existing
    if now() < parse_date(original["ends_at"]):
        raise ValueError("Record final outcomes only after the prespecified end; do not stop early for a favorable score")
    if data["execution_status"] == "completed":
        for review in valid_reviews(store, ids):
            obs = review["observation"]
            if review["read_scope"] == "metadata_only" or review["collection_basis"] not in ("user_owned", "authorized_export"):
                raise ValueError("Results need reviewed user-owned or authorized measurement records, not public attention signals")
            event = parse_date(obs.get("event_at"))
            if not event or not start <= event <= end:
                raise ValueError("Measurement evidence must be dated within the reported collection window")
    data["recorded_at"] = stamp()
    with store.db:
        store.record("validation_result", data)
        from . import blue_ocean
        portfolio_events = blue_ocean.note_dependency_change(store, data["dossier_id"], "validation_result", data["id"])
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="validation_result")
    return {"status": "recorded", "id": data["id"], "record": data,
            "blue_ocean_events": portfolio_events, "portfolio_reassessment": reassessment}


def status(store, dossier_id=None):
    ensure_radar(store)
    if dossier_id is not None:
        get_dossier(store, dossier_id)
    plans = [p for p in store.records("validation_plan") if dossier_id is None or p["dossier_id"] == dossier_id]
    results = {r["plan_id"]: r for r in store.records("validation_result")}
    feedback = store.records("feedback")
    experiments = []
    for p in plans:
        r = results.get(p["id"])
        phase = "awaiting_result" if now() >= parse_date(p["ends_at"]) else "in_progress" if now() >= parse_date(p["starts_at"]) else "planned"
        evidence_status = "not_applicable"
        if r and r["execution_status"] == "completed":
            try:
                valid_reviews(store, [l["evidence_id"] for l in r["evidence_links"]])
                evidence_status = "available_for_recheck"
            except ValueError:
                evidence_status = "stale_changed_or_unavailable"
        experiments.append({"plan_id": p["id"], "dossier_id": p["dossier_id"], "hypothesis": p["hypothesis"],
                            "method_type": p.get("method_type", "quantitative"),
                            "phase": r["execution_status"] if r else phase, "ends_at": p["ends_at"],
                            "outcome": r["outcome"] if r else None,
                            "measurement": r["measurement"] if r else None, "evidence_status": evidence_status,
                            "feedback": [f for f in feedback if f.get("subject_id") == p["id"]][:12]})
    return {"registered": len(plans), "resolved": sum(e["outcome"] is not None for e in experiments),
            "outcome_counts": {k: sum(e["outcome"] == k for e in experiments)
                               for k in ("criterion_met", "stop_criterion_met", "inconclusive", "not_run")},
            "experiments": experiments, "legacy_unvalidated_notes": len(store.records("experiment")),
            "boundary": "All registered trials, including failures and not-run trials; no claimed business success rate"}
