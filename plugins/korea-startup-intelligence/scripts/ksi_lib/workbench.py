"""No-key research workbench. Local attribution is not remote authentication."""
import difflib
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4
from .model import assets, atomic_json, digest, now, parse_date, stamp, canonical_url
from . import insights, research_tools

# Explicit contracts keep agent-generated notes distinct from verified research.
CONTRACTS = {
    'founder': ('budget', 'region', 'skills', 'customer_access', 'time_available', 'excluded_sectors'),
    'glossary': ('term', 'meaning', 'aliases', 'excluded_meanings', 'query_precision'),
    'watchlist': ('platform', 'domain_ids', 'handles_or_urls', 'selection_reason', 'review_after', 'access_basis'),
    'signal': ('platform', 'url', 'observed_at', 'read_scope', 'collection_basis', 'summary', 'limitations'),
    'claim_review': ('claim', 'evidence_id', 'locator', 'producer', 'speaker_role', 'relation', 'interpretation', 'scope_limits', 'counter_search'),
    'metric_definition': ('definition', 'unit', 'population', 'normalization', 'period', 'vintage', 'industry_code'),
    'source_change': ('evidence_id', 'change', 'basis', 'checked_at'),
    'attachment_review': ('file_sha256', 'pages_read', 'pages_total', 'tables_checked', 'footnotes_checked', 'ocr_verified', 'limitations'),
    'origin': ('evidence_ids', 'producer', 'original_url', 'relationship', 'verification'),
    'market_scope': ('domain_ids', 'region', 'population', 'refresh_target_hours', 'channels', 'unknowns'),
    'competitor': ('name', 'segment', 'region', 'price', 'features', 'manual_alternative', 'switching_reason', 'checked_at', 'evidence_ids'),
    'policy': ('title', 'stage', 'effective_at', 'official_url', 'read_scope', 'conditions_complete', 'evidence_ids'),
    'unknown': ('question', 'decision_impact', 'uncertainty', 'research_cost', 'founder_fit', 'next_action'),
    'business': ('dossier_id', 'customer', 'user', 'buyer', 'approver', 'beachhead', 'reachable_this_month', 'model', 'mvp', 'gtm', 'bottlenecks', 'stop_condition', 'reopen_condition'),
    'transfer': ('foreign_signal', 'korean_alternatives', 'culture_income_distribution_limits', 'expected_observation', 'deadline', 'falsifier'),
    'interview': ('selection', 'consent', 'nonleading_questions', 'observation_fields', 'sampling_bias', 'execution_status'),
    'feedback_action': ('subject_id', 'feedback_ids', 'affected_sections', 'proposed_change', 'decision', 'reason'),
    'document_qa': ('application_id', 'file_sha256', 'format', 'page_count', 'page_limit', 'rendered_pages_checked', 'clipping', 'font_check', 'official_template', 'limitations'),
    'budget_link': ('application_id', 'item', 'quote_basis', 'milestone', 'deliverable', 'allowability', 'official_locator'),
    'outcome': ('subject_id', 'kind', 'result', 'evidence_ids', 'limitations', 'attribution'),
    'comment': ('subject_id', 'claim_locator', 'body', 'resolution'),
    'decision': ('subject_id', 'decision', 'reason', 'reopen_condition'),
    'review': ('subject_id', 'author_actor', 'verdict', 'reason', 'independent'),
    'session': ('goal', 'mode', 'budget_minutes', 'request_limit', 'context_limit', 'storage_limit_mb', 'model_cost_limit', 'next_action'),
    'checkpoint': ('session_id', 'completed', 'remaining', 'blockers', 'next_action', 'manual_interventions', 'retries', 'elapsed_minutes', 'requests', 'context_used', 'model_cost'),
    'benchmark': ('question', 'cutoff', 'deadline', 'baseline', 'truth_rule', 'queries', 'rules_version', 'platform', 'domain_id', 'detected', 'probability', 'detected_at', 'available_evidence_ids'),
    'benchmark_result': ('benchmark_id', 'truth', 'state', 'baseline_at', 'evidence_ids', 'limitations'),
    'usability': ('task', 'participant_pseudonym', 'condition', 'minutes', 'missing_sources', 'rework', 'incorrect_citations', 'manual_interventions', 'completed', 'quality_basis'),
    'ablation': ('comparison_id', 'source_removed', 'same_task_and_cutoff', 'cost', 'lead_seconds', 'problems_found', 'limitations'),
}
IMMUTABLE = {'benchmark', 'benchmark_result', 'outcome', 'review', 'decision', 'checkpoint', 'usability', 'ablation'}
ROLES = {'reader': set(), 'researcher': set(CONTRACTS) - {'review'}, 'reviewer': {'review', 'comment', 'claim_review'}, 'owner': set(CONTRACTS)}
MENUS = {'explore': '새 시장·초기 신호 찾기', 'validate': '고객 문제·사업 가설 검증', 'apply': '지원사업·사업계획 준비', 'resume': '이전 조사 이어가기'}


