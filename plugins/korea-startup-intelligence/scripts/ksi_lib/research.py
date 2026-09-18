"""Evidence-linked domain research, missing-evidence planning and quality gates.

The agent supplies original-source reasoning. These checks make its provenance,
unknowns and counterevidence inspectable; they cannot certify semantic truth.
"""
import json
import re
from datetime import timedelta
from .model import KST, assets, atomic_json, atomic_text, digest, now, parse_date, stamp

# The master's 20 dimensions, plus four operational questions needed to act.
DIMENSIONS = {
    "problem_severity": "누가 어떤 손해를 겪으며 실제 사례는 무엇인가?",
    "problem_frequency": "문제가 같은 고객에게 얼마나 반복되는가?",
    "market_size": "고객 수 × 구매 단위 × 가격의 출처와 범위는?",
    "market_growth": "같은 모집단·기간·단위의 반복 관측이 있는가?",
    "willingness_to_pay": "사용자와 지불자는 누구이며 예산·기존 지출 근거는?",
    "competition": "국내 직접·간접 경쟁·대기업·수작업 대안은?",
    "differentiation": "현재 대안에서 옮겨올 이유와 전환 비용은?",
    "timing": "새 기술·행동·정책 변화의 실제 사건일은?",
    "technology_leverage": "기술 없이도 해결 가능한가; 성능·원가·권리는?",
    "distribution": "첫 고객을 만날 경로와 획득 비용의 근거는?",
    "retention": "재사용 주기와 실제 코호트/이탈 자료가 있는가?",
    "network_effect": "참여자 증가가 다른 참여자의 가치로 연결되는가?",
    "data_moat": "누적 데이터의 권리·고유성·성과 개선 근거는?",
    "brand_moat": "브랜드가 구매·전환 비용에 영향을 주는 근거는?",
    "regulatory_risk": "한국의 해당 사업 형태·정보·안전 규정은?",
    "mvp_feasibility": "가장 위험한 가설을 최소 기능으로 검증할 수 있는가?",
    "capital_intensity": "개발 외 운영·재고·인증·현금흐름 비용은?",
    "scalability": "한계비용·공급 확보·지역 확장의 제약은?",
    "global_potential": "해외 국가별 가격·규제·유통 차이는?",
    "korea_fit": "한국 고객의 실제 행동·지역·플랫폼 조건과 맞는가?",
    "current_workaround": "현재 어떤 순서로 어떤 도구·서비스에 시간/돈을 쓰는가?",
    "team_fit": "창업자의 시간·자금·팀·영업/기술 역량은 확인됐는가?",
    "supply_access": "공급자·데이터·파트너·라이선스를 확보할 수 있는가?",
    "support_fit": "현재 공식 공고의 자격·평가항목과 맞는가?",
}
BASES = {"direct_customer", "observed_behavior", "official_research", "official_rule",
         "provider_claim", "analyst_inference", "measured_series"}
PAIN_BASES = {"direct_customer", "observed_behavior", "official_research"}
METHODS = {
    "problem_first": "분야 × 구체 고객 × 반복 문제",
    "behavior_shift": "바뀐 행동 때문에 새로 생긴 불편",
    "cross_industry": "다른 산업 모델의 작동 원리 이전과 실패 조건",
    "technology_cost": "기술 성능/가격 변화로 바뀐 단위경제",
    "unused_data": "사용 허가된 미활용 데이터 → 의사결정",
    "overseas_to_korea": "해외 사례 → 한국 가격·유통·규제 현지화",
    "korea_to_global": "한국의 실제 행동 변화 → 다른 국가의 수요 검증",
    "fragmentation": "흩어진 업무/정보를 연결해 전환 비용 감소",
    "information_asymmetry": "비교/검증 가능한 정보로 정보 차이 감소",
    "transaction_cost": "탐색·계약·결제·사후관리 비용 감소",
    "manual_work": "반복 수작업의 가장 비싼 한 단계",
    "disintermediation": "중간 단계를 제거할 때 사라지는 신뢰/운영 기능도 확인",
    "trust": "사기·품질·평판 문제의 검증 비용 감소",
    "community_commerce": "기존 공동체의 실제 거래 마찰",
    "content_commerce": "콘텐츠 관심과 구매 행동 사이의 간극",
    "decision_support": "복잡한 판단의 오류·시간 비용 감소",
}
MODELS = ["B2B SaaS", "B2C service", "B2G", "marketplace", "community + commerce",
          "data/API business", "offline + online", "hardware + service", "content", "subscription"]


