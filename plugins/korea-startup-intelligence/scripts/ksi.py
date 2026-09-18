#!/usr/bin/env python3
"""Evidence-first startup workspace CLI, Python standard library only."""
import argparse
import fcntl
import json
import sys
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from ksi_lib.engine import choose_domains, coverage, refresh
from ksi_lib.model import (REQUIRED, Store, assets, atomic_json, canonical_url, credentials,
                           init_workspace, now, observation, parse_date, stamp, validate_record)
from ksi_lib import radar, telegram, research, grants, operations, venture, validation, agenda, application, market, workbench, competition, trend_forecast


def edit_payload(store, path, kind, prefix):
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError('저장할 내용은 JSON 객체여야 합니다.')
    key = payload.get('dossier_id', '').removeprefix('dossier-') if kind == 'venture_review' else payload.get('key', '')
    rid = prefix + key
    current = store.db.execute('SELECT revision FROM records WHERE kind=? AND id=?', (kind, rid)).fetchone()
    if current or 'expected_revision' in payload:
        store.assert_revision(kind, rid, payload.get('expected_revision'))
    return payload


@contextmanager
def locked(store):
    with (store.workspace / ".run.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another workspace run is active; try later") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def doctor(store):
    keys = credentials(store.workspace)
    sources = []
    for spec in assets("sources.json"):
        latest = store.db.execute("SELECT status,attempted_at FROM fetches WHERE source=? ORDER BY id DESC LIMIT 1", (spec["id"],)).fetchone()
        sources.append({"source": spec["id"], "implemented": bool(spec["adapter"]),
                        "enabled": spec["id"] in store.config["enabled_sources"],
                        "credential_present": all(k in keys for k in spec["credentials"]) if spec["credentials"] else None,
                        "last_attempt": dict(latest) if latest else None,
                        "access": spec["access"]})
    return {"workspace": str(store.workspace), "sqlite_integrity": store.db.execute("PRAGMA integrity_check").fetchone()[0],
            "sources": sources, "coverage": {k: v for k, v in coverage(store).items() if k != "unqueried_domains"}, "research_references": len(assets("research_index.json")),
            "credentials_values_logged": False,
            "scheduler": radar.ensure_radar(store)["scheduler"] if (store.workspace / "radar.json").exists() else {"status": "not_configured"},
            "telegram": telegram.status(store) if (store.workspace / "radar.json").exists() else {"enabled": False},
            "learning_boundary": "Persistent evidence and outcome records, not model weight training or guaranteed skill improvement"}


def import_evidence(store, path):
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, list) or len(payload) > 500:
        raise ValueError("Import a list of at most 500 permitted source observations")
    rows = []
    for item in payload:
        for field in ("topic", "title", "url", "event_at", "collection_basis"):
            if not item.get(field):
                raise ValueError("Import requires topic,title,url,event_at,collection_basis")
        if item["collection_basis"] not in ("user_owned", "authorized_export", "public_source_verified"):
            raise ValueError("Unsupported collection basis; no login bypass or unauthorized personal data")
        if not parse_date(item["event_at"]) or parse_date(item["event_at"]) > now():
            raise ValueError("Evidence needs a valid non-future event date")
        kind = item.get("kind", "manual_evidence")
        if kind not in ("manual_evidence", "interview", "transaction", "aggregate_metric", "grant"):
            raise ValueError("Unsupported manual evidence kind")
        row = observation("manual", kind, item["topic"], item["title"], item["url"], item["event_at"],
                          geography=item.get("geography", "KR"),
                          content_scope="user_supplied_summary_not_independently_verified",
                          collection_basis=item["collection_basis"],
                          metrics=item.get("metrics", {}), limitations=["manual_import_requires_source_review"])
        rows.append(row)
    with store.db:
        for row in rows:
            store.put_observation(row)
    return {"imported": len(rows), "ids": [r["id"] for r in rows]}


