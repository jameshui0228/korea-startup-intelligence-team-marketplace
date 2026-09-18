"""Derived, no-network research tools. Outputs are checks, not market validation."""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta
from .model import now, parse_date, stamp
from .insights import number


def cashflow(payload):
    balance = number(payload.get('opening_cash_krw'), 'opening_cash_krw')
    rows = payload.get('periods')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 60:
        raise ValueError('periods: 시간순으로 1~60개 현금 수입·지출 기간을 입력하세요.')
    output, previous = [], None
    inflows = ('customer_receipts', 'financing', 'other_receipts')
    outflows = ('supplier_payments', 'payroll', 'marketing', 'tax', 'refunds', 'capex', 'debt_service', 'other_payments')
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('basis'), str) or not row['basis'].strip():
            raise ValueError('각 기간에 실제 관측 또는 가정의 basis가 필요합니다.')
        date = parse_date(row.get('ends_at'))
        if not date or (previous and date <= previous):
            raise ValueError('ends_at: 중복 없이 시간순으로 입력하세요.')
        previous = date
        values = {k: number(row.get(k), k) for k in inflows + outflows}
        opening = balance
        receipts, payments = sum(values[k] for k in inflows), sum(values[k] for k in outflows)
        balance += receipts - payments
        output.append({'ends_at': stamp(date), 'basis': row['basis'], 'opening_cash_krw': opening,
                       'receipts_krw': receipts, 'payments_krw': payments, 'closing_cash_krw': balance,
                       'funding_gap_krw': max(0, -balance), 'inputs': values})
    return {'periods': output, 'first_cash_shortfall': next((r['ends_at'] for r in output if r['closing_cash_krw'] < 0), None),
            'maximum_funding_gap_krw': max(r['funding_gap_krw'] for r in output),
            'boundary': '입력한 현금 입출금 시나리오 계산. 매출 인식·세무 판단·자금 조달 확정 아님.'}


def sampling(payload):
    counts = {}
    for key in ('invited', 'responded', 'eligible', 'completed', 'friends', 'incentivized', 'self_selected'):
        value = payload.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(key + ': 0 이상의 실제 인원수가 필요합니다.')
        counts[key] = value
    if not counts['completed'] <= counts['eligible'] <= counts['responded'] <= counts['invited']:
        raise ValueError('완료≤적격≤응답≤초대 인원 순서를 확인하세요.')
    if any(counts[k] > counts['completed'] for k in ('friends', 'incentivized', 'self_selected')):
        raise ValueError('편향 특성별 인원은 완료 인원 이하여야 합니다. 특성은 서로 겹칠 수 있습니다.')
    n = counts['completed']
    return {'counts': counts, 'response_rate': counts['responded']/counts['invited'] if counts['invited'] else None,
            'completion_rate': n/counts['invited'] if counts['invited'] else None,
            'not_completed': counts['invited']-n,
            'bias_shares': {k: counts[k]/n if n else None for k in ('friends', 'incentivized', 'self_selected')},
            'representativeness_verified': False, 'boundary': '등록한 표본 내 기술 통계. 무응답 이유·모집단 대표성은 별도 조사.'}


def due_reviews(store):
    """Expose stale assertions without fetching or advancing their review dates."""
    policies = {'wb_competitor': ('checked_at', 168), 'wb_policy': ('recorded_at', 24),
                'wb_signal': ('observed_at', 24), 'wb_market_scope': ('recorded_at', None),
                'wb_watchlist': ('review_after', 0)}
    due = []
    for kind, (field, hours) in policies.items():
        for row in store.records(kind):
            when = parse_date(row.get(field))
            interval = row.get('refresh_target_hours') if hours is None else hours
            valid_interval = type(interval) in (int, float) and 0 < interval <= 87600
            deadline = when + timedelta(hours=interval) if when and (valid_interval or interval == 0) else None
            if deadline is None or deadline <= now():
                due.append({'kind': kind, 'id': row['id'], 'due_at': stamp(deadline) if deadline else None,
                            'reason': 'review_due' if deadline else 'review_time_unknown',
                            'action': '원문을 실제 재확인하고 checkout 후 갱신. 수집일만 바꾸지 마세요.'})
    return {'items': sorted(due, key=lambda x: x['due_at'] or ''), 'count': len(due),
            'network_requests': 0, 'timestamps_advanced': False}


