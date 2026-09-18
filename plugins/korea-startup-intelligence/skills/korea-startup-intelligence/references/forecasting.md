# 한국 트렌드 선행 예측과 검증

트렌드를 남보다 먼저 발견한다는 목표를 실제 사전 예측과 만기 결과로 검증할 때 사용한다.
현재 인기 목록을 미래 예측으로 바꾸지 않고, 선행 지표의 확산 경로·반례·목표 사건·기한·판정 원문을 먼저 고정한다.

## 1. 예측 후보 준비

```text
trend-forecast prepare --limit 12
```

실제로 본문을 검토한 source review를 주제별로 묶어 원생산자와 신호 계열을 표시한다.
원생산자 2개·신호 계열 2개·실제 사건일이 있어야 forecast_ready_structure가 참이다.
이는 수요나 미래 확산이 확인됐다는 뜻이 아니다. metric_changes는 동일 대상의 저장 스냅샷 변화이며 플랫폼 전체 성장률이 아니다.
prepare는 예측을 자동 등록하지 않는다.

## 2. 사전 예측 등록

`trend-forecast register --file forecast.json`은 다음을 변경 불가 기록으로 저장한다.

- key, question, domain_id, stage.
- cutoff와 미래 deadline. 기간은 1일~3년이다.
- probability, baseline_probability, decision_threshold. 양성 예측이면 cutoff 이하의 실제 detected_at.
- evidence_ids와 counterevidence_ids. 실제 원문을 읽은 현재 근거만 사용하며 cutoff 이후 자료는 거부한다.
- counter_search와 confounders. 광고·계절성·뉴스·낮은 기저·수집 변경 등 가능한 설명을 적는다.
- target: metric, operator(gte/lte/eq/increase_by), value, unit, population, geography, observation_window, source_plan.
- leading_indicator_chain 2~6단계. 각 단계는 signal, status(INFERENCE/ASSUMPTION/UNKNOWN), evidence_ids, expected_next다.
- review_schedule_days 1~90일.

확률은 주관적인 사전 예측이며 지금의 정확도를 뜻하지 않는다. 기준 확률은 단순한 비교 모델로 함께 고정한다.
원생산자/신호 계열이 각각 2개 미만이거나 연결된 반례가 없으면 structural_gaps가 남고 알림 적격이 아니다.
같은 예측을 수정하지 않고 새 정보로 판단을 바꾸면 새 key를 등록한다.

## 3. 관찰과 만기 판정

`trend-forecast status`는 watching/review_due/overdue_unresolved를 구분한다. team-queue에도 재검토·만기 과제가 나타난다.
재검토는 새 근거와 반례를 읽는 작업이며 기존 확률을 소급 변경하지 않는다. 후속 예측을 새로 만들 수 있다.

deadline 이후 실제 판정 원문을 다시 읽고 다음을 실행한다.

```text
trend-forecast resolve --file result.json
```

result는 forecast_id, state(completed/failed/unresolved), outcome, baseline_at, evidence_ids, limitations를 가진다.
completed는 true/false와 deadline 이후 재검토한 근거가 필요하다. true면 목표가 실제 발생한 cutoff~deadline 사이 시각을 baseline_at에 넣는다.
failed/unresolved는 outcome=null이며 분모에서 삭제되지 않는다.

## 4. 정확도와 선행시간

`trend-forecast evaluate`는 모든 등록 예측을 분모로 유지하고 다음을 계산한다.

- TP/FP/FN/TN, pending, failed, precision, 등록 truth set 안의 recall.
- 주관 확률의 평균 Brier와 고정 기준 확률의 평균 Brier 차이.
- 확률 구간별 평균 예측과 실제 발생률.
- 양성 적중의 detected_at→baseline_at 평균 선행시간.
- 분야·단계·30/90/180/365일/다년 기간별 결과.

만기 완료 30건 미만이면 예측 능력을 주장하지 않는다. 30건 이상도 등록한 주제 집합 안의 결과이며,
한국의 모든 트렌드에 대한 정확도나 인과 효과가 아니다. 놓친 트렌드를 분모에 넣으려면 고정된 기준 주제 집합과 음성 사례를 함께 사전 등록해야 한다.

