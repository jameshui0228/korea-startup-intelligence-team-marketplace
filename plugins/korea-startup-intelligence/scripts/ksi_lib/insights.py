"""Measured comparisons, not claims of predictive accuracy or customer demand."""
import math
from collections import defaultdict
from .model import now, parse_date, stamp


def number(value, field, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        raise ValueError(field + ': 유한한 숫자를 입력하세요. 문자열·음수·참/거짓은 허용하지 않습니다.')
    return value


def velocity(store):
    groups = defaultdict(list)
    for row in store.db.execute('SELECT * FROM metric_samples WHERE expires_at>? ORDER BY observed_at', (stamp(),)):
        groups[(row['source'], row['url'], row['metric'])].append(dict(row))
    results = []
    for (source, url, metric), samples in groups.items():
        intervals = []
        for left, right in zip(samples, samples[1:]):
            hours = (parse_date(right['observed_at']) - parse_date(left['observed_at'])).total_seconds() / 3600
            delta = right['value'] - left['value']
            intervals.append({'from': left['observed_at'], 'to': right['observed_at'], 'hours': hours,
                              'delta': delta, 'per_hour': delta / hours if hours > 0 and delta >= 0 else None,
                              'status': 'counter_reset_or_correction' if delta < 0 else 'descriptive_rate'})
        results.append({'source': source, 'url': url, 'metric': metric, 'samples': len(samples),
                        'intervals': intervals[-12:], 'acceleration_verified': False,
                        'confounders_to_check': ['baseline', 'seasonality', 'paid_distribution', 'one_off_news', 'definition_change'],
                        'boundary': '동일 대상·정의의 관측 간 증가율. 고유 사용자·한국 수요·플랫폼 전체 성장 아님.'})
    return results


def economics(payload):
    rows = payload.get('scenarios')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        raise ValueError('scenarios: 가격·원가 가정을 달리한 1~12개 시나리오가 필요합니다.')
    result = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('name') or not row.get('basis'):
            raise ValueError('각 시나리오에 name과 basis(관측/견적/가정의 출처)를 적으세요.')
        values = {k: number(row.get(k), k) for k in ('price_krw', 'variable_cost_krw', 'service_cost_krw',
                  'cac_krw', 'orders_per_customer', 'customers', 'fixed_cost_krw', 'working_capital_krw')}
        contribution = values['price_krw'] - values['variable_cost_krw'] - values['service_cost_krw']
        per_customer = contribution * values['orders_per_customer'] - values['cac_krw']
        result.append({'name': row['name'], 'basis': row['basis'], 'inputs': values,
                       'contribution_per_order_krw': contribution, 'contribution_per_customer_krw': per_customer,
                       'break_even_customers': math.ceil(values['fixed_cost_krw'] / per_customer) if per_customer > 0 else None,
                       'operating_result_krw': per_customer * values['customers'] - values['fixed_cost_krw'],
                       'cash_after_working_capital_krw': per_customer * values['customers'] - values['fixed_cost_krw'] - values['working_capital_krw'],
                       'status': 'assumption_scenario_not_forecast'})
    return {'scenarios': result, 'unit': 'KRW over the user-specified scenario period',
            'missing_adjustments': ['tax', 'refunds', 'payment_timing', 'capital_expenditure', 'financing']}


def compare(payload):
    """Fail closed across mismatched metric definitions/cohorts/normalization."""
    left, right = payload.get('left', {}), payload.get('right', {})
    required = ('definition', 'unit', 'population', 'normalization', 'period_seconds', 'format', 'age_bucket', 'channel_cohort')
    missing = [k for k in required if left.get(k) in (None, '', 'UNKNOWN') or right.get(k) in (None, '', 'UNKNOWN')]
    mismatches = [k for k in required if left.get(k) != right.get(k)]
    if missing or mismatches:
        return {'comparable': False, 'missing': missing, 'mismatches': mismatches, 'change_ratio': None}
    a, b = number(left.get('value'), 'left.value'), number(right.get('value'), 'right.value')
    return {'comparable': True, 'absolute_change': b-a, 'change_ratio': b/a-1 if a else None,
            'low_base': a < 10, 'demand_verified': False}


def latency(payload):
    fields = ('published_at', 'provider_available_at', 'collected_at', 'reviewed_at', 'notified_at')
    dates = {k: parse_date(payload.get(k)) for k in fields}
    for k in fields:
        if payload.get(k) is not None and (dates[k] is None or dates[k] > now()):
            raise ValueError(k + ': 실제 발생한 시각만 입력하세요.')
    previous = None
    for k in fields:
        if dates[k]:
            if previous and dates[k] < previous:
                raise ValueError('시간 순서가 맞지 않습니다. 수집일과 발행일을 구분하세요.')
            previous = dates[k]
    return {'timestamps': {k: stamp(v) if v else None for k, v in dates.items()},
            'seconds': {a + '_to_' + b: (dates[b]-dates[a]).total_seconds() if dates[a] and dates[b] else None
                        for a, b in zip(fields, fields[1:])}, 'missing_times_are_unknown': True}


def evaluate(rows):
    """All registered cases stay in denominators, including pending and failed runs."""
    counts = {'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0, 'pending': 0, 'failed': 0}
    leads, scores = [], []
    for row in rows:
        if row.get('state') == 'failed':
            counts['failed'] += 1
        if row.get('truth') not in (True, False) or type(row.get('truth')) is not bool:
            counts['pending'] += 1
            continue
        predicted = row.get('detected') is True
        counts[('t' if predicted == row['truth'] else 'f') + ('p' if predicted else 'n')] += 1
        if row.get('probability') is not None:
            probability = number(row['probability'], 'probability')
            if probability > 1:
                raise ValueError('probability: 0~1 범위입니다.')
            scores.append((probability - int(row['truth'])) ** 2)
        if predicted and row['truth'] and row.get('detected_at') and row.get('baseline_at'):
            leads.append((parse_date(row['baseline_at']) - parse_date(row['detected_at'])).total_seconds())
    return {'registered': len(rows), **counts,
            'precision': counts['tp'] / (counts['tp']+counts['fp']) if counts['tp']+counts['fp'] else None,
            'recall_within_registered_truth_set': counts['tp']/(counts['tp']+counts['fn']) if counts['tp']+counts['fn'] else None,
            'mean_brier': sum(scores)/len(scores) if scores else None, 'brier_n': len(scores),
            'mean_lead_seconds': sum(leads)/len(leads) if leads else None, 'lead_n': len(leads),
            'boundary': '등록된 평가 집합 내 결과. 모든 트렌드의 재현율·통계적 우월성·인과 효과 아님.'}
