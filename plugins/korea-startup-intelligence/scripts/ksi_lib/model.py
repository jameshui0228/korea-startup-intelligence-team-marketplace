import hashlib
import html
import json
import math
import os
import re
import sqlite3
import tempfile
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
KST = timezone(timedelta(hours=9))
SECRETS = ("NAVER_HUB_CLIENT_ID", "NAVER_HUB_CLIENT_SECRET", "YOUTUBE_API_KEY", "BIZINFO_API_KEY",
           "KOSIS_API_KEY", "X_BEARER_TOKEN")


def now():
    return datetime.now(UTC)


def stamp(value=None):
    return (value or now()).astimezone(UTC).isoformat(timespec="seconds")


def parse_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(str(value))
        except (ValueError, TypeError, OverflowError):
            return None
    # Korean date-only / provider-local timestamps are interpreted in KST, never machine-local.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(UTC)


def clean(text, limit=500):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", str(text or "")))).strip()[:limit]


def canonical_url(value):
    parts = urlsplit(str(value))
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Evidence URLs must be public HTTP(S) URLs without credentials")
    pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        if re.search(r"(?i)token|secret|api.?key|crtfcKey|serviceKey|password|authorization", k):
            raise ValueError("Credential-like parameter in evidence URL")
        if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid"):
            pairs.append((k, v))
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", urlencode(sorted(pairs)), ""))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def atomic_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".ksi-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            out.write(value)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def assets(name):
    return json.loads((ROOT / "assets" / name).read_text())


def credentials(workspace):
    values = {key: os.environ[key] for key in SECRETS if os.environ.get(key)}
    # Explicit opt-in only. Never print keychain command output or create entries.
    if os.environ.get('KSI_USE_KEYCHAIN') == '1' and sys.platform == 'darwin':
        service = 'korea-startup-intelligence:' + str(Path(workspace).expanduser().resolve())
        for key in SECRETS:
            if key not in values:
                try:
                    result = subprocess.run(['/usr/bin/security', 'find-generic-password', '-s', service, '-a', key, '-w'],
                                            capture_output=True, text=True, timeout=5, check=False)
                    if result.returncode == 0 and result.stdout.strip():
                        values[key] = result.stdout.strip()
                except (OSError, subprocess.TimeoutExpired):
                    pass
    path = Path(workspace) / ".secrets.env"
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise ValueError(".secrets.env must be a regular private file (chmod 600); values were not read")
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, val = line.partition("=")
            if not sep or key not in SECRETS:
                raise ValueError("Invalid key in .secrets.env; values are never printed")
            val = val.strip().strip("\"'")
            if val and not val.startswith("YOUR_"):
                values.setdefault(key, val)
    return values


def observation(source, kind, topic, title, url, event_at=None, **extra):
    url = canonical_url(url)
    observed = stamp()
    parsed = parse_date(event_at)
    result = {"source": source, "kind": kind, "topic": clean(topic, 160), "title": clean(title, 240),
              "url": url, "event_at": stamp(parsed) if parsed else None, "observed_at": observed,
              "geography": "KR", "content_scope": "metadata_only", "metrics": {}, "series": [],
              "domain_ids": [], "publisher": urlsplit(url).hostname, "origin_key": url,
              "limitations": [], "expires_at": stamp(now() + timedelta(days=28))}
    result.update(extra)
    if parsed and parsed > now() + timedelta(days=1):
        result["limitations"].append("future_event_timestamp")
    result["id"] = "obs-" + digest([source, kind, result["topic"], url,
                                   observed[:10] if kind in ("series", "search_spike") else ""])[:24]
    result["content_hash"] = digest({k: v for k, v in result.items() if k not in ("observed_at", "expires_at")})
    return result


def normalize_title(value):
    value = re.sub(r"\[[^\]]*\]", "", clean(value)).split(" - ")[0]
    return re.sub(r"[^\w가-힣]", "", unicodedata.normalize("NFKC", value).lower())


