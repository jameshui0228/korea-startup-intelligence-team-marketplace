# 지속 레이더와 텔레그램

> 레거시 기록 설명: v0.7.0의 기본 제품은 수동 `on_demand` 모드이며 새 heartbeat 실행을 거부한다.
> 사용자가 향후 자동화를 명시적으로 다시 요청하는 경우에만 별도 범위로 검토한다. 현재 핵심 흐름은
> [API 키 없는 수동 공개 웹 조사](on-demand-public-web.md)를 따른다.

## 운용 경계

이 모드는 사용자가 반복 조사·아이디어 생성·알림을 요청한 경우에만 사용한다.
코드는 스스로 LLM을 호출하지 않는다. 현재 Codex 작업 또는 공식 예약 작업이 원문 읽기와 추론을 담당한다.
플러그인을 설치했다는 이유만으로 예약 실행이 켜지지 않는다. macOS cron/launchd/백그라운드 루프를 별도로 설치하지 않는다.
사용자의 주기가 있으면 앱의 공식 자동화 도구로 같은 작업의 heartbeat를 만들거나 기존 것을 갱신한다.
이 상태 폴더를 사용하는 로컬 작업은 컴퓨터와 앱의 가동이 필요하다. 30분은 점검 주기이며 정보원 갱신이나 알림 도착시간 보장이 아니다.

분석 지침은 `trend-radar.md`, `ideation.md`, `research-workbench.md`를 함께 읽는다. 미래 예측·지불의사·시장 공백·지원사업 선정은 검증 전 가설이다.
탐색 가설도 로컬에 저장할 수 있지만 텔레그램 선별은 동일 문제의 24항목 dossier, 고객 문제·현재 행동·지불 근거,
실제 한국 검색·대안·전환 이유와 원문 생산자 2개/신호 계열 2개/최근 날짜가 확인된 변화를 요구한다.
이는 구조 검증이며 원문 독립성·인과관계·사업성의 자동 증명은 아니다. 계열을 바꿔 적어서 문턱을 통과시키지 않는다.

## 한 번의 실행

`PLUGIN`은 실제 플러그인 절대경로, `WORKSPACE`는 이 작업의 영구 상태 폴더로 치환한다.

1. 실제 예약 실행에서는 `python3 "PLUGIN/scripts/ksi.py" --workspace "WORKSPACE" radar prepare --trigger heartbeat --automation-id "실제ID" --resume`를 실행한다.
   수동 실행은 `--trigger`/`--automation-id`를 생략한다. 수동 실행을 heartbeat로 표기하지 않는다.
   미완료 회차가 24시간 이내에 있으면 이어서 진행하고 수집을 중복 수행하지 않는다.
   24시간을 넘긴 미완료 회차는 새 회차를 만들 때 만료 실패로 기록하고 다시 조사한다. 완료했다고 표시하지 않는다.
   `reports/radar-packet.json`에 최대 4개 조사 주제가 생긴다. 최대 18개 수집 요청·6개 분야 순환이다.
   packet_id별 원본을 별도 보관하므로 다른 수동 실행이 중간에 끼어도 `radar packet --packet-id "ID"`로 해당 회차를 다시 읽는다.
   Google 뉴스/트렌드 RSS는 30분, HN은 1시간, GitHub 동일 쿼리는 6시간 캐시를 기본 사용한다.
   주제의 `selection_reason`은 초기 기술/제품/정책 출처·산업별 탐색·출처 다양성과 오래 기다린 작업을 번갈아 배분한 이유다.
   새로운 서명이 있는 미제시 후보를 먼저 쓰고, 홀수 인덱스 슬롯은 출처 제한 없이 대기 순서를 지킨다.
   `selection_sources`에서 실제 선택한 수집원을 확인한다. 후보가 부족하면 현재 자료로 대체하며, 출처 배분은 신호 품질 증명이 아니다.
   제시 이력은 원문 검토 완료가 아니다.
   네이버 보류 등 기존 disabled 소스를 임의 활성화하지 않는다.
