# 허구김 · v0.6.1

한국의 약한 시장 신호에서 아직 충분히 해결되지 않은 고객 문제와 공급 공백을 찾고,
아이디어를 검증·실행하고 창업자 적합성·시간·예산·WIP·실험·출시 KPI·보류·폐기·재개까지 관리하는
개인용 Codex 창업 운영 에이전트 **허구김**.
기본 사용은 **추가 API 키와 예약 자동화 없이**, 사용자가 호출한 현재 Codex 작업에서 공개 웹 원문을 조사해
블루오션 탐색과 아이디어 포트폴리오 운영을 수행한다. 공모전·지원사업·협업은 명시적으로 요청할 때만 쓰는 선택 기능이다.
API는 수집 범위/빈도를 확장하는 선택 사항일 뿐 핵심 기능의 선행 조건이 아니며 사업 성공이나 예측 정확도를 보장하지 않는다.

사용자가 제시한 76개 개선 항목의 번호별 구현/부분/연결·실측 대기는 [ACCEPTANCE_76.md](ACCEPTANCE_76.md)에, 두 마스터 프롬프트의 대조는 [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md)에 있다.

## 지금 포함된 것

- blue-ocean 운영체제: 시장공백 8항목, 신호 6항목, 후보별 다음 행동·중단/재개 조건·상태 전이·판단 이력.
- detected → watching → researching → validating → building → launched → scaling 생명주기와 parked/killed 관리.
- 개인 창업 운영 프로필: 확인된 주간 시간·주간 예산·현금·보호 예비금·단계별 WIP 한도와 자동 운영 정책.
- 후보별 창업자 적합성: 역량·고객 접근·동기·시간·자본·도메인·규제 차원을 합산 점수 없이 비교.
- 자원 배분: 명시 우선순위·단계·기한을 따라 시간/예산/WIP를 배정하고, 미확인 요구량은 0으로 숨기지 않음.
- interview → MVP → pricing → GTM validation plan 의존성, 결과에 따른 다음 행동·기한·예산 자동 연결.
- 출시 이후 불변 KPI 정의와 사용자 소유 거래/집계 근거의 주간 snapshot·직전 주 변화.
- 주간 check-in과 CEO 브리핑: 실제 시간·지출·장애물·결정·KPI·집중 후보·다음 행동 통합.
- 규칙 기반 수동 운영 보조: 요청 시 WIP 초과/장기 미검토/적합성 충돌 보류, 사전 중단 기준 폐기,
  자리 확보 또는 폐기 이후 확인된 새 근거에 따른 재개. 외부 연락·지출·게시·출시는 자동 실행하지 않음.