DEFAULT_CONFIG = {"schema_version": 1, "workspace_profile_version": 6,
                  "timezone": "Asia/Seoul", "freshness_hours": 6,
                  "sector_batch": 8, "max_requests": 30, "timeout_seconds": 12,
                  "enabled_sources": ["github_new", "hackernews", "crossref_recent",
                                      "google_trends_rss", "google_news_rss"],
                  "watch_topics": [], "countries": ["KR"], "auto_update_code": False,
                  "kosis_series": [],
                  "product_focus": "blue_ocean_discovery_and_personal_founder_operations",
                  "signal_intake_lanes": ["jobs", "patents", "standards", "papers", "technology_cost",
                                          "procurement", "app_store", "commerce", "crowdfunding", "regulation",
                                          "kosis", "ecos", "instagram", "tiktok", "x", "threads", "reddit"],
                  "optional_modules": ["grants", "competitions", "team_workbench", "telegram"],
                  "global_queries": ["robotics", "healthcare", "agriculture", "education", "climate", "manufacturing", "mobility", "developer-tools"],
                  "retention_days": 28}


def migrate_config(path, config, *, persist=True):
    """Add safe product defaults without overwriting user configuration.

    The SQLite schema and the human-facing product profile evolve separately.
    Older workspaces therefore keep schema_version=1 while receiving newly
    introduced, non-secret defaults.  Existing lists and user choices always
    win; migrations never enable a source or external action.
    """
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValueError("Unsupported workspace schema")
    migrated = dict(config)
    for key, value in DEFAULT_CONFIG.items():
        if key not in migrated:
            # JSON round-trip provides an independent copy for mutable defaults.
            migrated[key] = json.loads(json.dumps(value, ensure_ascii=False))
    # Product focus is descriptive metadata, not a founder preference. Upgrade
    # only the exact prior default; preserve any custom value a user supplied.
    if migrated.get("product_focus") == "blue_ocean_discovery_and_venture_lifecycle":
        migrated["product_focus"] = DEFAULT_CONFIG["product_focus"]
    legacy_default_sources = ["github_new", "hackernews", "google_trends_rss", "google_news_rss"]
    if migrated.get("enabled_sources") == legacy_default_sources:
        migrated["enabled_sources"] = json.loads(json.dumps(DEFAULT_CONFIG["enabled_sources"]))
    migrated["workspace_profile_version"] = DEFAULT_CONFIG["workspace_profile_version"]
    if persist and migrated != config:
        atomic_json(path, migrated)
    return migrated