def duplicate_candidates(store):
    rows = store.observations()[:500]
    def tokens(title):
        return set(re.findall(r'[\w]+', unicodedata.normalize('NFKC', title).casefold()))
    prepared = [(r, tokens(r.get('title', ''))) for r in rows]
    candidates = []
    for i, (left, a) in enumerate(prepared):
        for right, b in prepared[i+1:]:
            union = a | b
            score = len(a & b)/len(union) if union else 0
            same_url = left.get('url') == right.get('url') and bool(left.get('url'))
            if same_url or (len(a) >= 3 and len(b) >= 3 and score >= .7):
                candidates.append({'left': left['id'], 'right': right['id'], 'title_overlap': score,
                                   'same_url': same_url, 'independence': 'UNKNOWN', 'auto_merged': False})
                if len(candidates) == 100:
                    break
        if len(candidates) == 100:
            break
    return {'candidates': candidates, 'examined': len(rows), 'limit': 500,
            'boundary': '제목 토큰 유사도 후보만 제시. 의미 동일성·같은 원 생산자 여부는 원문 확인 필요.'}


def workflow(store):
    applications = store.records('application')
    ventures = store.records('venture_review')
    result = []
    for dossier in store.records('dossier'):
        rid = dossier['id']
        missing = [k for k, v in dossier.get('findings', {}).items() if isinstance(v, dict) and v.get('status') == 'UNKNOWN']
        app = next((a for a in applications if a.get('dossier_id') == rid), None)
        venture = next((v for v in ventures if v.get('dossier_id') == rid), None)
        if dossier.get('decision') in ('park', 'reject'):
            step, action = 'paused', '기각·보류 이유를 바꾸는 새 근거가 있을 때만 재개'
        elif missing:
            step, action = 'research', '미확인 주장에 연결할 실제 고객 행동·지불·대안 근거 검토'
        elif not venture:
            step, action = 'venture_review', '고객 질문·대안·실패 조건 검토'
        elif not app:
            step, action = 'validation', '최소 실험 사전등록 또는 사용자가 지정한 공고로 지원서 준비'
        else:
            step, action = 'application_audit', 'application check로 근거·자격·예산·검수 확인; 제출은 별도 요청'
        result.append({'dossier_id': rid, 'stage': step, 'next_action': action, 'unknown_dimensions': missing,
                       'application_id': app['id'] if app else None})
    return {'work': result, 'external_actions_taken': False,
            'empty_next_action': '고객·문제·현재 행동을 조사하여 첫 dossier를 저장하세요.' if not result else None}


