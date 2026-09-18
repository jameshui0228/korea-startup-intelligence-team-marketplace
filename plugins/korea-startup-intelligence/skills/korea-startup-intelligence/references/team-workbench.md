# 자연어 창업 작업대와 팀 조사

이 참조는 팀 조사, 시작·재개, 비교·평가·복구에 사용한다. `ksi.py --workspace WORKSPACE` 뒤에 아래 명령을 붙인다.
사용자에게 JSON을 작성하라고 넘기지 않는다. Codex가 대화와 기존 자료로 양식을 채우고, 중요한 가정과 결과를 보여 준다.
사용자 진술·읽은 자료·모델 가설을 구분하고 모르는 값은 null/UNKNOWN으로 남긴다. 검증기가 필수 사실을 요구하면 사실을 만들지 말고 다음 조사로 남긴다.

## 한 번의 조사 흐름

1. `workbench start`로 기존 답·진행 중 세션·최근 변경·우선 미지수를 읽는다. 사용자의 목표를 탐색(explore), 검증(validate), 지원서(apply), 재개(resume)에 연결한다.
2. FOUNDER_CONTEXT.md와 wb_founder를 함께 읽는다. 불일치 시 최신 진술의 날짜와 이유를 확인한다. 예산·지역·접근 가능한 고객 중 지금 판단을 바꾸는 질문만 묻는다. 무응답을 동의나 사실로 바꾸지 않는다.
3. `workbench template session`으로 목표·시간·요청·컨텍스트·저장·비용 상한을 계획한다. 별도 LLM API는 필요 없다. 실제 모델 비용을 알 수 없으면 null로 두고 비용 준수를 보장하지 않는다.
4. `research-work plan`에서 기존 미지수와 새 시장을 함께 고른다. 결정 영향·불확실성·조사 비용·창업자 적합성을 wb_unknown에 기록한다. 휴리스틱 우선순위는 성공확률이 아니다. 관심 분야만 반복하지 말고 적어도 하나의 새로운 분야를 남긴다.
5. 담당자는 `research-work start --task-id ID --actor 별칭`으로 작업한다. 다른 담당자의 진행 중 작업은 가져오지 않는다. 24시간 내 재개하거나 `research-work handoff --run-id ID --actor 현재담당 --to-actor 새담당 --note 인계이유`로 넘긴다.
6. `workbench capabilities`로 접근 가능한 경로를 확인한다. 원문 URL/허용 파일을 `workbench intake --file 접수.json`에 넣는다. 접수는 읽기나 evidence 등록이 아니다. 실제 열람 후 기존 import-evidence/review-source 계약으로 근거를 기록한다.
7. 근거→반례→한국 대안→사업 가설→값싼 실험 순으로 작업한다. 탐색 신호는 wb_signal에 남기고, dossier/venture/opportunity의 엄격한 품질 검사를 우회하지 않는다.
8. `workbench template checkpoint`의 completed/remaining/blockers/next_action과 실제 소요·요청·수동 개입을 기록한다. 상한 초과면 새 수집을 멈추고 저장·인계한다. Python 검사는 보고된 값 기반이며 Codex 전체 사용량을 자동 계측하지 않는다.
9. 먼저 ‘새 판단 / 가장 강한 반례 / 다음 행동’ 세 가지를 간결하게 제시한다. 사용자가 자세히 보길 원하면 claim_review의 출처 위치·읽기 범위·시각·한계를 펼친다. 재생성한 보고서만으로 새 성과라고 알리지 않는다.

## 저장과 수정

`workbench template KIND`는 입력 필드와 빈 초안을 반환한다. `workbench save --file FILE`은 kind, actor, role, expected_revision, data를 받는다.
기존 기록은 `workbench checkout wb_KIND ID`의 expected_revision과 data를 사용한다. 새 기록은 expected_revision=0이다.
founder는 같은 ID를 갱신해 기존 답을 유지한다. 일부 답만 바꾸려면 전체 최신 data를 먼저 읽고 변경 필드만 수정한다.
기존 dossier/application/grant/venture_review 수정도 checkout의 revision을 각 save 입력 최상위 expected_revision에 넣는다.
application resume는 이를 포함한다. 충돌하면 `workbench diff KIND ID --revision 이전번호`로 차이를 보고 최신본에 수동 병합한다. 재조회 없이 revision만 바꾸지 않는다.

