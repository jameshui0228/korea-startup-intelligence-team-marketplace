"""Match explicitly extracted official notice rules, never selection probability."""
import math
import re
from .model import now, parse_date, stamp
from .research import id_list, record_key, text

OPS = {"eq", "in", "not_in", "gte", "lte", "between"}


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_rule(rule, evidence_ids):
    if not isinstance(rule, dict) or rule.get("operator") not in OPS:
        raise ValueError("Use a supported explicit notice condition")
    if not isinstance(rule.get("field"), str) or not re.fullmatch(r"[a-z][a-z0-9_]{1,79}", rule["field"]):
        raise ValueError("Use a non-identifying founder/business profile field")
    if rule["field"] in ("resident_registration_number", "bank_account", "phone", "email", "name", "address"):
        raise ValueError("Do not store unnecessary personal identifiers")
    ids = id_list(rule.get("evidence_ids"), "notice rule evidence", empty=False)
    if set(ids) - set(evidence_ids):
        raise ValueError("Notice rule evidence must be reviewed notice evidence")
    op, value = rule["operator"], rule.get("value")
    if op in ("gte", "lte") and not number(value):
        raise ValueError("Numeric notice threshold required")
    if op == "between" and (not isinstance(value, list) or len(value) != 2 or not all(number(x) for x in value) or value[0] > value[1]):
        raise ValueError("Use a bounded numeric eligibility interval")
    if op in ("in", "not_in") and (not isinstance(value, list) or not 1 <= len(value) <= 100 or any(type(x) not in (str, int, bool) for x in value)):
        raise ValueError("Use a finite set of explicit allowed/excluded values")
    if op == "eq" and type(value) not in (str, int, bool):
        raise ValueError("Equality requires an explicit scalar")
    return {"field": rule["field"], "operator": op, "value": value, "evidence_ids": ids,
            "description": text(rule.get("description"), "rule description"),
            "locator": text(rule.get("locator"), "notice page/section", 300),
            "as_of_basis": text(rule.get("as_of_basis"), "eligibility reference date", 300)}


def save_notice(store, payload):
    from .radar import ensure_radar, valid_reviews
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError("Notice must be an object")
    key = record_key(payload.get("key"))
    if 'expected_revision' in payload:
        store.assert_revision('grant', 'grant-' + key, payload['expected_revision'])
    ids = id_list(payload.get("evidence_ids"), "official notice evidence", empty=False)
    reviews = valid_reviews(store, ids)
    if any(r["read_scope"] == "metadata_only" for r in reviews):
        raise ValueError("Read the official notice before extracting conditions")
    if payload.get("official_notice_confirmed") is not True:
        raise ValueError("Confirm issuer's official notice and attachments were checked")
    rules = payload.get("rules")
    if not isinstance(rules, list) or not 1 <= len(rules) <= 60:
        raise ValueError("Notice requires 1..60 extracted conditions")
    if type(payload.get("conditions_complete")) is not bool:
        raise ValueError("Declare whether exclusions/attachments were fully reviewed")
    data = {"id": "grant-" + key, "key": key, "evidence_ids": ids,
            "official_notice_confirmed": True, "conditions_complete": payload["conditions_complete"],
            "rules": [validate_rule(r, ids) for r in rules]}
    for field in ("title", "issuer", "notice_version", "coverage_note"):
        data[field] = text(payload.get(field), field)
    for field in ("opens_at", "closes_at"):
        value = payload.get(field)
        # A date-only deadline is not silently treated as midnight or end-of-day.
        if value is not None and (not isinstance(value, str) or not re.search(r"T\d\d:\d\d.*(?:Z|[+-]\d\d:\d\d)$", value) or not parse_date(value)):
            raise ValueError("Use explicit timezone and time, or null for unknown deadline")
        data[field] = stamp(parse_date(value)) if value else None
    if data["opens_at"] and data["closes_at"] and parse_date(data["opens_at"]) >= parse_date(data["closes_at"]):
        raise ValueError("Notice opening must precede closing")
    criteria = payload.get("evaluation_criteria", [])
    if not isinstance(criteria, list) or len(criteria) > 30:
        raise ValueError("Bound official evaluation criteria")
    data["evaluation_criteria"] = []
    for c in criteria:
        if not isinstance(c, dict):
            raise ValueError("Evaluation criteria must be objects")
        weight = c.get("weight")
        if weight is not None and (not number(weight) or not 0 <= weight <= 100):
            raise ValueError("Use published criterion weight or null")
        data["evaluation_criteria"].append({"criterion": text(c.get("criterion"), "criterion", 300),
            "weight": weight, "locator": text(c.get("locator"), "criterion locator", 300)})
    data["reviewed_at"] = stamp()
    data["boundary"] = "Agent-extracted conditions, not official eligibility approval; recheck amendments before applying"
    with store.db:
        revision = store.record("grant", data, payload.get('expected_revision'))
    return {"id": data["id"], "revision": revision, "rules": len(rules), "conditions_complete": data["conditions_complete"]}


