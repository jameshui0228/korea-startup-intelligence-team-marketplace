"""Research receipts and bounded revisit scheduling, independent of API fetching."""
import json
from datetime import timedelta
from uuid import uuid4

from .model import assets, atomic_json, digest, now, parse_date, stamp
from .radar import ensure_radar, evidence_signature, text_list, valid_reviews
from .research import id_list, text

OUTCOMES = {"investigated", "no_evidence", "blocked"}
BLOCKERS = {"access", "source_unavailable", "customer_permission", "budget", "scope"}


def records(store, kind):
    return [json.loads(r[0]) for r in store.db.execute(
        "SELECT data FROM records WHERE kind=? ORDER BY updated_at DESC,rowid DESC", (kind,))]


def snapshot(store):
    ensure_radar(store)
    return {"observations": store.observations(), "dossiers": store.records("dossier"),
            "reviews": {r["evidence_id"]: json.loads(r["data"]) for r in store.db.execute("SELECT evidence_id,data FROM source_reviews")},
            "decisions": store.records("venture_review") + store.records("validation_plan") + store.records("validation_result"),
            "cards": store.records("opportunity"),
            "feedback": store.records("feedback"), "runs": records(store, "research_run"),
            "receipts": records(store, "research_receipt")}


def domains_for(task):
    return [task["domain"]["domain_id"]] if task["kind"] == "domain_discovery" else task["domain_ids"]


def context_signature(task, state):
    domains = set(domains_for(task))
    dossiers = [d for d in state["dossiers"] if d["id"] == task.get("dossier_id")] if task.get("dossier_id") else [
        d for d in state["dossiers"] if domains & set(d["domain_ids"])]
    dossier_ids = {d["id"] for d in dossiers}
    evidence_ids = {i for d in dossiers for i in d["evidence_ids"]}
    obs = [r for r in state["observations"] if r["id"] in evidence_ids or domains & set(r.get("domain_ids", []))]
    decisions = [d for d in state["decisions"] if d.get("dossier_id") in dossier_ids]
    subjects = dossier_ids | {"problem-" + d["key"] for d in dossiers} | {d["id"] for d in decisions} | {
        c["id"] for c in state["cards"] if c.get("dossier_id") in dossier_ids}
    reviews = [{k: v for k, v in state["reviews"][o["id"]].items() if k != "reviewed_at"}
               for o in obs if o["id"] in state["reviews"]]
    # Retrieval time and small counter changes do not manufacture novelty. A
    # meaningful source/decision change or an expired source can reopen work.
    return digest({"observations": sorted(evidence_signature(o) for o in obs),
                   "dossiers": sorted(dossiers, key=lambda d: d["id"]),
                   "reviews": sorted(reviews, key=lambda r: r["evidence_id"]),
                   "decisions": sorted(decisions, key=lambda d: (d["id"], digest(d))),
                   "feedback": sorted((f for f in state["feedback"] if f.get("subject_id") in subjects), key=lambda f: f["id"])})


def availability(task, state):
    runs = [r for r in state["runs"] if r["task_id"] == task["task_id"]]
    receipts = [r for r in state["receipts"] if r["task_id"] == task["task_id"]]
    closed = {r["run_id"] for r in state["receipts"]}
    active = next((r for r in runs if r["id"] not in closed and now() - parse_date(r["started_at"]) < timedelta(hours=24)), None)
    latest = receipts[0] if receipts else None
    if active:
        return {"state": "in_progress", "run_id": active["id"], "attempts": len(runs)}
    if not latest:
        return {"state": "ready", "reason": "interrupted_retry" if runs else "never_recorded", "attempts": len(runs)}
    changed = latest["context_after"] != context_signature(task, state)
    due = now() >= parse_date(latest["revisit_at"])
    return {"state": "ready" if changed or due else "cooling_down", "attempts": len(runs),
            "reason": "context_changed" if changed else "revisit_due" if due else "waiting_for_new_evidence_or_due_date",
            "last_outcome": latest["outcome"], "last_summary": latest["summary"], "revisit_at": latest["revisit_at"]}


