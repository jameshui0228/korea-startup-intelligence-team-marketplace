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
from ksi_lib import (radar, telegram, research, grants, operations, venture, validation,
                     agenda, application, market, workbench, competition, trend_forecast,
                     blue_ocean, founder_ops, venture_intelligence, venture_ops, signal_intake,
                     prevalidation, no_api_research, frontier)


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
    sync_preview = blue_ocean.sync(store, apply=False)
    validation_plans = store.records("validation_plan")
    operator_status = founder_ops.status(store)
    radar_cfg = radar.ensure_radar(store) if (store.workspace / "radar.json").exists() else {
        "operating_mode": store.config.get("operating_mode", "on_demand"),
        "scheduler_required": store.config.get("scheduler_required", False),
        "scheduler": {"status": "not_required", "automation_id": None},
    }
    return {"workspace": str(store.workspace), "sqlite_integrity": store.db.execute("PRAGMA integrity_check").fetchone()[0],
            "workspace_profile_version": store.config.get("workspace_profile_version"),
            "operating_mode": radar_cfg["operating_mode"],
            "discovery_mode": store.config.get("discovery_mode"),
            "api_credentials_required_for_core": False,
            "sources": sources, "coverage": {k: v for k, v in coverage(store).items() if k != "unqueried_domains"}, "research_references": len(assets("research_index.json")),
            "credentials_values_logged": False,
            "scheduler": radar_cfg["scheduler"],
            "telegram": telegram.status(store) if (store.workspace / "radar.json").exists() else {"enabled": False},
            "blue_ocean": {"candidates": len(store.records("blue_ocean")),
                           "frontier_hypotheses": len(store.records("frontier_hypothesis")),
                           "frontier_batches": len(store.records("frontier_batch")),
                           "next_actions": len(blue_ocean.next_actions(store, 50)["items"]),
                           "unmanaged_radar_hypotheses": sum(i["action"] == "adopt" for i in sync_preview["items"]),
                           "qualitative_experiments": sum(e.get("method_type") == "qualitative" for e in validation_plans),
                           "prevalidation_bootstraps": len(store.records("prevalidation_bootstrap"))},
            "founder_operations": {"configured": operator_status["configured"],
                                   "focus_candidates": len(operator_status["capacity_plan"].get("focus", [])),
                                   "overflow_candidates": len(operator_status["capacity_plan"].get("overflow", [])),
                                   "kpi_plans": operator_status["kpi_plans"],
                                   "kpi_snapshots": operator_status["kpi_snapshots"],
                                   "checkins": operator_status["checkins"]},
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
    events = [event for row in rows for event in blue_ocean.note_evidence_change(store, row["id"])]
    reassessment = blue_ocean.reassess_all(store, apply=True, trigger="evidence_import")
    return {"imported": len(rows), "ids": [r["id"] for r in rows],
            "blue_ocean_events": events, "portfolio_reassessment": reassessment}


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


def read_only_command(args):
    if args.command in {"domains", "research", "coverage", "brief", "list", "ideation-plan", "evaluation"}:
        return True
    if args.command == "blue-ocean":
        return args.action in {"template", "status", "next", "history", "signals", "patterns", "lag",
                               "transfers", "portfolio", "design", "sources", "metrics", "search", "catch-up",
                               "frontier", "frontier-template", "frontier-list"} or \
               (args.action == "bootstrap" and not args.apply) or \
               (args.action == "tournament" and not args.apply)
    if args.command == "operator":
        return args.action in {"template", "status", "plan", "task-board", "monthly", "variance",
                               "failures", "kpi-defaults", "overview"}
    return args.command == "signal" and args.action in {"template", "capabilities", "web-plan"}


def run(args):
    if args.command == "init":
        return {"workspace": init_workspace(args.workspace)}
    store = Store(args.workspace, read_only=read_only_command(args))
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
        # Pure portfolio reads do not take the run-wide writer lock. SQLite keeps
        # a consistent read snapshot while an unrelated long research cycle is
        # active, so status checks no longer fail merely because collection runs.
        if args.command == "blue-ocean" and args.action == "template":
            return blue_ocean.template()
        if args.command == "blue-ocean" and args.action == "status":
            return blue_ocean.status(store, args.id)
        if args.command == "blue-ocean" and args.action == "next":
            return blue_ocean.next_actions(store, args.limit)
        if args.command == "blue-ocean" and args.action == "history":
            return blue_ocean.history(store, args.id)
        if args.command == "blue-ocean" and args.action == "signals":
            return venture_intelligence.signal_graph(store)
        if args.command == "blue-ocean" and args.action == "patterns":
            return venture_intelligence.opportunity_patterns(store)
        if args.command == "blue-ocean" and args.action == "lag":
            return venture_intelligence.overseas_korea_lag(store)
        if args.command == "blue-ocean" and args.action == "transfers":
            return venture_intelligence.cross_industry_transfers(store)
        if args.command == "blue-ocean" and args.action == "portfolio":
            return venture_intelligence.portfolio_decisions(store, blue_ocean.assess)
        if args.command == "blue-ocean" and args.action == "design":
            candidate = next((row for row in store.records("blue_ocean")
                              if row["id"] == args.id or row["key"] == args.id), None)
            if not candidate:
                raise ValueError("블루오션 후보를 찾을 수 없습니다.")
            return venture_intelligence.entry_dynamics(store, candidate)
        if args.command == "blue-ocean" and args.action == "sources":
            return venture_intelligence.source_capabilities(store)
        if args.command == "blue-ocean" and args.action == "metrics":
            return venture_intelligence.performance_metrics(store)
        if args.command == "blue-ocean" and args.action == "search":
            return {"items": venture_intelligence.filter_candidates(store, args.query, args.domain,
                        args.stage, args.max_budget, args.due_before)}
        if args.command == "blue-ocean" and args.action == "catch-up":
            return venture_intelligence.catch_up(store, args.since)
        if args.command == "blue-ocean" and args.action == "frontier":
            return frontier.frontier_packet(store, args.topic, args.limit)
        if args.command == "blue-ocean" and args.action == "frontier-template":
            return frontier.tournament_template()
        if args.command == "blue-ocean" and args.action == "frontier-list":
            return frontier.saved_hypotheses(store)
        if args.command == "blue-ocean" and args.action == "tournament" and not args.apply:
            return frontier.evaluate_tournament(store, json.loads(Path(args.file).read_text()), apply=False)
        if args.command == "blue-ocean" and args.action == "bootstrap" and not args.apply:
            return prevalidation.bootstrap(store, args.id, args.limit, apply=False)
        if args.command == "blue-ocean" and args.action == "onboard":
            portfolio = blue_ocean.status(store)
            adoption = blue_ocean.sync(store)
            profile = next(iter(store.records("founder_profile")), None)
            next_step = ("기존 dossier/레이더 근거를 blue-ocean sync --apply로 보존 승계"
                         if any(row["action"] in ("adopt", "adopt_dossier") for row in adoption["items"]) else
                         "blue-ocean run으로 허용 최신 소스를 수집하고 중요한 원문을 검토")
            return {"candidate_count": portfolio["portfolio_size"],
                    "unmanaged_research_count": sum(row["action"] in ("adopt", "adopt_dossier") for row in adoption["items"]),
                    "founder_profile_configured": profile is not None,
                    "first_question": "이번 달 직접 접근 가능한 고객 집단은 누구인가요?" if not profile else None,
                    "next_step": next_step + " 후 blue-ocean frontier로 30→10→3 참신성 토너먼트 실행",
                    "boundary": "초기 안내이며 자동 아이디어 생성·검증 또는 API 연결 성공이 아닙니다."}
        if args.command == "operator" and args.action == "template":
            return venture_ops.template(args.kind) if args.kind in ("task", "task-result", "action", "action-transition") else founder_ops.template(args.kind)
        if args.command == "operator" and args.action == "status":
            return founder_ops.status(store)
        if args.command == "operator" and args.action == "plan":
            return founder_ops.capacity_plan(store)
        if args.command == "operator" and args.action == "task-board":
            return venture_ops.task_board(store, args.id)
        if args.command == "operator" and args.action == "monthly":
            return venture_ops.monthly_plan(store, args.month)
        if args.command == "operator" and args.action == "variance":
            return venture_ops.weekly_variance(store, args.week_start)
        if args.command == "operator" and args.action == "failures":
            return venture_ops.failure_patterns(store)
        if args.command == "operator" and args.action == "kpi-defaults":
            return venture_ops.standard_kpis()
        if args.command == "operator" and args.action == "overview":
            return venture_ops.status(store)
        if args.command == "signal" and args.action in ("template", "capabilities", "web-plan"):
            if args.action == "template":
                return signal_intake.template()
            if args.action == "capabilities":
                return signal_intake.capabilities(store)
            return no_api_research.plan(store, args.topic, args.lane, args.limit, args.since_days)
        with locked(store):
            if args.command == "blue-ocean":
                if args.action == "prepare":
                    return blue_ocean.prepare(store, args.limit, args.no_refresh, args.max_requests, args.sector_batch, args.topic)
                if args.action == "run":
                    prepared = blue_ocean.prepare(store, args.limit, args.no_refresh, args.max_requests, args.sector_batch, args.topic)
                    report = blue_ocean.brief(store)
                    return {"discovery": prepared, "brief": report, "operator": venture_ops.status(store),
                            "prevalidation": prevalidation.bootstrap(store, limit=min(args.limit, 5), apply=False),
                            "boundary": "프런티어 조합은 발산 재료입니다. Codex가 실제 원문을 열고 30→10→3 토너먼트를 완료해야 하며, 명령 자체는 고객 수요를 검증하지 않습니다."}
                if args.action == "tournament":
                    return frontier.evaluate_tournament(store, json.loads(Path(args.file).read_text()), apply=True)
                if args.action == "template":
                    return blue_ocean.template()
                if args.action == "save":
                    return blue_ocean.save(store, json.loads(Path(args.file).read_text()))
                if args.action == "status":
                    return blue_ocean.status(store, args.id)
                if args.action == "next":
                    return blue_ocean.next_actions(store, args.limit)
                if args.action == "transition":
                    return blue_ocean.transition(store, json.loads(Path(args.file).read_text()))
                if args.action == "brief":
                    return blue_ocean.brief(store)
                if args.action == "sync":
                    return blue_ocean.sync(store, args.apply)
                if args.action == "reassess":
                    return blue_ocean.reassess_all(store, apply=args.apply)
                if args.action == "bootstrap":
                    return prevalidation.bootstrap(store, args.id, args.limit, apply=True)
            if args.command == "operator":
                if args.action == "task":
                    return venture_ops.save_task(store, json.loads(Path(args.file).read_text()))
                if args.action == "task-result":
                    return venture_ops.record_task_result(store, json.loads(Path(args.file).read_text()))
                if args.action == "action":
                    return venture_ops.save_action(store, json.loads(Path(args.file).read_text()))
                if args.action == "action-transition":
                    return venture_ops.transition_action(store, json.loads(Path(args.file).read_text()))
                if args.action == "package":
                    return venture_ops.execution_package(store, args.id, args.apply)
                if args.action == "configure":
                    return founder_ops.configure(store, json.loads(Path(args.file).read_text()))
                if args.action == "fit":
                    return founder_ops.save_fit(store, json.loads(Path(args.file).read_text()))
                if args.action == "pipeline":
                    return founder_ops.save_pipeline(store, json.loads(Path(args.file).read_text()))
                if args.action == "kpi-plan":
                    return founder_ops.save_kpi_plan(store, json.loads(Path(args.file).read_text()))
                if args.action == "kpi-snapshot":
                    return founder_ops.save_kpi_snapshot(store, json.loads(Path(args.file).read_text()))
                if args.action == "checkin":
                    return founder_ops.save_checkin(store, json.loads(Path(args.file).read_text()))
                if args.action == "reopen-signal":
                    return founder_ops.save_reopen_signal(store, json.loads(Path(args.file).read_text()))
                if args.action == "reconcile":
                    return founder_ops.reconcile(store, args.apply)
                if args.action == "weekly":
                    return founder_ops.weekly_brief(store, args.week_start, args.apply)
            if args.command == "signal" and args.action == "import":
                return signal_intake.import_signal(store, json.loads(Path(args.file).read_text()))
            if args.command == "signal" and args.action == "batch-import":
                return signal_intake.import_signals(store, json.loads(Path(args.file).read_text()))
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
                if args.action == "qualitative-plan":
                    return validation.qualitative_plan(store, json.loads(Path(args.file).read_text()))
                if args.action == "qualitative-result":
                    return validation.qualitative_result(store, json.loads(Path(args.file).read_text()))
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
    s = sub.add_parser("blue-ocean", help="Discover and manage evidence-linked Korean market whitespace")
    actions = s.add_subparsers(dest="action", required=True)
    r = actions.add_parser("prepare", help="Refresh permitted sources, adopt research and prepare discovery")
    r.add_argument("--limit", type=int, default=6)
    r.add_argument("--no-refresh", action="store_true", help="Use stored evidence only")
    r.add_argument("--max-requests", type=int)
    r.add_argument("--sector-batch", type=int)
    r.add_argument("--topic", help="이번 수동 공개 웹 조사에서 좁힐 고객 문제·시장 주제")
    r = actions.add_parser("run", help="One command for collection, portfolio sync, reassessment and brief")
    r.add_argument("--limit", type=int, default=6)
    r.add_argument("--no-refresh", action="store_true")
    r.add_argument("--max-requests", type=int)
    r.add_argument("--sector-batch", type=int)
    r.add_argument("--topic", help="이번 수동 공개 웹 조사에서 좁힐 고객 문제·시장 주제")
    actions.add_parser("onboard", help="Start the guided no-key founder workflow")
    actions.add_parser("template", help="Return the candidate contract Codex fills for the user")
    r = actions.add_parser("save", help="Save or revise an evidence-linked market-whitespace candidate")
    r.add_argument("--file", required=True)
    r = actions.add_parser("status", help="Show the persistent candidate portfolio and current evidence gaps")
    r.add_argument("--id")
    r = actions.add_parser("next", help="Show due next actions; not a success-probability ranking")
    r.add_argument("--limit", type=int, default=10)
    r = actions.add_parser("transition", help="Move a candidate through validation and execution with stage gates")
    r.add_argument("--file", required=True)
    actions.add_parser("brief", help="Write a concise personal founder brief from the current portfolio")
    r = actions.add_parser("sync", help="Preview or apply evidence-preserving adoption of existing radar hypotheses")
    r.add_argument("--apply", action="store_true", help="Write the previewed portfolio adoption; never advances stages automatically")
    r = actions.add_parser("reassess", help="Compare evidence and decision changes; --apply records the review queue")
    r.add_argument("--apply", action="store_true")
    r = actions.add_parser("history", help="Explain why one candidate changed")
    r.add_argument("--id", required=True)
    r = actions.add_parser("design", help="Compare business structures, channels, cost and large-company entry risk")
    r.add_argument("--id", required=True)
    for name in ("signals", "patterns", "lag", "transfers", "portfolio", "sources", "metrics"):
        actions.add_parser(name)
    r = actions.add_parser("search", help="Filter candidates by customer/problem, field, stage, budget or deadline")
    r.add_argument("--query")
    r.add_argument("--domain", action="append")
    r.add_argument("--stage", action="append", choices=blue_ocean.STAGES)
    r.add_argument("--max-budget", type=int)
    r.add_argument("--due-before")
    r = actions.add_parser("catch-up", help="Show saved changes since the last visit")
    r.add_argument("--since", required=True)
    r = actions.add_parser("frontier", help="Build 30 structurally different discovery prompts before conservative validation")
    r.add_argument("--topic", help="Optional customer change or market theme to narrow stored signal atoms")
    r.add_argument("--limit", type=int, default=30, help="Divergent prompt count, 12..60; default 30")
    actions.add_parser("frontier-template", help="Return the contract for the 30-to-10-to-3 novelty tournament")
    r = actions.add_parser("tournament", help="Reject generic repackaging and compare novelty, evidence and execution separately")
    r.add_argument("--file", required=True)
    r.add_argument("--apply", action="store_true", help="Save all hypotheses and rejects as an immutable learning denominator")
    actions.add_parser("frontier-list", help="List saved exploration hypotheses; these are not validated opportunities")
    r = actions.add_parser("bootstrap", help="Make progress before any experiment result exists")
    r.add_argument("--id", help="Candidate id or key; omit for a learning-priority portfolio")
    r.add_argument("--limit", type=int, default=5)
    r.add_argument("--apply", action="store_true", help="Save the bootstrap and local desk-research tasks; no external action")
    s = sub.add_parser("operator", help="Personal founder fit, resources, WIP, experiment pipeline, KPI and CEO briefing")
    actions = s.add_subparsers(dest="action", required=True)
    r = actions.add_parser("template")
    r.add_argument("kind", choices=("profile", "fit", "pipeline", "kpi-plan", "kpi-snapshot", "checkin", "reopen-signal",
                                    "task", "task-result", "action", "action-transition"))
    for name in ("configure", "fit", "pipeline", "kpi-plan", "kpi-snapshot", "checkin", "reopen-signal"):
        r = actions.add_parser(name)
        r.add_argument("--file", required=True)
    for name in ("task", "task-result", "action", "action-transition"):
        r = actions.add_parser(name)
        r.add_argument("--file", required=True)
    actions.add_parser("status")
    actions.add_parser("plan")
    r = actions.add_parser("task-board")
    r.add_argument("--id")
    r = actions.add_parser("package", help="Create interview, MVP, pricing and GTM plan for a candidate")
    r.add_argument("--id", required=True)
    r.add_argument("--apply", action="store_true", help="Save local package and tasks; no external action")
    r = actions.add_parser("monthly")
    r.add_argument("--month")
    r = actions.add_parser("variance")
    r.add_argument("--week-start")
    for name in ("failures", "kpi-defaults", "overview"):
        actions.add_parser(name)
    r = actions.add_parser("reconcile", help="Preview local lifecycle changes; --apply writes only local state")
    r.add_argument("--apply", action="store_true")
    r = actions.add_parser("weekly", help="Generate weekly CEO brief and optionally apply local operating policy")
    r.add_argument("--week-start", help="KST Monday in YYYY-MM-DD; defaults to the current week")
    r.add_argument("--apply", action="store_true")
    s = sub.add_parser("signal", help="Review and import authorized SNS/industry source signals without direct API access")
    actions = s.add_subparsers(dest="action", required=True)
    actions.add_parser("template")
    actions.add_parser("capabilities")
    r = actions.add_parser("web-plan", help="Create a bounded public-web research plan that needs no API key")
    r.add_argument("--topic")
    r.add_argument("--lane", action="append", choices=tuple(no_api_research.LANES))
    r.add_argument("--limit", type=int, default=12)
    r.add_argument("--since-days", type=int, default=30)
    r = actions.add_parser("import")
    r.add_argument("--file", required=True)
    r = actions.add_parser("batch-import", help="Atomically save 1-50 actually reviewed public sources")
    r.add_argument("--file", required=True)
    s = sub.add_parser("refresh")
    s.add_argument("--topic", action="append")
    s.add_argument("--source", action="append")
    s.add_argument("--max-requests", type=int)
    s.add_argument("--sector-batch", type=int)
    s.add_argument("--force", action="store_true", help="Bypass freshness; use only for targeted diagnosis")
    s = sub.add_parser("list")
    s.add_argument("kind", choices=["evidence", "trend", "resolution", "opportunity", "blue_ocean", "blue_ocean_event", "dossier", "grant",
                                    "venture_review", "validation_plan", "validation_result", "research_run", "research_receipt", "application",
                                    "founder_profile", "founder_fit", "founder_pipeline", "founder_lifecycle",
                                    "founder_kpi_plan", "founder_kpi_snapshot", "founder_checkin", "founder_reopen_signal",
                                    "founder_task", "founder_task_result", "founder_action", "founder_action_event",
                                    "founder_execution_package", "blue_ocean_assessment", "blue_ocean_review_task"] + list(REQUIRED))
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
    r.add_argument("--trigger", choices=("manual",), default="manual", help="on-demand mode permits manual runs only")
    r.add_argument("--automation-id", help=argparse.SUPPRESS)
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
    for name in ("plan", "result", "qualitative-plan", "qualitative-result"):
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