def compare(actual, op, expected):
    # Do not silently coerce '30' to 30, or True to one year of company age.
    if op in ("gte", "lte", "between"):
        if not number(actual):
            return None
        return actual >= expected if op == "gte" else actual <= expected if op == "lte" else expected[0] <= actual <= expected[1]
    if op == "eq":
        return actual == expected if type(actual) is type(expected) else None
    if not any(type(actual) is type(x) for x in expected):
        return None
    member = any(type(actual) is type(x) and actual == x for x in expected)
    return member if op == "in" else not member


def match_notice(store, grant_id, profile):
    from .radar import valid_reviews
    notice = next((g for g in store.records("grant") if g["id"] == grant_id), None)
    if not notice:
        raise ValueError("Unknown notice; import the reviewed official notice first")
    if not isinstance(profile, dict):
        raise ValueError("Founder profile must be an object of confirmed non-identifying fields")
    stale = False
    try:
        valid_reviews(store, notice["evidence_ids"])
    except ValueError:
        stale = True
    rows = []
    for rule in notice["rules"]:
        value = profile.get(rule["field"])
        confirmed = isinstance(value, dict) and value.get("status") == "confirmed" and value.get("basis")
        # Basis must explicitly be computed at the notice's reference point.
        basis_matches = confirmed and value.get("as_of_basis") == rule["as_of_basis"]
        actual = value.get("value") if basis_matches else None
        matched = compare(actual, rule["operator"], rule["value"]) if actual is not None and not stale else None
        rows.append({"field": rule["field"], "condition": rule["description"], "source_locator": rule["locator"],
                     "reference_date": rule["as_of_basis"], "result": "UNKNOWN" if matched is None else "PASS" if matched else "FAIL",
                     "reason": "stale_notice" if stale else "missing_confirmed_value_or_reference_basis" if not basis_matches else "recorded_condition_comparison"})
    results = {r["result"] for r in rows}
    eligibility = "INELIGIBLE_BY_RECORDED_RULE" if "FAIL" in results else "UNKNOWN" if "UNKNOWN" in results or not notice["conditions_complete"] else "MATCHES_RECORDED_RULES"
    start, end = parse_date(notice["opens_at"]), parse_date(notice["closes_at"])
    phase = "closed" if end and now() >= end else "upcoming" if start and now() < start else "open" if start and end else "unknown"
    return {"grant_id": grant_id, "title": notice["title"], "eligibility": eligibility,
            "application_phase": phase, "notice_stale": stale, "conditions_complete": notice["conditions_complete"],
            "coverage_note": notice["coverage_note"],
            "conditions": rows, "evaluation_criteria": notice["evaluation_criteria"], "selection_probability": None,
            "actionable_candidate": eligibility == "MATCHES_RECORDED_RULES" and phase == "open" and not stale,
            "boundary": "Not official approval or selection forecast; manual current-notice and attachment check before submission"}