- 경쟁사 검색 결과 0건을 블루오션으로 오인하지 않는 근거 게이트. UNKNOWN을 0점이나 임의 성공확률로 바꾸지 않음.
- 레이더 가설→블루오션 후보→dossier→수치/정성 검증 결과를 연결하고, 직전 브리핑 이후 달라진 판단만 보여 주는 개인 창업 포트폴리오.
- 기존 워크스페이스의 사용자 설정을 보존하면서 v0.6.1의 `on_demand`·API 무키 기본값을 채우는 안전한 설정 마이그레이션.
- 핵심 상태·포트폴리오·운영 조회는 읽기 전용 SQLite 연결을 사용해 수집 실행과의 쓰기 잠금 경합을 줄임.
- `signal web-plan`: 공개 SNS·채용·특허·표준·논문·기술 가격·조달·앱·커머스·펀딩·규제·KOSIS/ECOS를 API 키 없이 조사할 검색·원문 검토 계약을 만든다.
- `signal batch-import`: 실제 읽은 공개 원문 1~50개를 모두 검증한 뒤 원자적으로 저장하고 관련 후보를 즉시 재평가한다.
- `blue-ocean run`: 선택 무키 소스 수집→공개 웹 조사 계획→기존 opportunity/dossier 승계→후보 재평가→변화 브리핑을 한 번에 준비. Codex가 같은 사용자 요청 안에서 원문을 읽고 검토 자료를 접수한다.
- `blue-ocean bootstrap`: 고객 실험 결과가 0건이어도 핵심 주장/반례표, 대안·공개 가격 감사, 연락 전 채널 지도, null을 보존한 단위경제 가정 범위, 첫 검증 사전 기준을 만든다. 사업 순위나 가상 고객 결과를 만들지 않으며 `--apply`는 외부 행동 없는 로컬 작업 5개만 생성한다.
- 공개 웹 조사는 키 없이 실행하며, 실제 읽은 원문/허용 export를 날짜·생산자·읽은 범위·단위와 함께 일괄 접수한다. Crossref 등 무키 수집기는 보조 신호이고 KOSIS 등 키 기반 connector는 선택 사항이다. 공개 검색 표본을 직접 실시간 플랫폼 연결이나 전수조사라고 표시하지 않는다.
- 신호 그래프·수요/공급 불일치 후보·해외→한국 관측 시차·역방향/상시 문제 후보·산업 간 이전 질문과 광고/계절/봇 위험 표시.
- 개인 창업자 파일과 구조화 적합성, 설명형 파레토 비교, 월간 시간·예산, 후보별 작업 결과, 외부 행동 승인 상태, 인터뷰/MVP/가격/GTM 패키지, 계획 대비 실행 편차.
- 판단 변화 전후값·사유, 의미 중복 경고, 포화도 추적, 후보 검색/따라잡기, 9개 성능지표의 명시적 분모/미측정 상태.
- 사용자 원본 **400개 분야·3,559개 세부항목·89개 압축 분류**와 2개 마스터 요청의 원문/해시 보존.
- 기존 GitHub 조사 **177개 저장소 메타데이터 색인**과 실제 설계에 반영한 출처.
- 신규 GitHub·Hacker News·Crossref 최근 등록 논문 메타데이터·Google Trending RSS·Google News RSS 읽기 전용 수집.
- 기존 사용자를 위한 선택 connector: NAVER API HUB, YouTube, 기업마당, KOSIS 등록 표. 별도 키와 live 확인이 필요하지만 핵심 경로에서는 사용하지 않는다.
- 일부 분야만 반복하지 않는 순환 조사, 조회 성공/심층 검토 구분, 캐시·호출 예산·오류 상태.
- 원천/제목 중복 정리, 동일 요청 내 검색지수 변화/가속도/감소 후보, 신뢰도와 확산 단계 분리.
- 주장·문제·아이디어·실험·피드백·예측/관측 이력, 변경 없는 후보 알림 억제.
- 한국 경쟁/규제/시장/고객·MVP·GTM·지원사업·사업계획 검토를 위한 통합 스킬.
- 수동 레이더: 공개 웹 계획 → 원문 검토 → Codex 아이디어 생성 → 필수 근거/고객/MVP/반증 검증 → 가설 카드 저장. 스케줄러를 요구하지 않는다.
- 과거 텔레그램·예약 레이더 기록은 기존 사용자 호환을 위해 읽을 수 있지만 v0.6.1은 새 heartbeat 실행을 거부한다.
- 24항목 근거 연결형 dossier: 원문 위치·지지/반박·국내 검색·대안·미지수 → 다음 조사 과제.
- 고객 문제·현재 행동·지불·한국 대안·전환 이유가 없는 카드는 알림 제외. 전송 직전에도 재검사.
- 공식 공고 조건 대조: 필수 조건별 PASS/FAIL/UNKNOWN, 기준일·마감 시각·부분 검토·예외 한계 구분.
- 일/주/월 9섹션 로컬 보고서·분야/출처 공백·피드백·후속 조사. 2시점 증가는 가속으로 부르지 않음.
- market-map: 400분야의 저장 신호·원문 검토·조사·실험 공백을 구분하는 지도. 메타데이터만으로 트렌드 단계를 만들지 않음.
- research-work start/complete/history: 실제 조사·근거 미발견·접근 장애를 구분하고 새 근거/재검토 시점에 후속 조사로 복귀.
- gstack 적용 venture-review: 단계별 고객 질문, 현상 유지 포함 대안, 실패 경로, 유효한 답 재사용과 오래된 답 재검토.
- validation: 사전 기준과 실제 결과를 분리해 성공·실패·불충분·미실행을 보존. 수치 실험과 사전 코드형 정성 사례를 구분하며 고객 결과를 자동으로 만들어내지 않음.
- application: 근거가 연결된 본문·공식 평가항목·예산 합계·일정·발표·심사 Q&A·제출 전 점검을 JSON/Markdown으로 작성/검사.
- application resume/check/attest: 기존 초안을 보존하며 수정, 우선순위별 보완 과제, 발표/Q&A 출처 색인, 문서 버전에 연결된 재검토. 내용·공고·원문 해석 변경 시 이전 검토 표시 재사용 차단.

## 사용