def ensure_research(store):
    store.db.executescript("""
    CREATE TABLE IF NOT EXISTS knowledge_edges(owner_id TEXT, source_id TEXT, target_id TEXT,
      relation TEXT, dimension TEXT, updated_at TEXT,
      PRIMARY KEY(owner_id,source_id,target_id,relation,dimension));
    CREATE INDEX IF NOT EXISTS knowledge_target ON knowledge_edges(target_id);
    """)


def text(value, name, maximum=1200):
    from .radar import bounded_text
    return bounded_text(value, name, maximum)


def id_list(value, name, maximum=40, empty=True):
    if not isinstance(value, list) or len(value) > maximum or (not empty and not value):
        raise ValueError("Invalid bounded ID list: " + name)
    if any(not isinstance(x, str) or not x or len(x) > 140 for x in value) or len(value) != len(set(value)):
        raise ValueError("Use unique string IDs: " + name)
    return value


def record_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,99}", value):
        raise ValueError("Use a stable lowercase research key")
    return value


def unknown_finding(question):
    return {"status": "UNKNOWN", "conclusion": question, "links": []}


def finding(item, reviews):
    if not isinstance(item, dict) or item.get("status") not in ("FACT", "INFERENCE", "ASSUMPTION", "UNKNOWN"):
        raise ValueError("Research findings need explicit epistemic status")
    result = {"status": item["status"], "conclusion": text(item.get("conclusion"), "finding conclusion"), "links": []}
    links = item.get("links", [])
    if not isinstance(links, list) or len(links) > 12:
        raise ValueError("Finding links must be a bounded list")
    for link in links:
        if not isinstance(link, dict) or link.get("evidence_id") not in reviews:
            raise ValueError("Finding must link to reviewed dossier evidence")
        if link.get("relation") not in ("supports", "contradicts", "context") or link.get("basis") not in BASES:
            raise ValueError("Use a defined evidence relation and basis")
        if reviews[link["evidence_id"]]["read_scope"] == "metadata_only":
            raise ValueError("Dossier conclusions require original-source review, not only titles")
        result["links"].append({k: link[k] for k in ("evidence_id", "relation", "basis")} | {
            "locator": text(link.get("locator"), "source locator", 300),
            "note": text(link.get("note"), "claim-to-source explanation", 600)})
    if result["status"] in ("FACT", "INFERENCE") and not any(l["relation"] != "context" for l in result["links"]):
        raise ValueError("Evidence-backed findings need support or counterevidence, not only background")
    return result