def research_qa(store):
    """Audit every dossier and produce a bounded, evidence-linked repair queue."""
    from .radar import ensure_radar, valid_reviews
    from .research import DIMENSIONS, dossier_quality
    ensure_radar(store)
    review_rows = {r['evidence_id']: json.loads(r['data'])
                   for r in store.db.execute('SELECT evidence_id,data FROM source_reviews')}
    core = ('problem_severity', 'problem_frequency', 'willingness_to_pay', 'current_workaround',
            'competition', 'differentiation', 'korea_fit', 'distribution')
    items, queue = [], []
    for dossier in store.records('dossier'):
        valid_ids, invalid_ids = [], []
        for evidence_id in dossier.get('evidence_ids', []):
            try:
                valid_reviews(store, [evidence_id])
                valid_ids.append(evidence_id)
            except ValueError:
                invalid_ids.append(evidence_id)
        findings = dossier.get('findings', {})
        links = [(dimension, link) for dimension, finding in findings.items()
                 for link in finding.get('links', [])]
        substantive = [(dimension, link) for dimension, link in links if link.get('relation') != 'context']
        linked_ids = {link.get('evidence_id') for _, link in links}
        core_links = [(dimension, link) for dimension, link in substantive if dimension in core]
        origin_groups = sorted({review_rows[eid].get('origin_group') for _, link in core_links
                                if (eid := link.get('evidence_id')) in valid_ids and
                                review_rows.get(eid, {}).get('origin_group')})
        contradictions = sorted({dimension for dimension, link in substantive
                                  if link.get('relation') == 'contradicts'})
        status_counts = Counter(finding.get('status', 'UNKNOWN') for finding in findings.values())
        unknown_core = [dimension for dimension in core
                        if findings.get(dimension, {}).get('status') in (None, 'UNKNOWN', 'ASSUMPTION')]
        evidence_use = Counter(link.get('evidence_id') for _, link in substantive)
        quality = dossier_quality(store, dossier)
        actions = []
        if invalid_ids:
            actions.append(('critical', 'recheck_sources', '만료·변경·누락된 원문을 다시 읽고 연결 주장을 재검토'))
        if quality['blocking_gaps']:
            actions.append(('high', 'resolve_alert_gaps', '알림 차단 사유의 고객 행동·지불·한국 대안 근거를 보완'))
        if len(origin_groups) < 2:
            actions.append(('high', 'independent_origin', '핵심 주장에 독립 원생산자 자료를 추가하고 재인용 관계를 확인'))
        if not contradictions:
            actions.append(('high', 'counterevidence', '만들지 말아야 할 이유와 반대 자료를 별도 검색해 연결'))
        competitor_kinds = {row.get('kind') for row in dossier.get('competitors', [])}
        if 'manual' not in competitor_kinds:
            actions.append(('medium', 'manual_alternative', '고객의 수작업·엑셀·대행 흐름과 전환 비용을 조사'))
        if not competitor_kinds.intersection({'direct', 'indirect', 'platform'}):
            actions.append(('medium', 'market_alternative', '한국의 직접·간접·플랫폼 대안을 최소 하나 원문으로 검토'))
        if unknown_core:
            actions.append(('medium', 'core_unknowns', '핵심 미확인 항목을 우선 조사: ' + ', '.join(unknown_core)))
        orphan_ids = sorted(set(valid_ids) - linked_ids)
        if orphan_ids:
            actions.append(('low', 'unlinked_evidence', 'dossier에 포함됐지만 주장에 연결되지 않은 근거의 역할을 검토'))
        priority_value = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}
        for priority, code, action in actions:
            queue.append({'priority': priority, 'priority_value': priority_value[priority],
                          'dossier_id': dossier['id'], 'code': code, 'action': action})
        items.append({'dossier_id': dossier['id'], 'decision': dossier.get('decision'),
                      'ready_for_opportunity_alert': quality['ready_for_opportunity_alert'],
                      'blocking_gaps': quality['blocking_gaps'], 'valid_evidence_ids': valid_ids,
                      'invalid_evidence_ids': invalid_ids, 'core_origin_groups': origin_groups,
                      'independent_core_origin_count': len(origin_groups),
                      'contradicted_dimensions': contradictions, 'unknown_core_dimensions': unknown_core,
                      'unlinked_evidence_ids': orphan_ids, 'finding_status_counts': dict(status_counts),
                      'substantive_link_count': len(substantive),
                      'largest_single_source_link_share': (max(evidence_use.values()) / len(substantive)) if substantive else None,
                      'actions': [{'priority': p, 'code': c, 'action': a} for p, c, a in actions]})
    queue.sort(key=lambda row: (-row['priority_value'], row['dossier_id'], row['code']))
    return {'dossiers': items, 'dossier_count': len(items),
            'alert_ready_count': sum(row['ready_for_opportunity_alert'] for row in items),
            'repair_queue': queue[:100], 'repair_queue_total': len(queue),
            'network_requests': 0, 'records_modified': False,
            'boundary': '구조·연결·신선도 감사. 출처의 진실성, 고객 수요, 성공 가능성을 자동 인증하지 않는다.'}