actor는 비식별 별칭이다. role의 reader/researcher/reviewer/owner 검사는 **로컬 작업 역할**이며 로그인·파일 접근 보안이 아니다.
같은 OS 계정 사용자는 역할을 변경할 수 있다. 원격 RBAC가 구현됐다고 설명하지 않는다.
검토는 wb_review에 작성자·검토자·의견·독립 여부를 남긴다. 다른 actor 문자열만으로 독립성을 입증하지 않는다. 같은 모델 역할극은 independent=false다.
문장별 의견은 wb_comment의 claim_locator에, 결정은 wb_decision의 이유·재개 조건에 연결한다. subject_snapshot이 당시 버전과 해시를 보존한다.

## 신호 수집과 비교

- watchlist: 플랫폼·분야·관찰 계정/URL·선정 이유·재검토일·접근 근거. 관찰 목록은 연결 설정이 아니다. 선행 기여는 benchmark/ablation으로 따로 평가한다.
- YouTube: 허용된 채널의 실제 uploads playlist ID를 config의 youtube_upload_playlists에 넣고 사용자가 연결을 원하는 경우 youtube_uploads를 enable한다. 새 어댑터는 기본 비활성이다. 한 요청은 첫 20개 항목, 회차 최대 두 목록이며 페이지 추가 요청을 숨기지 않는다. 정해진 요청 상한과 캐시를 따른다.
- 형식: Shorts/일반/라이브를 실제 확인한 범위에서 기록한다. 재생 길이나 세로 화면만으로 확정하지 않는다. UNKNOWN 형식은 동종 비교 통과 불가다.
- 댓글: 공개 열람/허용 내보내기에서 범위·추출 방법·표본 수를 먼저 정한다. 사용자명·연락처는 저장하지 않고 사용 경험/불편/구매 질문을 자기 말로 요약한다. 인기순 표본·인센티브·조직적 반응 가능성을 기록한다. 키워드 횟수는 고객 수가 아니다. 자동 댓글 대량 수집은 제공하지 않는다.
- 영상 내용: 실제 시청 구간, 허용 녹취/자막의 시간 위치를 기록한다. 자막 다운로드 권한이나 전체 영상 열람을 가정하지 않는다.
- Instagram/X/TikTok/Threads/Reddit: 공개 웹 원문·허용 내보내기 접수 경로를 사용한다. 직접 수집 어댑터/승인/비용 계약 없이 연속 감시라고 표시하지 않는다. Instagram 소비자 전체·X 전체 아카이브·무키 스트림을 약속하지 않는다.
- 비SNS: 가격표·발주/입찰·채용·업무 양식·납품 요건·매장 운영·반품/취소를 확인한다. 판매자 홍보는 실제 고객 행동 근거와 분리한다.
- `workbench velocity`: 시각별 누적 집계의 차이/실제 경과 시간을 반환한다. 감소는 카운터 정정/초기화 가능성으로 표시한다. 봇이나 수요 감소라고 자동 판정하지 않는다.
- `workbench compare --file FILE`: left/right 각각 value, definition, unit, population, normalization, period_seconds, format, age_bucket, channel_cohort를 받는다. 조건 누락/불일치는 비교를 거부한다. 낮은 기저·광고·계절·단발 뉴스는 별도 검토한다.
- `workbench latency --file FILE`: published_at/provider_available_at/collected_at/reviewed_at/notified_at의 실제 시각만 쓴다. 모르는 단계는 null, 시간대 없는 날짜는 KST로 해석되므로 가능하면 명시적 시간대를 사용한다.
- 가속 주장은 같은 정의·모집단·정규화의 완료된 연속 세 구간, 기저·계절·광고 반증이 필요하다. velocity만으로 acceleration_verified를 true로 바꾸지 않는다.

## 근거 품질과 한국 시장