def save_dossier(store, payload):
    from .radar import ensure_radar, valid_reviews
    ensure_radar(store)
    ensure_research(store)
    if not isinstance(payload, dict):
        raise ValueError("Dossier must be an object")
    key = record_key(payload.get("key"))
    if 'expected_revision' in payload:
        store.assert_revision('dossier', 'dossier-' + key, payload['expected_revision'])
    ids = id_list(payload.get("evidence_ids"), "dossier evidence", empty=False)
    reviews = {r["evidence_id"]: r for r in valid_reviews(store, ids)}
    domains = id_list(payload.get("domain_ids"), "domain_ids", 6, False)
    if set(domains) - {d["id"] for d in assets("taxonomy.json")["domains"]}:
        raise ValueError("Dossier domain IDs must exist in the taxonomy")
    data = {"id": "dossier-" + key, "key": key, "domain_ids": domains, "evidence_ids": ids}
    for field in ("title", "topic", "target", "problem", "decision_reason"):
        data[field] = text(payload.get(field), field)
    if payload.get("decision") not in ("research", "test", "park", "reject"):
        raise ValueError("Dossier decision must be research, test, park or reject")
    data["decision"] = payload["decision"]
    items = payload.get("findings", {})
    if not isinstance(items, dict) or set(items) - set(DIMENSIONS):
        raise ValueError("Unknown research dimension")
    data["findings"] = {k: finding(items[k], reviews) if k in items else unknown_finding(q) for k, q in DIMENSIONS.items()}
    audits = payload.get("search_audit", [])
    if not isinstance(audits, list) or len(audits) > 20:
        raise ValueError("Bound search audit to 20 actual searches")
    data["search_audit"] = []
    for a in audits:
        if not isinstance(a, dict):
            raise ValueError("Search audit entries must be objects")
        when = parse_date(a.get("checked_at"))
        if not when or not now() - timedelta(days=14) <= when <= now():
            raise ValueError("Search audit needs a real recent search time")
        read_ids = id_list(a.get("read_evidence_ids"), "read evidence")
        if set(read_ids) - set(ids):
            raise ValueError("Search audit references must belong to the dossier")
        data["search_audit"].append({k: text(a.get(k), k, 600) for k in ("query", "market", "channel", "limitations")} |
                                    {"checked_at": stamp(when), "read_evidence_ids": read_ids})
    competitors = payload.get("competitors", [])
    if not isinstance(competitors, list) or len(competitors) > 20:
        raise ValueError("Bound competitors to 20 actually investigated alternatives")
    data["competitors"] = []
    for c in competitors:
        if not isinstance(c, dict) or c.get("kind") not in ("direct", "indirect", "manual", "platform"):
            raise ValueError("Classify direct, indirect, manual or platform alternatives")
        cids = id_list(c.get("evidence_ids"), "competitor evidence", empty=False)
        if set(cids) - set(ids):
            raise ValueError("Competitors need reviewed dossier evidence")
        data["competitors"].append({k: text(c.get(k), k, 600) for k in
                                      ("name", "market", "advantage", "switching_barrier")} |
                                   {"kind": c["kind"], "evidence_ids": cids})
    counterarguments = payload.get("counterarguments", [])
    if not isinstance(counterarguments, list) or not 1 <= len(counterarguments) <= 12:
        raise ValueError("Record bounded counterarguments, including reasons not to build")
    data["counterarguments"] = [text(x, "counterargument", 600) for x in counterarguments]
    data["research_boundary"] = "Agent-reviewed evidence map, not market validation or complete industry knowledge"
    # Repeated identical imports do not inflate learning/revision counts.
    old = next((d for d in store.records("dossier") if d["id"] == data["id"]), None)
    if old and {k: v for k, v in old.items() if k != "reviewed_at"} == data:
        return {"status": "unchanged", "id": data["id"]}
    data["reviewed_at"] = stamp()
    with store.db:
        revision = store.record("dossier", data, payload.get('expected_revision'))
        store.db.execute("DELETE FROM knowledge_edges WHERE owner_id=?", (data["id"],))
        edges = [(data["id"], data["id"], d, "covers", "", stamp()) for d in domains]
        for dim, f in data["findings"].items():
            edges += [(data["id"], l["evidence_id"], data["id"], l["relation"], dim, stamp()) for l in f["links"]]
        store.db.executemany("INSERT OR IGNORE INTO knowledge_edges VALUES (?,?,?,?,?,?)", edges)
        # A reusable problem record, explicitly not counted as an interviewed customer.
        store.record("problem", {"id": "problem-" + key, "problem": data["problem"], "user": data["target"],
            "industry": domains, "frequency": data["findings"]["problem_frequency"],
            "severity": data["findings"]["problem_severity"], "current_solution": data["findings"]["current_workaround"],
            "evidence_ids": ids, "dossier_id": data["id"], "status": "research_hypothesis"})
    render_dossier(store, data)
    from . import blue_ocean
    portfolio_sync = []
    for card in store.records("opportunity"):
        if card.get("dossier_id") == data["id"]:
            try:
                portfolio_sync.append(blue_ocean.sync_opportunity(store, card))
            except ValueError as exc:
                portfolio_sync.append({"status": "not_synced", "reason": str(exc), "opportunity_id": card["id"]})
    if not any(card.get("dossier_id") == data["id"] for card in store.records("opportunity")):
        try:
            portfolio_sync.append(blue_ocean.sync_dossier(store, data))
        except ValueError as exc:
            portfolio_sync.append({"status": "not_synced", "reason": str(exc), "dossier_id": data["id"]})
    with store.db:
        dependency_events = blue_ocean.note_dependency_change(store, data["id"], "dossier", data["id"])
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="dossier_saved")
    return {"status": "saved", "id": data["id"], "revision": revision,
            "blue_ocean_sync": portfolio_sync, "blue_ocean_events": dependency_events,
            "portfolio_reassessment": reassessment,
            **dossier_quality(store, data)}


