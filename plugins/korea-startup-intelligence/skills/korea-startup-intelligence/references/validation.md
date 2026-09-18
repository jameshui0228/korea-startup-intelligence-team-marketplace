# 사전 실험과 실제 관측

실험 제안, 등록, 실행, 관측은 다르다. 이 명령은 로컬 기록만 수행하며 고객 연락·광고·결제·API 사용·개발을 실행하지 않는다.
고객 실험은 사용자가 허용한 범위에서만 수행한다. 응답·매출·거절을 만들어 채우지 않는다.

## 사전 계획

`validation plan --file 계획.json`은 기존 dossier에 실험을 연결한다. 수집 시작 전에 등록해야 하며
등록 후 지표·표본·기간·기준을 바꿀 수 없다. 변경된 실험은 새 key와 replaces_plan_id로 연결하고 이전 계획을 남긴다.
같은 입력 재실행은 unchanged이며 결과를 새로 만들지 않는다.

필수 필드:

- key: 소문자/숫자/하이픈 3~100자. ID는 validation- + key.
- dossier_id, hypothesis, method, population, recruitment, collection_plan, safety_stop: 구체적인 문자열.
- starts_at, ends_at: 시간대가 있는 ISO 시각. 예: `2026-10-01T09:00:00+09:00`. 실제 실험에 맞는 미래 기간을 정한다.
- budget_krw: 0 이상의 정수. 지출 승인이 아니라 계획이다.
- evidence_ids: 계획의 배경 자료 ID 배열. 빈 배열도 허용하며 dossier 외 자료를 재사용하지 않는다.
- metric: definition, aggregation(rate/mean), unit, direction(higher/lower), min_sample, pass_threshold, stop_threshold.

rate는 성공 건수 / 관측 대상 수이며 unit은 fraction, 기준은 0~1이다. mean은 총 측정량 / 표본 수이며
unit은 1인당 분·원 등 평균의 단위다. 현재 자동 채점은 **음수가 아닌 비율·평균**만 지원한다.
다른 통계량·정성 인터뷰·추적 중인 시계열은 dossier에 분석하고 억지로 비율로 바꾸지 않는다.
높을수록 좋은 지표는 pass > stop, 낮을수록 좋은 지표는 pass < stop이며 사이 값은 inconclusive다.
최소 표본 수는 1~1,000,000이다. 이것은 시스템 입력 범위이지 적절한 연구 표본 수를 보장하지 않는다.

## 실제 결과

마감 후 `validation result --file 결과.json`. 성공 사례뿐 아니라 실패·불충분·미실행도 남긴다.

필수: plan_id, execution_status(completed/not_run), summary, counterevidence, limitations(문자열 1~12개),
cost_krw(보고된 실제 비용), data_quality_issues(문자열 0~12개).
completed에는 measurement와 evidence_links가 추가로 필요하다.

measurement는 numerator, denominator, unit, collected_from, collected_to.
분모는 관측 표본 수이며 성공한 고객만 선택한 분모가 아니다. rate의 분자는 정수 성공 건수이고 분모 이하다.
수집 기간은 사전 계획 안에 있어야 한다. 기간 일부만 관측했거나 표본 미달·자료 품질 문제가 있으면
수치가 좋아도 inconclusive로 기록한다. 유리한 중간 결과를 보고 조기 통과시키지 않는다.
심각한 안전 문제가 있으면 실제 활동은 즉시 중단한다. 점수를 위해 계속하지 말고 중단 사유와 부분 관측을 마감 후 기록한다.

evidence_links는 1~12개이며 각 항목은 evidence_id, basis, locator, note.
basis는 direct_customer / observed_behavior / transaction / aggregate_measurement.
실제 측정 원자료를 익명화/집계한 **사용자 소유 또는 허용된 내보내기**로 등록하고, 원문 해당 부분을 검토해야 한다.
자료 날짜는 보고한 수집 기간에 들어가야 한다. 기사·판매자 주장·조회수 제목을 실험 결과로 바꾸지 않는다.
자료 준비에는 기존 `import-evidence`, `radar review-source`를 사용한다. 비밀키나 개인 고객 식별정보를 넣지 않는다.
not_run에는 summary에 미실행 이유를 남기며 measurement나 실험 성공 근거를 붙이지 않는다.

결과의 outcome은 시스템이 사전 기준과 비교해 criterion_met / stop_criterion_met / inconclusive / not_run으로 계산한다.
같은 결과의 재실행은 멱등이며 숫자·해석의 덮어쓰기는 거부한다. 원자료 오류를 발견하면 연결된 feedback으로
오류를 명시하고 후속 실험을 별도 등록한다. feedback의 subject_id에는 validation-로 시작하는 계획 ID를 넣는다.
원래 결과와 피드백이 status 및 후속 조사에 함께 남으며, 오류를 자동으로 교정한 측정치처럼 표시하지 않는다.
잘못된 결과를 삭제하거나 성공 사례만 다시 계산하지 않는다.

`validation status`는 **전체 등록 실험**의 진행/결과 분모와 실패·미실행을 보여준다.
`--dossier-id`로 한 후보만 확인할 수 있다. 자료가 오래되면 재확인 필요를 표시하되 과거 결과는 보존한다.
결과 기한이 지난 실험은 research-work plan의 후속 작업에, 전체 상태는 일/주/월 보고서에 연결된다.
기존 record experiment 메모는 이 분모에서 제외한다.

이 검증기는 수치·날짜·단위·참조·사전 기준 일관성을 검사한다. 원자료의 진실성, 표본 대표성,
통계적 유의성, 인과관계, 전 시장 유료 수요를 자동으로 입증하지 않으며 idea를 supported로 자동 승격하지 않는다.
