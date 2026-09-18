"""Prespecified Korean trend forecasts with honest denominators and calibration."""
import json
import math
from collections import defaultdict
from datetime import timedelta

from . import insights
from .model import assets, now, parse_date, stamp
from .research import id_list, record_key, text


STAGES = {'Weak Signal', 'Emerging', 'Accelerating', 'Mainstream', 'Saturated', 'Unknown'}
OPS = {'gte', 'lte', 'eq', 'increase_by'}


def _number(value, name, low=0, high=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < low or (high is not None and value > high):
        raise ValueError(name + ': 허용 범위의 유한한 숫자가 필요합니다.')
    return value


def _strings(value, name, minimum=1, maximum=12):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(name + f': {minimum}~{maximum}개 문자열이 필요합니다.')
    return [text(item, name, 600) for item in value]


def _reviewed(store, evidence_ids, cutoff=None, substantive=True):
    from .radar import valid_reviews
    reviews = valid_reviews(store, evidence_ids)
    for review in reviews:
        if substantive and review['read_scope'] == 'metadata_only':
            raise ValueError('예측 근거는 제목·검색 메타데이터가 아닌 실제 원문 검토가 필요합니다.')
        observed = parse_date(review['observation']['observed_at'])
        if cutoff and (not observed or observed > cutoff):
            raise ValueError('예측 cutoff 이후에 수집한 근거를 등록 예측에 사용할 수 없습니다.')
    return reviews


def prepare(store, limit=12):
    from .radar import ensure_radar
    ensure_radar(store)
    if type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError('limit: 1~30개 신호를 준비하세요.')
    observations = {row['id']: row for row in store.observations()}
    groups = defaultdict(list)
    for row in store.db.execute('SELECT evidence_id,reviewed_at,data FROM source_reviews ORDER BY reviewed_at DESC'):
        review = json.loads(row['data'])
        observation = observations.get(row['evidence_id'])
        if observation and review.get('read_scope') != 'metadata_only':
            groups[observation['topic']].append((observation, review))
    signals = []
    for topic, rows in groups.items():
        origins = sorted({review.get('origin_group') for _, review in rows if review.get('origin_group')})
        families = sorted({review.get('family') for _, review in rows if review.get('family')})
        dated = [parse_date(obs.get('event_at')) for obs, _ in rows if parse_date(obs.get('event_at'))]
        signals.append({'topic': topic, 'evidence_ids': [obs['id'] for obs, _ in rows[:12]],
                        'origin_groups': origins, 'families': families,
                        'latest_event_at': stamp(max(dated)) if dated else None,
                        'forecast_ready_structure': len(origins) >= 2 and len(families) >= 2 and bool(dated),
                        'maturity': 'multi_origin_multi_family' if len(origins) >= 2 and len(families) >= 2 else
                                    'multi_origin_single_family' if len(origins) >= 2 else 'single_origin',
                        'next_check': '한국의 실제 행동·지출·대안과 반증 자료를 확인하고 결과 정의를 먼저 고정'})
    signals.sort(key=lambda row: (not row['forecast_ready_structure'], row['latest_event_at'] is None,
                                  -parse_date(row['latest_event_at']).timestamp() if row['latest_event_at'] else 0,
                                  row['topic']))
    pending = status(store)['pending']
    return {'candidate_signals': signals[:limit], 'metric_changes': store.snapshot_changes()[:limit],
            'pending_forecasts': pending[:limit],
            'forecast_contract': {'required': ['key', 'question', 'domain_id', 'stage', 'cutoff', 'deadline',
                'probability', 'baseline_probability', 'decision_threshold', 'detected_at', 'evidence_ids',
                'counterevidence_ids', 'counter_search', 'target', 'leading_indicator_chain', 'confounders',
                'review_schedule_days'],
                'target_fields': ['metric', 'operator', 'value', 'unit', 'population', 'geography',
                                  'observation_window', 'source_plan']},
            'recommended_horizons_days': [30, 90, 180, 365], 'forecasts_created': 0,
            'boundary': '원문 검토 신호와 비교 가능한 관측 후보. 미래를 자동 예측하거나 정확도를 보장하지 않는다.'}


def register(store, payload):
    from .radar import ensure_radar
    ensure_radar(store)
    if not isinstance(payload, dict):
        raise ValueError('trend-forecast register 입력은 JSON 객체여야 합니다.')
    key = record_key(payload.get('key'))
    forecast_id = 'trend-forecast-' + key
    if any(row['id'] == forecast_id for row in store.records('trend_forecast')):
        raise ValueError('등록 예측은 변경할 수 없습니다. 새 key로 새 예측을 만드세요.')
    domain_id = payload.get('domain_id')
    if domain_id not in {row['id'] for row in assets('taxonomy.json')['domains']}:
        raise ValueError('domain_id: taxonomy의 정확한 분야 ID가 필요합니다.')
    if payload.get('stage') not in STAGES:
        raise ValueError('stage: Weak Signal/Emerging/Accelerating/Mainstream/Saturated/Unknown 중 하나가 필요합니다.')
    cutoff, deadline = parse_date(payload.get('cutoff')), parse_date(payload.get('deadline'))
    if not cutoff or cutoff > now() or not deadline or deadline <= now() or deadline <= cutoff:
        raise ValueError('cutoff는 현재 이하, deadline은 현재와 cutoff 이후여야 합니다.')
    horizon_days = (deadline - cutoff).total_seconds() / 86400
    if not 1 <= horizon_days <= 1095:
        raise ValueError('예측 기간은 1일~3년이어야 합니다.')
    probability = _number(payload.get('probability'), 'probability', 0, 1)
    baseline = _number(payload.get('baseline_probability'), 'baseline_probability', 0, 1)
    threshold = _number(payload.get('decision_threshold'), 'decision_threshold', 0, 1)
    detected = probability >= threshold
    detected_at = parse_date(payload.get('detected_at')) if payload.get('detected_at') else None
    if detected and (not detected_at or detected_at > cutoff):
        raise ValueError('양성 탐지에는 cutoff 이하의 실제 detected_at이 필요합니다.')
    if not detected and detected_at is not None:
        raise ValueError('음성 예측에는 detected_at을 넣지 마세요.')
    evidence_ids = id_list(payload.get('evidence_ids'), 'forecast evidence', 30, False)
    counter_ids = id_list(payload.get('counterevidence_ids', []), 'forecast counterevidence', 20)
    if set(evidence_ids) & set(counter_ids):
        raise ValueError('지지 근거와 반증 근거 ID를 같은 역할로 중복 사용하지 마세요.')
    reviews = _reviewed(store, evidence_ids, cutoff)
    counter_reviews = _reviewed(store, counter_ids, cutoff) if counter_ids else []
    target = payload.get('target')
    if not isinstance(target, dict) or target.get('operator') not in OPS:
        raise ValueError('target: metric/operator/value/unit/population/geography/observation_window/source_plan이 필요합니다.')
    target_value = _number(target.get('value'), 'target value', 0)
    target_data = {'metric': text(target.get('metric'), 'metric', 300), 'operator': target['operator'],
                   'value': target_value, 'unit': text(target.get('unit'), 'unit', 200),
                   'population': text(target.get('population'), 'population', 600),
                   'geography': text(target.get('geography'), 'geography', 200),
                   'observation_window': text(target.get('observation_window'), 'observation_window', 300),
                   'source_plan': text(target.get('source_plan'), 'source_plan', 600)}
    chain = payload.get('leading_indicator_chain')
    if not isinstance(chain, list) or not 2 <= len(chain) <= 6:
        raise ValueError('leading_indicator_chain: 2~6단계 확산 가설이 필요합니다.')
    chain_data = []
    for index, step in enumerate(chain):
        if not isinstance(step, dict) or step.get('status') not in ('INFERENCE', 'ASSUMPTION', 'UNKNOWN'):
            raise ValueError('선행 지표 단계는 INFERENCE/ASSUMPTION/UNKNOWN으로 기록하세요.')
        ids = id_list(step.get('evidence_ids', []), 'leading indicator evidence', 20)
        if set(ids) - set(evidence_ids):
            raise ValueError('선행 지표 단계는 등록 예측의 지지 근거만 연결하세요.')
        if step['status'] == 'INFERENCE' and not ids:
            raise ValueError('INFERENCE 선행 지표 단계에는 근거가 필요합니다.')
        chain_data.append({'order': index + 1, 'signal': text(step.get('signal'), 'signal', 600),
                           'status': step['status'], 'evidence_ids': ids,
                           'expected_next': text(step.get('expected_next'), 'expected_next', 600)})
    origin_groups = sorted({review.get('origin_group') for review in reviews if review.get('origin_group')})
    families = sorted({review.get('family') for review in reviews if review.get('family')})
    confounders = _strings(payload.get('confounders'), 'confounders', 1, 12)
    review_days = payload.get('review_schedule_days')
    if type(review_days) is not int or not 1 <= review_days <= 90:
        raise ValueError('review_schedule_days: 1~90일 정수가 필요합니다.')
    gaps = []
    if len(origin_groups) < 2:
        gaps.append('fewer_than_two_origin_groups')
    if len(families) < 2:
        gaps.append('fewer_than_two_signal_families')
    if not counter_ids:
        gaps.append('no_linked_counterevidence')
    next_review = min(now() + timedelta(days=review_days), deadline)
    data = {'id': forecast_id, 'key': key, 'question': text(payload.get('question'), 'question', 1200),
            'domain_id': domain_id, 'stage': payload['stage'], 'cutoff': stamp(cutoff),
            'deadline': stamp(deadline), 'horizon_days': horizon_days, 'probability': probability,
            'baseline_probability': baseline, 'decision_threshold': threshold, 'detected': detected,
            'detected_at': stamp(detected_at) if detected_at else None, 'evidence_ids': evidence_ids,
            'counterevidence_ids': counter_ids, 'counter_search': text(payload.get('counter_search'), 'counter_search', 1200),
            'origin_groups': origin_groups, 'families': families, 'target': target_data,
            'leading_indicator_chain': chain_data, 'confounders': confounders,
            'review_schedule_days': review_days, 'next_review_at': stamp(next_review),
            'registered_at': stamp(now()), 'probability_type': 'subjective_prespecified_not_calibrated',
            'structural_gaps': gaps, 'notification_eligible': not gaps,
            'counterevidence_review_count': len(counter_reviews),
            'boundary': '사전 등록된 확산 가설. 확률은 주관적이며 충분한 만기 결과 전에는 예측 능력을 뜻하지 않는다.'}
    with store.db:
        store.record('trend_forecast', data)
    return data


def resolve(store, payload):
    if not isinstance(payload, dict):
        raise ValueError('trend-forecast resolve 입력은 JSON 객체여야 합니다.')
    forecast_id = payload.get('forecast_id')
    forecast = next((row for row in store.records('trend_forecast') if row['id'] == forecast_id), None)
    if not forecast:
        raise ValueError('등록된 trend forecast를 찾을 수 없습니다.')
    if any(row['forecast_id'] == forecast_id for row in store.records('trend_forecast_result')):
        raise ValueError('예측 결과는 변경할 수 없습니다. 정정은 별도 결과 기록으로 감사해야 합니다.')
    deadline = parse_date(forecast['deadline'])
    if now() < deadline:
        raise ValueError('사전 등록한 deadline 이후에만 결과를 판정하세요.')
    state = payload.get('state')
    outcome = payload.get('outcome')
    if state not in ('completed', 'failed', 'unresolved'):
        raise ValueError('state: completed/failed/unresolved 중 하나가 필요합니다.')
    if state == 'completed' and type(outcome) is not bool:
        raise ValueError('completed 결과에는 outcome true/false가 필요합니다.')
    if state != 'completed' and outcome is not None:
        raise ValueError('failed/unresolved 결과의 outcome은 null이어야 합니다.')
    evidence_ids = id_list(payload.get('evidence_ids', []), 'resolution evidence', 20,
                           empty=state != 'completed')
    reviews = _reviewed(store, evidence_ids, substantive=True) if evidence_ids else []
    review_rows = {row['evidence_id']: parse_date(row['reviewed_at'])
                   for row in store.db.execute('SELECT evidence_id,reviewed_at FROM source_reviews')}
    if state == 'completed' and not any(review_rows.get(eid) and review_rows[eid] >= deadline for eid in evidence_ids):
        raise ValueError('deadline 이후 실제로 재검토한 판정 근거가 필요합니다.')
    baseline_at = parse_date(payload.get('baseline_at')) if payload.get('baseline_at') else None
    if outcome is True and (not baseline_at or not parse_date(forecast['cutoff']) <= baseline_at <= deadline):
        raise ValueError('성공 판정은 cutoff~deadline 사이 목표 도달 시각 baseline_at이 필요합니다.')
    if outcome is not True and baseline_at is not None:
        raise ValueError('성공이 아닌 판정에는 baseline_at을 넣지 마세요.')
    result = {'id': 'trend-result-' + forecast['key'], 'forecast_id': forecast_id,
              'state': state, 'truth': outcome, 'baseline_at': stamp(baseline_at) if baseline_at else None,
              'evidence_ids': evidence_ids, 'limitations': _strings(payload.get('limitations'), 'limitations', 1, 12),
              'resolved_at': stamp(now()), 'reviewed_resolution_sources': len(reviews),
              'brier': (forecast['probability'] - int(outcome)) ** 2 if type(outcome) is bool else None,
              'baseline_brier': (forecast['baseline_probability'] - int(outcome)) ** 2 if type(outcome) is bool else None,
              'lead_seconds': ((baseline_at - parse_date(forecast['detected_at'])).total_seconds()
                               if outcome is True and forecast['detected'] and forecast['detected_at'] else None),
              'boundary': '사전 정의에 대한 판정 기록. 원문 검토자의 판정이며 독립 감사나 인과 증명이 아니다.'}
    with store.db:
        store.record('trend_forecast_result', result)
    return result


def _evaluation_rows(store):
    results = {row['forecast_id']: row for row in store.records('trend_forecast_result')}
    rows = []
    for forecast in store.records('trend_forecast'):
        result = results.get(forecast['id'], {})
        rows.append({**forecast, **result, 'probability': forecast['probability'],
                     'detected': forecast['detected'], 'detected_at': forecast['detected_at'],
                     'state': result.get('state', 'pending'), 'truth': result.get('truth'),
                     'baseline_at': result.get('baseline_at')})
    return rows


def evaluate(store):
    rows = _evaluation_rows(store)
    overall = insights.evaluate(rows)
    completed = [row for row in rows if type(row.get('truth')) is bool]
    baseline_scores = [(row['baseline_probability'] - int(row['truth'])) ** 2 for row in completed]
    bins = []
    for lower in (0, .2, .4, .6, .8):
        upper = round(lower + .2, 1)
        selected = [row for row in completed if lower <= row['probability'] <= upper
                    and (lower == .8 or row['probability'] < upper)]
        bins.append({'lower': lower, 'upper': upper, 'n': len(selected),
                     'mean_probability': sum(row['probability'] for row in selected)/len(selected) if selected else None,
                     'observed_rate': sum(row['truth'] for row in selected)/len(selected) if selected else None})
    def horizon(row):
        days = row['horizon_days']
        return '30d' if days <= 30 else '90d' if days <= 90 else '180d' if days <= 180 else '365d' if days <= 365 else 'multi_year'
    groups = {'domain_id': {}, 'stage': {}, 'horizon': {}}
    for key, getter in (('domain_id', lambda row: row['domain_id']), ('stage', lambda row: row['stage']),
                        ('horizon', horizon)):
        values = sorted({getter(row) for row in rows})
        groups[key] = {value: insights.evaluate([row for row in rows if getter(row) == value]) for value in values}
    baseline_mean = sum(baseline_scores)/len(baseline_scores) if baseline_scores else None
    return {'overall': overall, 'baseline_mean_brier': baseline_mean,
            'brier_improvement_vs_baseline': (baseline_mean - overall['mean_brier']
                                               if baseline_mean is not None and overall['mean_brier'] is not None else None),
            'calibration_bins': bins, 'groups': groups, 'resolved_denominator': len(completed),
            'skill_claim_allowed': len(completed) >= 30,
            'interpretation': ('표본 30건 미만이므로 선행 예측 능력을 주장하지 않음' if len(completed) < 30 else
                               '등록 분모 내 성능만 해석하고 기간 외 기준선과 계속 비교'),
            'boundary': '등록된 예측 집합의 기술 평가. 선택 편향이 있으며 한국의 모든 트렌드에 대한 정확도가 아니다.'}


def status(store):
    results = {row['forecast_id']: row for row in store.records('trend_forecast_result')}
    pending, completed = [], []
    for forecast in store.records('trend_forecast'):
        result = results.get(forecast['id'])
        if result:
            completed.append({'forecast_id': forecast['id'], 'state': result['state'],
                              'truth': result['truth'], 'resolved_at': result['resolved_at']})
        else:
            deadline, review_at = parse_date(forecast['deadline']), parse_date(forecast['next_review_at'])
            pending.append({'forecast_id': forecast['id'], 'question': forecast['question'],
                            'deadline': forecast['deadline'], 'next_review_at': forecast['next_review_at'],
                            'state': 'overdue_unresolved' if deadline <= now() else
                                     'review_due' if review_at <= now() else 'watching',
                            'structural_gaps': forecast['structural_gaps']})
    return {'pending': pending, 'completed': completed, 'evaluation': evaluate(store),
            'external_actions_taken': False}
