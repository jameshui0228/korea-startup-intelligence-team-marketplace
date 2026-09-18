# 허구김 · v0.2.1

한국의 약한 시장 신호에서 아직 충분히 해결되지 않은 고객 문제와 공급 공백을 찾고,
아이디어를 검증·실행·보류·폐기까지 관리하는 개인용 Codex 창업 에이전트 **허구김**.
기본 사용은 **추가 API 키 없이 현재 Codex에서** 블루오션 탐색과 아이디어 포트폴리오 운영을 수행한다.
공모전·지원사업·협업·텔레그램은 명시적으로 요청할 때만 쓰는 선택 기능이다.
API는 수집 범위/빈도를 확장하는 선택 사항이며 사업 성공이나 예측 정확도를 보장하지 않는다.

요청 전체와 구현/절차/미연결 범위의 대조는 [REQUIREMENTS_COVERAGE.md](REQUIREMENTS_COVERAGE.md)를 확인한다.

## 지금 포함된 것

- blue-ocean 운영체제: 시장공백 8항목, 신호 6항목, 후보별 다음 행동·중단/재개 조건·상태 전이·판단 이력.
- detected → watching → researching → validating → building → launched → scaling 생명주기와 parked/killed 관리.
- 경쟁사 검색 결과 0건을 블루오션으로 오인하지 않는 근거 게이트. UNKNOWN을 0점이나 임의 성공확률로 바꾸지 않음.
- 오늘의 후보·판단 변경·마감 행동을 보여 주는 개인 창업 포트폴리오 브리핑.
- 사용자 원본 **400개 분야·3,559개 세부항목·89개 압축 분류**와 2개 마스터 요청의 원문/해시 보존.
- 기존 GitHub 조사 **177개 저장소 메타데이터 색인**과 실제 설계에 반영한 출처.
- 신규 GitHub·Hacker News·Google Trending RSS·Google News RSS 읽기 전용 수집.
- NAVER API HUB 뉴스/블로그/카페/검색어 트렌드, YouTube 검색/선택 영상 집계, 기업마당 공고 어댑터. 별도 키와 live 확인 필요.
- 일부 분야만 반복하지 않는 순환 조사, 조회 성공/심층 검토 구분, 캐시·호출 예산·오류 상태.
- 원천/제목 중복 정리, 동일 요청 내 검색지수 변화/가속도/감소 후보, 신뢰도와 확산 단계 분리.
- 주장·문제·아이디어·실험·피드백·예측/관측 이력, 변경 없는 후보 알림 억제.
- 한국 경쟁/규제/시장/고객·MVP·GTM·지원사업·사업계획 검토를 위한 통합 스킬.
- 지속 레이더: 출처별 TTL → 원문 검토 packet → Codex 아이디어 생성 → 필수 근거/고객/MVP/반증 검증 → 가설 카드 저장.
- 텔레그램 개인 대화/채널의 정확한 수신 대상 확인, 미리보기, 발송 대기열, 중복/요청 제한/오류 처리. 별도 봇 인증 필요.
- 회차별 조사 이력·중단 재개·완료 영수증, 전송 시도 이력, 이상 상태 변화 확인, 명시적 수동 복구.
- 24항목 근거 연결형 dossier: 원문 위치·지지/반박·국내 검색·대안·미지수 → 다음 조사 과제.
- 고객 문제·현재 행동·지불·한국 대안·전환 이유가 없는 카드는 알림 제외. 전송 직전에도 재검사.
- 공식 공고 조건 대조: 필수 조건별 PASS/FAIL/UNKNOWN, 기준일·마감 시각·부분 검토·예외 한계 구분.
- 일/주/월 9섹션 로컬 보고서·분야/출처 공백·피드백·후속 조사. 2시점 증가는 가속으로 부르지 않음.
- market-map: 400분야의 저장 신호·원문 검토·조사·실험 공백을 구분하는 지도. 메타데이터만으로 트렌드 단계를 만들지 않음.
- research-work start/complete/history: 실제 조사·근거 미발견·접근 장애를 구분하고 새 근거/재검토 시점에 후속 조사로 복귀.
- gstack 적용 venture-review: 단계별 고객 질문, 현상 유지 포함 대안, 실패 경로, 유효한 답 재사용과 오래된 답 재검토.
- validation: 사전 기준과 실제 결과를 분리해 성공·실패·불충분·미실행을 보존. 고객 결과를 자동으로 만들어내지 않음.
- application: 근거가 연결된 본문·공식 평가항목·예산 합계·일정·발표·심사 Q&A·제출 전 점검을 JSON/Markdown으로 작성/검사.
- application resume/check/attest: 기존 초안을 보존하며 수정, 우선순위별 보완 과제, 발표/Q&A 출처 색인, 문서 버전에 연결된 재검토. 내용·공고·원문 해석 변경 시 이전 검토 표시 재사용 차단.