class Store:
    def __init__(self, workspace, *, read_only=False):
        self.workspace = Path(workspace).expanduser().resolve()
        config_path = self.workspace / "config.json"
        if not config_path.exists():
            raise ValueError("Workspace not initialized; run init first")
        self.config = migrate_config(config_path, json.loads(config_path.read_text()), persist=not read_only)
        db_path = self.workspace / "intelligence.sqlite3"
        self.db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True, timeout=10) if read_only else \
            sqlite3.connect(db_path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        if read_only:
            # Status/report commands must not migrate schemas or contend with
            # a long collection run for a write lock.
            self.db.execute("PRAGMA query_only=ON")
            return
        tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'records' in tables and 'metric_samples' not in tables:
            directory = self.workspace / 'backups'
            directory.mkdir(mode=0o700, exist_ok=True)
            fd, filename = tempfile.mkstemp(prefix='before-intraday-', suffix='.sqlite3', dir=directory)
            os.close(fd)
            destination = sqlite3.connect(filename)
            try:
                self.db.backup(destination)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('Migration backup integrity check failed; original schema unchanged')
            finally:
                destination.close()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, source TEXT, topic TEXT, kind TEXT,
          observed_at TEXT, expires_at TEXT, data TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS obs_topic ON observations(topic);
        CREATE TABLE IF NOT EXISTS fetches(id INTEGER PRIMARY KEY, source TEXT, query TEXT, attempted_at TEXT,
          status TEXT, item_count INTEGER, receipt TEXT);
        CREATE INDEX IF NOT EXISTS fetch_lookup ON fetches(source,query,attempted_at);
        CREATE TABLE IF NOT EXISTS coverage(domain_id TEXT PRIMARY KEY, attempts INTEGER DEFAULT 0,
          last_attempt TEXT, last_success TEXT, reviewed_at TEXT);
        CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, revision INTEGER, updated_at TEXT, data TEXT,
          PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS revisions(kind TEXT,id TEXT,revision INTEGER,updated_at TEXT,data TEXT,
          PRIMARY KEY(kind,id,revision));
        CREATE TABLE IF NOT EXISTS metric_snapshots(source TEXT,url TEXT,metric TEXT,day TEXT,value REAL,
          observed_at TEXT,expires_at TEXT,PRIMARY KEY(source,url,metric,day));
        CREATE TABLE IF NOT EXISTS metric_samples(source TEXT,url TEXT,metric TEXT,observed_at TEXT,value REAL,
          expires_at TEXT,PRIMARY KEY(source,url,metric,observed_at));
        """)
        # Preserve the available legacy observations without inventing intraday history.
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metric_samples SELECT source,url,metric,observed_at,value,expires_at FROM metric_snapshots")

    def close(self):
        self.db.close()

    def put_observation(self, row):
        for metric in ("stars_snapshot", "forks_snapshot", "points_snapshot", "comments_snapshot",
                       "views_play_start_20260824_snapshot", "likes_snapshot", "comment_count_snapshot"):
            value = row.get("metrics", {}).get(metric)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                day = parse_date(row["observed_at"]).astimezone(KST).date().isoformat()
                self.db.execute("INSERT OR REPLACE INTO metric_snapshots VALUES (?,?,?,?,?,?,?)",
                                (row["source"], row["url"], metric, day, value, row["observed_at"], row["expires_at"]))
                self.db.execute("INSERT OR IGNORE INTO metric_samples VALUES (?,?,?,?,?,?)",
                                (row["source"], row["url"], metric, row["observed_at"], value, row["expires_at"]))
        self.db.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?,?)",
                        (row["id"], row["source"], row["topic"], row["kind"], row["observed_at"], row["expires_at"],
                         json.dumps(row, ensure_ascii=False, allow_nan=False)))

    def observations(self, topic=None):
        query = "SELECT data FROM observations WHERE expires_at>?"
        args = [stamp()]
        if topic:
            query += " AND topic=?"
            args.append(topic)
        return [json.loads(r[0]) for r in self.db.execute(query, args)]

    def latest_fetch(self, source, query, success=False):
        sql = "SELECT * FROM fetches WHERE source=? AND query=?"
        if success:
            sql += " AND status='ok'"
        return self.db.execute(sql + " ORDER BY id DESC LIMIT 1", (source, query)).fetchone()

    def snapshot_changes(self):
        groups = {}
        for row in self.db.execute("SELECT * FROM metric_snapshots WHERE expires_at>? ORDER BY day", (stamp(),)):
            groups.setdefault((row["source"], row["url"], row["metric"]), []).append(dict(row))
        output = []
        for (source, url, metric), samples in groups.items():
            latest = samples[-1]
            prior = [s for s in samples[:-1] if (parse_date(latest["day"]) - parse_date(s["day"])).days >= 7]
            base = prior[-1] if prior else None
            change = None if not base or base["value"] < 10 else (latest["value"] / base["value"] - 1)
            output.append({"source": source, "url": url, "metric": metric, "snapshots": len(samples),
                           "status": "descriptive_change" if change is not None else "insufficient_history_or_low_base",
                           "from_date": base["day"] if base else None, "to_date": latest["day"],
                           "from_value": base["value"] if base else None, "to_value": latest["value"],
                           "change_ratio": change, "boundary": "Same object snapshot change; not user demand or representative platform growth"})
        return output

    def fetch_log(self, source, query, status, count, receipt):
        self.db.execute("INSERT INTO fetches(source,query,attempted_at,status,item_count,receipt) VALUES (?,?,?,?,?,?)",
                        (source, query, stamp(), status, count, json.dumps(receipt, ensure_ascii=False)))

    def checkout(self, kind, record_id):
        row = self.db.execute("SELECT revision,data FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        if not row:
            raise ValueError("Record not found")
        return {"kind": kind, "id": record_id, "expected_revision": row["revision"], "data": json.loads(row["data"])}

    def assert_revision(self, kind, record_id, expected_revision):
        row = self.db.execute("SELECT revision FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        current = row[0] if row else 0
        if type(expected_revision) is not int or expected_revision != current:
            raise ValueError(f"편집 충돌: {kind}/{record_id}, 현재 revision={current}. workbench checkout으로 최신 내용을 읽고 병합하세요.")

    def record(self, kind, data, expected_revision=None):
        # Reserve the writer before reading the revision. Otherwise two connections
        # can both validate the same revision before either performs its write.
        if not self.db.in_transaction:
            self.db.execute("BEGIN IMMEDIATE")
        if expected_revision is not None:
            self.assert_revision(kind, data["id"], expected_revision)
        previous = self.db.execute("SELECT revision,data FROM records WHERE kind=? AND id=?", (kind, data["id"])).fetchone()
        if previous and json.loads(previous["data"]) == data:
            return previous["revision"]
        revision = previous["revision"] + 1 if previous else 1
        values = (kind, data["id"], revision, stamp(), json.dumps(data, ensure_ascii=False, allow_nan=False))
        self.db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?,?)", values)
        self.db.execute("INSERT INTO revisions VALUES (?,?,?,?,?)", values)
        return revision

    def records(self, kind):
        return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM records WHERE kind=? ORDER BY updated_at DESC", (kind,))]

    def purge_expired(self):
        # Provider metadata isn't retained forever. User-owned reasoning and evaluation records remain.
        count = self.db.execute("DELETE FROM observations WHERE expires_at<=?", (stamp(),)).rowcount
        self.db.execute("DELETE FROM metric_snapshots WHERE expires_at<=?", (stamp(),))
        self.db.execute("DELETE FROM metric_samples WHERE expires_at<=?", (stamp(),))
        cutoff = stamp(now() - timedelta(days=28))
        self.db.execute("DELETE FROM records WHERE kind='trend' AND updated_at<?", (cutoff,))
        self.db.execute("DELETE FROM revisions WHERE kind='trend' AND updated_at<?", (cutoff,))
        self.db.commit()
        return count


def init_workspace(path):
    path = Path(path).expanduser().resolve()
    created = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    if created:
        path.chmod(0o700)
    if not (path / "config.json").exists():
        atomic_json(path / "config.json", DEFAULT_CONFIG)
    files = {
        "FOUNDER_CONTEXT.md": "# 창업자 컨텍스트\n\n시장: 대한민국\n단계: 블루오션 탐색\n지역: 미확인\n주간 가용 시간: 미확인\n주간 운영 예산: 미확인\n총 가용 현금: 미확인\n보호 예비금: 미확인\n역량/경험: 미확인\n접근 가능한 고객: 미확인\n제외 산업: 미확인\n위험 경계: 미확인\n\n개인 식별정보·주민번호·계좌·API 키를 쓰지 않는다.\n",
        "NEXT_ACTIONS.md": "# 다음 행동\n\n1. blue-ocean prepare로 기존 후보·근거 공백·덜 조사한 시장을 함께 확인한다.\n2. operator template profile로 실제 주간 시간·예산·보호 예비금·WIP 한도를 확인한다.\n3. 후보별 창업자 적합성과 interview→MVP→pricing→GTM 파이프라인을 연결한다.\n4. operator weekly로 집중 과제·KPI·보류/폐기/재개 결정을 검토한다.\n\n공모전·지원사업·협업·메시지 전달은 요청할 때만 선택적으로 사용한다. 고객 연락·비용 집행·신청은 별도 요청이 필요하다.\n",
        ".gitignore": ".secrets.env\n.telegram.env\n*.sqlite3*\nreports/\n*.private.*\n",
        ".secrets.env.example": "# 실제 키는 .secrets.env에 입력하고 chmod 600으로 제한. 채팅에 붙이지 않는다.\nNAVER_HUB_CLIENT_ID=\nNAVER_HUB_CLIENT_SECRET=\nYOUTUBE_API_KEY=\nBIZINFO_API_KEY=\nKOSIS_API_KEY=\n",
    }
    for name, content in files.items():
        if not (path / name).exists():
            atomic_text(path / name, content)
    store = Store(path)
    store.close()
    return str(path)


REQUIRED = {
    "claim": ("claim", "status", "evidence_ids", "assumptions", "next_test"),
    "problem": ("problem", "user", "industry", "frequency", "severity", "current_solution", "evidence_ids", "status"),
    "idea": ("idea", "problem", "target", "solution", "business_model", "domain_ids", "evidence_ids", "risk", "next_experiment", "status"),
    "experiment": ("hypothesis", "method", "success_criterion", "stop_criterion", "status", "evidence_ids"),
    "forecast": ("question", "probability", "deadline", "resolution_rule", "evidence_ids"),
    "feedback": ("subject_id", "outcome", "lesson", "evidence_ids"),
}


def validate_record(store, kind, data):
    if kind not in REQUIRED:
        raise ValueError("Unsupported record type")
    if not isinstance(data, dict) or any(k not in data for k in ("id",) + REQUIRED[kind]):
        raise ValueError("Missing fields: " + ", ".join(("id",) + REQUIRED[kind]))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(data["id"])):
        raise ValueError("Record id must contain letters, digits, hyphens or underscores")
    json.dumps(data, allow_nan=False)
    ids = data["evidence_ids"]
    if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
        raise ValueError("evidence_ids must be a list of observation ids")
    known = {r["id"] for r in store.observations()}
    if set(ids) - known:
        raise ValueError("Unknown or expired evidence ids; refresh or re-import evidence")
    if kind == "claim":
        if data["status"] not in ("FACT", "INFERENCE", "ASSUMPTION", "UNKNOWN"):
            raise ValueError("Invalid claim status")
        if data["status"] == "FACT" and (not ids or not data.get("verification_note")):
            raise ValueError("FACT requires evidence ids and an explicit source verification note")
    if kind == "idea":
        domains = {d["id"] for d in assets("taxonomy.json")["domains"]}
        if not isinstance(data["domain_ids"], list) or not data["domain_ids"] or set(data["domain_ids"]) - domains:
            raise ValueError("Use valid taxonomy IDs")
        if data["status"] not in ("hypothesis", "testing", "supported", "rejected", "parked"):
            raise ValueError("Invalid idea status")
        if data["status"] == "supported" and not ids:
            raise ValueError("Supported idea requires evidence, not a score")
        if data.get("score") is not None and (not ids or not data.get("score_rationale")):
            raise ValueError("Score requires evidence and criterion-level rationale; it is not a success probability")
    if kind == "forecast":
        p = data["probability"]
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError("Forecast probability must be between 0 and 1")
        deadline = parse_date(data["deadline"])
        if not deadline or deadline <= now():
            raise ValueError("A new forecast requires a future resolution deadline")
        if not str(data["resolution_rule"]).strip():
            raise ValueError("Define the measurable resolution rule first")
        if any(r["id"] == data["id"] for r in store.records("forecast")):
            raise ValueError("Forecasts are immutable; create a new forecast id")
        data["created_at"] = stamp()
        data["probability_type"] = "subjective_unvalidated"
    return data
