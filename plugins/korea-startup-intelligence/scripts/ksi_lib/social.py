"""Bounded SNS intake and opt-in X preview; no background collection or posting."""
import json
import re
from urllib.parse import urlencode, urlsplit
from .model import canonical_url, credentials, digest, now, parse_date, stamp
from .collectors import fetch, FetchError

HOSTS = {'instagram': {'instagram.com', 'www.instagram.com'},
         'x': {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'},
         'threads': {'threads.net', 'www.threads.net', 'threads.com', 'www.threads.com'},
         'tiktok': {'tiktok.com', 'www.tiktok.com'},
         'youtube': {'youtube.com', 'www.youtube.com', 'youtu.be'},
         'reddit': {'reddit.com', 'www.reddit.com'}}


def public_post(platform, url):
    if platform not in HOSTS:
        raise ValueError('지원 플랫폼: ' + ', '.join(HOSTS))
    clean = canonical_url(url)
    parts = urlsplit(clean)
    if parts.hostname not in HOSTS[platform]:
        raise ValueError('플랫폼과 원문 도메인이 일치하지 않습니다. 단축 URL은 실제 공개 원문으로 확인하세요.')
    if not parts.path.strip('/'):
        raise ValueError('홈페이지 대신 실제 게시물 주소를 입력하세요.')
    return clean


def batch_import(store, payload):
    """Validate whole batch first, then atomically store reviewed summaries only."""
    from .workbench import bounded_text, validate_payload
    actor = bounded_text(payload.get('actor'), 'actor', 80)
    rows = payload.get('items')
    if payload.get('privacy_reviewed') is not True or not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError('비식별 요약을 검토하고 items에 1~50개 게시물을 넣으세요.')
    prepared = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('items 항목은 객체여야 합니다.')
        platform = row.get('platform')
        url = public_post(platform, row.get('url'))
        summary = bounded_text(row.get('summary'), 'summary', 1200)
        if re.search(r'(?i)(bearer\s|api[_ -]?key|client[_ -]?secret|[\w.+-]+@[\w.-]+\.[a-z]{2,}|01[016789][- ]?\d{3,4}[- ]?\d{4})', summary):
            raise ValueError('요약에 개인정보·인증정보 패턴이 있습니다. 원문 복사 대신 비식별 요약을 쓰세요.')
        data = {k: row.get(k) for k in ('observed_at', 'read_scope', 'collection_basis', 'limitations')}
        data.update({'id': 'social-' + digest(url)[:24], 'platform': platform, 'url': url, 'summary': summary,
                     'actor': actor, 'role': 'researcher', 'recorded_at': stamp()})
        bounded_text(data['limitations'], 'limitations', 1200)
        validate_payload(store, 'signal', data)
        if data['id'] in prepared and {k: v for k, v in prepared[data['id']].items() if k != 'recorded_at'} != {k: v for k, v in data.items() if k != 'recorded_at'}:
            raise ValueError('같은 게시물에 서로 다른 요약이 있습니다. 하나를 선택하거나 별도 검토로 기록하세요.')
        prepared[data['id']] = data
    inserted, existing = [], []
    with store.db:
        if not store.db.in_transaction:
            store.db.execute('BEGIN IMMEDIATE')
        for rid, data in prepared.items():
            if store.db.execute("SELECT 1 FROM records WHERE kind='wb_signal' AND id=?", (rid,)).fetchone():
                existing.append(rid)
            else:
                store.record('wb_signal', data, 0)
                inserted.append(rid)
    return {'inserted': inserted, 'existing_not_overwritten': existing, 'network_requests': 0,
            'boundary': '허용 자료의 사용자/에이전트 요약 접수. 직접 플랫폼 수집·수요 검증 아님.'}


def x_recent(query, token):
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 256:
        raise ValueError('query: 1~256자 공개 검색식을 입력하세요.')
    params = {'query': query, 'max_results': 10, 'tweet.fields': 'created_at'}
    raw, receipt = fetch('https://api.x.com/2/tweets/search/recent?' + urlencode(params),
                         headers={'Authorization': 'Bearer ' + token})
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get('errors') or 'error' in result:
        raise FetchError('x_partial_or_failed_response')
    if not isinstance(result.get('meta', {}), dict):
        raise FetchError('x_schema_changed')
    rows = result.get('data', [])
    if not isinstance(rows, list) or len(rows) > 10 or ('data' not in result and result.get('meta', {}).get('result_count') != 0):
        raise FetchError('x_schema_changed')
    posts = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not re.fullmatch(r'\d{1,30}', row['id']):
            raise FetchError('x_schema_changed')
        # Text and author fields are intentionally not retained or returned.
        posts.append({'url': 'https://x.com/i/web/status/' + row['id'], 'published_at': row.get('created_at'),
                      'read_scope': 'metadata_only'})
    return {'posts': posts, 'has_more': bool(result.get('meta', {}).get('next_token')), 'receipt': receipt,
            'coverage': 'recent_search_first_page_max10_not_platform_census', 'content_reviewed': False}


def x_preview(store, payload):
    cfg = store.config.get('x_read_access', {})
    if not isinstance(cfg, dict) or cfg.get('enabled') is not True:
        return {'status': 'disabled', 'network_requests': 0, 'fallback': 'social-import로 공개 자료의 검토 요약을 접수하세요.'}
    limit = cfg.get('daily_request_limit')
    if cfg.get('user_approved_paid_reads') is not True or cfg.get('provider_spend_cap_confirmed') is not True or type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError('X 조회는 사용자 비용 승인·공급자 지출 상한 확인·일 1~10회 한도가 필요합니다.')
    query = payload.get('query')
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 256:
        raise ValueError('query: 1~256자 검색식을 입력하세요.')
    failed = x_status(store)['unresolved']
    if failed:
        return {'status': 'blocked_after_failure', 'network_requests': 0, 'next_action': '이전 실패/전송 불명 상태를 먼저 조사하세요. 자동 재시도하지 않습니다.'}
    start = stamp(now().replace(hour=0, minute=0, second=0, microsecond=0))
    count = store.db.execute("SELECT COUNT(*) FROM fetches WHERE source='x_preview' AND attempted_at>=?", (start,)).fetchone()[0]
    if count >= limit:
        return {'status': 'daily_limit', 'network_requests': 0}
    key = credentials(store.workspace).get('X_BEARER_TOKEN')
    if not key:
        return {'status': 'key_missing', 'network_requests': 0}
    store.fetch_log('x_preview', digest(query), 'started', 0, {'text_stored': False})
    rid = store.db.execute('SELECT last_insert_rowid()').fetchone()[0]
    store.db.commit()
    try:
        result = x_recent(query, key)
    except (FetchError, ValueError, TypeError, KeyError) as exc:
        code = str(exc) if isinstance(exc, FetchError) and str(exc) in (
            'http_401', 'http_403', 'http_429', 'x_schema_changed', 'x_partial_or_failed_response') else 'unknown_failure'
        with store.db:
            store.db.execute("UPDATE fetches SET status='source_unavailable',receipt=? WHERE id=?",
                             (json.dumps({'failure_code': code, 'text_stored': False}), rid))
        return {'status': 'source_unavailable', 'automatic_retry': False}
    with store.db:
        store.db.execute("UPDATE fetches SET status='ok',item_count=?,receipt=? WHERE id=?",
                         (len(result['posts']), json.dumps(result['receipt']), rid))
    return {'status': 'metadata_for_review', **result, 'automatic_pagination': False}


def x_status(store):
    resolved = {r['attempt_id'] for r in store.records('x_recovery')}
    rows = store.db.execute("SELECT id,status,attempted_at,receipt FROM fetches WHERE source='x_preview' AND status!='ok' ORDER BY id").fetchall()
    unresolved = []
    for row in rows:
        if row['id'] not in resolved:
            receipt = json.loads(row['receipt'])
            code = receipt.get('failure_code', 'unknown_failure')
            unresolved.append({'attempt_id': row['id'], 'status': row['status'], 'attempted_at': row['attempted_at'],
                               'failure_code': code, 'manual_recovery_supported': code in ('http_401', 'http_403', 'x_schema_changed', 'x_partial_or_failed_response')})
    return {'unresolved': unresolved, 'blocked': bool(unresolved), 'network_requests': 0,
            'next_action': '원인·권한·요금 확인 후 사용자가 재개를 요청한 건만 x-recover. 429·중단·원인 불명은 자동 해제 금지.'}


def x_recover(store, payload):
    from .workbench import bounded_text
    attempt = payload.get('attempt_id')
    if type(attempt) is not int or payload.get('user_confirmed_resume') is not True or payload.get('billing_and_access_checked') is not True:
        raise ValueError('실패 attempt_id와 사용자의 명시적 재개 승인·접근 권한/요금 확인이 필요합니다.')
    actor = bounded_text(payload.get('actor'), 'actor', 80)
    reason = bounded_text(payload.get('resolution_summary'), 'resolution_summary', 1000)
    with store.db:
        if not store.db.in_transaction:
            store.db.execute('BEGIN IMMEDIATE')
        row = next((r for r in x_status(store)['unresolved'] if r['attempt_id'] == attempt), None)
        if not row or not row['manual_recovery_supported']:
            raise ValueError('이 실패는 수동 복구 대상이 아니거나 이미 처리됐습니다. 429·중단·원인 불명 기록은 해제하지 않습니다.')
        store.record('x_recovery', {'id': 'x-recovery-' + str(attempt), 'attempt_id': attempt,
                    'actor': actor, 'resolution_summary': reason, 'confirmed_at': stamp(),
                    'user_confirmed_resume': True, 'billing_and_access_checked': True}, 0)
    return {'status': 'recovery_recorded', 'attempt_id': attempt, 'request_retried': False,
            'failure_history_preserved': True, 'remaining': x_status(store)}