## 사용

새 Codex 작업에서 `$korea-startup-intelligence`를 선택하거나 “오늘 한국의 블루오션 후보를 찾고 다음 행동까지 관리해줘”라고 요청한다.
플러그인은 해당 프로젝트의 `korea_startup_intelligence` 폴더를 상태 저장소로 사용한다.
기존 상태가 있는 프로젝트에서 이어서 사용하면 누적 자료를 유지한다. 서로 다른 사업의 자료를 묻지 않고 합치지 않는다.

직접 실행:

```bash
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path init
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean prepare --limit 6
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean status
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean next
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path blue-ocean brief
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path market-map --limit 400
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path research-work plan --limit 6
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path domains --query "제조"
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path ideation-plan --limit 10
python3 /absolute/plugin/path/scripts/ksi.py --workspace /absolute/state/path list idea
```

`/absolute/plugin/path`는 이 README가 있는 설치 폴더로, `/absolute/state/path`는 영구 상태 폴더로 바꾼다.
코드/배포 폴더에 키나 사업 데이터를 넣지 않는다. 데이터 분석은 Codex의 현재 모델이 수행하므로 별도의 LLM API 키는 요구하지 않는다.
현재 시장/공고는 Codex의 공개 웹 도구나 사용자 제공 최신 자료로 확인한다. 키 없음과 인터넷 없음은 다르다.
웹을 사용할 수 없을 때는 보유 자료의 날짜를 밝히고 초안 작업을 이어가며 최신 확인을 완료했다고 하지 않는다.
`refresh --topic "검색어"`는 선택적 수집 보완이고 `doctor`는 연결 진단이다. 먼저 인증 설정을 해야 아이디어를 낼 수 있는 구조가 아니다.
Python 3.10+ 표준 라이브러리, macOS/Linux 지원. Windows의 파일 잠금은 별도 구현 전 미지원.

## 정확한 경계

블루오션은 경쟁 부재가 아니라 문제·현재 지출·공급 공백·시기·한국 적합성·고객 접근·전환 이유·반대 근거를 함께 검토한 가설이다.
후보는 `unproven`/`plausible`/`investigated`로 구분하지만 어느 상태도 성공확률이 아니다.
수집기는 기본적으로 제목·링크·집계지수를 수집한다. 자동 본문 완독기, 유료 SNS 데이터 무제한 수집기, 검색량/매출 추정기가 아니다.
중요 후보의 원문은 스킬이 별도로 열어 검토하고 결론과 증거를 저장한다. 400개 분야를 등록했다고 전 분야를 깊게 학습했다고 하지 않는다.
트렌드 휴리스틱은 통계적/예측적 검증이 아직 없다. 별도 실제 결과를 쌓아 기본 모델과 비교해야 한다.
창업지원·수상·투자·매출은 보장하지 않는다. 실제 고객·단위경제·경쟁·권리·규제 검증이 우선이다.

Google Trends 전체 API, Instagram/TikTok/X/Threads/Reddit, Product Hunt, K-Startup, KOSIS/ECOS,
특허/채용/앱 순위/커머스/투자 데이터는 별도 권한·어댑터·테스트가 필요하다. registry 등록과 실연결을 구분한다.
네이버 구 쇼핑 검색 API가 종료된 상태이므로 이를 동작한다고 표시하지 않는다.
HWP/HWPX 생성·렌더링, 신청서 자동 제출, 고객 연락, SNS 게시, 결제는 본 CLI 기능이 아니다.

## 자동 업데이트와 축적

실행할 때 갱신하며, 기본 최대 30요청·3개 동시 연결·8개 분야 순환 조회다. 새 정보가 없으면 강한 트렌드를 억지로 만들지 않는다.
프로세스를 상시 실행하지 않으며, 별도 시간표 자동 실행은 사용자가 정한 주기에 Codex 자동화를 연결해야 한다.
현재 스케줄 연결 여부는 SETUP_STATUS.md를 확인한다. 플러그인만 설치했다고 PC가 꺼져 있어도 수집되는 것은 아니다.
자동 개선은 자료·검증 결과의 누적을 말하며, 모델 학습이나 코드의 무승인 자동 변경을 의미하지 않는다.

### 30분 레이더와 텔레그램

