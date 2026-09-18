# 누적 지식과 결과 평가

모델 가중치를 훈련하거나 “완벽하게 학습했다”고 주장하지 않는다. 이 플러그인은 로컬의 근거·판단·가설·실험·
실제 결과를 다시 읽어 다음 의사결정에 반영한다. 실제 결과가 쌓여도 개선 여부는 별도 평가해야 한다.

## 상태 저장

워크스페이스에 `config.json`, `FOUNDER_CONTEXT.md`, `NEXT_ACTIONS.md`, `intelligence.sqlite3`, `reports/latest.*`가 있다.
SQLite는 observations/fetches/coverage/records/revisions를 분리한다. 사용자 기록은 덮어쓰더라도 이전 revision을 보존한다.
GitHub/HN 수치는 metric_snapshots에 날짜별로 쌓인다. 같은 대상의 7일 이상 간격과 충분한 기저가 없으면 변화율은 null이다.
YouTube 선택 영상의 조회/좋아요/댓글 **집계 건수**도 어댑터 연결 후 같은 방식으로 축적한다. 조회 정의 버전이 다르면 연결하지 않는다.
이는 전체 플랫폼의 성장률이 아니라 관측된 대상의 기술통계이며, 원자료 보유/갱신 조건에 따라 28일로 제한한다.
plugin cache에는 상태를 쓰지 않는다. 재설치·버전 변경으로 사업 지식이 사라지지 않게 한다.

지원 기록: claim, problem, idea, experiment, forecast, feedback. 읽기는 `list <종류>`, 저장은 `record <종류> --file <JSON>`.
추가: dossier는 `research-work save`, grant는 `grants save` 전용 검증기를 사용한다. 입력 형식은 research-workbench.md / grant-matching.md.
사업 검토는 `venture-review save`, 사전 실험/결과는 `validation plan`/`validation result` 전용 검증기를 사용한다.
기존 `record experiment` 기록은 자유 형식 메모이며 사전 등록·실행·결과 검증 건수에 포함하지 않는다.
실제 실험을 설계하거나 기록할 때는 [사전 실험과 결과](validation.md)를 읽는다.
카드의 피드백은 연결된 dossier의 다음 조사 과제로 돌아간다. `research-work maintenance`가 일/주/월 자료와 현재 부족한 근거를 만든다.
각 기록은 id와 evidence_ids가 필요하다. evidence_ids는 현재 유효한 observation ID만 허용한다.
명시적 허용 자료는 `import-evidence --file <JSON>`으로 넣는다. 사용자 소유/허용된 export/실제로 검토한 공개 출처를 구분한다.
매출·거래·인터뷰는 원자료 검토 전 스스로 검증된 것으로 선언하지 않는다. 개인정보는 익명화하고 필요한 집계만 남긴다.

가설 카드 예시(근거가 아직 없으므로 수치는 비워둔다):

```json
{
  "id": "idea-example-001",
  "idea": "돌봄기관의 교대 인계 누락을 줄이는 수동 검증 실험",
  "problem": "인계 누락이 반복된다는 가설; 아직 실사용자 확인 전",
  "target": "소규모 돌봄기관의 교대 근무 관리자",
  "solution": "먼저 기존 인계 양식과 누락 사례를 조사한 뒤 표준 확인표를 수동 적용",
  "business_model": "기관 구독 가능성은 가설이며 가격 미확인",
  "domain_ids": ["KR-180"],
  "evidence_ids": [],
  "risk": ["문제 빈도 미확인", "개인 건강정보를 수집하지 않는 실험 설계 필요"],
  "next_experiment": "관리자 5명에게 최근 실제 인계 과정과 사례를 질문; 문제 부재이면 중단",
  "status": "hypothesis",
  "score": null
}
```

이는 사용 예시이지 추천 아이디어나 고객 증거가 아니다. 사용자 지식베이스에 예시를 실제 결과처럼 넣지 않는다.

## 피드백 루프

1. 실행 전: 가설, 성공/중단 기준, 데이터 정의, 예산, 마감일을 기록한다.
2. 실행 후: 관측 결과·불편이 없었던 사례·거절·실패·탈락 이유까지 보존한다.
3. 판단: 기존 믿음과 다른 부분, 증거의 대표성/표본/관측 오류, 바꿀 의사결정을 구분한다.
4. 다음 단계: 아이디어 유지·보류·폐기·재실험을 결정하고 이유를 기록한다.
5. 주간 검토: 새로운 증거가 있는 idea/problem을 다시 평가한다. 최신 자료가 없으면 기존 판단을 강화하지 않는다.
6. 월간 검토: 분야별 공백, 편향, 오래된 출처, API 규격/이용약관, 실패 사례, 다음 adapter 우선순위를 점검한다.

출처/관측 범위가 있는 claim의 FACT에는 verification_note도 필수다. 소스 링크 존재만으로 사실을 보증하지 않는다.
새 근거가 기존 판단과 모순되면 기존 기록의 revision을 남겨 수정한다. 모순 자료를 삭제하지 않는다.

## 미래 예측 평가

forecast는 question, probability(주관적이며 미검증), deadline, resolution_rule, evidence_ids를 기록한다.
만든 뒤 수정하지 않는다. 수정 예측은 새 id를 만든다. 확률을 요청받지 않았다면 임의로 숫자를 붙이지 않는다.
마감 후에만 `resolve <id> --outcome 0|1 --evidence-id <관측 ID>`를 실행한다.
관측 출처가 없거나 마감 전이면 점수 산출을 거부한다. 분모·성공 기준은 사전 기록과 대조한다.
`evaluation`은 누적 건수와 평균 Brier만 계산한다. 이 수치만으로 예측 능력 검증/향상을 선언하지 않는다.
사전 기준·전체 예측(실패 포함)·기본 확률 기준모델·기간 외 검증·표본 크기가 있어야 비교할 수 있다.

한국 트렌드의 확산 경로·목표 지표·기준 확률·반례·선행시간까지 평가하려면 [트렌드 예측 평가](forecasting.md)의
`trend-forecast prepare/register/resolve/evaluate/status`를 사용한다. 기존 단순 forecast 기록을 소급 변환하지 않는다.

## 반복 실행

플러그인 실행 시 freshness를 검사하여 최신 자료를 갱신한다. CLI 자체는 상주 서버나 스케줄러가 아니다.
사용자가 별도 주기를 정하면 Codex의 공식 recurring mechanism으로 같은 워크스페이스를 갱신한다.
cron을 몰래 설치하거나 추가 작업을 만들지 않는다. 변경 없는 상태는 알리지 않고 의미 있는 변화·실패·필요한 사용자 조치만 알린다.
새로운 소스/코드/프롬프트의 변경은 출처와 회귀 테스트를 갖춘 버전 업데이트로 수행한다.
