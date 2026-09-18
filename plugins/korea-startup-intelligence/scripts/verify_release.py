"""Verify package resources and secret separation without printing secret values."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from ksi_lib.model import ROOT, Store, assets, atomic_json, credentials, stamp
from ksi_lib.telegram import telegram_keys


def files(root):
    return [p for p in Path(root).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--installed", type=Path)
    args = p.parse_args()
    keys = credentials(args.workspace)
    keys.update(telegram_keys(args.workspace))
    values = [v.encode() for v in keys.values() if len(v) >= 8]
    roots = [ROOT] + ([args.installed] if args.installed else [])
    issues = []
    for root in roots:
        for path in files(root):
            if path.name in (".secrets.env", ".telegram.env") or path.suffix in (".sqlite3", ".db"):
                issues.append("state_or_secret_file_inside_plugin")
            if any(value in path.read_bytes() for value in values):
                issues.append("credential_value_inside_plugin")
    hashes_ok = all(hashlib.sha256((ROOT / "assets/user_inputs" / name).read_bytes()).hexdigest() == meta["sha256"]
                    for name, meta in assets("input_manifest.json").items())
    mismatches = []
    if args.installed:
        for path in files(ROOT):
            installed = args.installed / path.relative_to(ROOT)
            if not installed.is_file() or installed.read_bytes() != path.read_bytes():
                mismatches.append(str(path.relative_to(ROOT)))
    store = Store(args.workspace)
    try:
        counts = {r["source"]: r["n"] for r in store.db.execute("SELECT source,COUNT(*) n FROM observations GROUP BY source")}
        integrity = store.db.execute("PRAGMA integrity_check").fetchone()[0]
        result = {"checked_at": stamp(), "status": "pass" if hashes_ok and not issues and not mismatches and integrity == "ok" else "fail",
                  "input_hashes_match": hashes_ok, "package_credential_leaks": len(issues),
                  "source_installed_mismatches": mismatches, "sqlite_integrity": integrity,
                  "observations_by_source": counts, "naver_enabled": any(s.startswith("naver_") for s in store.config["enabled_sources"]),
                  "source_path": str(ROOT), "installed_path": str(args.installed) if args.installed else None,
                  "boundary": "Packaging, source parity and storage checks; not forecasting or business-outcome validation"}
        atomic_json(args.workspace / "reports/release-verification.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "pass" else 1
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