def select(store, followups, domain_tasks, limit):
    state = snapshot(store)
    enriched = [{**t, "research_history": availability(t, state)} for t in followups + domain_tasks]
    ready = [t for t in enriched if t["research_history"]["state"] == "ready"]
    # Never-recorded questions first; a formerly blocked, due question remains
    # eligible but does not displace every untouched sector.
    prior = {r["task_id"]: r for r in reversed(state["receipts"])}
    ready.sort(key=lambda t: (t["research_history"]["attempts"], prior.get(t["task_id"], {}).get("completed_at", "")))
    follow = [t for t in ready if t["kind"] != "domain_discovery"][:limit // 2]
    broad = [t for t in ready if t["kind"] == "domain_discovery"][:limit - len(follow)]
    return {"status": "research_tasks_not_generated_opportunities", "tasks": follow + broad,
            "in_progress": [t["research_history"] | {"task_id": t["task_id"]} for t in enriched if t["research_history"]["state"] == "in_progress"],
            "cooling_down_count": sum(t["research_history"]["state"] == "cooling_down" for t in enriched),
            "unknowns_do_not_mean_no_competitors": True}


def start(store, task_id, revisit=False, actor=None):
    from .research import research_candidates
    follow, domains = research_candidates(store)
    task = next((t for t in follow + domains if t["task_id"] == task_id), None)
    if not task:
        raise ValueError("Unknown or obsolete research task; read the current research-work plan")
    state = snapshot(store)
    available = availability(task, state)
    if available["state"] == "in_progress":
        run = next(r for r in state["runs"] if r["id"] == available["run_id"])
        if run.get("actor") and run["actor"] != actor:
            raise ValueError("다른 담당자가 진행 중입니다. 명시적인 handoff 또는 작업 만료 후 재개하세요.")
        if actor and not run.get("actor"):
            run = {**run, "actor": text(actor, "actor", 80)}
            with store.db:
                store.record("research_run", run)
        return {"status": "resumed", "run": run}
    if available["state"] != "ready" and not revisit:
        raise ValueError("Task is waiting for evidence or its revisit date; --revisit is an explicit local override")
    run = {"id": "research-run-" + uuid4().hex, "task_id": task_id, "task": task,
           "context_before": context_signature(task, state), "started_at": stamp(), "explicit_revisit": revisit}
    if actor:
        run["actor"] = text(actor, "actor", 80)
    with store.db:
        store.record("research_run", run)
    return {"status": "started_not_researched", "run": run, "network_calls": 0}


def complete(store, payload):
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError("Research receipt must be a JSON object")
    run = next((r for r in records(store, "research_run") if r["id"] == payload.get("run_id")), None)
    if not run or not isinstance(payload.get("outcome"), str) or payload["outcome"] not in OUTCOMES:
        raise ValueError("Use an existing research run and investigated/no_evidence/blocked outcome")
    if run.get("actor") and payload.get("actor") != run["actor"]:
        raise ValueError("조사 담당자와 완료 기록의 actor가 다릅니다.")
    newer = next((r for r in records(store, "research_run") if r["task_id"] == run["task_id"]), None)
    if newer and newer["id"] != run["id"]:
        raise ValueError("Superseded research run; complete the current run instead")
    cooldown = payload.get("revisit_after_hours", 168 if payload["outcome"] == "blocked" else 72 if payload["outcome"] == "investigated" else 24)
    if type(cooldown) is not int or not 1 <= cooldown <= 720:
        raise ValueError("Revisit interval must be 1..720 hours")
    ids = id_list(payload.get("evidence_ids", []), "research receipt evidence", 40)
    dossier_ids = id_list(payload.get("dossier_ids", []), "research receipt dossiers", 6)
    blocker = payload.get("blocker")
    if (payload["outcome"] == "blocked" and (not isinstance(blocker, str) or blocker not in BLOCKERS)) or (payload["outcome"] != "blocked" and blocker is not None):
        raise ValueError("Blocked research needs a defined blocker; other outcomes must not set one")
    data = {"id": run["id"], "run_id": run["id"], "task_id": run["task_id"], "domain_ids": domains_for(run["task"]),
            "outcome": payload["outcome"], "blocker": blocker, "evidence_ids": ids, "dossier_ids": dossier_ids,
            "summary": text(payload.get("summary"), "research outcome summary"),
            "next_action": text(payload.get("next_action"), "next research action"),
            "limitations": text_list(payload.get("limitations"), "research scope limitations"),
            "revisit_after_hours": cooldown, "search_log": []}
    searches = payload.get("search_log", [])
    if not isinstance(searches, list) or len(searches) > 20 or any(not isinstance(s, dict) for s in searches):
        raise ValueError("Search log must be a bounded list")
    for search in searches:
        checked = parse_date(search.get("checked_at"))
        if not checked or not parse_date(run["started_at"]) <= checked <= now():
            raise ValueError("Search log must be dated during the actual research run")
        if search.get("outcome") not in ("read", "no_results", "access_limited"):
            raise ValueError("Search log outcome must be read/no_results/access_limited")
        linked = id_list(search.get("read_evidence_ids", []), "search read sources", 40)
        if set(linked) - set(ids) or (search["outcome"] == "read" and not linked):
            raise ValueError("Read searches must link receipt evidence IDs")
        data["search_log"].append({"query": text(search.get("query"), "search query", 300),
            "channel": text(search.get("channel"), "search channel", 100), "checked_at": stamp(checked),
            "outcome": search["outcome"], "read_evidence_ids": linked})
    if data["outcome"] == "no_evidence" and not data["search_log"]:
        raise ValueError("No-evidence outcome needs an actual search log; use blocked for work not performed")
    old = next((r for r in records(store, "research_receipt") if r["id"] == run["id"]), None)
    if old:
        if any(old.get(k) != value for k, value in data.items()):
            raise ValueError("Research receipts are immutable; start a new revisit to record a revised investigation")
        return {"status": "unchanged", "receipt": old}
    reviewed = valid_reviews(store, ids)
    if data["outcome"] == "investigated":
        if not ids or not dossier_ids or any(r["read_scope"] == "metadata_only" for r in reviewed):
            raise ValueError("Investigated work requires substantive sources and linked dossiers")
    dossiers = {d["id"]: d for d in store.records("dossier")}
    for did in dossier_ids:
        if did not in dossiers or not set(dossiers[did]["domain_ids"]) & set(data["domain_ids"]):
            raise ValueError("Receipt dossiers must match the research domain")
        if run["task"].get("dossier_id") and did != run["task"]["dossier_id"]:
            raise ValueError("Followup receipt must refer to its original dossier")
    if data["outcome"] == "investigated" and not set(ids) <= {i for did in dossier_ids for i in dossiers[did]["evidence_ids"]}:
        raise ValueError("Substantive receipt sources must be connected in its dossier reasoning")
    data.update({"completed_at": stamp(), "revisit_at": stamp(now() + timedelta(hours=cooldown)),
                 "context_after": context_signature(run["task"], snapshot(store)),
                 "boundary": "A bounded investigation record, not complete field expertise or customer validation"})
    with store.db:
        store.record("research_receipt", data)
    atomic_json(store.workspace / "reports/research-journal" / (data["id"] + ".json"), data)
    return {"status": "recorded", "receipt": data}


def handoff(store, run_id, actor, to_actor, note):
    run = next((r for r in records(store, "research_run") if r["id"] == run_id), None)
    if not run or not run.get("actor") or run["actor"] != actor:
        raise ValueError("현재 담당자만 인계할 수 있습니다. actor는 로컬 협업 표시이며 인증 수단은 아닙니다.")
    if any(r["run_id"] == run_id for r in records(store, "research_receipt")):
        raise ValueError("Completed run cannot be handed off")
    newest = next(r for r in records(store, "research_run") if r["task_id"] == run["task_id"])
    if newest["id"] != run_id:
        raise ValueError("Superseded run cannot be handed off")
    updated = {**run, "actor": text(to_actor, "to_actor", 80)}
    with store.db:
        store.record("research_handoff", {"id": "handoff-" + uuid4().hex, "run_id": run_id,
            "from_actor": actor, "to_actor": updated["actor"], "note": text(note, "handoff note"), "at": stamp()})
        store.record("research_run", updated)
    return {"status": "handed_off", "run": updated, "boundary": "Local attribution, not authenticated access control"}


def status(store):
    runs, receipts = records(store, "research_run"), records(store, "research_receipt")
    closed = {r["run_id"] for r in receipts}
    return {"started_runs": len(runs), "recorded_outcomes": len(receipts),
            "outcome_counts": {o: sum(r["outcome"] == o for r in receipts) for o in sorted(OUTCOMES)},
            "domains_with_investigation_receipts": len({d for r in receipts if r["outcome"] == "investigated" for d in r["domain_ids"]}),
            "taxonomy_denominator": assets("taxonomy.json")["domain_count"],
            "unfinished_runs": [{"run_id": r["id"], "task_id": r["task_id"],
                                 "status": "superseded" if any(new["task_id"] == r["task_id"] for new in runs[:index]) else
                                           "interrupted" if now() - parse_date(r["started_at"]) >= timedelta(hours=24) else "in_progress"}
                                for index, r in enumerate(runs) if r["id"] not in closed],
            "recent_receipts": [{k: r[k] for k in ("id", "task_id", "outcome", "blocker", "summary", "next_action", "revisit_at")}
                                for r in receipts[:20]],
            "boundary": "Query attempts, substantive investigation receipts, customer trials and business results are separate denominators"}