def dossier_quality(store, dossier):
    from .radar import valid_reviews
    reasons = []
    try:
        reviews = {r["evidence_id"]: r for r in valid_reviews(store, dossier["evidence_ids"])}
    except ValueError:
        reviews = {}
        reasons.append("stale_or_changed_research_sources")
    findings = dossier["findings"]
    def supports(key, bases=None):
        f = findings[key]
        return f["status"] in ("FACT", "INFERENCE") and any(
            l["relation"] == "supports" and l["evidence_id"] in reviews and (not bases or l["basis"] in bases)
            for l in f["links"])
    for key, bases in (("problem_severity", PAIN_BASES), ("current_workaround", PAIN_BASES),
                       ("willingness_to_pay", PAIN_BASES), ("korea_fit", PAIN_BASES | {"official_rule"})):
        if not supports(key, bases):
            reasons.append("missing_customer_evidence:" + key)
    # Neither search-result absence nor a marketing product page establishes a Korean gap.
    if not any(a["market"] == "KR" and a["read_evidence_ids"] and
               now() - timedelta(days=14) <= parse_date(a["checked_at"]) <= now() for a in dossier["search_audit"]):
        reasons.append("missing_current_korean_search_audit")
    if not any(c["market"] == "KR" and set(c["evidence_ids"]) & set(reviews) for c in dossier["competitors"]):
        reasons.append("missing_reviewed_korean_alternative")
    if not supports("differentiation"):
        reasons.append("missing_switching_reason_evidence")
    if dossier["decision"] in ("park", "reject"):
        reasons.append("dossier_decision:" + dossier["decision"])
    known = sum(f["status"] in ("FACT", "INFERENCE") for f in findings.values())
    return {"ready_for_opportunity_alert": not reasons, "blocking_gaps": reasons,
            "evidence_backed_dimensions": known, "dimension_denominator": len(DIMENSIONS),
            "boundary": "Evidence coverage, not probability of success; classifications are reviewer attestations"}


