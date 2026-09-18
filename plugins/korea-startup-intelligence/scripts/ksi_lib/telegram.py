"""One-way Telegram Bot API delivery with recipient binding and durable receipts.

No incoming messages are interpreted as instructions. Ambiguous deliveries never
auto-retry: Telegram sendMessage has no client-provided idempotency key.
"""
import json
import os
import re
import ssl
import stat
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path
from .model import ROOT, KST, atomic_json, atomic_text, clean, credentials, digest, now, parse_date, stamp
from .radar import ensure_radar, valid_reviews
from .research import opportunity_gate

KEYS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
CONNECTION_CHECK = "허구김 연결 확인\n\n확인하신 개인 대화로 알림을 보낼 수 있습니다. 이 메시지는 연결 시험이며 창업 아이디어나 트렌드 분석 결과가 아닙니다.\n\n30분 확인 주기에도 고객 문제·지불 근거·한국 대안·새 변화가 충분한 후보만 알립니다. 새로 보낼 만한 내용이 없으면 조용히 넘어갑니다. 선정·수상·예측 정확도를 보장하지 않습니다."
DELIVERY_CHECK = "허구김 자동화 전송 점검\n\n업그레이드한 발송 경로로 보낸 시험 메시지입니다. 창업 아이디어나 예약 실행 완료 알림은 아닙니다.\n\n설정한 30분 점검에서 의미 있는 새 근거가 있는 후보만 공유합니다. 전송 결과가 불명확하면 자동 재전송하지 않고 확인 대상으로 남깁니다."
SYSTEM_CARDS = ("connection-check", "delivery-check")


def package_version():
    return json.loads((ROOT / ".codex-plugin/plugin.json").read_text())["version"]


def ensure_private_message(store, message, keys=None):
    values = {**credentials(store.workspace), **(keys or telegram_keys(store.workspace))}
    if any(value in message for value in values.values() if len(value) >= 8):
        raise ValueError("Sensitive value detected in notification; content withheld")
    if not message.strip() or len(message.encode("utf-16-le")) // 2 > 4096:
        raise ValueError("Telegram message size is invalid")


def safe_error(code):
    known = {"network_outcome_unknown", "invalid_response", "redirect_refused", "invalid_token", "method_not_allowed"}
    return code if isinstance(code, str) and (code in known or re.fullmatch(r"http_[0-9]{3}", code)) else "delivery_outcome_unknown"


class TelegramError(Exception):
    def __init__(self, code, retry_after=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TelegramError("redirect_refused")


def init_telegram(store):
    ensure_radar(store)
    path = store.workspace / ".telegram.env"
    if not path.exists():
        atomic_text(path, "# BotFather 토큰은 이 비공개 로컬 파일에만 입력하세요. 채팅에 붙이지 마세요.\nTELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n")
        path.chmod(0o600)
    return {"config_file": str(path), "values_logged": False,
            "next_step": "Create a dedicated BotFather bot, start its private chat, and fill the token locally. Use telegram discover to identify the chat, then verify and explicitly enable the exact recipient."}


def telegram_keys(workspace):
    values = {key: os.environ[key] for key in KEYS if os.environ.get(key)}
    path = Path(workspace) / ".telegram.env"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_mode & 0o077:
            raise ValueError(".telegram.env must be a private regular file with chmod 600; values not read")
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep or key not in KEYS:
                raise ValueError("Invalid .telegram.env key; values are not printed")
            value = value.strip().strip("\"'")
            if value:
                values.setdefault(key, value)
    token = values.get("TELEGRAM_BOT_TOKEN")
    chat = values.get("TELEGRAM_CHAT_ID")
    if token and not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}", token):
        raise ValueError("Invalid Telegram bot token format; check the private file")
    # Numeric IDs pin a recipient; mutable @usernames aren't accepted for delivery.
    if chat and not re.fullmatch(r"-?[1-9][0-9]{0,19}", chat):
        raise ValueError("TELEGRAM_CHAT_ID must be an exact numeric chat ID")
    return values


def fingerprint(keys):
    if not all(keys.get(k) for k in KEYS):
        return None
    return digest([keys[k] for k in KEYS])