def bounded_text(value, field, maximum=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(field + ': 비어 있지 않은 텍스트가 필요합니다. 입력 범위를 확인하세요.')
    return value.strip()


def get(store, kind, record_id):
    return store.checkout(kind, record_id)


def validate_payload(store, kind, data):
    missing = [k for k in CONTRACTS[kind] if k not in data]
    if missing:
        raise ValueError('누락된 항목: ' + ', '.join(missing) + '. workbench template으로 입력 양식을 확인하세요. 미확인은 UNKNOWN/null로 유지하세요.')
    for field in ('platform', 'domain_id', 'term', 'meaning', 'producer', 'relationship', 'question', 'baseline', 'truth_rule', 'rules_version'):
        if field in CONTRACTS[kind]:
            bounded_text(data[field], field, 1200)
    for field in ('aliases', 'excluded_meanings', 'handles_or_urls', 'domain_ids', 'queries'):
        if field in CONTRACTS[kind] and (not isinstance(data[field], list) or len(data[field]) > 50 or
                                       any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in data[field])):
            raise ValueError(field + ': 최대 50개 문자열 목록을 입력하세요.')
    if 'domain_ids' in data:
        known_domains = {d['id'] for d in assets('taxonomy.json')['domains']}
        if set(data['domain_ids']) - known_domains:
            raise ValueError('domain_ids: domains 명령에서 확인한 분야 ID를 사용하세요.')
    # Values are a schema-checked agent/human assertion, never automatic truth promotion.
    known = {o['id']: o for o in store.observations()}
    ids = data.get('evidence_ids', [])
    if not isinstance(ids, list) or len(ids) > 50 or any(not isinstance(i, str) or i not in known for i in ids):
        raise ValueError('evidence_ids: 현재 접근 가능한 저장 근거 ID만 연결하세요.')
    if 'evidence_id' in data and data['evidence_id'] not in known:
        raise ValueError('evidence_id: 현재 저장된 근거를 선택하세요.')
    if kind == 'signal':
        data['url'] = canonical_url(data['url'])
        if data['collection_basis'] not in ('public_source_verified', 'user_owned', 'authorized_export'):
            raise ValueError('collection_basis: 공개 확인·사용자 소유·허용된 내보내기만 지원합니다.')
        if data['read_scope'] not in ('metadata_only', 'excerpt', 'full_text', 'user_supplied_summary'):
            raise ValueError('read_scope: 실제 읽은 범위를 선택하세요.')
        if not parse_date(data['observed_at']) or parse_date(data['observed_at']) > now():
            raise ValueError('observed_at: 실제 관측 시각이 필요합니다.')
        data['lane'] = 'exploration_not_opportunity'
    if kind == 'interview' and data['execution_status'] not in ('planned', 'not_run', 'completed'):
        raise ValueError('execution_status: planned/not_run/completed 중 실제 상태를 기록하세요.')
    if kind == 'glossary' and data['query_precision'] is not None:
        if insights.number(data['query_precision'], 'query_precision') > 1:
            raise ValueError('query_precision: 실제 측정 비율 0~1 또는 null입니다.')
    if kind == 'claim_review':
        if data['relation'] not in ('supports', 'contradicts', 'context') or data['speaker_role'] not in ('producer', 'advertiser', 'customer', 'expert', 'unknown'):
            raise ValueError('relation/speaker_role: 근거 관계와 발언자를 구분하세요.')
        for field in ('claim', 'locator', 'interpretation', 'scope_limits', 'counter_search'):
            bounded_text(data[field], field)
        data['semantic_truth_verified_automatically'] = False
    if kind == 'review':
        if type(data['independent']) is not bool or data['verdict'] not in ('draft', 'changes_requested', 'reviewed'):
            raise ValueError('review: 검토 상태와 독립 여부를 명시하세요.')
        if data['independent'] and data['author_actor'] == data['actor']:
            raise ValueError('작성자 자신의 검토를 독립 검토로 기록할 수 없습니다.')
    if kind == 'policy' and data['stage'] not in ('proposal', 'announced', 'enacted', 'effective', 'open', 'closed', 'UNKNOWN'):
        raise ValueError('stage: 예고·확정·시행·접수 상태를 구분하세요.')
    if kind == 'policy' and type(data['conditions_complete']) is not bool:
        raise ValueError('conditions_complete: 실제 전체 조건 검토 여부를 true/false로 기록하세요.')
    if kind == 'unknown':
        for k in ('decision_impact', 'uncertainty', 'founder_fit'):
            if insights.number(data[k], k) > 1:
                raise ValueError(k + ': 0~1 범위의 우선순위 가정입니다.')
        insights.number(data['research_cost'], 'research_cost')
        data['priority'] = data['decision_impact'] * data['uncertainty'] * (0.25 + data['founder_fit']) / (1 + data['research_cost'])
        data['priority_is_probability'] = False
    if kind == 'session':
        if data['mode'] not in MENUS:
            raise ValueError('mode: explore/validate/apply/resume 중 선택하세요.')
        for k in ('budget_minutes', 'request_limit', 'context_limit', 'storage_limit_mb'):
            insights.number(data[k], k)
        if data['model_cost_limit'] is not None:
            insights.number(data['model_cost_limit'], 'model_cost_limit')
    if kind == 'checkpoint':
        session = get(store, 'wb_session', data['session_id'])['data']
        for k in ('manual_interventions', 'retries', 'elapsed_minutes', 'requests', 'context_used'):
            insights.number(data[k], k)
        if data['model_cost'] is not None:
            insights.number(data['model_cost'], 'model_cost')
        exceeded = [metric for metric, limit in (('elapsed_minutes', 'budget_minutes'), ('requests', 'request_limit'), ('context_used', 'context_limit')) if data[metric] > session[limit]]
        size_mb = (store.workspace / 'intelligence.sqlite3').stat().st_size / 1048576
        if size_mb > session['storage_limit_mb']:
            exceeded.append('storage_limit_mb')
        if session['model_cost_limit'] is not None and data['model_cost'] is not None and data['model_cost'] > session['model_cost_limit']:
            exceeded.append('model_cost')
        data.update({'budget_exceeded': exceeded, 'continue_allowed': not exceeded,
                     'cost_measurement': 'unknown' if data['model_cost'] is None else 'reported_not_provider_audited'})
    if kind == 'benchmark':
        cutoff, deadline = parse_date(data['cutoff']), parse_date(data['deadline'])
        if not cutoff or not deadline or not cutoff <= now() < deadline:
            raise ValueError('benchmark: 과거/현재 cutoff와 미래 판정 기한을 고정하세요.')
        if type(data['detected']) is not bool:
            raise ValueError('detected: 실제 탐지 여부를 true/false로 입력하세요.')
        if data['probability'] is not None and insights.number(data['probability'], 'probability') > 1:
            raise ValueError('probability: 0~1 범위입니다.')
        available = data['available_evidence_ids']
        if not isinstance(available, list) or any(i not in known or parse_date(known[i]['observed_at']) > cutoff for i in available):
            raise ValueError('평가 cutoff 이후 수집된 근거는 사용할 수 없습니다.')
        if data['detected'] and (not parse_date(data['detected_at']) or parse_date(data['detected_at']) > cutoff):
            raise ValueError('detected_at: cutoff 이전의 실제 탐지 시각이 필요합니다.')
        data['retrospective'] = (now() - cutoff).total_seconds() > 3600
        data['no_lookahead_proven'] = False
    if kind == 'benchmark_result':
        plan = get(store, 'wb_benchmark', data['benchmark_id'])['data']
        if now() < parse_date(plan['deadline']):
            raise ValueError('사전 판정 기한이 지나야 결과를 등록할 수 있습니다.')
        if data['truth'] is not None and type(data['truth']) is not bool:
            raise ValueError('truth: true/false 또는 미판정 null입니다.')
        if data['truth'] is not None and not ids:
            raise ValueError('판정에는 근거 ID가 필요합니다.')
        if data['state'] not in ('completed', 'failed', 'unresolved'):
            raise ValueError('state: completed/failed/unresolved를 사용하세요.')
        if (data['state'] == 'completed') != (data['truth'] is not None):
            raise ValueError('completed에는 판정이 필요하고 failed/unresolved에는 truth=null이 필요합니다.')
        if data['baseline_at'] is not None and (not parse_date(data['baseline_at']) or parse_date(data['baseline_at']) > now()):
            raise ValueError('baseline_at: 실제 관측된 기준선 시각만 입력하세요.')
        if any(r['benchmark_id'] == data['benchmark_id'] for r in store.records('wb_benchmark_result')):
            raise ValueError('이미 판정된 평가입니다. 정정은 feedback으로 기록하세요.')
    if kind == 'usability':
        for k in ('minutes', 'missing_sources', 'rework', 'incorrect_citations', 'manual_interventions'):
            insights.number(data[k], k)
        if type(data['completed']) is not bool:
            raise ValueError('completed: 실제 완료 여부가 필요합니다.')
    if kind == 'outcome':
        if not ids:
            raise ValueError('실제 결과에는 근거가 필요합니다. 계획을 결과로 저장하지 마세요.')
        data['causal_effect_proven'] = False
    if kind == 'business':
        get(store, 'dossier', data['dossier_id'])
        from .business import check
        data['plan_check'] = check({'business': data})
    if kind in ('document_qa', 'budget_link'):
        get(store, 'application', data['application_id'])
    if kind in ('document_qa', 'attachment_review'):
        if not re.fullmatch('[a-f0-9]{64}', str(data['file_sha256'])):
            raise ValueError('실제 검토한 파일의 SHA256이 필요합니다.')
        data['automatic_render_verification'] = False
    if kind == 'document_qa':
        if data['format'] not in ('docx', 'hwpx', 'pdf'):
            raise ValueError('format: docx/hwpx/pdf 실제 파일 형식을 지정하세요.')
        count = data['page_count']
        pages = data['rendered_pages_checked']
        if type(count) is not int or count < 1 or not isinstance(pages, list) or any(type(p) is not int or not 1 <= p <= count for p in pages):
            raise ValueError('page_count/rendered_pages_checked: 실제 페이지 수와 1부터 시작하는 검토 페이지 목록이 필요합니다.')
        limit = data['page_limit']
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError('page_limit: 공식 페이지 제한 또는 null입니다.')
        data['all_pages_reported_checked'] = set(pages) == set(range(1, count+1))
        data['within_page_limit'] = count <= limit if limit is not None else None
    if kind == 'attachment_review':
        count, pages = data['pages_total'], data['pages_read']
        if type(count) is not int or count < 1 or not isinstance(pages, list) or any(type(p) is not int or not 1 <= p <= count for p in pages):
            raise ValueError('pages_total/pages_read: 실제 페이지 수와 범위 내 검토 페이지 목록이 필요합니다.')
        for field in ('tables_checked', 'footnotes_checked', 'ocr_verified'):
            if type(data[field]) is not bool:
                raise ValueError(field + ': 실제 확인 여부를 true/false로 기록하세요.')
        data['all_pages_reported_read'] = set(pages) == set(range(1, count + 1))
    subject = data.get('subject_id')
    if subject:
        records = store.db.execute('SELECT kind,revision,data FROM records WHERE id=?', (subject,)).fetchall()
        if len(records) != 1:
            raise ValueError('subject_id: 유일한 기존 기록을 지정하세요.')
        data['subject_snapshot'] = {'kind': records[0]['kind'], 'revision': records[0]['revision'], 'digest': digest(json.loads(records[0]['data']))}
    return data