def resolve_forecast(store, record_id, outcome, evidence_id):
    forecasts = {r["id"]: r for r in store.records("forecast")}
    if record_id not in forecasts:
        raise ValueError("Unknown forecast")
    forecast = forecasts[record_id]
    if parse_date(forecast["deadline"]) > now():
        raise ValueError("Resolve only after the prespecified deadline")
    if any(r["id"] == record_id for r in store.records("resolution")):
        raise ValueError("Resolution is immutable; append an explicit correction record separately")
    evidence = {r["id"]: r for r in store.observations()}.get(evidence_id)
    if not evidence or not parse_date(evidence["event_at"]) or parse_date(evidence["event_at"]) < parse_date(forecast["deadline"]):
        raise ValueError("Resolution needs nonexpired evidence dated at/after the deadline")
    result = {"id": record_id, "outcome": outcome, "brier_score": (forecast["probability"] - outcome) ** 2,
              "evidence_ids": [evidence_id], "resolved_at": stamp(), "verification": "user_or_agent_resolved_not_independent_audit"}
    store.record("resolution", result)
    store.db.commit()
    return result


def run(args):
    if args.command == "init":
        return {"workspace": init_workspace(args.workspace)}
    store = Store(args.workspace)
    try:
        if args.command == "doctor":
            return doctor(store)
        if args.command == "domains":
            values = assets("taxonomy.json")["domains"]
            if args.query:
                values = [d for d in values if args.query.lower() in json.dumps(d, ensure_ascii=False).lower()]
            return values[:args.limit]
        if args.command == "research":
            return [r for r in assets("research_index.json") if args.query.lower() in json.dumps(r, ensure_ascii=False).lower()][:args.limit]
        if args.command == "coverage":
            return coverage(store)
        if args.command == "market-map":
            return market.overview(store, args.query, args.limit)
        if args.command == "brief":
            path = store.workspace / "reports/latest.json"
            return json.loads(path.read_text()) if path.exists() else {"status": "never_refreshed"}
        if args.command == "list":
            return store.observations(args.topic)[:args.limit] if args.kind == "evidence" else store.records(args.kind)[:args.limit]
        if args.command == "ideation-plan":
            return {"status": "research_prompts_not_validated_ideas", "domains": choose_domains(store, args.limit),
                    "required_diversity": ["B2B", "B2C", "B2G", "offline_plus_online", "hardware", "service"],
                    "instruction": "Use these sectors to investigate people, repeated workarounds and real willingness to pay. Label any proposed idea hypothesis. Save only after source verification."}
        if args.command == "evaluation":
            rows = store.records("resolution")
            return {"resolved_forecasts": len(rows), "mean_brier": sum(r["brier_score"] for r in rows) / len(rows) if rows else None,
                    "calibration_validated": False, "note": "No claim of predictive skill from small selected samples; compare baselines and retain misses."}
        with locked(store):
            if args.command == 'workbench':
                return workbench.execute(store, args.action, args)
            if args.command == "application":
                if args.action == "prepare":
                    return application.prepare(store, args.dossier_id, args.grant_id)
                if args.action == "save":
                    return application.save(store, edit_payload(store, args.file, 'application', 'application-'))
                if args.action == "check":
                    return application.check(store, args.id)
                if args.action == "resume":
                    return application.resume(store, args.id)
                if args.action == "attest":
                    return application.attest(store, json.loads(Path(args.file).read_text()))
            if args.command == "venture-review":
                if args.action == "prepare":
                    return venture.prepare(store, args.dossier_id, args.stage)
                if args.action == "save":
                    return venture.save(store, edit_payload(store, args.file, 'venture_review', 'venture-'))
                if args.action == "status":
                    return venture.status(store, args.dossier_id)
            if args.command == "validation":
                if args.action == "plan":
                    return validation.plan(store, json.loads(Path(args.file).read_text()))
                if args.action == "result":
                    return validation.result(store, json.loads(Path(args.file).read_text()))
                if args.action == "status":
                    return validation.status(store, args.dossier_id)
            if args.command == "grants":
                if args.action == "save":
                    return grants.save_notice(store, edit_payload(store, args.file, 'grant', 'grant-'))
                if args.action == "match":
                    return grants.match_notice(store, args.id, json.loads(Path(args.profile).read_text()))
            if args.command == "competition":
                if args.action == "prepare":
                    profile = json.loads(Path(args.profile).read_text()) if args.profile else {}
                    return competition.prepare(store, args.grant_id, profile, args.limit)
                if args.action == "evaluate":
                    return competition.evaluate(store, json.loads(Path(args.file).read_text()))
                if args.action == "status":
                    return competition.status(store, args.grant_id)
            if args.command == "trend-forecast":
                if args.action == "prepare":
                    return trend_forecast.prepare(store, args.limit)
                if args.action == "register":
                    return trend_forecast.register(store, json.loads(Path(args.file).read_text()))
                if args.action == "resolve":
                    return trend_forecast.resolve(store, json.loads(Path(args.file).read_text()))
                if args.action == "evaluate":
                    return trend_forecast.evaluate(store)
                if args.action == "status":
                    return trend_forecast.status(store)
            if args.command == "research-work":
                if args.action == "start":
                    return agenda.start(store, args.task_id, args.revisit, args.actor)
                if args.action == 'handoff':
                    return agenda.handoff(store, args.run_id, args.actor, args.to_actor, args.note)
                if args.action == "complete":
                    return agenda.complete(store, json.loads(Path(args.file).read_text()))
                if args.action == "history":
                    return agenda.status(store)
                if args.action == "save":
                    return research.save_dossier(store, edit_payload(store, args.file, 'dossier', 'dossier-'))
                if args.action == "plan":
                    return research.research_plan(store, args.limit)
                if args.action == "pain":
                    return research.mine_pain(store)
                if args.action == "graph":
                    return research.graph(store, args.node)
                if args.action == "report":
                    return research.report(store, args.period)
                if args.action == "quality":
                    radar.render_cards(store)
                    return [{"id": c["id"], **research.opportunity_gate(store, c)} for c in store.records("opportunity")]
                if args.action == "maintenance":
                    return research.maintenance(store)
            if args.command == "radar":
                if args.action in ("init", "status"):
                    return radar.status(store)
                if args.action == "prepare":
                    return radar.prepare(store, args.no_refresh, args.trigger, args.automation_id, args.resume)
                if args.action == "finish":
                    return operations.finish(store, args.packet_id, args.send)
                if args.action == "fail":
                    return operations.fail(store, args.packet_id, args.reason)
                if args.action == "runs":
                    return operations.runs(store, args.limit)
                if args.action == "packet":
                    radar.ensure_radar(store)
                    return operations.load_packet(store, args.packet_id)
                if args.action == "health":
                    return operations.health(store, args.acknowledge)
                if args.action == "review-source":
                    return radar.review_source(store, json.loads(Path(args.file).read_text()))
                if args.action == "publish":
                    return radar.publish_card(store, json.loads(Path(args.file).read_text()))
                if args.action == "submit":
                    return radar.submit(store, json.loads(Path(args.file).read_text()))
            if args.command == "telegram":
                if args.action == "init":
                    return telegram.init_telegram(store)
                if args.action == "status":
                    return telegram.status(store)
                if args.action == "discover":
                    return telegram.discover(store)
                if args.action == "verify":
                    return telegram.verify(store)
                if args.action == "enable":
                    return telegram.enable(store, args.confirm_chat_id)
                if args.action == "disable":
                    return telegram.disable(store)
                if args.action == "queue":
                    return telegram.enqueue(store)
                if args.action == "connection-check":
                    return telegram.enqueue_connection_check(store, args.confirm_chat_id)
                if args.action == "self-test":
                    return telegram.enqueue_self_test(store)
                if args.action == "history":
                    return telegram.history(store, args.limit)
                if args.action == "resolve":
                    return telegram.resolve_delivery(store, args.alert_id, args.outcome, args.confirm_chat_id,
                                                     args.note, args.retry, args.message_id)
                if args.action in ("preview", "deliver"):
                    return telegram.deliver(store, send=args.action == "deliver" and args.send)
            if args.command == "refresh":
                report = refresh(store, args.topic, args.source, args.max_requests, args.sector_batch, args.force)
                result = {k: report[k] for k in ("status", "generated_at", "requests_made", "new_observations", "sources", "unavailable", "deferred")}
                result["coverage"] = {k: v for k, v in report["coverage"].items() if k != "unqueried_domains"}
                return result
            if args.command == "import-evidence":
                return import_evidence(store, args.file)
            if args.command == "record":
                payload = json.loads(Path(args.file).read_text())
                expected = payload.pop('expected_revision', None)
                data = validate_record(store, args.kind, payload)
                if store.db.execute('SELECT 1 FROM records WHERE kind=? AND id=?', (args.kind, data['id'])).fetchone() or expected is not None:
                    store.assert_revision(args.kind, data['id'], expected)
                revision = store.record(args.kind, data, expected)
                store.db.commit()
                return {"kind": args.kind, "id": data["id"], "revision": revision}
            if args.command == "resolve":
                return resolve_forecast(store, args.id, args.outcome, args.evidence_id)
            if args.command == "enable":
                registered = {s["id"]: s for s in assets("sources.json")}
                if args.source not in registered or not registered[args.source]["adapter"]:
                    raise ValueError("Source adapter not implemented")
                store.config["enabled_sources"] = list(dict.fromkeys(store.config["enabled_sources"] + [args.source]))
                atomic_json(store.workspace / "config.json", store.config)
                return {"enabled": args.source, "note": "Credentials and successful live call still required"}
        raise ValueError("Unsupported command")
    finally:
        store.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True, help="Persistent state directory outside the installed plugin")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("init", "doctor", "coverage", "brief", "evaluation"):
        sub.add_parser(name)
    s = sub.add_parser('workbench', help='키 없이 조사 시작·협업·비교·평가·복구')
    actions = s.add_subparsers(dest='action', required=True)
    for name in ('start', 'velocity', 'evaluation', 'backup', 'capabilities', 'due-reviews', 'duplicates',
                 'workflow', 'research-qa', 'team-queue', 'usability', 'x-status', 'feedback-queue'):
        actions.add_parser(name)
    r = actions.add_parser('queries')
    r.add_argument('--query', required=True)
    r = actions.add_parser('template')
    r.add_argument('kind', choices=list(workbench.CONTRACTS))
    for name in ('checkout', 'diff'):
        r = actions.add_parser(name)
        r.add_argument('kind')
        r.add_argument('id')
        if name == 'diff':
            r.add_argument('--revision', type=int)
    r = actions.add_parser('impact')
    r.add_argument('id')
    for name in ('save', 'economics', 'compare', 'latency', 'export', 'merge-preview', 'restore-copy', 'intake', 'cashflow', 'sampling', 'ablation-compare', 'comment-sample', 'social-import', 'x-preview', 'x-recover', 'business-check', 'portfolio', 'interview-pack'):
        r = actions.add_parser(name)
        r.add_argument('--file', required=True)
        if name == 'restore-copy':
            r.add_argument('--destination', required=True)
    for name in ("domains", "research"):
        s = sub.add_parser(name)
        s.add_argument("--query", default="")
        s.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("ideation-plan")
    s.add_argument("--limit", type=int, default=10)
    s = sub.add_parser("market-map", help="All-sector navigation with signal, review and result coverage; no API keys")
    s.add_argument("--query", default="")
    s.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("refresh")
    s.add_argument("--topic", action="append")
    s.add_argument("--source", action="append")
    s.add_argument("--max-requests", type=int)
    s.add_argument("--sector-batch", type=int)
    s.add_argument("--force", action="store_true", help="Bypass freshness; use only for targeted diagnosis")
    s = sub.add_parser("list")
    s.add_argument("kind", choices=["evidence", "trend", "resolution", "opportunity", "dossier", "grant",
                                    "venture_review", "validation_plan", "validation_result", "research_run", "research_receipt", "application"] + list(REQUIRED))
    s.add_argument("--topic")
    s.add_argument("--limit", type=int, default=20)
    s = sub.add_parser("record")
    s.add_argument("kind", choices=list(REQUIRED))
    s.add_argument("--file", required=True)
    s = sub.add_parser("import-evidence")
    s.add_argument("--file", required=True)
    s = sub.add_parser("resolve")
    s.add_argument("id")
    s.add_argument("--outcome", type=int, choices=(0, 1), required=True)
    s.add_argument("--evidence-id", required=True)
    s = sub.add_parser("enable")
    s.add_argument("source")
    s = sub.add_parser("radar", help="Prepare original-source research and save gated startup hypotheses")
    actions = s.add_subparsers(dest="action", required=True)
    for name in ("init", "status"):
        actions.add_parser(name)
    r = actions.add_parser("prepare")
    r.add_argument("--no-refresh", action="store_true", help="Use stored evidence without network calls")
    r.add_argument("--trigger", choices=("manual", "heartbeat"), default="manual")
    r.add_argument("--automation-id")
    r.add_argument("--resume", action="store_true", help="Resume a recent unfinished cycle of the same trigger")
    r = actions.add_parser("finish")
    r.add_argument("--packet-id", required=True)
    r.add_argument("--send", action="store_true", help="Finish all topic reviews and deliver at most one eligible queued message")
    r = actions.add_parser("fail")
    r.add_argument("--packet-id", required=True)
    r.add_argument("--reason", choices=("source_unavailable", "research_interrupted", "local_error"), required=True)
    r = actions.add_parser("runs")
    r.add_argument("--limit", type=int, default=20)
    r = actions.add_parser("packet")
    r.add_argument("--packet-id", required=True)
    r = actions.add_parser("health")
    r.add_argument("--acknowledge", action="store_true", help="Acknowledge the current issue set only after reporting it")
    for name in ("review-source", "publish", "submit"):
        r = actions.add_parser(name)
        r.add_argument("--file", required=True)
    s = sub.add_parser("telegram", help="Dedicated bot, exact-recipient binding and one-way notifications")
    actions = s.add_subparsers(dest="action", required=True)
    for name in ("init", "status", "discover", "verify", "disable", "queue", "preview"):
        actions.add_parser(name)
    r = actions.add_parser("enable")
    r.add_argument("--confirm-chat-id", required=True)
    r = actions.add_parser("connection-check", help="Queue one fixed connection-test message, not an idea")
    r.add_argument("--confirm-chat-id", required=True)
    actions.add_parser("self-test", help="Queue one fixed manual release check; never used by the scheduler")
    r = actions.add_parser("history")
    r.add_argument("--limit", type=int, default=20)
    r = actions.add_parser("resolve", help="Record explicit user confirmation for an uncertain send; no network calls")
    r.add_argument("--alert-id", required=True)
    r.add_argument("--outcome", choices=("delivered", "not_delivered", "discard"), required=True)
    r.add_argument("--confirm-chat-id", required=True)
    r.add_argument("--note", required=True)
    r.add_argument("--message-id", type=int)
    r.add_argument("--retry", action="store_true", help="Explicitly request retry only after confirming not_delivered")
    r = actions.add_parser("deliver")
    r.add_argument("--send", action="store_true", help="Actually send at most one queued card to the enabled verified recipient")
    s = sub.add_parser("research-work", help="Evidence-linked 24-dimension dossiers, research backlog and reports")
    actions = s.add_subparsers(dest="action", required=True)
    r = actions.add_parser("save")
    r.add_argument("--file", required=True)
    r = actions.add_parser("plan")
    r.add_argument("--limit", type=int, default=6)
    r = actions.add_parser("start")
    r.add_argument("--task-id", required=True)
    r.add_argument('--actor', help='비식별 로컬 담당자명. 인증 계정이 아닙니다.')
    r.add_argument("--revisit", action="store_true", help="Explicit local revisit before the cooldown expires; no external actions")
    r = actions.add_parser('handoff')
    for field in ('run-id', 'actor', 'to-actor', 'note'):
        r.add_argument('--' + field, required=True)
    r = actions.add_parser("complete")
    r.add_argument("--file", required=True)
    actions.add_parser("history")
    r = actions.add_parser("graph")
    r.add_argument("--node")
    r = actions.add_parser("report")
    r.add_argument("--period", choices=("daily", "weekly", "monthly"), default="daily")
    for name in ("pain", "quality", "maintenance"):
        actions.add_parser(name)
    s = sub.add_parser("venture-review", help="Evidence-linked founder questions, alternatives and failure paths")
    actions = s.add_subparsers(dest="action", required=True)
    r = actions.add_parser("prepare")
    r.add_argument("--dossier-id", required=True)
    r.add_argument("--stage", choices=tuple(venture.STAGE_PRIORITIES))
    r = actions.add_parser("save")
    r.add_argument("--file", required=True)
    r = actions.add_parser("status")
    r.add_argument("--dossier-id")
    s = sub.add_parser("validation", help="Immutable prespecified experiments and separately recorded measured results")
    actions = s.add_subparsers(dest="action", required=True)
    for name in ("plan", "result"):
        r = actions.add_parser(name)
        r.add_argument("--file", required=True)
    r = actions.add_parser("status")
    r.add_argument("--dossier-id")
    s = sub.add_parser("application", help="No-key business plan, official-criteria mapping, budget, pitch and judge rehearsal")
    actions = s.add_subparsers(dest="action", required=True)
    r = actions.add_parser("prepare")
    r.add_argument("--dossier-id", required=True)
    r.add_argument("--grant-id")
    r = actions.add_parser("save")
    r.add_argument("--file", required=True)
    r = actions.add_parser("check")
    r.add_argument("id")
    r = actions.add_parser("resume")
    r.add_argument("id")
    r = actions.add_parser("attest")
    r.add_argument("--file", required=True)
    s = sub.add_parser("grants", help="Match reviewed official notice conditions with confirmed founder facts")
    actions = s.add_subparsers(dest="action", required=True)
    r = actions.add_parser("save")
    r.add_argument("--file", required=True)
    r = actions.add_parser("match")
    r.add_argument("id")
    r.add_argument("--profile", required=True)
    s = sub.add_parser("competition", help="공식 공고 기반 아이디어 발산·근거·평가표·시연 준비도 스프린트")
    actions = s.add_subparsers(dest="action", required=True)
    r = actions.add_parser("prepare")
    r.add_argument("--grant-id", required=True)
    r.add_argument("--profile")
    r.add_argument("--limit", type=int, default=12)
    r = actions.add_parser("evaluate")
    r.add_argument("--file", required=True)
    r = actions.add_parser("status")
    r.add_argument("--grant-id")
    s = sub.add_parser("trend-forecast", help="선행 신호→한국 확산 예측→만기 판정→기준선·선행시간 평가")
    actions = s.add_subparsers(dest="action", required=True)
    r = actions.add_parser("prepare")
    r.add_argument("--limit", type=int, default=12)
    for name in ("register", "resolve"):
        r = actions.add_parser(name)
        r.add_argument("--file", required=True)
    actions.add_parser("evaluate")
    actions.add_parser("status")
    args = p.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2, allow_nan=False))
    except telegram.TelegramError as exc:
        print(json.dumps({"status": "telegram_error", "code": exc.code, "retry_after": exc.retry_after,
                          "values_logged": False}), file=sys.stderr)
        return 2
    except (ValueError, OSError, sqlite3.Error) as exc:
        from ksi_lib.errors import explain
        print(json.dumps(explain(exc), ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