def api(token, method, payload=None):
    if method not in ("getMe", "getChat", "getUpdates", "sendMessage"):
        raise TelegramError("method_not_allowed")
    if not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}", token):
        raise TelegramError("invalid_token")
    request = urllib.request.Request("https://api.telegram.org/bot" + token + "/" + method,
                                     data=json.dumps(payload or {}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "KoreaStartupIntelligence/0.1"})
    paths = ssl.get_default_verify_paths()
    bundle = Path("/etc/ssl/cert.pem")
    context = ssl.create_default_context(cafile=str(bundle) if not paths.cafile and bundle.is_file() else None)
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=context))
    try:
        try:
            with opener.open(request, timeout=12) as response:
                raw = response.read(500001)
        except urllib.error.HTTPError as error:
            # Raw error body and the auth-bearing URL are never logged.
            retry = None
            if error.code == 429:
                try:
                    body = json.loads(error.read(10000))
                    parameters = body.get("parameters") if isinstance(body, dict) else None
                    candidate = parameters.get("retry_after") if isinstance(parameters, dict) else None
                    if type(candidate) is int and candidate > 0:
                        retry = candidate
                except (ValueError, OSError):
                    pass
            raise TelegramError("http_" + str(error.code), retry) from None
        if len(raw) > 500000:
            raise TelegramError("invalid_response")
        body = json.loads(raw)
        if not isinstance(body, dict) or body.get("ok") is not True:
            code = body.get("error_code") if isinstance(body, dict) else None
            parameters = body.get("parameters") if isinstance(body, dict) else None
            retry = parameters.get("retry_after") if isinstance(parameters, dict) else None
            raise TelegramError("http_" + str(code) if type(code) is int else "invalid_response",
                                retry if type(retry) is int and retry > 0 else None)
        return body.get("result")
    except TelegramError:
        raise
    except (urllib.error.URLError, OSError, TimeoutError):
        raise TelegramError("network_outcome_unknown") from None
    except (ValueError, TypeError, KeyError):
        raise TelegramError("invalid_response") from None


def discover(store):
    keys = telegram_keys(store.workspace)
    if not keys.get("TELEGRAM_BOT_TOKEN"):
        return {"status": "token_missing", "values_logged": False}
    # No offset means this read does not acknowledge/drop other pending updates.
    # Do not change webhook or allowed_updates settings on the user's bot.
    result = api(keys["TELEGRAM_BOT_TOKEN"], "getUpdates", {"limit": 20, "timeout": 0})
    if not isinstance(result, list):
        raise TelegramError("invalid_response")
    chats = {}
    for update in result:
        if not isinstance(update, dict):
            raise TelegramError("invalid_response")
        for field in ("message", "channel_post", "my_chat_member"):
            message = update.get(field, {})
            chat = message.get("chat", {}) if isinstance(message, dict) else {}
            if not isinstance(chat, dict):
                raise TelegramError("invalid_response")
            if type(chat.get("id")) is int:
                chats[chat["id"]] = {"chat_id": str(chat["id"]), "type": chat.get("type"),
                                     "display_name": clean(chat.get("title") or chat.get("first_name"), 80)}
    return {"status": "choose_exact_recipient" if chats else "start_bot_private_chat_then_retry",
            "chats": list(chats.values()), "message_bodies_logged": False, "destination_selected": False}


def verify(store):
    cfg = ensure_radar(store)
    keys = telegram_keys(store.workspace)
    if not fingerprint(keys):
        return {"status": "credentials_missing", "missing_keys": [k for k in KEYS if not keys.get(k)]}
    me = api(keys["TELEGRAM_BOT_TOKEN"], "getMe")
    chat = api(keys["TELEGRAM_BOT_TOKEN"], "getChat", {"chat_id": keys["TELEGRAM_CHAT_ID"]})
    if not isinstance(me, dict) or me.get("is_bot") is not True or type(me.get("id")) is not int:
        raise TelegramError("invalid_bot_identity")
    if not isinstance(chat, dict) or str(chat.get("id")) != keys["TELEGRAM_CHAT_ID"] or chat.get("type") not in ("private", "channel"):
        raise TelegramError("recipient_mismatch_or_unsupported_type")
    with store.db:
        store.db.execute("INSERT OR REPLACE INTO telegram_binding VALUES (1,?,?,?,?,NULL)",
                         (fingerprint(keys), me["id"], chat["type"], stamp()))
    cfg["telegram_enabled"] = False
    atomic_json(store.workspace / "radar.json", cfg)
    return {"status": "identity_verified_not_delivery_tested", "bot_username": clean(me.get("username"), 80),
            "chat_type": chat["type"], "chat_id": keys["TELEGRAM_CHAT_ID"],
            "display_name": clean(chat.get("title") or chat.get("first_name"), 80), "message_sent": False}


def enable(store, confirm_chat_id):
    cfg = ensure_radar(store)
    keys = telegram_keys(store.workspace)
    binding = store.db.execute("SELECT * FROM telegram_binding WHERE id=1").fetchone()
    if not binding or binding["fingerprint"] != fingerprint(keys) or binding["blocked_reason"]:
        raise ValueError("Verify the current bot and exact chat before enabling delivery")
    if str(confirm_chat_id) != keys.get("TELEGRAM_CHAT_ID"):
        raise ValueError("Explicit confirmation must match the verified chat ID")
    if parse_date(binding["verified_at"]) < now() - timedelta(hours=24):
        raise ValueError("Recipient verification is too old; verify again")
    cfg["telegram_enabled"] = True
    atomic_json(store.workspace / "radar.json", cfg)
    return {"status": "enabled", "chat_type": binding["chat_type"], "message_sent": False}


def disable(store):
    cfg = ensure_radar(store)
    cfg["telegram_enabled"] = False
    atomic_json(store.workspace / "radar.json", cfg)
    return {"status": "disabled"}