def opportunity_gate(store, card):
    from .radar import valid_reviews
    from .venture import assess
    reasons = []
    dossier = next((d for d in store.records("dossier") if d["id"] == card.get("dossier_id")), None)
    if not dossier:
        return {"version": 2, "eligible": False, "reasons": ["missing_evidence_linked_dossier"]}
    reasons.extend(dossier_quality(store, dossier)["blocking_gaps"])
    review = next((v for v in store.records("venture_review") if v["dossier_id"] == dossier["id"]), None)
    if review:
        if not assess(store, review)["current"]:
            reasons.append("stale_venture_review")
        if review["decision"] in ("park", "reject"):
            reasons.append("venture_decision:" + review["decision"])
    if not set(card.get("domain_ids", [])) & set(dossier["domain_ids"]):
        reasons.append("unrelated_dossier_domains")
    # Pin exact customer/problem, preventing reuse of an unrelated 'good' dossier.
    if card.get("problem") != dossier["problem"] or card.get("target") != dossier["target"]:
        reasons.append("dossier_customer_problem_mismatch")
    required = {l["evidence_id"] for k in ("problem_severity", "current_workaround", "willingness_to_pay", "korea_fit", "differentiation")
                for l in dossier["findings"][k]["links"] if l["relation"] != "context"}
    if not required <= set(card.get("evidence_ids", [])):
        reasons.append("card_omits_core_dossier_evidence")
    try:
        reviews = valid_reviews(store, card["evidence_ids"])
        substantive = [r for r in reviews if r["read_scope"] != "metadata_only"]
        if len({r["origin_group"] for r in substantive}) < 2 or len({r["family"] for r in substantive}) < 2:
            reasons.append("insufficient_independent_signal_families")
        changed = set(card.get("change", {}).get("evidence_ids", []))
        if not any(r["evidence_id"] in changed and parse_date(r["event_at"]) and
                   now() - timedelta(days=14) <= parse_date(r["event_at"]) <= now() for r in substantive):
            reasons.append("no_recent_dated_change")
    except ValueError:
        reasons.append("stale_card_evidence")
    return {"version": 2, "eligible": not reasons, "reasons": list(dict.fromkeys(reasons)),
            "dossier_id": dossier["id"], "dossier_reviewed_at": dossier["reviewed_at"],
            "boundary": "Investigated hypothesis, not validated demand; no automatic truth or award guarantee"}


def research_candidates(store):
    from .engine import choose_domains
    from .venture import status as venture_status
    from .validation import status as validation_status
    followups = []
    reviews = {r["dossier_id"]: r for r in venture_status(store)["reviews"]}
    experiments = validation_status(store)["experiments"]
    for dossier in reversed(store.records("dossier")):
        quality = dossier_quality(store, dossier)
        if dossier["decision"] == "reject":
            continue
        unknown = [k for k, f in dossier["findings"].items() if f["status"] in ("UNKNOWN", "ASSUMPTION")]
        priority = ["problem_severity", "current_workaround", "willingness_to_pay", "competition", "differentiation", "regulatory_risk"]
        unknown.sort(key=lambda k: (priority.index(k) if k in priority else len(priority), k))
        stale = "stale_or_changed_research_sources" in quality["blocking_gaps"]
        review = reviews.get(dossier["id"])
        trials = [e for e in experiments if e["dossier_id"] == dossier["id"]]
        review_due = not review or not review["current"] or review["unverified_questions"]
        results_due = any(e["phase"] == "awaiting_result" for e in trials)
        if unknown or stale or review_due or results_due:
            dimension = "source_refresh" if stale else "experiment_result" if results_due else unknown[0] if unknown else "venture_review"
            related = {dossier["id"], "problem-" + dossier["key"], "venture-" + dossier["key"]} | {e["plan_id"] for e in trials} | {
                c["id"] for c in store.records("opportunity") if c.get("dossier_id") == dossier["id"]}
            followups.append({"task_id": "research-" + digest([dossier["id"], dimension])[:20],
                "kind": "recheck_sources" if stale else "record_due_result" if results_due else "close_evidence_gap", "dossier_id": dossier["id"],
                "topic": dossier["topic"], "domain_ids": dossier["domain_ids"], "dimension": dimension,
                "question": "기존 근거 원문이 여전히 유효한지 재확인" if stale else
                            "사전 실험의 실제 결과 또는 미실행 사유 기록; 결과를 만들지 않기" if results_due else
                            DIMENSIONS.get(dimension, "여섯 창업자 질문·현재 방식 포함 대안·실패 경로 재검토"),
                "customer": dossier["target"], "blocking_gaps": quality["blocking_gaps"],
                "queries": [dossier["topic"] + " " + dossier["target"] + " 불편 수작업 비용",
                            dossier["topic"] + " 국내 서비스 가격 대체재"],
                "feedback": [f for f in store.records("feedback") if f.get("subject_id") in related][:5],
                "venture_review": review or {"status": "not_reviewed"}, "experiments": trials})
    domain_tasks = []
    taxonomy = {d["id"]: d for d in assets("taxonomy.json")["domains"]}
    receipts = store.records("research_receipt")
    for domain in choose_domains(store, len(taxonomy)):
        task_id = "research-domain-" + domain["domain_id"]
        completed = sum(r["task_id"] == task_id for r in receipts)
        specification = taxonomy[domain["domain_id"]]
        if completed:
            subfield = specification["subfields"][completed % len(specification["subfields"])]
            domain = {**domain, "subfield_id": subfield["id"], "subfield": subfield["name"],
                      "query": specification["name"] + " " + subfield["name"]}
        index = specification["number"] + completed
        domain_tasks.append({"task_id": task_id, "kind": "domain_discovery", "domain": domain,
                      "question": "실제 사용자·반복 불편·현재 지출·한국 대체재부터 조사",
                      "ideation_lenses": list(METHODS.items())[index % 4::4], "business_structures": MODELS[index % 3::3]})
    return followups, domain_tasks