새 Codex 작업에서 `$korea-startup-intelligence`를 선택하거나 “오늘 한국의 블루오션 후보를 찾고 다음 행동까지 관리해줘”라고 요청한다.
플러그인은 해당 프로젝트의 `korea_startup_intelligence` 폴더를 상태 저장소로 사용한다.
기존 상태가 있는 프로젝트에서 이어서 사용하면 누적 자료를 유지한다. 서로 다른 사업의 자료를 묻지 않고 합치지 않는다.

직접 실행:

```bash
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path init
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean onboard
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean run --topic "고객 문제" --limit 6
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean prepare --no-refresh --limit 6
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean sync
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean sync --apply
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean status
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean next
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean signals
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean patterns
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean portfolio
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean metrics
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean bootstrap --id CANDIDATE_ID
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean bootstrap --id CANDIDATE_ID --apply
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean brief
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator template profile
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator configure --file /absolute/founder-profile.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator status
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator plan
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator monthly
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator package --id CANDIDATE_ID --apply
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator task-board
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator variance
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator reconcile
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator reconcile --apply
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path operator weekly --week-start 2026-09-14
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path market-map --limit 400
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work plan --limit 6
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path domains --query "제조"
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path ideation-plan --limit 10
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path list idea
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path signal capabilities
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path signal web-plan --topic "고객 문제" --limit 12
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path signal template
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path signal import --file /absolute/reviewed-signal.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path signal batch-import --file /absolute/reviewed-signals.json
```

`/absolute/plugin/path`는 이 README가 있는 설치 폴더로, `/absolute/state/path`는 영구 상태 폴더로 바꾼다.
코드/배포 폴더에 키나 사업 데이터를 넣지 않는다. 데이터 분석은 Codex의 현재 모델이 수행하므로 별도의 LLM API 키는 요구하지 않는다.
현재 시장/공고는 Codex의 공개 웹 도구나 사용자 제공 최신 자료로 확인한다. 키 없음과 인터넷 없음은 다르다.
웹을 사용할 수 없을 때는 보유 자료의 날짜를 밝히고 초안 작업을 이어가며 최신 확인을 완료했다고 하지 않는다.
`signal web-plan`은 무키 공개 웹 조사, `refresh --topic "검색어"`는 선택적 무키/연결 소스 보완, `doctor`는 진단이다. 먼저 인증 설정을 해야 아이디어를 낼 수 있는 구조가 아니다.
Python 3.10+ 표준 라이브러리, macOS/Linux 지원. Windows의 파일 잠금은 별도 구현 전 미지원.

## 정확한 경계

블루오션은 경쟁 부재가 아니라 문제·현재 지출·공급 공백·시기·한국 적합성·고객 접근·전환 이유·반대 근거를 함께 검토한 가설이다.
후보는 `unproven`/`plausible`/`investigated`로 구분하지만 어느 상태도 성공확률이 아니다.
수집기는 기본적으로 제목·링크·집계지수를 수집한다. 자동 본문 완독기, 유료 SNS 데이터 무제한 수집기, 검색량/매출 추정기가 아니다.
중요 후보의 원문은 스킬이 별도로 열어 검토하고 결론과 증거를 저장한다. 400개 분야를 등록했다고 전 분야를 깊게 학습했다고 하지 않는다.
트렌드 휴리스틱은 통계적/예측적 검증이 아직 없다. 별도 실제 결과를 쌓아 기본 모델과 비교해야 한다.
창업지원·수상·투자·매출은 보장하지 않는다. 실제 고객·단위경제·경쟁·권리·규제 검증이 우선이다.

Google Trends 전체 API, Instagram/TikTok/X/Threads/Reddit, Product Hunt, K-Startup, ECOS,
특허/채용/앱 순위/커머스/투자 데이터의 **직접 자동 전수 수집**은 하지 않는다. 대신 접근 가능한 공개 원문을 현재 요청에서 조사해 검토·접수하며 플랫폼 전체 실연결과 구분한다.
네이버 구 쇼핑 검색 API가 종료된 상태이므로 이를 동작한다고 표시하지 않는다.
HWP/HWPX 생성·렌더링, 신청서 자동 제출, 고객 연락, SNS 게시, 결제는 본 CLI 기능이 아니다.

## 수동 갱신과 축적