def clip(value, units):
    # Conservative UTF-16 budgeting also handles astral Unicode/emoji correctly.
    encoded = str(value).encode("utf-16-le")
    return str(value) if len(encoded) <= units * 2 else encoded[:max(0, units - 1) * 2].decode("utf-16-le", errors="ignore") + "…"


def render_message(card):
    experiment = card["next_experiment"]
    confidence = {"limited": "제한적", "medium": "중간", "high": "높음"}[card["confidence"]]
    parts = ["[창업 가설 · 시장 검증 전] " + clip(clean(card["title"]), 120),
             f"{card['stage']} / 근거 신뢰도: {confidence}",
             "새 변화: " + clip(clean(card["change"]["reason"]), 180),
             "누구의 문제: " + clip(clean(card["target"] + " — " + card["problem"]), 260),
             "지불자: " + clip(clean(card["payer"]), 120),
             "제안: " + clip(clean(card["solution"]), 260),
             "한국의 공백(검증 필요): " + clip(clean(card["korea_gap"]), 190),
             "수익모델 가설: " + clip(clean(card["monetization"]), 150),
             "MVP: " + clip(clean(card["mvp"]), 180),
             "작은 실험: " + clip(clean(experiment["method"]), 200),
             "통과/중단: " + clip(clean(experiment["pass_condition"] + " / " + experiment["stop_condition"]), 180),
             "반례·위험: " + clip(clean(" / ".join(card["contrarian"][:2])), 220),
             "미확인: " + clip(clean(" / ".join(card["unknowns"][:3])), 200),
             "출처 (발견 근거이며 수요·매출의 증명은 아님):"]
    # A card is a single atomic API message: no partial multi-message retries.
    remaining = 3900 - len("\n\n".join(parts).encode("utf-16-le")) // 2 - 150
    urls = [u for u in card["evidence_urls"] if len(u.encode("utf-16-le")) // 2 <= 600][:3]
    for url in urls:
        if len(url) + 2 <= remaining:
            parts.append(url)
            remaining -= len(url.encode("utf-16-le")) // 2 + 2
    reviewed = parse_date(card["reviewed_at"]).astimezone(KST).strftime("%Y-%m-%d %H:%M KST")
    parts += ["상세 카드: " + card["id"], "검토 시각: " + reviewed]
    message = "\n\n".join(parts)
    if len(message.encode("utf-16-le")) // 2 > 4096:
        raise ValueError("Telegram message exceeded safe size")
    return message


def enqueue(store):
    cfg = ensure_radar(store)
    keys = telegram_keys(store.workspace)
    dest = fingerprint(keys)
    binding = store.db.execute("SELECT * FROM telegram_binding WHERE id=1").fetchone()
    if not cfg["telegram_enabled"] or not binding or not dest or binding["fingerprint"] != dest or binding["blocked_reason"]:
        return {"status": "delivery_not_enabled_or_verified", "queued": 0}
    count, skipped = 0, {}
    for row in store.db.execute("SELECT * FROM records WHERE kind='opportunity' ORDER BY updated_at DESC").fetchall():
        card = json.loads(row["data"])
        gate = opportunity_gate(store, card)
        if not gate["eligible"]:
            for reason in gate["reasons"]:
                skipped[reason] = skipped.get(reason, 0) + 1
            continue
        if not parse_date(card.get("reviewed_at")) or parse_date(card["reviewed_at"]) < now() - timedelta(hours=cfg["telegram_card_max_age_hours"]):
            skipped["card_expired"] = skipped.get("card_expired", 0) + 1
            continue
        try:
            valid_reviews(store, card["evidence_ids"])
        except ValueError:
            skipped["stale_evidence"] = skipped.get("stale_evidence", 0) + 1
            continue
        message = render_message(card)
        ensure_private_message(store, message, keys)
        # Never send a renamed/revised version while this idea's delivery is unresolved.
        if store.db.execute("SELECT 1 FROM telegram_outbox WHERE card_id=? AND status IN ('uncertain','sending')", (card["id"],)).fetchone():
            skipped["prior_delivery_unresolved"] = skipped.get("prior_delivery_unresolved", 0) + 1
            continue
        # Does not change on destination rotation: old delivered ideas are not broadcast anew.
        oid = "alert-" + digest([card["id"], row["revision"]])[:24]
        with store.db:
            store.db.execute("UPDATE telegram_outbox SET status='superseded' WHERE card_id=? AND card_revision<? AND status='pending'",
                             (card["id"], row["revision"]))
            count += store.db.execute("INSERT OR IGNORE INTO telegram_outbox(id,card_id,card_revision,created_at,status,destination,message,evidence_ids) VALUES (?,?,?,?,'pending',?,?,?)",
                                      (oid, card["id"], row["revision"], stamp(), dest, message, json.dumps(card["evidence_ids"]))).rowcount
    return {"status": "queued", "queued": count, "skipped_reasons": skipped}


def blue_ocean_gate(store, candidate):
    """Never alert on an unverified whitespace or a mere attention spike."""
    from . import blue_ocean
    assessment = blue_ocean.assess(store, candidate)
    if candidate.get("stage") not in blue_ocean.ACTIVE_STAGES or assessment["whitespace_state"] != "investigated":
        return False
    if assessment["blocking_gaps"] or not {"problem", "current_spend", "supply_gap", "switching_reason"} <= set(assessment["evidence_backed_assessments"]):
        return False
    if not parse_date(candidate.get("updated_at")) or parse_date(candidate["updated_at"]) < now() - timedelta(hours=24):
        return False
    try:
        valid_reviews(store, candidate["evidence_ids"])
    except ValueError:
        return False
    return True


def render_blue_ocean_message(store, candidate):
    assessment = candidate["assessments"]
    observations = {row["id"]: row for row in store.observations()}
    urls = list(dict.fromkeys(observations[eid]["url"] for eid in candidate["evidence_ids"] if eid in observations))[:3]
    parts = ["허구김 · 블루오션 후보 판단 변화", candidate["title"],
             "고객: " + clean(candidate["customer"], 170),
             "반복 문제: " + clean(candidate["problem"], 260),
             "현재 행동·지출: " + clean(assessment["current_spend"]["conclusion"], 260),
             "한국 대안·공백: " + clean(assessment["supply_gap"]["conclusion"], 260),
             "전환 이유: " + clean(assessment["switching_reason"]["conclusion"], 240),
             "지불자: " + clean(candidate["payer"], 160),
             "다음 검증: " + clean((candidate.get("next_action") or {}).get("action"), 220),
             "근거: " + " / ".join(urls),
             "판단: 조사된 가설. 경쟁 부재·사업 성공·미래 유행을 증명하지 않습니다."]
    message = "\n\n".join(parts)
    if len(message.encode("utf-16-le")) // 2 > 4096:
        raise ValueError("Blue-ocean alert too long")
    return message


def enqueue_blue_ocean_changes(store, changes):
    cfg = ensure_radar(store)
    keys = telegram_keys(store.workspace)
    dest = fingerprint(keys)
    binding = store.db.execute("SELECT * FROM telegram_binding WHERE id=1").fetchone()
    if not cfg["telegram_enabled"] or not binding or not dest or binding["fingerprint"] != dest or binding["blocked_reason"]:
        return {"status": "delivery_not_enabled_or_verified", "queued": 0}
    meaningful = set()
    for item in changes.get("added", []):
        meaningful.add(item["candidate_id"])
    for item in changes.get("changed", []):
        if set(item["changed_fields"]) & {"stage", "whitespace_state", "saturation_status", "blocking_gaps", "evidence_ids", "recommended_transition"}:
            meaningful.add(item["candidate_id"])
    count = 0
    for candidate in store.records("blue_ocean"):
        if candidate["id"] not in meaningful or not blue_ocean_gate(store, candidate):
            continue
        if candidate.get("source_opportunity_id") and store.db.execute(
                "SELECT 1 FROM telegram_outbox WHERE card_id=? AND status IN ('pending','sending','uncertain','sent')",
                (candidate["source_opportunity_id"],)).fetchone():
            continue
        card_id = "blue-ocean-change:" + candidate["id"]
        if store.db.execute("SELECT 1 FROM telegram_outbox WHERE card_id=? AND status IN ('sending','uncertain')", (card_id,)).fetchone():
            continue
        record = store.db.execute("SELECT revision FROM records WHERE kind='blue_ocean' AND id=?", (candidate["id"],)).fetchone()
        revision = record["revision"]
        message = render_blue_ocean_message(store, candidate)
        ensure_private_message(store, message, keys)
        alert_id = "alert-" + digest([card_id, revision])[:24]
        with store.db:
            store.db.execute("UPDATE telegram_outbox SET status='superseded' WHERE card_id=? AND card_revision<? AND status='pending'",
                             (card_id, revision))
            count += store.db.execute(
                "INSERT OR IGNORE INTO telegram_outbox(id,card_id,card_revision,created_at,status,destination,message,evidence_ids) VALUES (?,?,?,?,'pending',?,?,?)",
                (alert_id, card_id, revision, stamp(), dest, message, json.dumps(candidate["evidence_ids"]))).rowcount
    return {"status": "queued", "queued": count, "meaningful_candidate_count": len(meaningful)}


def enqueue_connection_check(store, confirm_chat_id):
    """Explicit, fixed-content connectivity test; never an arbitrary-message escape."""
    cfg = ensure_radar(store)
    keys = telegram_keys(store.workspace)
    dest = fingerprint(keys)
    binding = store.db.execute("SELECT * FROM telegram_binding WHERE id=1").fetchone()
    if not cfg["telegram_enabled"] or not binding or not dest or binding["fingerprint"] != dest or binding["blocked_reason"]:
        raise ValueError("Enable the verified recipient before queuing a connection check")
    if confirm_chat_id != keys.get("TELEGRAM_CHAT_ID"):
        raise ValueError("Explicit matching recipient confirmation required")
    oid = "connection-" + dest[:24]
    with store.db:
        count = store.db.execute("INSERT OR IGNORE INTO telegram_outbox(id,card_id,card_revision,created_at,status,destination,message,evidence_ids) VALUES (?,'connection-check',0,?,'pending',?,?,'[]')",
                                 (oid, stamp(), dest, CONNECTION_CHECK)).rowcount
    return {"status": "queued" if count else "already_recorded", "queued": count,
            "message_sent": False, "boundary": "One fixed connection check per bot/recipient binding, not an idea alert"}


def enqueue_self_test(store):
    """Manual release verification, fixed text once per installed version/binding."""
    cfg = ensure_radar(store)
    keys = telegram_keys(store.workspace)
    dest = fingerprint(keys)
    binding = store.db.execute("SELECT * FROM telegram_binding WHERE id=1").fetchone()
    if not cfg["telegram_enabled"] or not dest or not binding or binding["fingerprint"] != dest or binding["blocked_reason"]:
        raise ValueError("Self-test requires the already enabled exact recipient")
    version = package_version()
    oid = "check-" + digest([dest, version])[:24]
    with store.db:
        count = store.db.execute("INSERT OR IGNORE INTO telegram_outbox(id,card_id,card_revision,created_at,status,destination,message,evidence_ids) VALUES (?,'delivery-check',0,?,'pending',?,?,?)",
                                 (oid, stamp(), dest, DELIVERY_CHECK, json.dumps([version]))).rowcount
    return {"status": "queued" if count else "already_recorded", "queued": count, "alert_id": oid,
            "message_sent": False, "boundary": "Manual fixed-text check; never called by scheduled research"}


def reconcile_outbox(store, cfg, dest):
    # The CLI owns the exclusive workspace lock, so 'sending' here is an
    # interrupted earlier process, never a concurrently running send.
    with store.db:
        store.db.execute("UPDATE telegram_attempts SET outcome='uncertain',finished_at=?,error='interrupted_delivery_check_chat_manually' WHERE outcome='sending'", (stamp(),))
        store.db.execute("UPDATE telegram_outbox SET status='uncertain',error='interrupted_delivery_check_chat_manually' WHERE status='sending'")
        store.db.execute("UPDATE telegram_outbox SET status='expired' WHERE status='pending' AND created_at<?",
                         (stamp(now() - timedelta(hours=cfg["telegram_card_max_age_hours"])),))
        if dest:
            store.db.execute("UPDATE telegram_outbox SET status='destination_changed' WHERE status='pending' AND destination<>?", (dest,))


def delivery_window(store, cfg, dest):
    current = now().astimezone(KST)
    quiet = cfg["quiet_hours_kst"]
    if quiet and (quiet[0] <= current.hour < quiet[1] if quiet[0] < quiet[1] else current.hour >= quiet[0] or current.hour < quiet[1]):
        end = current.replace(hour=quiet[1], minute=0, second=0, microsecond=0)
        if end <= current:
            end += timedelta(days=1)
        return {"reason": "quiet_hours", "next_allowed_at": stamp(end)}
    day_start = stamp(current.replace(hour=0, minute=0, second=0, microsecond=0))
    # Legacy rows are included until an attempt ledger exists. Confirming an
    # uncertain send manually never erases the attempt or bypasses the caps.
    counts = store.db.execute("SELECT COUNT(*) FROM telegram_attempts WHERE destination=? AND started_at>=? AND outcome IN ('sent','uncertain','sending','confirmed_delivered')", (dest, day_start)).fetchone()[0]
    counts += store.db.execute("SELECT COUNT(*) FROM telegram_outbox o WHERE destination=? AND attempts>0 AND status IN ('sent','uncertain','sending','confirmed_delivered') AND COALESCE(sent_at,next_attempt_at,created_at)>=? AND NOT EXISTS(SELECT 1 FROM telegram_attempts a WHERE a.alert_id=o.id)", (dest, day_start)).fetchone()[0]
    if counts >= cfg["telegram_daily_limit"]:
        return {"reason": "daily_limit", "next_allowed_at": stamp(current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))}
    last = store.db.execute("SELECT MAX(at) FROM (SELECT started_at AS at FROM telegram_attempts WHERE destination=? AND outcome IN ('sent','uncertain','sending','confirmed_delivered') UNION ALL SELECT COALESCE(sent_at,next_attempt_at,created_at) FROM telegram_outbox o WHERE destination=? AND attempts>0 AND status IN ('sent','uncertain','sending','confirmed_delivered') AND NOT EXISTS(SELECT 1 FROM telegram_attempts a WHERE a.alert_id=o.id))", (dest, dest)).fetchone()[0]
    gates = []
    if last:
        gates.append((parse_date(last) + timedelta(minutes=cfg["telegram_min_interval_minutes"]), "cooldown"))
    retry = store.db.execute("SELECT MAX(next_attempt_at) FROM telegram_outbox WHERE destination=? AND error='http_429'", (dest,)).fetchone()[0]
    if retry:
        gates.append((parse_date(retry), "rate_limit_backoff"))
    gates = [(date, reason) for date, reason in gates if date > now()]
    if gates:
        date, reason = max(gates)
        return {"reason": reason, "next_allowed_at": stamp(date)}
    return {"reason": None, "next_allowed_at": None}