def team_queue(store):
    """Merge research, review, feedback and workflow obligations into one local queue."""
    from .business import feedback_queue
    qa = research_qa(store)
    work = workflow(store)
    due = due_reviews(store)
    items = [{'lane': 'research_qa', **row} for row in qa['repair_queue']]
    items += [{'lane': 'source_review', 'priority': 'high', 'priority_value': 3,
               'subject_id': row['id'], 'code': row['reason'], 'action': row['action']}
              for row in due['items']]
    items += [{'lane': 'workflow', 'priority': 'medium', 'priority_value': 2,
               'subject_id': row['dossier_id'], 'code': row['stage'], 'action': row['next_action']}
              for row in work['work'] if row['stage'] != 'paused']
    items += [{'lane': 'feedback', 'priority': 'medium', 'priority_value': 2,
               'subject_id': row['subject_id'], 'code': 'feedback_action', 'action': row['next_action']}
              for row in feedback_queue(store)['items']]
    items += [{'lane': 'comment', 'priority': 'medium', 'priority_value': 2,
               'subject_id': row.get('subject_id'), 'code': 'unresolved_comment',
               'action': '코멘트의 주장 위치를 확인하고 해결 또는 근거 있는 보류로 기록'}
              for row in store.records('wb_comment') if row.get('resolution') in ('open', 'UNKNOWN', None)]
    for evaluation in store.records('competition_evaluation')[:5]:
        for candidate in evaluation.get('candidates', []):
            blocks = candidate.get('hard_blocks', [])
            gaps = candidate.get('evidence_gaps', [])
            if blocks or gaps:
                items.append({'lane': 'competition', 'priority': 'high' if blocks else 'medium',
                              'priority_value': 3 if blocks else 2, 'subject_id': candidate.get('key'),
                              'code': 'candidate_blocked' if blocks else 'candidate_evidence_gap',
                              'action': '공모전 후보 보완: ' + ', '.join(blocks + gaps)})
    from .trend_forecast import status as forecast_status
    for forecast in forecast_status(store)['pending'][:20]:
        if forecast['state'] in ('review_due', 'overdue_unresolved') or forecast['structural_gaps']:
            urgent = forecast['state'] == 'overdue_unresolved'
            items.append({'lane': 'trend_forecast', 'priority': 'critical' if urgent else 'medium',
                          'priority_value': 4 if urgent else 2, 'subject_id': forecast['forecast_id'],
                          'code': forecast['state'],
                          'action': ('만기 결과를 사전 기준대로 판정' if urgent else
                                     '새 근거·반례·구조 공백을 검토: ' + ', '.join(forecast['structural_gaps']))})
    items.sort(key=lambda row: (-row['priority_value'], row['lane'], row.get('subject_id', row.get('dossier_id', ''))))
    return {'items': items[:100], 'total': len(items),
            'by_lane': dict(Counter(row['lane'] for row in items)),
            'network_requests': 0, 'external_actions_taken': False,
            'boundary': '로컬 기록에서 만든 작업 우선순위. 담당자 배정·고객 연락·제출은 수행하지 않는다.'}


def usability_report(store):
    groups = defaultdict(list)
    for row in store.records('wb_usability'):
        groups[(row['task'], row['condition'])].append(row)
    results = []
    for (task, condition), rows in sorted(groups.items()):
        n = len(rows)
        results.append({'task': task, 'condition': condition, 'trials': n,
                        'participants': len({r['participant_pseudonym'] for r in rows}),
                        'completion_rate': sum(r['completed'] for r in rows)/n,
                        'means': {k: sum(r[k] for r in rows)/n for k in
                                  ('minutes', 'missing_sources', 'rework', 'incorrect_citations', 'manual_interventions')}})
    return {'groups': results, 'real_trials_registered': sum(len(r) for r in groups.values()),
            'causal_superiority_proven': False, 'boundary': '과제·조건별 기술 통계. 반복 참가자·학습 효과·표본 차이는 별도 확인.'}


def ablation_compare(payload):
    left, right = payload.get('baseline'), payload.get('without_source')
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise ValueError('baseline/without_source 두 조건의 측정 결과가 필요합니다.')
    keys = ('task', 'cutoff', 'truth_set', 'rules_version')
    mismatch = [k for k in keys if not left.get(k) or left[k] == 'UNKNOWN' or left[k] != right.get(k)]
    if mismatch:
        return {'comparable': False, 'mismatches': mismatch}
    metrics = ('cost', 'true_positives', 'false_positives', 'lead_seconds')
    a = {k: number(left.get(k), k, minimum=-1e12 if k == 'lead_seconds' else 0) for k in metrics}
    b = {k: number(right.get(k), k, minimum=-1e12 if k == 'lead_seconds' else 0) for k in metrics}
    return {'comparable': True, 'source_added_delta': {k: a[k]-b[k] for k in metrics},
            'causal_effect_proven': False, 'boundary': '동일 평가 조건의 관측 차이. 소스 제거 외 조건 통제 여부는 별도 검토.'}