wb_claim_review에서 주장·원문 위치·생산자·발언 역할·supports/contradicts/context·해석·범위 한계·반례 검색을 기록한다.
숫자가 가리키는 모집단·단위·기간과 주장의 범위를 직접 대조한다. 스키마 통과는 의미의 진실성을 증명하지 않는다.
wb_origin은 번역/재인용/보도자료의 원 생산자와 확인 정도를 연결한다. 원 생산자가 같은 자료는 독립 근거로 세지 않는다. 의미가 비슷하다는 이유만으로 삭제하지 않는다.
wb_metric_definition에 원/천원/백만원, 계정/사람/구매자, 누적/기간, 모집단, 통계 시점·개정·업종 코드를 남긴다.
가격·접수 마감은 행동 직전 공식 재확인, 빠른 신호는 짧은 간격, 구조 통계는 새 판본 시점으로 재검토한다. 사용자 보류·공급자 캐시/한도가 우선이다.
wb_source_change로 정정/삭제/만료를 남기고 `workbench impact EVIDENCE_ID`로 연결 주장과 하위 문서·실험을 재검토한다.
첨부는 페이지/표/각주/OCR 확인 범위를 wb_attachment_review에 기록한다. OCR 숫자는 원본 시각 대조 전 확정하지 않는다.
wb_market_scope에는 지역·대상 집단·갱신 목표·관찰 채널·미지수를 기록한다. 서울 표본을 전국으로 확장하지 않는다.
교차 분야 dossier는 하나의 고객 문제에 여러 domain_ids를 연결한다. 분야 연결 건수와 독립 dossier 수를 별도 보고한다.
wb_glossary에 의미·별칭·제외 의미·실측 쿼리 적합률을 저장하고 `workbench queries --query 용어`로 후보를 가져온다. 실제 적합률을 측정하기 전 null이다.
wb_competitor는 시점별 가격/기능/고객/수작업 대안/전환 이유를 누적한다. 갱신은 checkout/diff를 사용한다.
wb_policy는 proposal/announced/enacted/effective/open/closed를 구분한다. 기사만 읽고 법 적용이나 신청 자격을 확정하지 않는다.

## 보관·공유·복구

`workbench backup`은 SQLite 일관 백업과 무결성 검사를 수행한다. 비밀 설정은 포함하지 않지만 연구 내용 자체는 비공개일 수 있다.
`workbench restore-copy --file 백업 --destination 새절대경로`는 기존 폴더를 덮어쓰지 않고 네트워크 소스를 비활성화한 복원본을 만든다. 원본 설정·개인 파일까지 복원하는 전체 컴퓨터 백업은 아니다.
`workbench merge-preview --file 다른DB`는 같은 기록·신규 후보·내용 충돌만 표시하고 쓰지 않는다. domain save 계약을 통해 명시적으로 병합한다.
`workbench export --file FILE`은 summary/public_urls/actor/privacy_reviewed=true를 받는다. 원시 DB·고객 메모·키·설정을 복사하지 않는다. 요약 자체의 비밀정보도 직접 검토한다. 패턴 필터는 완전한 개인정보 탐지기가 아니다.
macOS는 선택적으로 KSI_USE_KEYCHAIN=1이면 서비스 `korea-startup-intelligence:워크스페이스절대경로`, 계정=허용 키 이름에서 읽는다. 플러그인은 키체인 항목을 생성/이전하지 않는다. 환경변수→키체인→비공개 파일 순서다. 값을 출력하지 않는다.
메타데이터·집계의 기존 28일 만료를 유지한다. 새로 수집한 날짜로 오래된 사건을 새 사실처럼 만들지 않는다.

## 성능을 검증하는 방법

wb_benchmark에 질문·당시 cutoff·미래 deadline·고정 기준선·판정 규칙·쿼리·규칙 버전·플랫폼·분야·탐지 여부·사전 확률·당시 이용 가능 근거를 등록한다.
결과를 본 뒤 사례/쿼리를 고른 회고 분석은 prospective 증거가 아니다. retrospective 표시와 no_lookahead_proven=false를 유지한다.
마감 후 wb_benchmark_result에 truth(true/false/null), state(completed/failed/unresolved), 실제 baseline_at, 판정 근거·한계를 연결한다.
`workbench evaluation`은 전체 등록 분모, TP/FP/FN/TN, 미판정, 실패, Brier, 비교 가능한 선행 시간과 플랫폼·분야별 결과를 보여 준다. 실패와 미판정은 겹칠 수 있다.
실제 팀 사용 시험은 wb_usability에 익명 참가자·동일 과제·수동/플러그인 조건·시간·근거 누락·재작업·오인용·개입·완료·품질 확인 근거를 남긴다. 합성 테스트를 팀 실사용으로 저장하지 않는다.
wb_ablation은 같은 과제와 cutoff에서 소스를 뺐을 때 추가 가치/비용을 비교한다. 자기 보고 결과는 인과 효과 증명이 아니다.
등록만으로 우월성·SNS보다 빠른 탐지·지원사업 성공을 주장하지 않는다. 실제 검증 없는 항목은 [100개 완료 기준](improvement-register.md)에 대기로 남긴다.