def validate_pending(store, row, cfg, keys):
    dest = fingerprint(keys)
    if row["destination"] != dest:
        return "destination_changed"
    if parse_date(row["created_at"]) < now() - timedelta(hours=cfg["telegram_card_max_age_hours"]):
        return "expired"
    if row["card_id"] in SYSTEM_CARDS:
        if row["card_id"] == "connection-check":
            expected_id, expected_text, expected_evidence = "connection-" + dest[:24], CONNECTION_CHECK, "[]"
        else:
            version = package_version()
            expected_id, expected_text, expected_evidence = "check-" + digest([dest, version])[:24], DELIVERY_CHECK, json.dumps([version])
        if (row["id"], row["message"], row["card_revision"], row["evidence_ids"]) != (expected_id, expected_text, 0, expected_evidence):
            return "quality_blocked"
    elif row["card_id"].startswith("blue-ocean-change:"):
        candidate_id = row["card_id"].removeprefix("blue-ocean-change:")
        record = store.db.execute("SELECT revision,data FROM records WHERE kind='blue_ocean' AND id=?", (candidate_id,)).fetchone()
        if not record or record["revision"] != row["card_revision"]:
            return "superseded"
        candidate = json.loads(record["data"])
        if not blue_ocean_gate(store, candidate):
            return "quality_blocked"
        if json.loads(row["evidence_ids"]) != candidate["evidence_ids"] or row["message"] != render_blue_ocean_message(store, candidate):
            return "quality_blocked"
        if store.db.execute("SELECT 1 FROM telegram_outbox WHERE card_id=? AND id<>? AND status IN ('uncertain','sending')", (row["card_id"], row["id"])).fetchone():
            return "prior_delivery_unresolved"
    else:
        record = store.db.execute("SELECT revision,data FROM records WHERE kind='opportunity' AND id=?", (row["card_id"],)).fetchone()
        if not record or record["revision"] != row["card_revision"]:
            return "superseded"
        card = json.loads(record["data"])
        if not parse_date(card.get("reviewed_at")) or parse_date(card["reviewed_at"]) < now() - timedelta(hours=cfg["telegram_card_max_age_hours"]):
            return "expired"
        try:
            evidence_ids = json.loads(row["evidence_ids"])
            if evidence_ids != card["evidence_ids"] or row["message"] != render_message(card):
                return "quality_blocked"
            valid_reviews(store, evidence_ids)
        except (ValueError, KeyError, TypeError):
            return "stale_evidence"
        if not opportunity_gate(store, card)["eligible"]:
            return "quality_blocked"
        if store.db.execute("SELECT 1 FROM telegram_outbox WHERE card_id=? AND id<>? AND status IN ('uncertain','sending')", (row["card_id"], row["id"])).fetchone():
            return "prior_delivery_unresolved"
    ensure_private_message(store, row["message"], keys)
    return None


