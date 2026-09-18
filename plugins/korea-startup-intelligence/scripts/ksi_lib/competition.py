"""Competition-response packets and candidate gates; never an award forecast."""
import math
from uuid import uuid4

from . import grants, research
from .model import assets, now, parse_date, stamp


LENSES = (
    ('problem_first', '반복되는 고객 업무·비용·위험에서 시작'),
    ('behavior_shift', '최근 행동 변화가 만든 새 불편에서 시작'),
    ('manual_work', '엑셀·카카오톡·전화·대행의 비싼 한 단계에서 시작'),
    ('policy_timing', '공식 정책·표준·의무 변화의 실행 부담에서 시작'),
    ('regional_offline', '지역·현장·비디지털 운영 제약에서 시작'),
    ('cross_industry', '다른 산업의 검증된 작동 원리를 제약과 함께 이전'),
    ('supply_bottleneck', '공급·납품·인증·품질·일정 병목에서 시작'),
    ('trust_transaction', '검증·계약·정산·사후관리 비용에서 시작'),
)
CORE_CLAIMS = ('problem', 'current_alternative', 'willingness_to_pay', 'why_now',
               'differentiation', 'korea_fit')
STATUSES = {'FACT', 'INFERENCE', 'ASSUMPTION', 'UNKNOWN'}


def _notice(store, grant_id):
    notice = next((row for row in store.records('grant') if row['id'] == grant_id), None)
    if not notice:
        raise ValueError('공식 공고를 먼저 grants save로 저장하세요.')
    return notice


