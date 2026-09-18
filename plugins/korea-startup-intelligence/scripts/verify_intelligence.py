"""Offline selection smoke test on an isolated copy of real stored evidence."""
import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from ksi_lib import agenda, application, market, radar, research, validation, venture
from ksi_lib.model import Store, atomic_json, init_workspace, stamp


def verify(workspace):
    workspace = Path(workspace).expanduser().resolve()
    # No secrets or Telegram environment files are copied. Back up through SQLite
    # so an active writer/WAL cannot leave us with a torn data file.
    with tempfile.TemporaryDirectory(prefix="ksi-intelligence-check-") as temporary:
        isolated = Path(temporary) / "state"
        init_workspace(isolated)
        atomic_json(isolated / "config.json", json.loads((workspace / "config.json").read_text()))
        source = sqlite3.connect("file:" + quote(str(workspace / "intelligence.sqlite3"), safe="/") + "?mode=ro", uri=True)
        target = sqlite3.connect(str(isolated / "intelligence.sqlite3"))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        if (workspace / "radar.json").exists():
            cfg = json.loads((workspace / "radar.json").read_text())
            cfg["telegram_enabled"] = False
            atomic_json(isolated / "radar.json", cfg)
        store = Store(isolated)
        try:
            with patch.dict("os.environ", {}, clear=True), \
                    patch("ksi_lib.model.credentials", side_effect=AssertionError("Core work must not request API credentials")), \
                    patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Offline check forbids network")), \
                    patch("ksi_lib.telegram.api", side_effect=AssertionError("Offline check forbids Telegram")):
                radar.prepare(store, no_refresh=True)
                packet = json.loads((isolated / "reports/radar-packet.json").read_text())
                overview = market.overview(store, limit=400)
                plan = research.research_plan(store)
                drafts = [application.prepare(store, d["id"]) for d in store.records("dossier")]
                roundtrips = []
                for draft in drafts:
                    payload = draft["input_template"]
                    payload["key"] = "offline-check-" + payload["key"]
                    saved = application.save(store, payload)
                    resumed = application.resume(store, saved["id"])
                    checked = application.check(store, saved["id"])
                    if resumed["input_template"]["sections"] != payload["sections"] or checked["readiness"] != "working_draft":
                        raise AssertionError("Unreviewed research scaffold must be preserved and remain a working draft")
                    if any(c["checked"] for c in resumed["input_template"]["final_checks"].values()):
                        raise AssertionError("Offline verification must not fabricate manual approval")
                    roundtrips.append({"dossier_id": draft["source_dossier"]["id"], "status": "save_resume_check_pass",
                                       "readiness": checked["readiness"], "revision_task_count": len(checked["revision_tasks"]),
                                       "scope": "temporary_database_only_not_a_finished_document"})
                return {"checked_at": stamp(), "status": "pass", "scope": "offline_real_state_snapshot",
                        "network_calls": 0, "telegram_calls": 0, "source_workspace_modified_by_selection": False,
                        "pending_topic_count": packet["pending_topic_count"],
                        "selection_sources": packet["selection_sources"],
                        "topics": [{"topic": t["topic"], "selection_reason": t["selection_reason"],
                                    "sources": sorted({r["source"] for r in t["observations"]}),
                                    "domain_ids": sorted({d for r in t["observations"] for d in r.get("domain_ids", [])})}
                                   for t in packet["topics"]],
                        "venture_reviews": venture.status(store), "validation": validation.status(store),
                        "key_free_core": {"credentials_requested": False, "market_domains": overview["returned_domains"],
                            "market_status_counts": overview["matched_status_counts"],
                            "research_tasks": len(plan["tasks"]), "journal": agenda.status(store),
                            "application_scaffolds": [{"dossier_id": d["source_dossier"]["id"], "status": d["status"]} for d in drafts],
                            "application_roundtrips": roundtrips,
                            "completed_application_documents": 0},
                        "boundary": "Stored-source selection and integration only; not a live trend review or customer experiment"}
        finally:
            store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    receipt = verify(args.workspace)
    atomic_json(args.workspace / "reports/intelligence-verification.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