허구김은 사용자가 부를 때만 실행한다. 예약 작업·heartbeat·cron·백그라운드 상주·자동 알림은 기본 제품에 필요하지 않으며 만들지 않는다.
한 번의 요청에서 공개 웹 조사 계획을 만들고, Codex가 실제 원문을 읽고, 검토 근거를 저장한 뒤 후보와 다음 행동을 재평가한다.
새 정보가 없으면 강한 트렌드를 억지로 만들지 않는다. 앱을 사용하지 않은 기간은 다음 호출에서 `catch-up`과 새 공개 웹 조사로 따라잡되,
그 사이 모든 변화를 소급 복원했다고 주장하지 않는다. 축적은 자료·판단·실험 결과 이력이며 모델 가중치 학습이나 코드 자동 변경이 아니다.

`radar prepare`를 사용하는 경우에도 수동 실행으로만 기록한다. `radar health`는 스케줄러 미설정이나 선택적 텔레그램 미연결을 장애로 표시하지 않는다.
단계·점수·원문 독립성은 검토자의 근거 있는 판단이며 구조 검증기가 사업성이나 인과관계를 자동 입증하지 않는다.

YouTube 연결 시 watch_topics가 비어 있어도 해당 회차의 분야 검색어 하나를 순환 조회한다.
검색은 실행당 최대 1회, `youtube_search_daily_limit` 기본 48회/KST일이며 캐시 재사용은 횟수를 소모하지 않는다.
이 로컬 상한과 실제 Google 프로젝트의 [Search Queries 할당량](https://developers.google.com/youtube/v3/docs/search/list)은 별개다.
영상 집계는 별도 최대 20개 ID/요청이며, 영상별 마지막 요청을 기준으로 캐시·오류 대기를 적용한다.
새 영상이 섞여도 아직 신선한 영상은 다시 조회하지 않으며, 반환되지 않은 ID도 조회 시도로 기록해 반복 요청을 막는다.
해당 검색 주제의 `supporting_metric_observations`에서 집계를 함께 읽는다. 같은 영상의 검색 결과와 집계는 독립 근거 두 개가 아니다.
전체 요청 예산도 적용한다. 모든 분야/영상의 실시간 전수 조사가 아니다.

## 다음 확장 우선순위

1. 블루오션 후보와 실제 고객·거래 결과를 연결해 보류·폐기까지 포함한 포트폴리오 판단을 개선.
2. 공개 웹 리뷰·채용·조달·특허·가격·품절·앱 원문의 비교 기준과 반례 검사를 강화.
3. 30/90/180일 결과로 거짓 양성·누락·계절성·기저와 한국 시장 진입 시차를 평가.
4. 자연어 요청에서 조사→저장→다음 행동→재평가까지 사용자가 내부 명령을 보지 않도록 단순화.
5. 공모전·지원사업·협업·Telegram은 핵심 탐색 흐름을 방해하지 않는 선택 모듈로 유지.

### 심층 조사 명령

```bash
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work plan --limit 6
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work save --file /absolute/reviewed-dossier.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work quality
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work maintenance
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work start --task-id research-domain-KR-001
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work complete --file /absolute/actual-research-receipt.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work history
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path venture-review prepare --dossier-id dossier-ID --stage pre_product
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path validation qualitative-plan --file /absolute/qualitative-plan.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path validation qualitative-result --file /absolute/qualitative-result.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path application prepare --dossier-id dossier-ID
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path application save --file /absolute/written-application.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path application check application-ID
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path application resume application-ID
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path application attest --file /absolute/actual-review-attestation.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path grants save --file /absolute/official-notice.json
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path grants match grant-ID --profile /absolute/confirmed-profile.json
```

입력 계약은 [조사 작업대](skills/korea-startup-intelligence/references/research-workbench.md)와
[공고 매칭](skills/korea-startup-intelligence/references/grant-matching.md)에 있다. 임의 예시를 실제 연구 자료로 저장하지 않는다.
`prepare` 출력은 Codex가 실제로 검토·작성할 자료이지 완성된 사업계획서가 아니다.
[개인 창업 운영](skills/korea-startup-intelligence/references/founder-operations.md)은 창업자 적합성,
자원/WIP, 실험 연결, KPI, 주간 CEO 브리핑과 자동 상태 관리의 입력·안전 경계를 설명한다.
[gstack 적용 방식](skills/korea-startup-intelligence/references/gstack-operating-model.md)과
[API 없는 지원사업 작업대](skills/korea-startup-intelligence/references/application-workbench.md)를 필요에 맞춰 사용한다.

검증 실행:

```bash
python3 -m unittest discover -s tests -v
```

외부 코드/README 전문을 재배포하지 않는다. 공개 데이터와 개별 서비스 약관·개인정보·콘텐츠 권리는 별도다.