`radar prepare`는 출처별 간격(뉴스/트렌드 RSS 30분, HN 1시간, GitHub 동일 쿼리 6시간)을 적용하고
최대 18요청·6개 분야를 조회한다. Codex가 원문과 한국 대안을 확인해 0~2개 가설을 생성하고 `radar submit`으로 저장한다.
조사 주제는 최근 변화와 오래 기다린 후보를 번갈아 고른다. 중간에 작업이 끊겨도 같은 이름순 후보에 고정되지 않는다.
패킷에 제시한 이력과 실제 검토 완료는 별도이며, `selection_reason`에 선정 이유를 남긴다.
0개도 정상 결과다. CLI만 반복 실행하면 LLM 아이디어가 자동 생성되는 구조는 아니다.
예약 Codex 작업이 같은 분석 흐름을 수행하며, 그 일정은 사용자별 상태 폴더와 앱에서 관리한다.

`telegram init`은 상태 폴더에 숨김 파일 `.telegram.env`를 만든다. 사용자가 BotFather 토큰과 정확한 숫자 대화 ID를
입력한 후 `telegram verify` → `telegram enable --confirm-chat-id "확인한 숫자 ID"`로 연결한다.
토큰은 채팅에 보내지 않는다. `telegram deliver`는 기본 미리보기이며 실제 전송은 `--send`가 필요하다.
동일 고객·문제 dossier의 핵심 고객/한국 대안 근거와 원문 생산자·신호 계열 각각 2개 이상·최근 변화가 있는 가설만 선별한다.
기본 하루 6개/최소 30분 간격이다. `connection-check`는 수신 대상별 고정 시험 문구 1건이며 아이디어 수와 별도로 집계한다.
상세 설정과 입력 필드는 [지속 레이더](skills/korea-startup-intelligence/references/live-radar.md)에 있다.

예약 작업은 `radar prepare --trigger heartbeat --automation-id ID --resume`로 중단된 조사를 재개하고,
모든 주제 검토를 제출한 뒤 `radar finish --packet-id ID --send`로 선별·전송·보고서·완료 기록을 마친다.
수동 실행에서는 heartbeat 표기를 생략한다. `radar health`, `radar runs`, `telegram history`에서 실제 이력을 확인한다.
전송 도중 중단된 건은 자동 재전송하지 않는다. 사용자가 수신함을 확인한 뒤 `telegram resolve`로 기록하고,
명시적으로 재전송까지 요청한 경우에만 `--retry`를 사용한다. API 성공과 사용자 확인은 다른 집계다.

단계·점수·원문 독립성은 검토자의 근거 있는 판단이다. 구조 검증기가 사업성이나 인과관계를 자동 입증하지 않는다.
수신 명령 해석·챗봇 대화·외부 서버 배포·24시간 클라우드 실행은 포함하지 않는다.

YouTube 연결 시 watch_topics가 비어 있어도 해당 회차의 분야 검색어 하나를 순환 조회한다.
검색은 실행당 최대 1회, `youtube_search_daily_limit` 기본 48회/KST일이며 캐시 재사용은 횟수를 소모하지 않는다.
이 로컬 상한과 실제 Google 프로젝트의 [Search Queries 할당량](https://developers.google.com/youtube/v3/docs/search/list)은 별개다.
영상 집계는 별도 최대 20개 ID/요청이며, 영상별 마지막 요청을 기준으로 캐시·오류 대기를 적용한다.
새 영상이 섞여도 아직 신선한 영상은 다시 조회하지 않으며, 반환되지 않은 ID도 조회 시도로 기록해 반복 요청을 막는다.
해당 검색 주제의 `supporting_metric_observations`에서 집계를 함께 읽는다. 같은 영상의 검색 결과와 집계는 독립 근거 두 개가 아니다.
전체 요청 예산도 적용한다. 모든 분야/영상의 실시간 전수 조사가 아니다.

## 다음 확장 우선순위

1. 블루오션 후보와 실제 고객·거래 결과를 연결해 보류·폐기까지 포함한 포트폴리오 판단을 개선.
2. 리뷰·채용·조달·특허·가격·품절·앱 변화 등 사업 선행 신호 어댑터를 공개·허용 범위에서 확장.
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
[gstack 적용 방식](skills/korea-startup-intelligence/references/gstack-operating-model.md)과
[API 없는 지원사업 작업대](skills/korea-startup-intelligence/references/application-workbench.md)를 필요에 맞춰 사용한다.

검증 실행:

```bash
python3 -m unittest discover -s tests -v
```

외부 코드/README 전문을 재배포하지 않는다. 공개 데이터와 개별 서비스 약관·개인정보·콘텐츠 권리는 별도다.
