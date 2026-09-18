# 근거 연결형 조사 작업대

전 분야 탐색·Deep Dive·근거 보완·기존 아이디어 재평가 때 사용한다. 기사 모음과 제품 설명을 고객 검증으로 바꾸어 부르지 않는다.
실행은 `python3 "PLUGIN/scripts/ksi.py" --workspace "WORKSPACE"` 뒤에 아래 명령을 붙인다.

## 조사에서 사업 가설로

1. `research-work plan --limit 6`과 기존 `list dossier`, `list opportunity`, `list feedback`을 읽는다.
   최대 절반은 기존 조사의 가장 중요한 미지수, 나머지는 덜 조회한 분야다. 16개 발상 원리와 10개 사업 구조는 **질문 재료**이지 사업기회가 아니다.
   의미상 동일한 주제는 기존 key를 유지한다. 실패/거절 피드백도 판단에 반영하되 검증된 사실로 바꾸지 않는다.
   후속 과제에는 해당 dossier의 창업자 검토·실험 상태가 함께 표시된다. 마감된 실험은 새 가설보다 실제 결과 기록을 우선한다.
2. 실제 고객의 행동·문제·현재 지출, 한국의 대안, 반대 자료를 우선 조사한다. 해외 성공 사례만으로 국내 공백을 선언하지 않는다.
   조사를 시작할 때 `research-work start --task-id plan의ID`로 질문과 시작 시점을 고정한다.
   같은 진행 중 작업을 start하면 재개되며, 선택만 했다고 조사 완료로 기록하지 않는다.
   한 번에 끝내기 어려우면 미확인 항목을 남기고 다음 회차에서 보완한다. 고객 연락·구매·유료 데이터 확대는 별도 요청 전 실행하지 않는다.
3. 실제 읽은 자료를 `radar review-source`로 저장한다. 원 생산자·읽은 범위·날짜·짧은 자기 말 요약을 남긴다.
4. 아래 형식으로 `research-work save --file "조사.json"`을 실행한다. 24개 항목의 누락은 자동 UNKNOWN이며 채우기 위한 숫자/근거를 만들지 않는다.
5. `ready_for_opportunity_alert`가 false면 blocking_gaps가 다음 행동이다. 기록은 남지만 텔레그램으로 보내지 않는다.
   통과해도 **조사한 사업 가설**이지 유료 수요 검증·사업 성공이 아니다. 새 변화가 있는 카드만 별도 `radar submit`으로 저장한다.
6. `research-work quality`는 오래된 카드까지 현행 기준으로 재검사한다. `research-work graph --node "dossier-ID"`는 출처↔판단↔분야의 연결을 보여 준다.
   지식 그래프는 검토자가 입력한 typed edge이며 자동 인과 추론이 아니다.
7. `research-work complete --file 조사결과.json`으로 이번 범위의 조사 결과를 남긴다. 아래 조사 이력 계약을 따른다.

## 조사 이력·재검토

complete 필수: run_id(start가 반환), outcome(investigated/no_evidence/blocked), summary, next_action,
limitations(1~12 문자열), evidence_ids(0~40), dossier_ids(0~6).
investigated는 실제 본문 검토 자료와 같은 분야/문제의 dossier가 필요하다. 전체 산업의 조사 완료나 수요 검증을 뜻하지 않는다.
blocked는 blocker(access/source_unavailable/customer_permission/budget/scope)가 필요하며 하지 않은 검색을 지어내지 않는다.
no_evidence는 search_log가 필요하다. 결과 없음은 사업 기회/경쟁자가 없다는 결론이 아니다.
search_log 항목은 query, channel, checked_at(이번 시작 이후 실제 시각), outcome(read/no_results/access_limited), read_evidence_ids.
read는 본 receipt의 근거 ID에 연결한다. 이 로그는 검토자 진술이며 실제 검색 원문 검토를 대신하지 않는다.

revisit_after_hours는 1~720 정수; 기본 investigated 72시간, no_evidence 24시간, blocked 168시간.
같은 근거·같은 판단이면 그때까지 다음 plan에서 잠시 제외하고 새 분야를 고른다. 관련 원문·dossier·피드백·실험 변화가 있으면 먼저 다시 연다.
단순 수집 시각 갱신이나 작은 조회수 변화는 새 학습이 아니다. `--revisit`는 사용자가 원할 때 이 대기만 우회하며 조사/연락 권한을 주지 않는다.
완료 receipt는 변경 불가이고 같은 제출은 멱등이다. 새로운 판단은 새 회차로 남긴다.
`research-work history`에 미실행/중단/재개·조사·자료 부족·접근 제한을 구분한다.
24시간 지난 미완료는 interrupted로 표시하고 다시 시작할 수 있다. 중단을 성공으로 세지 않는다.
coverage와 market-map의 조사 receipt 분모는 API 조회 횟수 및 고객 실험 결과와 분리한다.

## 조사 입력 계약

필수:

- `key`: 같은 고객·문제를 식별하는 소문자/숫자/하이픈 3~100자. 결과 ID는 `dossier-` + key.
- `title`, `topic`, `target`, `problem`, `decision_reason`: 빈 문자열 금지.
- `domain_ids`: 실제 taxonomy ID 1~6개, `evidence_ids`: 최근 다시 읽은 유효 자료 ID 1~40개.
- `decision`: research / test / park / reject. park·reject는 기존 알림도 차단한다.
- `counterarguments`: 만들지 말아야 할 이유와 실패 조건 1~12개.

