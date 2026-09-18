"""A fast, honest map of stored coverage across all Korean-sector taxonomy IDs."""
import json
from collections import Counter
from datetime import timedelta

from .model import assets, now, parse_date, stamp
from .radar import ensure_radar, valid_reviews


def overview(store, query="", limit=20):
    if type(limit) is not int or not 1 <= limit <= 400:
        raise ValueError("Market map limit must be 1..400")
    if not isinstance(query, str) or len(query) > 160:
        raise ValueError("Use a short sector/subfield search")
    ensure_radar(store)
    domains = assets("taxonomy.json")["domains"]
    observations = store.observations()
    dossiers = store.records("dossier")
    receipts = store.records("research_receipt")
    trials = store.records("validation_plan")
    results = {r["plan_id"]: r for r in store.records("validation_result")}
    source_ids = {s["id"] for s in assets("sources.json") if s.get("tier") == 1}
    matched = [d for d in domains if query.casefold() in json.dumps(d, ensure_ascii=False).casefold()]
    reviewed_ids = set()
    for row in store.db.execute("SELECT evidence_id FROM source_reviews"):
        try:
            if valid_reviews(store, [row[0]])[0]["read_scope"] != "metadata_only":
                reviewed_ids.add(row[0])
        except ValueError:
            pass
    recent_cutoff = now() - timedelta(days=14)
    indexed = []
    for domain in matched:
        ds = [d for d in dossiers if domain["id"] in d["domain_ids"]]
        dids = {d["id"] for d in ds}
        # Link only explicit tags or dossier references, never guessed sectors.
        linked = {i for d in ds for i in d["evidence_ids"]}
        rows = [r for r in observations if domain["id"] in r.get("domain_ids", []) or r["id"] in linked]
        recent = [r for r in rows if parse_date(r.get("event_at")) and recent_cutoff <= parse_date(r["event_at"]) <= now()]
        recent.sort(key=lambda r: r["event_at"], reverse=True)
        reviewed = {r["id"] for r in rows} & reviewed_ids
        completed = [r for r in receipts if domain["id"] in r["domain_ids"] and r["outcome"] == "investigated"]
        plans = [p for p in trials if p["dossier_id"] in dids]
        indexed.append({"domain_id": domain["id"], "domain": domain["name"], "subfield_count": len(domain["subfields"]),
                        "linked_sources": len(rows), "recent_14d_sources": len(recent), "substantive_source_reviews": len(reviewed),
                        "early_source_observations": sum(r["source"] in source_ids for r in recent),
                        "dossier_ids": sorted(dids), "investigation_receipts": len(completed),
                        "registered_experiments": len(plans), "recorded_results": sum(p["id"] in results for p in plans),
                        "status": "research_dossiers_present" if ds else "signals_to_read" if rows else "unexplored",
                        "trend_stage": "not_inferred_from_metadata",
                        "latest_signals": [{k: r[k] for k in ("id", "source", "title", "url", "event_at")} for r in recent[:3]],
                        "next_task_id": "research-domain-" + domain["id"],
                        "transfer_prompt": "다른 산업의 해결 원리를 이 분야의 실제 반복 업무에 적용할 수 있는지, 지불자·유통·규제 차이로 반증하기"})
    assigned = {i for d in dossiers for i in d["evidence_ids"]}
    return {"mode": "no_additional_api_key_required", "generated_at": stamp(), "query": query,
            "taxonomy_domains": len(domains), "matched_domains": len(matched), "returned_domains": min(limit, len(indexed)),
            "source_scope": "stored evidence only; public web review is needed for current facts",
            "unassigned_source_observations": sum(not r.get("domain_ids") and r["id"] not in assigned for r in observations),
            "matched_status_counts": dict(Counter(d["status"] for d in indexed)), "domains": indexed[:limit],
            "boundary": "A sector navigation and evidence-coverage map, not instant knowledge of every Korean market or a forecast"}
