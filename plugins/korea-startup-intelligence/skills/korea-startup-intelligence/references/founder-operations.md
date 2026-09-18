# 개인 창업 운영 에이전트

## 목적과 경계

`operator`는 블루오션 후보를 한 명의 창업자가 실제 시간·현금·집중력 안에서 운영하도록 돕는다.
창업자 적합성, 주간 시간·예산, WIP, 검증 파이프라인, 출시 KPI, 보류·폐기·재개를 하나의 로컬 기록으로 연결한다.
성공확률 점수는 만들지 않으며 미확인 시간·비용을 0으로 간주하지 않는다.

자동화 대상은 **로컬 계획과 후보 상태**다. 고객 연락, 인터뷰 실시, MVP 제작, 광고, 게시, 결제, 출시,
계정 변경은 자동 수행하지 않는다. `--apply`는 확인된 운영 정책에 따른 로컬 상태 변경만 허용한다.

## 기본 운영 순서

1. `operator template profile`을 바탕으로 창업자가 확인한 주간 시간, 주간 예산, 필요하면 별도 월간 시간·예산, 총 현금, 보호 예비금,
   단계별 WIP 한도와 자동 운영 정책을 `operator configure --file FILE`로 저장한다.
2. 관심 후보마다 `operator template fit`을 작성해 역량·고객 접근·동기·시간·자본·도메인·규제 적합성을
   ALIGNED/PARTIAL/MISFIT/UNKNOWN으로 분리한다. agent_inference는 확인된 적합성으로 승격하지 않는다.
3. `operator template pipeline`으로 인터뷰→MVP→가격→GTM 단계와 기존 validation plan을 연결하고, 후보별 주간 목표·병목·결정기한을 기록한다. `operator package --id ID --apply`는 네 단계의 인터뷰 질문/수동 MVP/가격 시험/GTM 초안과 로컬 작업 4개를 생성하지만 실행하지 않는다.
4. `operator plan`에서 이번 주 집중 후보, 시간·예산 배분, WIP 초과, 미설정 정보를 확인한다.
5. `operator reconcile`로 변경 예정 상태를 먼저 보고, 사용자가 운영을 요청한 경우 `--apply`로 로컬 정책을 적용한다.
6. 출시 전 KPI 정의를 등록하고 출시 이후 허용된 측정 근거로 주간 snapshot을 쌓는다.
7. 월요일 기준 check-in과 `operator weekly`로 주간 CEO 브리핑을 만든다. `operator variance`는 계획 대비 시간·지출, `operator task-board`는 실제 완료/미완료를 구분한다. `operator monthly`는 별도로 확인된 월간 시간·예산만 배분한다.

## 창업자 적합성

`operator fit --file FILE`은 다음 일곱 차원을 보존한다.

- skills: 현재 직접 수행하거나 조달 가능한 역량
- customer_access: 이번 달 접근 가능한 실제 고객 경로
- motivation: 문제를 장기간 탐색·운영할 의지
- time: 주간 가용 시간과 후보 요구 시간
- capital: 주간 예산, 초기 자금, 보호 예비금
- domain: 산업 지식과 현장 언어
- regulatory: 책임·허가·보안·개인정보 조건 대응 가능성

각 차원은 rationale과 basis(user_confirmed/observed/agent_inference)를 가진다. 한 숫자로 합산하지 않는다.
필요 시간이 가용 시간을 넘거나, 주간 예산을 넘거나, 초기 비용이 보호 예비금을 침범하면 명시적 충돌로 남긴다.

## 자원 배분과 WIP

운영 프로필은 discovery/validation/build/growth별 WIP 한도와 전체 활성 후보 한도를 가진다.
집중 순서는 창업자가 명시한 `priority_order`를 최우선으로 하고, 없으면 출시·구축·검증·탐색과 가까운 기한 순이다.
이는 성공 가능성 순위가 아니라 이미 시작한 고객 약속과 비용을 보호하기 위한 운영 순서다.

파이프라인이나 fit에 시간·예산 요구가 없으면 자동으로 0시간·0원으로 배정하지 않고 `needs_setup`으로 남긴다.
WIP/시간/주간 예산을 초과한 후보는 미리보기에서 이유를 확인한다. 운영 정책의 auto_park_overflow가 켜져 있고
`reconcile --apply`를 실행하면 초과 후보를 삭제하지 않고 parked로 옮기며 이전 단계·다음 행동을 보존한다.
자리가 생기면 auto_reopen_wip 정책이 이전 단계를 복원한다. 단계별 기존 근거 게이트는 그대로 적용된다.

## 인터뷰→MVP→가격→GTM 연결

