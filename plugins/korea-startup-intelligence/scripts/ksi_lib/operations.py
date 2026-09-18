"""Durable research-cycle completion and observable optional delivery.

The product defaults to manual runs. A legacy trigger label is a caller's
statement, not proof that an app scheduler ran.
No model calls, hidden daemon, or autonomous recovery of ambiguous sends.
"""
import json
import re
from datetime import timedelta
from . import radar, telegram, research
from .model import atomic_json, digest, now, parse_date, stamp


def validate_trigger(trigger, automation_id):
    if trigger not in ("manual", "heartbeat"):
        raise ValueError("Research trigger must be manual or heartbeat")
    if (trigger == "heartbeat") != bool(automation_id):
        raise ValueError("Only heartbeat runs must identify their automation")
    if automation_id and (not isinstance(automation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", automation_id)):
        raise ValueError("Invalid automation ID")


def start_run(store, packet, trigger, automation_id):
    validate_trigger(trigger, automation_id)
    with store.db:
        # A packet outside the review window cannot be resumed. Close it with
        # an explicit failure receipt, preserving any delivery attempts, so it
        # does not remain an unexplained unfinished cycle forever.
        for old in store.db.execute("SELECT * FROM radar_runs WHERE state IN ('prepared','reviewing') AND started_at<?", (stamp(now() - timedelta(hours=24)),)).fetchall():
            result = failure_receipt(store, old, "research_window_expired")
            store.db.execute("UPDATE radar_runs SET state='failed',completed_at=?,result=? WHERE packet_id=?",
                             (result["completed_at"], json.dumps(result), old["packet_id"]))
        store.db.execute("INSERT INTO radar_runs VALUES (?,?,?,?,NULL,'prepared',?,NULL)",
                         (packet["packet_id"], trigger, automation_id, packet["created_at"], json.dumps(packet, ensure_ascii=False)))
        # Keep run receipts, but do not retain provider metadata inside packets indefinitely.
        store.db.execute("UPDATE radar_runs SET packet=NULL WHERE started_at<?", (stamp(now() - timedelta(days=28)),))


def resume_run(store, trigger, automation_id):
    row = store.db.execute("SELECT packet FROM radar_runs WHERE trigger=? AND automation_id IS ? AND state IN ('prepared','reviewing') AND started_at>? AND packet IS NOT NULL ORDER BY rowid DESC LIMIT 1",
                           (trigger, automation_id, stamp(now() - timedelta(hours=24)))).fetchone()
    if not row:
        return None
    packet = json.loads(row["packet"])
    atomic_json(store.workspace / "reports/radar-packet.json", packet)
    reviewed = {r[0] for r in store.db.execute("SELECT topic FROM radar_submissions WHERE packet_id=?", (packet["packet_id"],))}
    return {"packet_id": packet["packet_id"], "status": "resumed",
            "topics_to_review": [t["topic"] for t in packet["topics"] if t["topic"] not in reviewed],
            "collection_status": packet["collection_status"], "network_calls": 0,
            "packet_path": str(store.workspace / "reports/radar-packet.json")}


def load_packet(store, packet_id):
    if not isinstance(packet_id, str) or not re.fullmatch(r"packet-[a-f0-9]{20,32}", packet_id):
        raise ValueError("Invalid research packet ID")
    row = store.db.execute("SELECT packet FROM radar_runs WHERE packet_id=?", (packet_id,)).fetchone()
    path = store.workspace / "reports/radar-packet.json"
    packet = json.loads(row["packet"]) if row and row["packet"] else json.loads(path.read_text()) if path.exists() else None
    if not packet or packet.get("packet_id") != packet_id or parse_date(packet.get("created_at")) is None:
        raise ValueError("Unknown research packet")
    if not now() - timedelta(hours=24) <= parse_date(packet["created_at"]) <= now():
        raise ValueError("Unknown or stale research packet")
    return packet


def finish(store, packet_id, send=False):
    radar.ensure_radar(store)
    run = store.db.execute("SELECT * FROM radar_runs WHERE packet_id=?", (packet_id,)).fetchone()
    if not run:
        raise ValueError("This packet has no cycle receipt; prepare a new research cycle")
    if run["result"]:
        return {**json.loads(run["result"]), "replayed_receipt": True, "network_calls_this_call": 0}
    packet = load_packet(store, packet_id)
    submissions = {r["topic"]: json.loads(r["result"]) for r in store.db.execute("SELECT topic,result FROM radar_submissions WHERE packet_id=?", (packet_id,))}
    missing = [t["topic"] for t in packet["topics"] if t["topic"] not in submissions]
    if missing:
        return {"status": "review_incomplete", "packet_id": packet_id, "topics_to_review": missing, "sent": 0}
    radar.render_cards(store)
    from . import blue_ocean
    portfolio_sync = blue_ocean.sync(store, apply=True)
    portfolio_reassessment = blue_ocean.reassess_all(store, apply=True, trigger="radar_finish")
    portfolio_brief = blue_ocean.brief(store, commit=send)
    queued = telegram.enqueue(store)
    blue_ocean_queued = telegram.enqueue_blue_ocean_changes(store, portfolio_brief["changes_since_previous_brief"])
    preview = telegram.deliver(store)
    # A normal invocation without --send is a side-effect-free network preview;
    # it does not finalize the cycle or consume its later send opportunity.
    if not send:
        return {"status": "ready_to_finish", "packet_id": packet_id, "queue": queued, "preview": preview,
                "blue_ocean_queue": blue_ocean_queued, "portfolio_reassessment": portfolio_reassessment,
                "blue_ocean_sync": portfolio_sync, "blue_ocean_changes": portfolio_brief["changes_since_previous_brief"],
                "network_calls": 0}
    delivery = telegram.deliver(store, send=True, cycle_id=packet_id)
    maintenance = research.maintenance(store)
    # If the founder has explicitly configured operating limits and policies,
    # a completed research cycle also refreshes the local CEO operating brief.
    # This can change local portfolio state but never performs external actions.
    from . import founder_ops
    founder_operations = founder_ops.weekly_brief(store, apply=True)
    result = {"status": "completed", "packet_id": packet_id, "trigger": run["trigger"],
              "automation_id": run["automation_id"], "completed_at": stamp(),
              "topics_reviewed": len(submissions), "cards_saved": sum(len(s["cards"]) for s in submissions.values()),
              "queue": queued, "blue_ocean_queue": blue_ocean_queued,
              "portfolio_reassessment": portfolio_reassessment,
              "delivery": delivery, "reports_generated": len(maintenance["generated"]),
              "founder_operations": {"report_path": founder_operations["report_path"],
                                     "actions": founder_operations["reconciliation"].get("actions", []),
                                     "external_actions_executed": False},
              "blue_ocean_sync": portfolio_sync,
              "blue_ocean_changes": portfolio_brief["changes_since_previous_brief"],
              "boundary": "Research decisions and send receipts; neither scheduler proof nor validated market demand"}
    with store.db:
        store.db.execute("UPDATE radar_runs SET completed_at=?,state='completed',result=? WHERE packet_id=?",
                         (result["completed_at"], json.dumps(result, ensure_ascii=False), packet_id))
    atomic_json(store.workspace / "reports/radar-last-run.json", result)
    return result


def failure_receipt(store, run, reason):
    attempts = [dict(r) for r in store.db.execute(
        "SELECT alert_id,attempt_no,outcome,message_id,error FROM telegram_attempts WHERE cycle_id=? ORDER BY attempt_no",
        (run["packet_id"],))]
    return {"status": "failed", "packet_id": run["packet_id"], "trigger": run["trigger"],
            "automation_id": run["automation_id"], "reason": reason, "completed_at": stamp(),
            "delivery_attempts": attempts, "confirmed_api_sends": sum(a["outcome"] == "sent" for a in attempts),
            "network_calls_this_call": 0}


def fail(store, packet_id, reason):
    radar.ensure_radar(store)
    if reason not in ("source_unavailable", "research_interrupted", "local_error"):
        raise ValueError("Use a supported failure reason; do not include provider error bodies")
    row = store.db.execute("SELECT * FROM radar_runs WHERE packet_id=?", (packet_id,)).fetchone()
    if not row or row["state"] == "completed":
        raise ValueError("Only an existing unfinished cycle can be marked failed")
    if row["result"]:
        return {**json.loads(row["result"]), "replayed_receipt": True, "network_calls_this_call": 0}
    result = failure_receipt(store, row, reason)
    with store.db:
        store.db.execute("UPDATE radar_runs SET state='failed',completed_at=?,result=? WHERE packet_id=?",
                         (result["completed_at"], json.dumps(result), packet_id))
    return result


def runs(store, limit=20):
    radar.ensure_radar(store)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Run history limit must be 1..100")
    return [dict(r) for r in store.db.execute("SELECT packet_id,trigger,automation_id,started_at,completed_at,state FROM radar_runs ORDER BY rowid DESC LIMIT ?", (limit,))]


def health(store, acknowledge=False):
    cfg = radar.ensure_radar(store)
    delivery = telegram.status(store)
    recent = runs(store)
    heartbeat = store.db.execute("SELECT packet_id,started_at,completed_at,state FROM radar_runs WHERE trigger='heartbeat' AND automation_id IS ? ORDER BY rowid DESC LIMIT 1", (cfg["scheduler"].get("automation_id"),)).fetchone()
    issues = []
    if cfg.get("telegram_enabled") and (not delivery["enabled"] or not delivery["binding_matches"] or delivery["blocked_reason"]):
        issues.append("telegram_not_ready")
    issues.extend("delivery_attention:" + r["id"] + ":" + r["status"] for r in delivery["needs_attention"])
    overdue = now() - timedelta(minutes=max(90, cfg["check_interval_minutes"] * 3))
    unfinished = store.db.execute("SELECT COUNT(*) FROM radar_runs WHERE state IN ('prepared','reviewing') AND started_at<?", (stamp(overdue),)).fetchone()[0]
    if unfinished:
        issues.append("unfinished_research_cycle")
    scheduler_status = cfg["scheduler"].get("status", "not_required")
    scheduler_required = cfg.get("operating_mode") == "scheduled" and cfg.get("scheduler_required")
    if scheduler_required and scheduler_status == "ACTIVE":
        if not heartbeat:
            issues.append("no_recorded_heartbeat_run")
        elif parse_date(heartbeat["started_at"]) < overdue:
            issues.append("heartbeat_receipt_overdue")
        elif heartbeat["state"] == "failed":
            issues.append("latest_heartbeat_failed")
    elif scheduler_required and scheduler_status not in ("not_configured", None):
        # A stale local registration must never be interpreted as a working
        # scheduler. Preserve the reported state so a user can distinguish a
        # deliberately unconfigured workspace from a deleted/paused job.
        issues.append("scheduler_not_active:" + str(scheduler_status).lower())
    signature = digest(sorted(issues))
    path = store.workspace / "reports/radar-health-ack.json"
    previous = json.loads(path.read_text()) if path.exists() else None
    changed = bool(issues) if previous is None else previous.get("signature") != signature
    result = {"checked_at": stamp(), "status": "attention" if issues else "ok", "issues": issues,
              "notification_needed": changed, "telegram": delivery, "recent_runs": recent,
              "latest_recorded_heartbeat": dict(heartbeat) if heartbeat else None,
              "scheduler_registration": cfg["scheduler"],
              "operating_mode": cfg.get("operating_mode", "on_demand"),
              "scheduler_required": bool(scheduler_required),
              "boundary": "기본은 사용자가 호출할 때만 실행하는 수동 모드입니다. 상태 확인은 예약 실행이나 외부 알림을 만들지 않습니다."}
    if acknowledge:
        atomic_json(path, {"signature": signature, "acknowledged_at": stamp()})
    atomic_json(store.workspace / "reports/radar-health.json", result)
    return result