def deliver(store, send=False, transport=None, cycle_id=None):
    cfg = ensure_radar(store)
    transport = transport or api
    keys = telegram_keys(store.workspace)
    if not send:
        messages, blocked = [], []
        for row in store.db.execute("SELECT * FROM telegram_outbox WHERE status='pending' ORDER BY created_at,id LIMIT 50"):
            try:
                reason = validate_pending(store, row, cfg, keys)
            except ValueError:
                reason = "sensitive_or_invalid_content"
            if reason:
                blocked.append({"id": row["id"], "reason": reason})
            elif len(messages) < 3:
                messages.append({"id": row["id"], "text": row["message"], "message_hash": digest(row["message"])})
        return {"status": "dry_run", "messages": messages, "blocked": blocked, "network_calls": 0}
    dest = fingerprint(keys)
    binding = store.db.execute("SELECT * FROM telegram_binding WHERE id=1").fetchone()
    if not cfg["telegram_enabled"] or not binding or not dest or binding["fingerprint"] != dest or binding["blocked_reason"]:
        return {"status": "blocked_not_enabled_or_verified", "sent": 0}
    reconcile_outbox(store, cfg, dest)
    if cycle_id:
        if not store.db.execute("SELECT 1 FROM radar_runs WHERE packet_id=?", (cycle_id,)).fetchone():
            raise ValueError("Delivery cycle must refer to an existing research run")
        previous = store.db.execute("SELECT * FROM telegram_attempts WHERE cycle_id=? ORDER BY attempt_no DESC LIMIT 1", (cycle_id,)).fetchone()
        if previous:
            return {"status": previous["outcome"], "sent": int(previous["outcome"] == "sent"),
                    "alert_id": previous["alert_id"], "message_id": previous["message_id"],
                    "replayed_attempt_receipt": True, "network_calls_this_call": 0,
                    "manual_check_required": previous["outcome"] in ("uncertain", "blocked")}
    window = delivery_window(store, cfg, dest)
    if window["reason"]:
        return {"status": window["reason"], "sent": 0, "next_allowed_at": window["next_allowed_at"]}
    row, skipped = None, []
    for candidate in store.db.execute("SELECT * FROM telegram_outbox WHERE status='pending' AND destination=? AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY created_at,id LIMIT 50", (dest, stamp())).fetchall():
        try:
            reason = validate_pending(store, candidate, cfg, keys)
        except ValueError:
            reason = "sensitive_or_invalid_content"
        if not reason:
            row = candidate
            break
        with store.db:
            store.db.execute("UPDATE telegram_outbox SET status=? WHERE id=?", (reason, candidate["id"]))
        skipped.append({"id": candidate["id"], "reason": reason})
    if row is None:
        return {"status": skipped[-1]["reason"] if skipped else "nothing_to_send", "sent": 0, "skipped": skipped}
    attempt_no = row["attempts"] + 1
    with store.db:
        claimed = store.db.execute("UPDATE telegram_outbox SET status='sending',attempts=attempts+1,next_attempt_at=? WHERE id=? AND status='pending'", (stamp(), row["id"])).rowcount
        if not claimed:
            return {"status": "already_claimed", "sent": 0}
        store.db.execute("INSERT INTO telegram_attempts(alert_id,attempt_no,destination,started_at,outcome,message_hash,cycle_id) VALUES (?,?,?,?,'sending',?,?)",
                         (row["id"], attempt_no, dest, stamp(), digest(row["message"]), cycle_id))
    try:
        result = transport(keys["TELEGRAM_BOT_TOKEN"], "sendMessage",
                           {"chat_id": keys["TELEGRAM_CHAT_ID"], "text": row["message"],
                            "link_preview_options": {"is_disabled": True}, "protect_content": True})
        if (not isinstance(result, dict) or type(result.get("message_id")) is not int or result["message_id"] <= 0
                or not isinstance(result.get("chat"), dict) or str(result["chat"].get("id")) != keys["TELEGRAM_CHAT_ID"]
                or ("text" in result and result["text"] != row["message"])):
            raise TelegramError("invalid_response")
        with store.db:
            store.db.execute("UPDATE telegram_outbox SET status='sent',sent_at=?,message_id=?,error=NULL WHERE id=?",
                             (stamp(), result["message_id"], row["id"]))
            store.db.execute("UPDATE telegram_attempts SET outcome='sent',finished_at=?,message_id=? WHERE alert_id=? AND attempt_no=?",
                             (stamp(), result["message_id"], row["id"], attempt_no))
        return {"status": "sent", "sent": 1, "alert_id": row["id"], "message_id": result["message_id"], "skipped": skipped}
    except Exception as exc:
        code = safe_error(exc.code) if isinstance(exc, TelegramError) else "delivery_outcome_unknown"
        retry_at = None
        if code == "http_429":
            delivery_status = "pending"
            delay = exc.retry_after if type(exc.retry_after) is int and exc.retry_after > 0 else 60
            try:
                retry_at = stamp(now() + timedelta(seconds=delay))
            except OverflowError:
                # Do not shorten a server's wait time to fit a local cap.
                delivery_status, code = "blocked", "unrepresentable_retry_after"
        elif code in ("http_401", "http_403"):
            delivery_status = "blocked"
        elif code == "http_400":
            delivery_status = "failed"
        else:
            delivery_status = "uncertain"
        with store.db:
            store.db.execute("UPDATE telegram_outbox SET status=?,error=?,next_attempt_at=? WHERE id=?",
                             (delivery_status, code, retry_at or stamp(), row["id"]))
            store.db.execute("UPDATE telegram_attempts SET outcome=?,finished_at=?,error=?,retry_at=? WHERE alert_id=? AND attempt_no=?",
                             (delivery_status, stamp(), code, retry_at, row["id"], attempt_no))
            if delivery_status == "blocked":
                store.db.execute("UPDATE telegram_binding SET blocked_reason=? WHERE id=1", (code,))
        return {"status": delivery_status, "error": code, "sent": 0, "alert_id": row["id"],
                "retry_after_at": retry_at, "manual_check_required": delivery_status in ("uncertain", "blocked")}