def save(store, payload):
    if not isinstance(payload, dict) or payload.get('kind') not in CONTRACTS:
        raise ValueError('kind: workbench template에서 지원하는 기록 종류를 선택하세요.')
    kind, actor, role = payload['kind'], bounded_text(payload.get('actor'), 'actor', 80), payload.get('role', 'researcher')
    if role not in ROLES or kind not in ROLES[role]:
        raise ValueError('이 작업 역할에는 해당 기록 저장 권한이 없습니다. 로컬 역할은 로그인 인증이 아닙니다.')
    content = payload.get('data')
    if not isinstance(content, dict) or len(json.dumps(content, ensure_ascii=False)) > 100000:
        raise ValueError('data: 100KB 이하의 객체가 필요합니다.')
    record_id = payload.get('id') or 'wb-' + kind + '-' + uuid4().hex
    if not re.fullmatch('[a-zA-Z0-9_-]{1,160}', record_id):
        raise ValueError('id: 영문·숫자·하이픈·밑줄 1~160자만 사용하세요.')
    old = store.db.execute('SELECT 1 FROM records WHERE kind=? AND id=?', ('wb_' + kind, record_id)).fetchone()
    if old and kind in IMMUTABLE:
        raise ValueError('이 기록은 변경 불가입니다. 새 기록이나 명시적인 정정 의견을 추가하세요.')
    store.assert_revision('wb_' + kind, record_id, payload.get('expected_revision', 0))
    data = {k: content[k] for k in CONTRACTS[kind] if k in content}
    if kind == 'business' and 'alternatives' in content:
        data['alternatives'] = content['alternatives']
    data.update({'id': record_id, 'actor': actor, 'role': role, 'recorded_at': stamp()})
    validate_payload(store, kind, data)
    with store.db:
        revision = store.record('wb_' + kind, data, payload.get('expected_revision', 0))
    return {'id': record_id, 'revision': revision, 'status': 'saved_not_independently_verified', 'data': data}