## 실행 가능한 추가 조사 도구

모든 명령은 기존 `ksi.py --workspace WORKSPACE workbench` 뒤에 붙인다. 자연어 요청을 Codex가 입력으로 변환하며, 모르는 숫자는 추정 사실로 채우지 않는다.

- `workflow`: dossier별 미지수·보류 상태·창업 검토·지원서 존재를 읽고 다음 작업을 반환한다. 추천된 단계는 외부 연락이나 제출 권한이 아니다.
- `research-qa`: 모든 dossier의 현재 근거를 다시 읽지 않고 구조적으로 감사한다. 만료·변경 원문, 핵심 주장의 독립 원생산자 수, 반례 연결, 한국의 수작업/시장 대안, 핵심 미확인 항목, 한 출처 의존도를 dossier별로 보여 주고 최대 100개 보완 작업을 우선순위로 반환한다. 출처 내용의 진실성을 자동 판정하지 않는다.
- `team-queue`: research-qa, 재검토 기한, dossier 다음 단계, 공모전 후보 차단/근거 공백, 피드백, 미해결 코멘트를 하나의 로컬 작업 큐로 합친다. 최대 100개를 표시하며 담당자 배정·고객 연락·지원서 제출은 하지 않는다. `workbench start`에도 상위 10개가 표시된다.
- `due-reviews`: 경쟁사 7일, 정책/신호 24시간, 관찰 목록의 review_after, 시장 범위의 refresh_target_hours를 기준으로 재확인 대기열을 만든다. 실제 원문을 읽기 전 검토일은 바꾸지 않는다. 가격·공고는 실행 직전 재확인이 추가로 필요하다.
- `duplicates`: 최대 500개 관측에서 URL 일치 또는 제목 토큰 유사도 0.7 이상인 후보 최대 100쌍을 반환한다. 원 생산자 동일성이나 의미 중복을 확정하지 않고 자동 병합하지 않는다.
- `usability`: 저장된 실제 사용 시험을 과제·조건별로 집계한다. 완료율·평균 소요 시간·누락·재작업·오인용·수동 개입과 고유 참가자 수를 보여 준다. 불완료 시험을 분모에서 빼지 않는다.
- `sampling --file FILE`: invited/responded/eligible/completed/friends/incentivized/self_selected 정수 인원으로 응답률·완료율·편향 특성 비중을 계산한다. 편향 특성은 완료자 기준이며 서로 겹칠 수 있다. 대표성은 검증되지 않는다.
- `ablation-compare --file FILE`: baseline/without_source 각각 task/cutoff/truth_set/rules_version이 같아야 cost/true_positives/false_positives/lead_seconds의 차이를 계산한다. 동일 조건 표시만으로 인과 효과를 인증하지 않는다.
- `cashflow --file FILE`: opening_cash_krw와 시간순 periods를 입력한다. 각 기간은 ends_at/basis 및 customer_receipts/financing/other_receipts/supplier_payments/payroll/marketing/tax/refunds/capex/debt_service/other_payments를 원 단위로 명시한다. 비용이 실제로 없을 때만 0을 쓴다. 기말 현금·첫 부족 시점·최대 부족액을 계산한다. 매출을 입금으로 자동 간주하지 않는다.
- `comment-sample --file FILE`: video_id/public_source_verified=true로 공개 YouTube 영상 한 개의 최신 최상위 댓글 최대 20개를 명시적으로 조회한다. 기존 YOUTUBE_API_KEY가 없으면 수동 원문 검토 경로를 반환한다. 자동으로 실행하거나 기본 레이더에 추가하지 않는다. 시간당 최대 3회, 동일 영상 1시간 이내 재시도 금지, 실패/중단도 한도에 포함한다. 본문은 최대 240자 발췌로 반환하고 작성자 필드를 제외하며 원문은 DB에 저장하지 않는다. 발췌의 개인정보 패턴 가림은 완전한 익명화가 아니므로 공유 전 검토한다. 차단·권한 오류는 우회하지 않는다. [공식 commentThreads.list 문서](https://developers.google.com/youtube/v3/docs/commentThreads/list)의 제한을 따른다.

`impact`는 dossier→지원서→검토→댓글처럼 여러 단계로 연결된 기록도 방문 중복 없이 추적한다. 연결하지 않은 자연어 언급은 자동 탐지하지 않는다.

## SNS 접수와 선택적 X 연결

`workbench social-import --file FILE`은 추가 API 키 없이 실제 검토한 SNS 자료의 비식별 요약을 한 번에 접수한다.
입력은 actor, privacy_reviewed=true, items(1~50개)이며 각 항목은 platform, url, observed_at,
read_scope, collection_basis, summary, limitations를 포함한다. platform은 instagram/x/threads/tiktok/youtube/reddit다.
플랫폼 도메인과 공개 원문 URL을 대조하고, 전체 입력을 먼저 검증한 뒤 일괄 저장한다. 중간 오류가 나면 일부만 저장하지 않는다.
동일 URL은 기존 요약을 덮어쓰지 않는다. 수정은 workbench checkout/save로 처리한다.
이것은 직접 스크래핑이나 전체 SNS 감시가 아니다. 다른 사람의 글 전체·DM·개인 프로필을 넣지 않는다.

`workbench x-preview --file FILE`은 query 하나로 X 공식 최근 검색의 첫 페이지 최대 10개 URL/발행일을 반환한다.
본문·작성자 정보·페이지 토큰은 저장하거나 반환하지 않는다. 반환 URL을 실제 열어 읽기 전에는 metadata_only다.
기본 비활성이며 지금 제공된 설정과 예약 레이더에는 활성화하지 않는다.
사용자가 X 비용과 사용을 명시적으로 승인했을 때만 config.json의 x_read_access에 enabled=true,
user_approved_paid_reads=true, provider_spend_cap_confirmed=true, daily_request_limit(1~10)을 설정한다.
공급자 지출 상한은 실제 공급자 설정을 확인한 뒤에만 true다. 요청 수 한도 자체는 금액 상한이 아니다.
X_BEARER_TOKEN은 기존 비공개 키 파일/환경변수/선택적 키체인으로만 읽는다. 채팅에 입력받지 않는다.
실패·429·인증 오류·중단은 자동 재시도를 차단한다. 실패 영수증을 지우거나 성공으로 바꿔 해제하지 않는다.
`workbench x-status`는 원문·키·검색어를 출력하지 않고 미해결 실패 ID와 분류를 보여 준다.
사용자가 원인 확인 후 재개를 명시적으로 요청한 경우에만 `workbench x-recover --file FILE`을 사용한다.
입력은 attempt_id, actor, resolution_summary, user_confirmed_resume=true, billing_and_access_checked=true다.
401/403 또는 확인된 응답 형식/부분 응답 오류만 대상으로 하며, 기존 실패 기록은 그대로 두고 별도 복구 이력을 추가한다.
복구 명령은 네트워크 요청을 하지 않고 일일 한도도 초기화하지 않는다. 429·중단·원인 불명은 이 명령으로 해제할 수 없다.
복구 승인 플래그는 사용자의 실제 승인과 확인을 반영해야 한다. 플러그인 개발 요청만으로 실서비스 재개를 승인받았다고 기록하지 않는다.
공식 범위 근거: [X Recent Search](https://docs.x.com/x-api/posts/search/quickstart/recent-search).
Instagram 직접 API 어댑터와 승인 절차는 여전히 미구현이다. social-import를 그 대체 구현 완료로 계산하지 않는다.

## 입력 오류와 시작 화면

CLI 입력 오류는 원래 검증 메시지에 code/next_action을 더한다. JSON 오류는 값 대신 행/열을,
파일·SQLite 오류는 민감 경로 대신 확인할 항목을 보여 준다. 예외를 성공으로 바꾸거나 자동 재실행하지 않는다.
`workbench start`에는 기존 기록과 함께 next_work(최대 6개 다음 작업), due_reviews(원문 재검토 대기열)가 포함된다.
추천 작업을 실제 수행하거나 자료를 재확인하기 전에는 완료·최신 상태로 표시하지 않는다.