`operator pipeline --file FILE`의 네 track은 validation plan ID와 depends_on을 가진다.
기본 의존성은 interview → mvp → pricing → gtm이다. 필요하면 실제 사업에 맞게 비순환 의존성을 조정한다.

track 상태는 ready/planned/running/awaiting_result/inconclusive/passed/stopped/blocked다.
사전 결과가 criterion_met이면 다음 의존 단계가 열리고 stop_criterion_met이면 운영 정책에 따라 후보 폐기가 제안된다.
`reconcile --apply`는 현재 track의 사전 계획에서 후보 next_action과 기한·예산을 동기화한다.
실험이 없으면 다음 validation plan 작성이 행동으로 제시될 뿐 고객 실험을 실행했다고 기록하지 않는다.

auto_advance_gated_stages는 기존 blue-ocean 근거 게이트가 이미 통과한 researching→validating,
실제 criterion_met 결과가 있는 validating→building만 이동한다. launched/scaling은 사용자 소유 실행·거래/KPI 근거를
별도로 확인해야 한다.

## 출시 KPI

`operator kpi-plan --file FILE`은 building/launched/scaling 후보에 주간 KPI 정의를 사전 등록한다.
각 KPI는 안정적인 key, 이름, 계산 정의, 단위, 방향, 선택적 target/floor를 가진다. 계획은 불변이며 정의가 바뀌면 새 key를 쓴다.

`operator kpi-snapshot --file FILE`은 launched/scaling 후보에만 허용한다. 월요일 week_start와 모든 KPI 값,
사용자 소유 또는 허용된 transaction/aggregate_metric 근거가 필요하다. 같은 주차 snapshot을 덮어쓰지 않는다.
on_target/attention/below_floor는 사전 기준 비교일 뿐 회계감사, 성장 인과, 시장 검증이 아니다.
`operator kpi-defaults`는 activation/retention/gross margin/CAC/repeat purchase의 정의를 제공하지만 실제 분자·분모와 코호트 기간은 각 사업에서 사전 고정해야 한다.

작업은 `operator task`로 계획하고 `operator task-result`로 실제 결과/비용/근거를 별도 기록한다. 고객 연락·구매 같은 외부 행동은 `operator action`의 planned→approved→executing→completed/failed/cancelled 상태를 사용하며 approved에는 사용자의 명시적 확인이 필요하다. 상태 기록은 플러그인이 실제 외부 행동을 수행했다는 뜻이 아니다. 실패 패턴은 `operator failures`로 활성 후보의 유사 문제에 경고로만 연결한다.

## 주간 check-in과 CEO 브리핑

`operator checkin --file FILE`은 월요일 기준 한 주에 한 번 저장한다. 후보별 실제 사용 시간·지출,
완료 항목·장애물·결정(none/continue/park/kill/reopen)과 근거를 남긴다. 자기보고 운영 기록을 고객 수요로 바꾸지 않는다.

`operator weekly --week-start YYYY-MM-DD`는 다음을 `reports/founder-ceo-weekly.md`와 JSON으로 만든다.

- 이번 주 집중 후보와 배정 시간·예산
- 실제 check-in과 설정 한도
- 인터뷰/MVP/가격/GTM의 현재 단계
- 출시 KPI와 직전 주 변화
- 적용 예정 보류·폐기·재개·다음 행동
- 창업자가 직접 결정하거나 정보를 보완할 항목

`--apply`를 붙이면 설정된 정책의 로컬 변경도 적용한다. 레이더의 완료된 예약 회차도 운영 프로필이 있을 때 이 브리핑을
갱신하지만, 프로필이 없으면 설정 필요 상태만 남기고 후보를 바꾸지 않는다.

## 보류·폐기·재개

- parked: WIP/시간/예산 초과, 장기 미검토, 창업자 적합성 충돌, 주간 명시 결정. 삭제가 아니며 이전 맥락을 보존한다.
- killed: 사전 stop_criterion_met 또는 주간 명시 결정. 실패·반례·결과 ID를 남긴다.
- WIP 재개: 운영 에이전트가 보류한 후보에 자리가 생기면 이전 활성 단계와 다음 행동을 복원한다.
- 폐기 재개: `operator reopen-signal --file FILE`에 폐기 이후의 새 근거, 기존 reopen_condition과의 일치 설명,
  창업자 확인을 기록해야 한다. 다음 reconcile에서 researching으로 돌아가며 새 시장성 증명으로 취급하지 않는다.

모든 자동 변경은 blue_ocean_event와 founder_lifecycle revision에 남는다. 예상 revision이 다르면 충돌로 중단한다.