def diff(store, kind, record_id, before=None):
    rows = store.db.execute('SELECT revision,data FROM revisions WHERE kind=? AND id=? ORDER BY revision', (kind, record_id)).fetchall()
    if not rows:
        raise ValueError('기록을 찾을 수 없습니다.')
    old = next((r for r in rows if r['revision'] == before), None) if before is not None else rows[-2] if len(rows) > 1 else None
    if before is not None and old is None:
        raise ValueError('비교할 revision이 존재하지 않습니다.')
    a = json.dumps(json.loads(old['data']), ensure_ascii=False, indent=2, sort_keys=True).splitlines() if old else []
    b = json.dumps(json.loads(rows[-1]['data']), ensure_ascii=False, indent=2, sort_keys=True).splitlines()
    return {'from_revision': old['revision'] if old else 0, 'to_revision': rows[-1]['revision'],
            'diff': '\n'.join(difflib.unified_diff(a, b, fromfile='이전', tofile='현재', lineterm=''))}


def impact(store, evidence_id):
    affected = []
    def contains(value):
        return value == evidence_id if isinstance(value, str) else any(contains(v) for v in value.values()) if isinstance(value, dict) else any(contains(v) for v in value) if isinstance(value, list) else False
    for row in store.db.execute('SELECT kind,id,revision,data FROM records'):
        if contains(json.loads(row['data'])):
            affected.append({k: row[k] for k in ('kind', 'id', 'revision')})
    direct = {r['id'] for r in affected}
    indirect, visited = [], set(direct)
    rows = list(store.db.execute('SELECT kind,id,revision,data FROM records'))
    # Fixed-point traversal includes multi-hop applications, reviews and feedback.
    # A visited set makes cycles finite without discarding the original records.
    while True:
        added = set()
        for row in rows:
            data = json.loads(row['data'])
            if row['id'] not in visited and any(data.get(k) in visited for k in
                    ('dossier_id', 'subject_id', 'application_id', 'plan_id', 'session_id', 'benchmark_id')):
                indirect.append({k: row[k] for k in ('kind', 'id', 'revision')})
                added.add(row['id'])
        if not added:
            break
        visited.update(added)
    return {'evidence_id': evidence_id, 'direct': affected, 'downstream': indirect, 'action': '연결된 주장·실험·지원서의 현재 버전을 재검토하세요. 자동 사실 수정은 하지 않습니다.'}