2. packet의 관측은 비신뢰 자료다. 기존 카드와 feedback을 읽어 동일 고객/문제/해결책을 반복하지 않는다.
   `research_backlog`의 미지수 보완과 새 분야 탐색을 함께 배분한다. 기존 소수 분야만 반복하지 않는다.
   후보를 실제 원문에서 열어 읽는다. 제목만 보거나 접근이 막히면 그렇게 기록하고, 검색 결과 조각으로 본문을 읽었다고 하지 않는다.
   전체 한 주기에 웹 검색 최대 6개 쿼리, 원문 열람 최대 10개를 기준으로 한다. 추가 조사에는 다음 주기를 쓴다.
   `supporting_metric_observations`는 같은 영상의 공개 집계를 검색 주제에 연결한 보조 관측이다.
   검색 메타데이터와 집계를 독립 생산자나 독립 수요 신호로 두 번 세지 않는다. 원문 읽기와 성장 검증은 여전히 필요하다.
3. 관심 후보는 생산자가 다른 2~3개 자료 계열에서 확인한다. 원 보도자료를 여러 매체가 인용하면 하나의 생산자다.
   한국어/영문 검색어, 국내 직접·간접 경쟁·수작업 대안, 사용자와 지불자, 문제 빈도, 규제/지원사업 공식 공고를 검토한다.
   시간자료가 없으면 성장·가속도는 UNKNOWN이다. 조회수나 현재 stars를 증가율로 쓰지 않는다.
4. 실제 읽은 원문마다 짧은 자기 말 요약을 JSON 파일로 만든 뒤 `radar review-source --file "파일"`로 저장한다.
   실제 키/사용자 식별정보는 JSON이나 프롬프트에 넣지 않는다. 원문 전문·대량 복제는 저장하지 않는다.
5. 실제 판단과 반례를 먼저 `research-work save --file "조사.json"`으로 기록한다. 미확인은 UNKNOWN으로 남는다.
   근거가 새 사업 가설에 충분할 때만 dossier_id를 연결한 구체 카드 0~2개를 작성한다. 판정이 나면 주제별 `radar submit --file "파일"`을 실행한다.
   전체 packet의 새 카드 합계는 2개 이하다. 약한/무관한 주제는 no_opportunity 또는 insufficient_evidence로 종료한다.
   실패/거절/반례도 기록한다. 조회 없는 분야를 검토 완료로 표시하지 않는다.
6. `radar finish --packet-id "이번ID"`로 대기 메시지 미리보기와 검토 완료 여부를 확인한다.
   실제 읽은 내용·수신 대상·문구를 검토한 뒤 `radar finish --packet-id "이번ID" --send`로 회차를 마친다.
   이 명령이 현행 품질 재검사 → 블루오션 포트폴리오 승계·판단 변화 브리핑 → queue → preview → deliver → maintenance와 완료 영수증을 처리한다.
   레이더 카드가 포트폴리오로 옮겨져도 조사 가설 상태와 원본 근거 성격을 유지하며 자동으로 validating/building 단계로 올리지 않는다.
   검토하지 않은 주제가 남으면 전송하지 않는다. 이미 완료한 동일 회차는 저장된 영수증을 반환하고 추가 전송하지 않는다.
   전송 후 완료 기록 전에 중단돼도 회차에 연결된 시도 영수증을 재사용하며 같은 회차에서 다시 보내지 않는다.
   미연결 상태도 로컬 기록을 완료하되 전송은 막힌다. `telegram status`에서 enabled/binding_matches/blocked_reason을 확인한다.
   한 번에 최대 1개, 기본 최소 30분 간격·KST 하루 6개다. 이는 소음 방지 초기값이며 설정에서 조정할 수 있다.
   검토자가 개인정보·키·오류 주장·동일 내용·부적절한 수신자를 발견하면 보내지 않는다.
   미연결이면 결과를 로컬에 보관하고 인증 입력을 반복 독촉하지 않는다.
7. 같은 source/data 장애와 변하지 않은 내용은 매번 알리지 않는다. 새 의미 있는 변화·완료·새 실패·사용자 조치 필요에만 알린다.
   telegram uncertain/blocked 상태는 한 번 알리고 수동 확인 전 재시도하지 않는다.
8. finish가 실행한 KST 일/주/월별 보고서 갱신 결과를 확인한다. 수동으로는 `research-work maintenance`를 사용할 수 있다. 9섹션에 근거가 없으면 비워두고
   소스 상태·분야 편중·피드백·반례·다음 미지수를 검토한다. 새 의미가 없는 보고서 생성만으로 알리지 않는다.