def research_plan(store, limit=6):
    from .agenda import select
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Research plan limit must be 1..20")
    followups, domains = research_candidates(store)
    # Reserve at least half for breadth; completed/blocked unchanged work cools
    # down without being called validated, and active work is offered to resume.
    return select(store, followups, domains, limit)


def mine_pain(store, limit=20):
    from .radar import ensure_radar, valid_reviews
    ensure_radar(store)
    phrases = ("불편", "귀찮", "수작업", "엑셀", "비싸", "매번", "돈 내", "manual", "spreadsheet", "expensive", "workaround")
    candidates, seen = [], set()
    for row in store.db.execute("SELECT data FROM source_reviews ORDER BY reviewed_at DESC"):
        review = json.loads(row[0])
        hits = [p for p in phrases if p in review["summary"].lower()]
        if not hits or review["read_scope"] == "metadata_only" or review["origin_group"] in seen:
            continue
        try:
            valid_reviews(store, [review["evidence_id"]])
        except ValueError:
            continue
        seen.add(review["origin_group"])
        candidates.append({"evidence_id": review["evidence_id"], "matched_phrases": hits, "summary": review["summary"],
                           "status": "needs_customer_context_review", "origin_group": review["origin_group"]})
    return {"candidates": candidates[:limit], "unit": "distinct_original_producers_not_people_or_demand",
            "boundary": "Keyword triage of reviewed paraphrases, not sentiment analysis or verified repeated pain"}


def graph(store, node=None):
    ensure_research(store)
    query, params = "SELECT * FROM knowledge_edges", ()
    if node:
        query += " WHERE source_id=? OR target_id=? OR owner_id=?"
        params = (node, node, node)
    return {"edges": [dict(r) for r in store.db.execute(query + " ORDER BY owner_id,dimension LIMIT 500", params)],
            "boundary": "Typed evidence/claim/domain links, not automatic causal discovery"}