def resolve_delivery(store, alert_id, outcome, confirm_chat_id, note, retry=False, message_id=None):
    """A user's observation of their chat, never an automatic retry decision."""
    ensure_radar(store)
    keys = telegram_keys(store.workspace)
    if str(confirm_chat_id) != keys.get("TELEGRAM_CHAT_ID") or not fingerprint(keys):
        raise ValueError("Recovery requires explicit confirmation of the current exact recipient")
    if outcome not in ("delivered", "not_delivered", "discard") or (retry and outcome != "not_delivered"):
        raise ValueError("Retry requires an explicit not_delivered observation")
    if not isinstance(note, str) or not 1 <= len(note.strip()) <= 1200:
        raise ValueError("Record a concise manual observation; no secrets")
    ensure_private_message(store, note, keys)
    if message_id is not None and (type(message_id) is not int or message_id <= 0 or outcome != "delivered"):
        raise ValueError("Message ID must be positive and only belongs to delivered recovery")
    row = store.db.execute("SELECT * FROM telegram_outbox WHERE id=?", (alert_id,)).fetchone()
    if not row or row["status"] != "uncertain" or row["destination"] != fingerprint(keys):
        raise ValueError("Only an unresolved uncertain delivery to this binding can be recovered")
    result_status = {"delivered": "confirmed_delivered", "not_delivered": "pending" if retry else "confirmed_not_delivered", "discard": "cancelled"}[outcome]
    with store.db:
        if not store.db.execute("SELECT 1 FROM telegram_attempts WHERE alert_id=?", (alert_id,)).fetchone():
            # Preserve the last known legacy attempt before changing its row.
            # Earlier individual attempts cannot be reconstructed from a count.
            store.db.execute("INSERT INTO telegram_attempts(alert_id,attempt_no,destination,started_at,finished_at,outcome,error,message_hash) VALUES (?,?,?,?,?,'uncertain','legacy_outbox_last_known_attempt',?)",
                             (alert_id, max(1, row["attempts"]), row["destination"], row["next_attempt_at"] or row["created_at"],
                              row["next_attempt_at"] or row["created_at"], digest(row["message"])))
        store.db.execute("INSERT INTO telegram_resolutions(alert_id,resolved_at,action,note,message_id) VALUES (?,?,?,?,?)",
                         (alert_id, stamp(), outcome + ("_retry_requested" if retry else ""), note.strip(), message_id))
        if outcome != "discard":
            store.db.execute("UPDATE telegram_attempts SET outcome=? WHERE alert_id=? AND outcome='uncertain'",
                             ("confirmed_delivered" if outcome == "delivered" else "confirmed_not_delivered", alert_id))
        store.db.execute("UPDATE telegram_outbox SET status=?,error=NULL,message_id=COALESCE(?,message_id),next_attempt_at=NULL WHERE id=?",
                         (result_status, message_id, alert_id))
    return {"status": result_status, "alert_id": alert_id, "network_calls": 0,
            "retry_requested": retry, "verification": "user_attested_not_api_receipt"}