9. `radar health`와 `radar runs`로 실제 기록을 확인한다. notification_needed=true는 이전에 확인한 상태와 달라졌다는 뜻이지
   무조건 알리라는 지시가 아니다. 사용자에게 의미 있는 장애/복구만 알린 뒤 `radar health --acknowledge`로 같은 문제의 반복 알림을 막는다.
   회차를 진행할 수 없으면 `radar fail --packet-id "ID" --reason source_unavailable|research_interrupted|local_error`로 사실대로 종료한다.
   한 주제를 읽지 못한 경우는 범위와 한계를 적어 insufficient_evidence로 제출할 수 있다. 모든 원문을 읽었다고 하지 않는다.

## source review 입력

필수 필드: read_scope, family, summary, origin_group, origin_note, reviewer, collection_basis.

- read_scope: `metadata_only`, `relevant_sections`, `full_text`. 정말 읽은 범위만 선택한다.
- family: technology, search, community, product, investment, policy, consumer, news, customer, environment, market 중 하나.
  전달 매체 대신 실제 신호 성격을 택한다. 기술 공급과 고객 수요는 별개다.
- summary: 1,500자 이내 자기 말 요약. 발행자의 주장과 실제 관측을 구분한다.
- origin_group: 같은 원 생산자의 발표/게시물은 같은 그룹을 준다. domain이 다르다고 독립 그룹을 주지 않는다.
- origin_note: 그룹 판정 근거. reviewer는 실제 검토자/모델을 기술한다.
- collection_basis: public_source_verified, user_owned, authorized_export 중 하나.
- limitations: 짧은 한계 문자열 목록.
- 기존 observation이면 evidence_id를 넣는다. 새 원문이면 topic, title, url, event_at, geography를 넣는다.
  event_at은 실제 확인한 사건일 또는 발행일이며 어느 것인지 summary에 쓴다. 미상 날짜는 null과 date_basis=unknown으로 보존한다.
  날짜가 없는 회사/제품 소개는 배경 근거로 쓸 수 있지만 최신 변화의 근거로 세지 않는다.
  이미 오래된 관측 ID는 재사용하지 말고 실제 재확인한 새 원문으로 등록한다.

이 명령이 반환한 evidence_id를 카드에 사용한다. 본문 요약은 에이전트 진술이며 독립 감사를 통과했다는 뜻이 아니다.

## opportunity 카드 입력

필수 텍스트 필드:
`title`, `summary`, `why_now`, `growth_evidence`, `korea_status`, `korea_gap`, `problem`, `target`, `payer`,
`current_alternative`, `solution`, `mvp`, `first_users`, `monetization`, `moat`, `competition_risk`, `regulatory_risk`, `support_fit`.
title은 140자, 나머지는 1,200자 이내다. 모르는 필드는 UNKNOWN과 구체적으로 부족한 근거를 쓴다.

기타 필수:

- opportunity_key: 같은 고객·문제·해결책에 재사용하는 영문 소문자·숫자·하이픈 키. 기존 packet 카드와 대조한다.
- stage: Weak Signal / Emerging / Accelerating / Mainstream / Saturated / Unknown.
- confidence: limited / medium / high. 성공 확률이 아니다.
- evidence_ids: 원문 검토 ID 1~12개; domain_ids: 실제 taxonomy ID 1~6개.
- business_models, global_players, korea_players, contrarian, watch_signals, unknowns: 각 1~12개 문자열 목록.
- next_experiment: hypothesis, method, pass_condition, stop_condition 문자열과 timebox_days(1~90), budget_krw(0~10,000,000 정수).
  예산은 권고 상한의 가설이지 지출 승인이 아니다. 실제 인터뷰나 구매를 하지 않는다.
- claims: text, status(FACT/INFERENCE/ASSUMPTION/UNKNOWN), evidence_ids를 가진 객체 목록.
  FACT는 본문 검토가 필요하다. 기업의 제품 소개는 “그 기업이 이렇게 설명했다”는 사실이지 효능/수요가 입증됐다는 사실이 아니다.
- score_components: growth, cross_platform, novelty, global_diffusion, korea_fit, pain, commercialization, low_competition을 모두 포함.
  각 값은 `{value: null, reason: "부족한 근거"}` 또는 value(0~1), reason, scale, evidence_ids 객체다.
  근거가 빠진 하나라도 있으면 총점은 null이다. 숫자를 채우는 것이 목표가 아니다. 가중치는 25/15/10/10/15/10/10/5.