def render_dossier(store, data):
    lines = ["# " + data["title"], "", "대상: " + data["target"], "", "문제: " + data["problem"], "",
             "판단: " + data["decision"] + " — " + data["decision_reason"], "", "## 근거 연결형 조사", ""]
    for key, f in data["findings"].items():
        lines += ["### " + key, "", f["status"] + ": " + f["conclusion"], ""]
        for link in f["links"]:
            lines += [f"- {link['relation']} · {link['basis']} · {link['evidence_id']} · {link['locator']}: {link['note']}"]
        lines.append("")
    lines += ["## 반대 근거와 위험", ""] + ["- " + x for x in data["counterarguments"]] + ["", "## 실제 검색 범위", ""]
    lines += [f"- {a['market']} / {a['checked_at']} / {a['query']} — {a['limitations']}" for a in data["search_audit"]]
    from .radar import valid_reviews
    lines += ["", "## 검토 원문", ""] + [f"- [{r['evidence_id']}]({r['url']}) — {r['read_scope']}" for r in valid_reviews(store, data["evidence_ids"])]
    atomic_json(store.workspace / "reports/dossiers" / (data["key"] + ".json"), data)
    atomic_text(store.workspace / "reports/dossiers" / (data["key"] + ".md"), "\n".join(lines) + "\n")