def dashboard(store):
    counts = {r['kind']: r['n'] for r in store.db.execute('SELECT kind,COUNT(*) AS n FROM records GROUP BY kind')}
    active = store.records('wb_session')
    return {'menu': MENUS, 'no_api_required': True, 'counts': counts,
            'next_work': research_tools.workflow(store)['work'][:6],
            'due_reviews': research_tools.due_reviews(store),
            'team_queue': research_tools.team_queue(store)['items'][:10],
            'founder_answers': store.records('wb_founder'), 'sessions': active[:5],
            'resume': store.records('wb_checkpoint')[:5],
            'next_unknowns': sorted(store.records('wb_unknown'), key=lambda r: r['priority'], reverse=True)[:6],
            'unresolved_comments': [r for r in store.records('wb_comment') if r['resolution'] in ('open', 'UNKNOWN', None)][:10],
            'exploration_signals': store.records('wb_signal')[:6],
            'recent_changes': [dict(r) for r in store.db.execute('SELECT kind,id,revision,updated_at FROM records ORDER BY updated_at DESC,rowid DESC LIMIT 10')],
            'execution': 'local_app_required; cloud_and_telegram_deferred; no_external_actions',
            'next_action': '목표를 말하면 Codex가 기존 답을 재사용하고 필요한 입력만 물어본 뒤 양식을 대신 작성합니다.'}