def history(store, limit=20):
    ensure_radar(store)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("History limit must be 1..100")
    return {"deliveries": [dict(r) for r in store.db.execute(
        "SELECT id,card_id,card_revision,created_at,status,attempts,sent_at,message_id,error,next_attempt_at FROM telegram_outbox ORDER BY created_at DESC,id LIMIT ?", (limit,))],
        "attempts": [dict(r) for r in store.db.execute(
        "SELECT alert_id,attempt_no,started_at,finished_at,outcome,error,retry_at,message_id,cycle_id FROM telegram_attempts ORDER BY started_at DESC,attempt_no DESC LIMIT ?", (limit,))],
        "values_logged": False, "boundary": "Legacy rows may predate per-attempt receipts; manual confirmation is not an API receipt"}


def status(store):
    cfg = ensure_radar(store)
    keys = telegram_keys(store.workspace)
    binding = store.db.execute("SELECT * FROM telegram_binding WHERE id=1").fetchone()
    dest = fingerprint(keys)
    queue_counts = {r["status"]: r["n"] for r in store.db.execute("SELECT status,COUNT(*) n FROM telegram_outbox GROUP BY status")}
    needs_attention = [dict(r) for r in store.db.execute("SELECT id,status,error FROM telegram_outbox WHERE status IN ('uncertain','sending','blocked','failed','sensitive_or_invalid_content') ORDER BY created_at DESC LIMIT 20")]
    window = delivery_window(store, cfg, dest) if dest else {"reason": "credentials_missing", "next_allowed_at": None}
    return {"enabled": cfg["telegram_enabled"], "token_present": bool(keys.get(KEYS[0])),
            "chat_id_present": bool(keys.get(KEYS[1])), "binding_matches": bool(binding and fingerprint(keys) == binding["fingerprint"]),
            "blocked_reason": binding["blocked_reason"] if binding else None,
            "live_deliveries_confirmed": store.db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE status='sent'").fetchone()[0],
            "idea_deliveries_confirmed": store.db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE status='sent' AND card_id NOT IN ('connection-check','delivery-check')").fetchone()[0],
            "connection_checks_confirmed": store.db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE status='sent' AND card_id='connection-check'").fetchone()[0],
            "release_checks_confirmed": store.db.execute("SELECT COUNT(*) FROM telegram_outbox WHERE status='sent' AND card_id='delivery-check'").fetchone()[0],
            "user_confirmed_deliveries": queue_counts.get("confirmed_delivered", 0),
            "queue_counts": queue_counts, "needs_attention": needs_attention,
            "last_api_delivery_at": store.db.execute("SELECT MAX(sent_at) FROM telegram_outbox WHERE status='sent'").fetchone()[0],
            "delivery_window": window,
            "settings": {k: cfg[k] for k in ("telegram_daily_limit", "telegram_min_interval_minutes", "telegram_card_max_age_hours", "quiet_hours_kst")},
            "values_logged": False}
