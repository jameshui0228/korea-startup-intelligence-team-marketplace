"""Executable planning checks; never substitutes plans for observed customer results."""
from .insights import number
from .model import parse_date

ROLES = ('customer', 'user', 'buyer', 'approver')
MVP_FIELDS = ('hypothesis', 'method', 'owner', 'materials', 'metric', 'pass_rule', 'stop_rule')
GTM_FIELDS = ('target', 'channel', 'message_draft', 'conversion_definition', 'denominator_definition')


def known(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip().upper() not in ('UNKNOWN', 'N/A', '미확인')


def check(payload):
    data = payload.get('business')
    if not isinstance(data, dict):
        raise ValueError('business: 검토할 사업 실행안 객체가 필요합니다.')
    gaps = []
    for field in ROLES + ('beachhead', 'reachable_this_month', 'stop_condition', 'reopen_condition'):
        if not known(data.get(field)):
            gaps.append(field + ': 역할·근거·조건을 구체적으로 확인하세요.')
    for section, fields in (('mvp', MVP_FIELDS), ('gtm', GTM_FIELDS)):
        item = data.get(section)
        if not isinstance(item, dict):
            gaps.append(section + ': 설명문만이 아니라 실행 항목별 구조화가 필요합니다.')
            continue
        for field in fields:
            if not known(item.get(field)):
                gaps.append(section + '.' + field + ': 미확인')
        if item.get('budget_krw') is None:
            gaps.append(section + '.budget_krw: 비용 상한 미확인')
        else:
            number(item['budget_krw'], section + '.budget_krw')
        start, end = parse_date(item.get('starts_at')), parse_date(item.get('ends_at'))
        if not start or not end or start >= end:
            gaps.append(section + ': 시작/종료 시각 또는 순서 확인 필요')
    mvp = data.get('mvp', {})
    if isinstance(mvp, dict):
        sample = mvp.get('minimum_sample')
        if type(sample) is not int or sample < 1:
            gaps.append('mvp.minimum_sample: 양의 정수 표본 기준 필요')
        if known(mvp.get('pass_rule')) and mvp.get('pass_rule') == mvp.get('stop_rule'):
            gaps.append('mvp: 통과와 중단 기준이 동일함')
    alternatives = data.get('alternatives', [])
    if not isinstance(alternatives, list) or len(alternatives) > 20:
        raise ValueError('alternatives: 20개 이하의 대안 목록이 필요합니다.')
    if any(not isinstance(a, dict) or not isinstance(a.get('kind'), str) for a in alternatives):
        raise ValueError('각 대안에 문자열 kind가 필요합니다.')
    kinds = {a['kind'] for a in alternatives}
    for index, alternative in enumerate(alternatives):
        for field in ('name', 'approach', 'tradeoff'):
            if not known(alternative.get(field)):
                gaps.append(f'alternatives[{index}].{field}: 대안의 실제 내용 필요')
    for kind in ('status_quo', 'manual', 'non_ai'):
        if kind not in kinds:
            gaps.append('alternatives.' + kind + ': 현 상태·수작업·비AI 대안 비교 필요')
    total = sum(data[s]['budget_krw'] for s in ('mvp', 'gtm') if isinstance(data.get(s), dict) and data[s].get('budget_krw') is not None)
    budget = payload.get('available_budget_krw')
    if budget is not None:
        number(budget, 'available_budget_krw')
        if total > budget:
            gaps.append('budget: MVP와 GTM 합계가 가용 예산 초과')
    return {'gaps': gaps, 'structured_plan_complete': not gaps, 'known_budget_total_krw': total,
            'budget_basis': 'MVP/GTM budgets treated as additive; overlapping costs must be adjusted in input',
            'market_validated': False, 'execution_authorized': False,
            'boundary': '계획 구조·수치 모순 검사. 내용의 타당성·시장 수요·실제 실행 승인 아님.'}


def portfolio(payload):
    candidates = payload.get('candidates')
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 20:
        raise ValueError('candidates: 2~20개 후보를 같은 기준으로 비교하세요.')
    fields = ('founder_fit', 'customer_access', 'evidence_strength', 'test_cost_krw', 'test_days')
    rows, ids = [], set()
    for candidate in candidates:
        if not isinstance(candidate, dict) or not known(candidate.get('id')) or candidate['id'] in ids:
            raise ValueError('후보마다 중복 없는 id가 필요합니다.')
        ids.add(candidate['id'])
        if not known(candidate.get('basis')):
            raise ValueError('basis: 평가 점수와 비용/기간의 근거·가정을 명시하세요.')
        values = {k: candidate.get(k) for k in fields}
        for key, value in values.items():
            if value is not None:
                number(value, key)
                if key in fields[:3] and value > 1:
                    raise ValueError(key + ': 0~1의 명시적 평가 가정 또는 null입니다.')
        rows.append({'id': candidate['id'], 'basis': candidate['basis'], **values,
                     'unknowns': [k for k, v in values.items() if v is None], 'dominated_by': []})
    # Pareto comparisons only when every criterion is known; unknown is never zero.
    for row in rows:
        if row['unknowns']:
            continue
        for other in rows:
            if row is other or other['unknowns']:
                continue
            deltas = [(other[k]-row[k]) * (1 if k in fields[:3] else -1) for k in fields]
            if all(d >= 0 for d in deltas) and any(d > 0 for d in deltas):
                row['dominated_by'].append(other['id'])
    return {'candidates': rows, 'comparable_frontier': [r['id'] for r in rows if not r['unknowns'] and not r['dominated_by']],
            'needs_research': [r['id'] for r in rows if r['unknowns']], 'automatic_rejection': False,
            'boundary': '입력한 판단/가정 내 파레토 비교. 성공확률·지원사업 선정 순위가 아니며 가정이 바뀌면 재검토.'}


def interview_pack(store, payload):
    dossier = store.checkout('dossier', payload.get('dossier_id'))
    data = dossier['data']
    target, problem = data.get('target', 'UNKNOWN'), data.get('problem', 'UNKNOWN')
    questions = [f'최근 {problem}와 관련된 실제 일을 시간 순서로 설명해 주세요.',
                 '그때 어떤 사람과 도구를 거쳤고 어느 단계가 가장 오래 걸렸나요?',
                 '그때 발생한 시간·비용·손해를 확인할 수 있는 기록이 있나요?',
                 '이미 시도한 대안과 계속 사용하거나 중단한 이유는 무엇인가요?',
                 '바꾸려면 누가 비용을 내고 누구의 승인이 필요한가요?',
                 '같은 문제가 발생하지 않은 경우에는 무엇이 달랐나요?']
    return {'dossier_id': data['id'], 'dossier_revision': dossier['expected_revision'],
            'input_template': {'kind': 'interview', 'actor': None, 'role': 'researcher', 'expected_revision': 0,
                'data': {'selection': {'target': target, 'inclusion': None, 'exclusion': None},
                         'consent': {'purpose': '실제 업무 문제와 현재 대안을 이해하기 위한 조사',
                                     'participation': '자발적 참여이며 답변 거절·중단 가능',
                                     'recording_permission': 'not_requested', 'retention_days': None},
                         'nonleading_questions': questions,
                         'observation_fields': ['role', 'context', 'actual_behavior', 'frequency', 'loss', 'current_spend',
                                                'payer', 'alternative', 'source_locator', 'counterexample'],
                         'sampling_bias': 'UNKNOWN', 'execution_status': 'planned'}},
            'must_confirm': ['대상/제외 조건', '기록 방식과 보관 기간', '실제 동의', '모집 표본 편향'],
            'contacted_customers': False, 'saved': False}


def feedback_queue(store):
    queue = []
    for action in store.records('wb_feedback_action'):
        sid = action.get('subject_id')
        rows = store.db.execute('SELECT kind,revision,data FROM records WHERE id=?', (sid,)).fetchall()
        snapshot = action.get('subject_snapshot', {})
        current = rows[0] if len(rows) == 1 else None
        changed = current is not None and current['revision'] != snapshot.get('revision')
        queue.append({'feedback_action_id': action['id'], 'subject_id': sid, 'decision': action.get('decision'),
                      'affected_sections': action.get('affected_sections'), 'proposed_change': action.get('proposed_change'),
                      'current_revision': current['revision'] if current else None, 'subject_changed': changed,
                      'implementation_verified': False,
                      'next_action': '거절 이유를 보존하고 적용하지 않음' if action.get('decision') in ('reject', 'rejected') else
                                     'diff로 제안된 변경이 실제 반영됐는지 확인' if changed else '채택 여부와 최신 원문을 확인한 뒤 도메인 저장기로 수정'})
    return {'items': queue, 'automatically_modified': False}