def _bounded(value, name, maximum=1200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(name + ': 비어 있지 않은 제한 길이 텍스트가 필요합니다.')
    return value.strip()


def _number(value, name, low=0, high=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < low or (high is not None and value > high):
        raise ValueError(name + ': 허용 범위의 유한한 숫자가 필요합니다.')
    return value


def prepare(store, grant_id, profile=None, limit=12):
    if type(limit) is not int or not 4 <= limit <= 20:
        raise ValueError('limit: 4~20개의 후보 슬롯을 사용하세요.')
    notice = _notice(store, grant_id)
    profile = profile or {}
    match = grants.match_notice(store, grant_id, profile)
    dossiers = []
    for dossier in store.records('dossier'):
        quality = research.dossier_quality(store, dossier)
        dossiers.append({'dossier_id': dossier['id'], 'title': dossier['title'],
                         'target': dossier['target'], 'problem': dossier['problem'],
                         'decision': dossier['decision'], 'domain_ids': dossier['domain_ids'],
                         'ready_for_opportunity_alert': quality['ready_for_opportunity_alert'],
                         'blocking_gaps': quality['blocking_gaps'],
                         'evidence_backed_dimensions': quality['evidence_backed_dimensions']})
    deadline = parse_date(notice.get('closes_at'))
    hours_left = max(0, (deadline - now()).total_seconds() / 3600) if deadline else None
    slots = []
    for index in range(limit):
        lens, instruction = LENSES[index % len(LENSES)]
        slots.append({'slot': index + 1, 'lens': lens, 'instruction': instruction,
                      'required_variation': ('B2B/B2G·현장 운영 포함' if index % 3 == 0 else
                                             '서비스·오프라인·하드웨어 가능성 포함' if index % 3 == 1 else
                                             '소프트웨어가 아닌 현 상태 유지 대안도 비교')})
    warnings = []
    if match['notice_stale']:
        warnings.append('official_notice_recheck_required')
    if not notice['conditions_complete']:
        warnings.append('notice_conditions_incomplete')
    if not notice['evaluation_criteria']:
        warnings.append('official_evaluation_criteria_missing')
    if match['eligibility'] != 'MATCHES_RECORDED_RULES':
        warnings.append('eligibility_not_confirmed')
    if match['application_phase'] != 'open':
        warnings.append('application_not_confirmed_open')
    return {'grant_id': grant_id, 'title': notice['title'], 'issuer': notice['issuer'],
            'notice_version': notice['notice_version'], 'deadline': notice.get('closes_at'),
            'hours_left': hours_left, 'urgent_under_72_hours': hours_left is not None and hours_left <= 72,
            'eligibility': match, 'evaluation_criteria': notice['evaluation_criteria'],
            'founder_profile_used': bool(profile), 'existing_dossiers': dossiers,
            'candidate_slots': slots, 'warnings': warnings,
            'candidate_contract': {'required_fields': ['key', 'title', 'target', 'problem', 'solution',
                'business_model', 'demo', 'first_users', 'founder_fit', 'claims', 'criterion_mapping',
                'risks', 'assumptions', 'dossier_id'],
                'core_claims': list(CORE_CLAIMS),
                'rule': '후보는 다양하게 발산하되 FACT/INFERENCE/ASSUMPTION/UNKNOWN을 분리하고 없는 실적을 만들지 않는다.'},
            'next_steps': ['candidate_slots에 맞춰 서로 다른 후보를 작성',
                           'competition evaluate로 자격·평가표·근거·시연 가능성 검사',
                           '통과 후보만 dossier/venture-review/application으로 발전'],
            'ideas_generated': False, 'selection_probability': None,
            'boundary': '공모전 대응 조사 패킷. 아이디어 생성·수상 가능성·기관 판단을 자동 확정하지 않는다.'}


def _claim(item, evidence, name):
    if not isinstance(item, dict) or item.get('status') not in STATUSES:
        raise ValueError(name + ': 상태를 FACT/INFERENCE/ASSUMPTION/UNKNOWN으로 구분하세요.')
    value = {'status': item['status'], 'text': _bounded(item.get('text'), name, 1600)}
    ids = item.get('evidence_ids', [])
    if not isinstance(ids, list) or len(ids) > 20 or len(ids) != len(set(ids)) or any(eid not in evidence for eid in ids):
        raise ValueError(name + ': 현재 저장된 고유 근거 ID 최대 20개를 사용하세요.')
    if item['status'] in ('FACT', 'INFERENCE') and not ids:
        raise ValueError(name + ': FACT/INFERENCE에는 근거가 필요합니다.')
    value['evidence_ids'] = ids
    return value


def evaluate(store, payload):
    from .radar import valid_reviews
    if not isinstance(payload, dict):
        raise ValueError('competition evaluate 입력은 JSON 객체여야 합니다.')
    notice = _notice(store, payload.get('grant_id'))
    profile = payload.get('profile', {})
    match = grants.match_notice(store, notice['id'], profile)
    candidates = payload.get('candidates')
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= 20:
        raise ValueError('candidates: 서로 다른 후보 2~20개가 필요합니다.')
    evidence = {row['id']: row for row in store.observations()}
    criteria = [row['criterion'] for row in notice['evaluation_criteria']]
    domains = {row['id'] for row in assets('taxonomy.json')['domains']}
    seen, results = set(), []
    for raw in candidates:
        if not isinstance(raw, dict):
            raise ValueError('각 후보는 JSON 객체여야 합니다.')
        key = research.record_key(raw.get('key'))
        if key in seen:
            raise ValueError('후보 key는 중복될 수 없습니다.')
        seen.add(key)
        row = {'key': key}
        for field in ('title', 'target', 'problem', 'solution', 'business_model', 'first_users'):
            row[field] = _bounded(raw.get(field), field, 1600)
        domain_ids = raw.get('domain_ids', [])
        if not isinstance(domain_ids, list) or not 1 <= len(domain_ids) <= 6 or set(domain_ids) - domains:
            raise ValueError('domain_ids: taxonomy의 분야 ID 1~6개가 필요합니다.')
        row['domain_ids'] = domain_ids
        claims = raw.get('claims')
        if not isinstance(claims, dict) or set(claims) != set(CORE_CLAIMS):
            raise ValueError('claims에는 problem/current_alternative/willingness_to_pay/why_now/differentiation/korea_fit이 모두 필요합니다.')
        row['claims'] = {name: _claim(claims[name], evidence, name) for name in CORE_CLAIMS}
        mappings = raw.get('criterion_mapping')
        if not isinstance(mappings, list) or len(mappings) > 30:
            raise ValueError('criterion_mapping: 공고 평가항목 대응 목록이 필요합니다.')
        mapped = {}
        for item in mappings:
            if not isinstance(item, dict) or item.get('criterion') not in criteria or item['criterion'] in mapped:
                raise ValueError('criterion_mapping은 실제 공고 평가항목을 각 한 번만 사용하세요.')
            mapped[item['criterion']] = _claim(item, evidence, 'criterion:' + item['criterion'])
        founder_fit = raw.get('founder_fit')
        if not isinstance(founder_fit, dict) or founder_fit.get('status') not in ('confirmed', 'unknown'):
            raise ValueError('founder_fit: confirmed/unknown과 statement/basis를 입력하세요.')
        row['founder_fit'] = {'status': founder_fit['status'],
                              'statement': _bounded(founder_fit.get('statement'), 'founder_fit statement'),
                              'basis': _bounded(founder_fit.get('basis'), 'founder_fit basis')}
        demo = raw.get('demo')
        if not isinstance(demo, dict):
            raise ValueError('demo: method/timebox_days/budget_krw/pass_condition/stop_condition이 필요합니다.')
        row['demo'] = {'method': _bounded(demo.get('method'), 'demo method'),
                       'timebox_days': _number(demo.get('timebox_days'), 'timebox_days', 1, 90),
                       'budget_krw': _number(demo.get('budget_krw'), 'budget_krw', 0),
                       'pass_condition': _bounded(demo.get('pass_condition'), 'pass_condition'),
                       'stop_condition': _bounded(demo.get('stop_condition'), 'stop_condition')}
        for field in ('risks', 'assumptions'):
            values = raw.get(field)
            if not isinstance(values, list) or not 1 <= len(values) <= 12:
                raise ValueError(field + ': 1~12개의 구체 항목이 필요합니다.')
            row[field] = [_bounded(value, field, 600) for value in values]
        hard_blocks = []
        if match['eligibility'] != 'MATCHES_RECORDED_RULES':
            hard_blocks.append('eligibility_not_confirmed')
        if match['application_phase'] != 'open':
            hard_blocks.append('application_not_confirmed_open')
        if match['notice_stale']:
            hard_blocks.append('official_notice_stale')
        if not notice['conditions_complete']:
            hard_blocks.append('notice_conditions_incomplete')
        if not criteria:
            hard_blocks.append('official_evaluation_criteria_missing')
        missing_criteria = sorted(set(criteria) - set(mapped))
        if missing_criteria:
            hard_blocks.append('official_criteria_not_fully_mapped')
        evidence_gaps = [name for name, claim in row['claims'].items()
                         if claim['status'] in ('UNKNOWN', 'ASSUMPTION')]
        invalid_review_ids = []
        for eid in {eid for claim in list(row['claims'].values()) + list(mapped.values())
                    for eid in claim['evidence_ids']}:
            try:
                valid_reviews(store, [eid])
            except ValueError:
                invalid_review_ids.append(eid)
        if invalid_review_ids:
            hard_blocks.append('evidence_review_stale_or_missing')
        dossier_id = raw.get('dossier_id')
        dossier = next((item for item in store.records('dossier') if item['id'] == dossier_id), None) if dossier_id else None
        dossier_gaps = []
        if not dossier:
            dossier_gaps.append('evidence_linked_dossier_missing')
        else:
            if dossier['target'] != row['target'] or dossier['problem'] != row['problem']:
                dossier_gaps.append('dossier_customer_problem_mismatch')
            dossier_gaps.extend(research.dossier_quality(store, dossier)['blocking_gaps'])
        if row['founder_fit']['status'] != 'confirmed':
            evidence_gaps.append('founder_fit')
        row.update({'criterion_mapping': mapped, 'dossier_id': dossier_id,
                    'missing_criteria': missing_criteria, 'hard_blocks': sorted(set(hard_blocks)),
                    'evidence_gaps': sorted(set(evidence_gaps + dossier_gaps)),
                    'invalid_review_evidence_ids': sorted(invalid_review_ids),
                    'structural_metrics': {'criteria_mapped': len(mapped), 'criteria_total': len(criteria),
                        'evidence_backed_core_claims': sum(c['status'] in ('FACT', 'INFERENCE') for c in row['claims'].values()),
                        'core_claims_total': len(CORE_CLAIMS), 'risk_count': len(row['risks'])},
                    'shortlist_eligible': not hard_blocks and not evidence_gaps and not dossier_gaps,
                    'award_probability': None})
        results.append(row)
    metric_names = ('criteria_mapped', 'evidence_backed_core_claims')
    frontier = []
    for candidate in results:
        if candidate['hard_blocks'] or candidate['evidence_gaps']:
            continue
        dominated = any(other['key'] != candidate['key'] and not other['hard_blocks'] and not other['evidence_gaps'] and
                        all(other['structural_metrics'][m] >= candidate['structural_metrics'][m] for m in metric_names) and
                        other['demo']['budget_krw'] <= candidate['demo']['budget_krw'] and
                        other['demo']['timebox_days'] <= candidate['demo']['timebox_days'] and
                        (any(other['structural_metrics'][m] > candidate['structural_metrics'][m] for m in metric_names) or
                         other['demo']['budget_krw'] < candidate['demo']['budget_krw'] or
                         other['demo']['timebox_days'] < candidate['demo']['timebox_days'])
                        for other in results)
        if not dominated:
            frontier.append(candidate['key'])
    data = {'id': 'competition-evaluation-' + uuid4().hex, 'grant_id': notice['id'],
            'notice_version': notice['notice_version'], 'evaluated_at': stamp(), 'eligibility': match,
            'candidates': results, 'pareto_frontier': frontier,
            'shortlist': [row['key'] for row in results if row['shortlist_eligible']],
            'boundary': '구조·근거·자격·시연 준비도 비교. 수상 확률, 심사위원 선호, 시장 성공을 예측하지 않는다.'}
    with store.db:
        store.record('competition_evaluation', data)
    return data


def status(store, grant_id=None):
    rows = store.records('competition_evaluation')
    if grant_id:
        rows = [row for row in rows if row['grant_id'] == grant_id]
    return {'evaluations': rows[:20], 'count': len(rows),
            'boundary': '저장된 평가 이력. 이후 공고 정정·근거 변경·실험 결과를 자동 반영하지 않는다.'}