`findings`의 항목은 `status`, `conclusion`, `links`로 구성한다.

```json
{
  "status": "UNKNOWN",
  "conclusion": "기존 도구를 바꿀 만큼 실제 비용이 발생하는지 아직 확인하지 못했다.",
  "links": []
}
```

status는 FACT / INFERENCE / ASSUMPTION / UNKNOWN. FACT·INFERENCE에는 context가 아닌 실제 지지·반박 연결이 필요하다.
각 link에는 `evidence_id`, `relation`(supports/contradicts/context), `basis`, `locator`(페이지/표/절), `note`(이 자료가 그 판단을 뒷받침/반박하는 이유)를 넣는다.
basis는 direct_customer / observed_behavior / official_research / official_rule / provider_claim / analyst_inference / measured_series.
자료의 성격을 정직하게 붙인다. 판매자의 기능 소개는 provider_claim이며 이용자의 실제 고통이나 지불의사로 분류하지 않는다.
같은 문장을 여러 칸에 넣는 것으로 근거가 늘어나지 않는다. 검증기는 의미의 진실성까지 증명하지 않는다.

24개 항목:

```text
problem_severity, problem_frequency, market_size, market_growth,
willingness_to_pay, competition, differentiation, timing,
technology_leverage, distribution, retention, network_effect,
data_moat, brand_moat, regulatory_risk, mvp_feasibility,
capital_intensity, scalability, global_potential, korea_fit,
current_workaround, team_fit, supply_access, support_fit
```

마스터의 20개 평가 요소와 4개 실행 질문이다. 현재는 항목별 근거 평가이며 24항목 종합 성공확률을 계산하지 않는다.
`evidence_backed_dimensions / 24`는 명시적인 FACT·INFERENCE 항목 수일 뿐 정보의 완전성·정확도·사업성이 아니다.

`search_audit`는 실제 검색 0~20개: query, market(KR 등), channel, checked_at, read_evidence_ids, limitations.
검색 결과가 없었다면 그 제한을 적고, 읽은 대안 없이 “한국에 없다”고 결론 내리지 않는다.
`competitors`는 실제 조사한 대안 0~20개: name, market, kind(direct/indirect/manual/platform), advantage, switching_barrier, evidence_ids.
고객이 쓰는 수작업도 경쟁이다. 찾아보지 않은 기업의 매출·점유율·가격을 채우지 않는다.

## 현행 알림 기준

모두 있어야 기회 알림 대상으로 올라간다.

- 유효한 동일 고객·문제 dossier, 관계있는 분야, 핵심 dossier 근거를 빠뜨리지 않은 카드.
- 실제 고객 자료/관찰/공식 연구에 연결한 문제의 심각성·현재 해결 행동·지불 근거.
- 한국 적합성 근거, 최근 14일 실제 국내 검색 기록, 검토한 한국 대안, 갈아탈 이유의 근거.
- 읽은 원문 생산자 2개 이상 + 신호 계열 2개 이상 + 최근 14일 날짜가 확인된 실제 변화.
- 기본 카드의 고객·지불자·MVP·반례·실험·미지수. 성장 가속 주장에는 별도 시계열 조건.

이 기준은 알림용 최소 조사 기준이다. 탐색 가설은 더 적은 근거로 로컬에 저장할 수 있다. 보류를 피하려고 자료 성격을 바꿔 입력하지 않는다.
빈 알림은 정상이다. 단, 같은 질문만 반복하지 말고 실제로 얻을 수 없는 증거라면 접근이 필요한지, 고객 조사 승인이 필요한지 기록한다.

## 누적 검토

`research-work pain`은 이미 읽은 요약에서 불편/수작업 표현을 찾아 후속 검토 후보를 만든다.
분모는 서로 다른 원 생산자이며 사람 수·고객 빈도·감정 분석이 아니다. 현재 대량 SNS 본문 분석기는 없다.

`research-work report --period daily|weekly|monthly`는 최근 1/7/30일의 9섹션 보고서와 조사 공백·연결 상태·피드백을 만든다.
`research-work maintenance`는 사용자가 요청한 수동 실행에서 KST 일/ISO 주/월이 바뀌었을 때 해당 로컬 보고서만 갱신한다.
보고서 생성은 알림이나 scheduler를 만들지 않는다. 명시적으로 원할 때 언제든 report로 갱신할 수 있다.
주간에는 반례·사용자 피드백·실험 결과, 월간에는 분야 편중·소스 품질·적중/실패 분모를 검토한다.
현재 보고서는 최신 rolling-window 자료이며 장기 플랫폼 데이터 보유권·예측 성능·모델 학습을 보증하지 않는다.

실패·거절은 `record feedback`, 사전 실험/관측은 `validation plan`/`validation result`, 사전 예측과 관측은 `record forecast`/`resolve`로 분리한다.
사업 대안은 [창업자 검토](venture-review.md), 실험 계약은 [사전 실험과 결과](validation.md)를 읽는다.
정확도는 결과와 비교 기준이 생긴 뒤 평가한다. 코드·가중치·유료 계약·스케줄을 스스로 바꾸지 않는다.