def report(store, period="daily"):
    from .radar import ensure_radar
    from .engine import coverage
    from .venture import status as venture_status
    from .validation import status as validation_status
    from .agenda import status as agenda_status
    ensure_radar(store)
    days = {"daily": 1, "weekly": 7, "monthly": 30}[period]
    cutoff = now() - timedelta(days=days)
    cards = [c for c in store.records("opportunity") if parse_date(c["reviewed_at"]) >= cutoff]
    dossiers = store.records("dossier")
    sections = {name: [] for name in ("Newly Detected", "Accelerating", "Overseas → Korea", "Technology", "Startup & VC", "Consumer", "New Problems", "Korea Opportunity", "Startup Ideas")}
    for c in cards:
        gate = opportunity_gate(store, c)
        entry = {"id": c["id"], "title": c["title"], "stage": c["stage"], "alert_eligible": gate["eligible"], "gaps": gate["reasons"]}
        sections["Startup Ideas"].append(entry)
        if c["change"]["kind"] == "new":
            sections["Newly Detected"].append(entry)
        if c["stage"] == "Accelerating":
            sections["Accelerating"].append(entry)
        if gate["eligible"]:
            sections["Korea Opportunity"].append(entry)
        # Category membership comes from reviewed source families, not buzzwords.
        families = c.get("independence", {}).get("signal_families", [])
        for family, name in (("technology", "Technology"), ("investment", "Startup & VC"), ("consumer", "Consumer")):
            if family in families:
                sections[name].append(entry)
        if c["change"]["kind"] == "korea_entry":
            sections["Overseas → Korea"].append(entry)
    sections["New Problems"] = [{"id": d["id"], "title": d["problem"], "status": "research_hypothesis"}
                                for d in dossiers if parse_date(d["reviewed_at"]) >= cutoff]
    health = []
    for source in assets("sources.json"):
        fetch = store.db.execute("SELECT status,attempted_at FROM fetches WHERE source=? ORDER BY id DESC LIMIT 1", (source["id"],)).fetchone()
        health.append({"id": source["id"], "enabled": source["id"] in store.config["enabled_sources"],
                       "implemented": bool(source["adapter"]), "last_attempt": dict(fetch) if fetch else None})
    feedback = store.records("feedback")
    labels = ("useful", "not_useful", "duplicate", "stale", "acted_on")
    eligible = sum(opportunity_gate(store, c)["eligible"] for c in cards)
    data = {"generated_at": stamp(), "period": period, "lookback_days": days, "sections": sections,
            "source_health": health, "coverage": {k: v for k, v in coverage(store).items() if k != "unqueried_domains"},
            "dossier_count": len(dossiers), "dossier_domains": len({i for d in dossiers for i in d["domain_ids"]}),
            "quality": [{"id": d["id"], **dossier_quality(store, d)} for d in dossiers],
            "candidate_alerts": {"numerator": eligible, "denominator": len(cards), "population": "opportunity_cards_reviewed_in_period"},
            "feedback_counts": {label: sum(f.get("outcome") == label for f in feedback) for label in labels},
            "feedback_denominator": len(feedback), "predictive_accuracy": None,
            "venture_reviews": venture_status(store), "validation": validation_status(store),
            "research_journal": agenda_status(store),
            "next_research": research_plan(store),
            "boundary": "No new evidence in a section is not proof the market has not changed; no validated forecasting accuracy"}
    lines = ["# Korea Startup Trend Radar", "", f"{period} · 최근 {days}일 · {data['generated_at']}", "",
             f"조사 파일 {len(dossiers)}개 / 실제 연결 분야 {data['dossier_domains']}개 / 분류 지도 400개.", "",
             f"기간 내 가설 {len(cards)}개 중 현재 알림 기준 통과 {eligible}개. 수요·매출 검증 건수가 아닙니다.", ""]
    for name, entries in sections.items():
        lines += ["## " + name, ""]
        lines += ["- " + e["title"] + " (" + e["id"] + ") — " +
                  ("알림 검토 기준 통과; 수요 미검증" if e.get("alert_eligible") else "조사 가설 / 알림 보류")
                  for e in entries] if entries else ["새로 검토한 근거 없음 / 미연결 범위는 source_health 참조."]
        lines.append("")
    lines += ["## 조사 공백과 다음 행동", ""]
    for q in data["quality"]:
        lines += [f"- {q['id']}: 근거 연결 {q['evidence_backed_dimensions']}/{q['dimension_denominator']}개 항목; " + ", ".join(q["blocking_gaps"])]
    trials = data["validation"]
    lines += ["", "## 사업 검토와 실험", "",
              f"창업자 검토 {len(data['venture_reviews']['reviews'])}건 / 미검토 조사 {len(data['venture_reviews']['missing_dossier_ids'])}건.", "",
              f"사전 실험 {trials['registered']}건 / 결과 기록 {trials['resolved']}건. 결과에는 실패·불충분·미실행을 포함합니다.", ""]
    lines += [f"- {e['plan_id']}: {e['phase']} / {e['outcome'] or '결과 없음'}" for e in trials["experiments"]]
    journal = data["research_journal"]
    lines += ["", f"조사 결과 기록 {journal['recorded_outcomes']}건 / 본문·조사 연결 이력이 있는 분야 {journal['domains_with_investigation_receipts']}/{journal['taxonomy_denominator']}개.",
              "접근 제한·결과 없음은 조사 완료나 해당 시장의 부재를 뜻하지 않습니다."]
    lines += ["", "예측 적중률: 미검증. 다운로드·검색·언급은 매출 또는 반복 구매의 대체 지표가 아닙니다."]
    atomic_json(store.workspace / "reports" / ("radar-" + period + ".json"), data)
    atomic_text(store.workspace / "reports" / ("radar-" + period + ".md"), "\n".join(lines) + "\n")
    return {"report_path": str(store.workspace / "reports" / ("radar-" + period + ".md")),
            "dossiers": len(dossiers), "candidate_alerts": data["candidate_alerts"]}


def maintenance(store):
    """Create local reports once per KST day, ISO week and calendar month.

    Called by the existing heartbeat; does not schedule, send or edit code.
    """
    current = now().astimezone(KST)
    generated = []
    def bucket(dt, period):
        return dt.date() if period == "daily" else dt.isocalendar()[:2] if period == "weekly" else (dt.year, dt.month)
    for period in ("daily", "weekly", "monthly"):
        path = store.workspace / "reports" / ("radar-" + period + ".json")
        previous = None
        if path.exists():
            try:
                previous = parse_date(json.loads(path.read_text()).get("generated_at"))
            except (ValueError, AttributeError):
                pass
        if not previous or bucket(previous.astimezone(KST), period) != bucket(current, period):
            generated.append({"period": period, **report(store, period)})
    return {"generated": generated, "network_calls": 0, "messages_sent": 0,
            "boundary": "Rolling-window local review aids, not autonomous code learning or scheduled execution proof"}