def capabilities(store):
    from .model import credentials
    keys = credentials(store.workspace)
    observations = store.observations()
    tables = {r[0] for r in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    reviewed = {r['evidence_id'] for r in store.db.execute('SELECT evidence_id,data FROM source_reviews')
                if json.loads(r['data']).get('read_scope') != 'metadata_only'} if 'source_reviews' in tables else set()
    result = []
    for source in assets('sources.json'):
        rows = [r for r in observations if r['source'] == source['id']]
        latest = store.db.execute('SELECT status,attempted_at FROM fetches WHERE source=? ORDER BY id DESC LIMIT 1', (source['id'],)).fetchone()
        missing = [k for k in source['credentials'] if k not in keys]
        enabled = source['id'] in store.config['enabled_sources']
        state = 'not_implemented' if not source['adapter'] else 'disabled' if not enabled else 'key_missing' if missing else 'available_not_live_verified'
        if enabled and latest and not missing and source['adapter']:
            state = 'data_collected' if latest['status'] == 'ok' else 'last_attempt_failed'
        result.append({'source': source['id'], 'state': state, 'enabled': enabled, 'missing_key_names': missing,
                       'observations': len(rows), 'reviewed_sources': sum(r['id'] in reviewed for r in rows),
                       'latest': dict(latest) if latest else None, 'limits': source['limitations'],
                       'fallback': '공개 원문 열람 또는 권한 있는 자료를 intake로 등록; 수집·본문 검토는 별도'})
    xcfg = store.config.get('x_read_access', {})
    xcfg = xcfg if isinstance(xcfg, dict) else {}
    return {'sources': result, 'credential_values_logged': False, 'all_platform_coverage': False,
            'manual_tools': {'social_import': {'implemented': True, 'api_required': False, 'direct_collection': False},
                             'x_preview': {'implemented': True, 'enabled': xcfg.get('enabled') is True,
                                           'key_present': bool(keys.get('X_BEARER_TOKEN')),
                                           'paid_reads_approved': xcfg.get('user_approved_paid_reads') is True,
                                           'background_collection': False}}}


def intake(store, payload):
    if payload.get('collection_basis') not in ('public_source_verified', 'user_owned', 'authorized_export'):
        raise ValueError('collection_basis: 공개 확인·소유·허용 내보내기 여부가 필요합니다.')
    if bool(payload.get('url')) == bool(payload.get('path')):
        raise ValueError('url 또는 path 중 하나를 지정하세요.')
    if payload.get('url'):
        locator = canonical_url(payload['url'])
        fingerprint = digest(locator)
    else:
        path = Path(payload['path']).expanduser()
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in ('.pdf', '.docx', '.hwpx', '.csv', '.txt', '.md', '.png', '.jpg', '.json'):
            raise ValueError('일반 자료 파일만 등록하세요. 비밀 설정·DB·실행 파일·심볼릭 링크는 제외합니다.')
        if any(s in path.name.lower() for s in ('secret', 'token', 'credential', '.env')) or path.stat().st_size > 50 * 1024 * 1024:
            raise ValueError('비밀정보 파일 또는 50MB 초과 파일은 접수하지 않습니다.')
        with path.open('rb') as handle:
            fingerprint = hashlib.file_digest(handle, 'sha256').hexdigest()
        locator = str(path.resolve())
    rid = 'intake-' + fingerprint[:24]
    existing = store.db.execute("SELECT data FROM records WHERE kind='wb_intake' AND id=?", (rid,)).fetchone()
    if existing:
        return {'status': 'duplicate', 'id': rid, 'read': False}
    data = {'id': rid, 'locator': locator, 'fingerprint': fingerprint, 'collection_basis': payload['collection_basis'],
            'actor': bounded_text(payload.get('actor'), 'actor', 80), 'read_scope': 'not_read', 'received_at': stamp(),
            'next_action': '권한과 자료를 실제 검토한 뒤 signal/source-review에 읽기 범위와 짧은 요약을 기록하세요.'}
    with store.db:
        store.record('wb_intake', data)
    return {'status': 'received_not_read', 'item': data}


def query_expansion(store, query):
    query = bounded_text(query, 'query', 120)
    matched = [r for r in store.records('wb_glossary') if query == r['term'] or isinstance(r['aliases'], list) and query in r['aliases']]
    return {'query': query, 'groups': [{'meaning': r['meaning'], 'queries': list(dict.fromkeys([r['term']] + r['aliases']))[:12],
                                      'exclude': r['excluded_meanings'], 'measured_precision': r['query_precision']} for r in matched],
            'fallback_queries': [query, query + ' 불편', query + ' 가격', query + ' 수작업', query + ' 실패'],
            'automatically_executed': False}


def benchmark_report(store):
    results = {r['benchmark_id']: r for r in store.records('wb_benchmark_result')}
    rows = [{**p, **results.get(p['id'], {})} for p in store.records('wb_benchmark')]
    groups = {}
    for key in ('platform', 'domain_id'):
        groups[key] = {v: insights.evaluate([r for r in rows if r[key] == v]) for v in sorted({r[key] for r in rows})}
    return {'overall': insights.evaluate(rows), 'groups': groups, 'usability_trials': store.records('wb_usability'),
            'ablations': store.records('wb_ablation'), 'live_benchmark_complete': bool(rows) and all(r.get('truth') is not None for r in rows)}


def backup(store):
    directory = store.workspace / 'backups'
    directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / ('intelligence-' + uuid4().hex + '.sqlite3')
    target.touch(mode=0o600, exist_ok=False)
    dest = sqlite3.connect(target)
    try:
        store.db.backup(dest)
        ok = dest.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        dest.close()
    if ok != 'ok':
        raise ValueError('백업 무결성 검사가 실패했습니다. 원본은 유지됩니다.')
    return {'path': str(target), 'integrity': ok, 'contains_private_research': True, 'credentials_included': False}


def restore_copy(source, destination):
    """Restore into a NEW isolated folder; never overwrite live state."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or not source.is_file():
        raise ValueError('복원은 존재하지 않는 새 폴더와 실제 SQLite 백업 파일을 사용하세요.')
    db = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('백업 무결성 검사 실패')
        columns = {r[1] for r in db.execute('PRAGMA table_info(records)')}
        if not {'kind', 'id', 'revision', 'updated_at', 'data'} <= columns:
            raise ValueError('지원하지 않는 백업 스키마입니다.')
        destination.mkdir(mode=0o700, parents=True)
        target = destination / 'intelligence.sqlite3'
        target.touch(mode=0o600)
        dest = sqlite3.connect(target)
        try:
            db.backup(dest)
        finally:
            dest.close()
        from .model import DEFAULT_CONFIG
        # No connector or messaging configuration is restored implicitly.
        atomic_json(destination / 'config.json', {**DEFAULT_CONFIG, 'enabled_sources': []})
    finally:
        db.close()
    return {'restored_copy': str(destination), 'original_unchanged': True, 'network_sources_enabled': False}


def export_public(store, payload):
    """Only an explicitly reviewed summary is exportable; no raw records/configs."""
    if payload.get('privacy_reviewed') is not True:
        raise ValueError('공유할 요약을 읽고 비밀정보·개인정보 제외 여부를 확인하세요.')
    summary = bounded_text(payload.get('summary'), 'summary')
    if re.search(r'(?i)(api[_ -]?key|client[_ -]?secret|bearer\s|bot\d+:|\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|01[016789][- ]?\d{3,4}[- ]?\d{4})', summary):
        raise ValueError('요약에 인증정보 또는 개인정보 형태가 있습니다. 제거 후 다시 검토하세요.')
    urls = [canonical_url(u) for u in payload.get('public_urls', [])]
    result = {'schema': 1, 'summary': summary, 'public_urls': urls, 'reviewed_by': bounded_text(payload.get('actor'), 'actor', 80),
              'boundary': '사용자가 검토한 공유 요약. 패턴 검사는 완전한 개인정보 탐지가 아닙니다.'}
    path = store.workspace / 'reports' / ('share-' + uuid4().hex + '.json')
    atomic_json(path, result)
    return {'path': str(path), 'raw_records_exported': False, 'sent': False}


def merge_preview(store, source):
    other = sqlite3.connect(Path(source).resolve().as_uri() + '?mode=ro', uri=True)
    result = {'same': 0, 'incoming_only': [], 'conflicts': [], 'mutated': False}
    try:
        for kind, rid, revision, raw in other.execute('SELECT kind,id,revision,data FROM records'):
            local = store.db.execute('SELECT revision,data FROM records WHERE kind=? AND id=?', (kind, rid)).fetchone()
            if local and json.loads(local['data']) == json.loads(raw):
                result['same'] += 1
            elif local:
                result['conflicts'].append({'kind': kind, 'id': rid, 'local_revision': local['revision'], 'incoming_revision': revision})
            else:
                result['incoming_only'].append({'kind': kind, 'id': rid})
    finally:
        other.close()
    result['next_action'] = '충돌은 checkout/diff로 검토하고 기존 도메인 저장기로 명시적으로 병합하세요. SQLite 파일 자체를 동기화하지 마세요.'
    return result


def execute(store, action, args):
    if action == 'feedback-queue':
        from .business import feedback_queue
        return feedback_queue(store)
    if action == 'x-status':
        from .social import x_status
        return x_status(store)
    derived = {'due-reviews': research_tools.due_reviews, 'duplicates': research_tools.duplicate_candidates,
               'workflow': research_tools.workflow, 'research-qa': research_tools.research_qa,
               'team-queue': research_tools.team_queue, 'usability': research_tools.usability_report}
    if action in derived:
        return derived[action](store)
    if action == 'start':
        return dashboard(store)
    if action == 'template':
        if args.kind not in CONTRACTS:
            raise ValueError('지원 kind: ' + ', '.join(CONTRACTS))
        return {'kind': args.kind, 'actor': None, 'role': 'researcher', 'expected_revision': 0,
                'data': {k: None for k in CONTRACTS[args.kind]}, 'status': 'draft_not_saved; null은 미확인, 검증 필드는 실제 자료 필요'}
    if action == 'checkout':
        return get(store, args.kind, args.id)
    if action == 'diff':
        return diff(store, args.kind, args.id, args.revision)
    if action == 'impact':
        return impact(store, args.id)
    if action == 'velocity':
        return insights.velocity(store)
    if action == 'evaluation':
        return benchmark_report(store)
    if action == 'capabilities':
        return capabilities(store)
    if action == 'queries':
        return query_expansion(store, args.query)
    if action == 'backup':
        return backup(store)
    if action == 'restore-copy':
        return restore_copy(args.file, args.destination)
    if action == 'merge-preview':
        return merge_preview(store, args.file)
    payload = json.loads(Path(args.file).read_text())
    if not isinstance(payload, dict):
        raise ValueError('입력 파일은 JSON 객체여야 합니다. Codex가 자연어 요청을 양식으로 정리할 수 있습니다.')
    if action == 'save':
        return save(store, payload)
    if action in ('business-check', 'portfolio', 'interview-pack'):
        from . import business
        if action == 'interview-pack':
            return business.interview_pack(store, payload)
        return business.check(payload) if action == 'business-check' else business.portfolio(payload)
    if action in ('social-import', 'x-preview', 'x-recover'):
        from . import social
        return {'social-import': social.batch_import, 'x-preview': social.x_preview, 'x-recover': social.x_recover}[action](store, payload)
    if action == 'comment-sample':
        return comment_sample(store, payload)
    calculators = {'cashflow': research_tools.cashflow, 'sampling': research_tools.sampling,
                   'ablation-compare': research_tools.ablation_compare}
    if action in calculators:
        return calculators[action](payload)
    if action == 'intake':
        return intake(store, payload)
    if action == 'economics':
        return insights.economics(payload)
    if action == 'compare':
        return insights.compare(payload)
    if action == 'latency':
        return insights.latency(payload)
    if action == 'export':
        return export_public(store, payload)
    raise ValueError('지원하지 않는 workbench 작업입니다.')


def comment_sample(store, payload):
    from datetime import timedelta
    from .model import credentials
    from .collectors import youtube_comment_sample, FetchError
    video = payload.get('video_id')
    if payload.get('public_source_verified') is not True or not isinstance(video, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise ValueError('공개 영상임을 확인하고 video_id를 입력하세요. 비공개·삭제·댓글 차단 우회는 하지 않습니다.')
    cutoff = stamp(now()-timedelta(hours=1))
    recent = store.db.execute("SELECT COUNT(*) FROM fetches WHERE source='youtube_comment_sample' AND attempted_at>=?", (cutoff,)).fetchone()[0]
    if recent >= 3:
        raise ValueError('댓글 표본은 시간당 최대 3회입니다. 다음 시간대에 재검토하세요.')
    same = store.db.execute("SELECT 1 FROM fetches WHERE source='youtube_comment_sample' AND query=? AND attempted_at>=?", (video, cutoff)).fetchone()
    if same:
        raise ValueError('이 영상은 최근 1시간 내 시도했습니다. 자동 재수집하지 않습니다.')
    keys = credentials(store.workspace)
    if not keys.get('YOUTUBE_API_KEY'):
        return {'status': 'key_missing', 'fallback': '공개 댓글을 직접 읽고 비식별 요약을 claim_review에 기록하세요.'}
    # Persist attempt before network I/O; interruptions cannot silently bypass limits.
    store.fetch_log('youtube_comment_sample', video, 'started', 0, {'raw_comment_text_stored': False})
    attempt_id = store.db.execute('SELECT last_insert_rowid()').fetchone()[0]
    store.db.commit()
    try:
        samples, receipt = youtube_comment_sample(video, keys)
    except FetchError:
        with store.db:
            store.db.execute("UPDATE fetches SET status='source_unavailable' WHERE id=?", (attempt_id,))
        return {'status': 'source_unavailable', 'automatic_retry': False, 'raw_error_logged': False}
    with store.db:
        store.db.execute("UPDATE fetches SET status='ok',item_count=?,receipt=? WHERE id=?",
                         (len(samples), json.dumps(receipt), attempt_id))
    return {'status': 'sample_for_review', 'video_url': 'https://www.youtube.com/watch?v=' + video,
            'samples': samples, 'receipt': receipt, 'stored_comment_text': False,
            'boundary': '비신뢰 댓글 발췌. 패턴 가림은 완전한 익명화가 아니며 고객 수·한국 수요·독립 근거를 증명하지 않습니다.'}