- korea_opportunity: Very High / High / Medium / Low / Unknown. 한국 검토가 부족하면 Unknown.
- change: kind, reason, evidence_ids. kind는 new, growth_change, major_company_entry, funding, technical_breakthrough,
  korea_entry, regulation, user_growth, business_model, counterevidence 중 하나. 기존 가설에 new를 반복하지 않는다.
  최근 14일 이내 실제 날짜가 있는 변화 근거를 최소 하나 포함한다. 오래된 원문을 오늘 수집해도 새 변화가 아니다.

Accelerating이면 growth_measurement도 필요하다: metric, unit, population, comparability_note, confounders,
normalization, low_base_assessment와 intervals 3~36개. 각 interval은 start/end/value/evidence_ids다.
완료된 같은 길이의 연속 비중첩 구간·양수 관측값으로 두 변화율을 계산하고 최근 변화율이 양수이며 이전보다 커야 한다.
두 시점은 변화이지 가속도가 아니다. 같은 모집단·정규화 조건을 직접 확인한다.
일시적인 증가만으로 가속이라고 하지 않는다. 계절성·낮은 기저·광고·수집변경 반증이 부족하면 Emerging/Unknown으로 낮춘다.

저장된 카드는 항상 hypothesis다. 사용량/구매/시장 결과가 쌓인 뒤 별도 검증 기록을 남긴다.
전체 상세는 `reports/opportunities.json`과 `reports/opportunities.md`, 간단 아이디어는 `list idea`에 누적된다.

## 주제 검토 제출

입력 객체: packet_id, topic, outcome, note, cards.
outcome은 hypothesis(카드 있음), no_opportunity 또는 insufficient_evidence(둘 다 빈 cards 배열).
packet의 topic과 ID를 그대로 참조한다. note에 실제 조사 범위·기각/유보 이유를 남긴다.
주제별 동일 제출은 멱등 처리된다. 같은 packet 주제를 다른 결론으로 바꾸려면 새 조사 packet을 만든다.
이전 가설을 단지 말만 바꿔 다시 알리지 않는다. 코드의 정확한 키/증거 중복 방지 외 의미 중복은 Codex가 검토한다.

## 텔레그램 연결 (최초 1회)

공식 규격 확인: 2026-09-17. [BotFather](https://core.telegram.org/bots/features#botfather),
[Bot API](https://core.telegram.org/bots/api#sendmessage).

1. `telegram init`으로 WORKSPACE/.telegram.env를 만들고 권한 600을 확인한다.
   Finder에서는 Command+Shift+.로 숨김 파일을 표시한다. 기존 네이버 .secrets.env와는 별도 파일이다.
2. 사용자가 공식 @BotFather에서 이 작업 전용 봇을 만들고 봇의 개인 대화에서 /start를 누른다.
   토큰은 로컬 파일의 TELEGRAM_BOT_TOKEN에 입력한다. 채팅/스크린샷으로 요청하지 않는다.
3. 사용자 입력 완료 후 `telegram discover`로 받은 대화 ID/유형/표시 이름만 조회한다.
   메시지 본문을 저장/출력하지 않고 offset을 진행시키거나 webhook을 제거하지 않는다.
   이 도구는 대화 선택을 자동 확정하지 않는다. 사용자 자신의 개인 대화임을 확인한다.
4. 확인된 숫자 chat_id를 TELEGRAM_CHAT_ID에 입력하고 `telegram verify`로 봇과 정확한 대화를 확인한다.
   이 호출은 전송하지 않는다. 다른 봇/토큰/대상으로 바뀌면 기존 전송 승인을 무효화한다.
5. 사용자가 요청한 개인 수신 대상이 확인되면 `telegram enable --confirm-chat-id "숫자ID"`를 실행한다.
   대상이 복수이거나 본인 여부가 불확실하면 먼저 묻는다. 임의 채널/그룹을 선택하지 않는다.
6. 실제 아이디어가 아직 기준을 통과하지 못했다면 `connection-check --confirm-chat-id "확인한 숫자ID"`로
   연결 시험임을 명시한 고정 문구 한 건을 queue에 넣을 수 있다. 같은 바인딩에서는 재생성되지 않으며 임의 메시지 기능이 아니다.
   `preview`, `deliver --send`로 실제 메시지 한 건만 보내고 message_id/수신 대화 응답을 확인한다.
   그 전까지는 “연결·수신 완료”라고 하지 않는다. 코드 테스트는 실제 수신 테스트가 아니다.
   연결 시험과 사업 아이디어 전송 수를 분리하고, 서버 응답이 사람의 읽음 확인을 뜻하지 않는다고 구분한다.

Telegram sendMessage는 HTTPS POST, 메시지 한 건 4,096자 이내로 사용한다. 인증 URL/원 오류 본문을 로그에 넣지 않는다.
인증 오류는 멈추고, 429는 retry_after 이후 별도 주기에 재시도한다. 타임아웃/5xx/응답 불명은 uncertain으로 남긴다.
Telegram에는 이 메시지를 위한 idempotency key가 없으므로 uncertain을 자동으로 pending으로 바꾸지 않는다.
수신함을 사람이 확인하고 명시적으로 재전송을 요청한 경우에만 별도 복구한다. 이전 sent 카드도 다시 보내지 않는다.

## 운영 상태와 명시적 복구

`telegram status`는 대기/전송/불명확/실패 건수, 확인할 ID, 다음 전송 가능 시각, 마지막 API 응답 시각을 보여준다.
`telegram history --limit 20`은 시도별 시각·결과·message_id를 보이며 키·수신 ID·메시지 본문은 제외한다.
API가 반환한 성공, 사용자가 직접 수신함에서 확인한 성공, 연결 시험, 실제 아이디어를 별도 집계한다.

전송 시도 전에 sending과 시도 기록을 저장한다. 중단된 sending은 다음 전송 처리에서 uncertain으로 전환한다.
불명확한 시도는 일일 한도와 최소 간격에 포함하고 같은 아이디어의 새 revision도 확인 전 발송하지 않는다.
429의 retry_after는 서버가 지정한 시간보다 줄이지 않는다. 만료·취소·구버전 항목을 건너뛰고 한 번에 유효 메시지 하나만 전송한다.
검토 카드와 대기 문구가 다르거나 알려진 API 키가 섞였으면 미리보기와 발송 모두 차단한다.

사용자가 자신의 수신함을 직접 확인한 경우에만 다음 복구를 실행한다. heartbeat는 이 명령을 실행하지 않는다.

```text
telegram resolve --alert-id 확인할ID --outcome delivered --confirm-chat-id 확인한숫자ID --note "사용자가 수신을 확인한 내용"
telegram resolve --alert-id 확인할ID --outcome not_delivered --confirm-chat-id 확인한숫자ID --note "사용자가 미수신을 확인한 내용"
```

두 명령 모두 네트워크 호출이 없다. 미수신 확인과 함께 사용자가 재전송까지 요청한 경우에만 `--retry`를 붙인다.
새 전송 시점에 근거·유효기간·한도·수신 바인딩을 다시 검사한다. 확인을 끝내지 않고 추적만 중단하려면 outcome=discard를 쓰며
실제 발송됐을 가능성이 있는 시도의 한도 계산은 지우지 않는다. 재인증/대상 변경은 기존 확인 절차를 따른다.

`telegram self-test`는 사용자가 요청한 설치/운영 점검에서만 사용한다. 현재 버전·확인된 수신 대상에 고정 시험 문구를 한 번 대기시킨다.
`telegram preview` → `telegram deliver --send`로 점검한다. 임의 문구 입력이나 기회 품질 기준 우회 기능이 아니다.
예약 실행은 self-test/connection-check/discover/verify/enable/resolve를 호출하지 않는다.

회차 이력의 trigger는 호출자의 표기다. 수동 완료와 자동 예약 실행 증거를 혼동하지 않는다.
로컬 앱/컴퓨터가 꺼져 있으면 이 상태 점검도 동작하지 않으므로 외부 장애 감시나 24시간 가동을 보장하지 않는다.

## 남은 범위

이 기능은 공개 수집원 + Codex의 실제 원문 검토 + 단방향 텔레그램 알림이다.
Instagram/TikTok/X/Reddit/투자/특허/채용 등 모든 플랫폼 API가 연결된 것은 아니다.
텔레그램 수신 명령·원격 관리 봇·유료 LLM 서버·24시간 외부 호스팅은 이번 구현에 포함하지 않는다.
장기 적중률·거짓 양성·고객검증 성과를 주간/월간으로 평가하여 데이터와 판단을 보정한다. 모델 자체 학습을 주장하지 않는다.
