# 창업 공모전 즉시 대응 스프린트

공고가 공개된 직후 자격과 평가표를 먼저 고정하고, 서로 다른 아이디어를 발산한 뒤 근거·시연·창업자 적합성으로 압축할 때 사용한다.
수상 가능성을 계산하거나 공고에 맞춰 실적·고객·특허·팀 역량을 만들지 않는다.

## 1. 공식 공고 고정

현재 공고·정정·첨부·평가표를 실제로 읽고 `radar review-source`와 `grants save`로 저장한다.
조건 전체를 읽지 못하면 conditions_complete=false다. 마감 시각이 없으면 closes_at=null로 둔다.
창업자 프로필은 공고 기준일과 근거가 확인된 비식별 사실만 넣는다.

```text
competition prepare --grant-id grant-ID --profile profile.json --limit 12
```

profile은 선택이며 없으면 자격을 UNKNOWN으로 유지한다. 결과는 마감까지 남은 시간, 자격 대조, 실제 평가항목,
기존 dossier, 경고, 8개 발상 렌즈를 순환한 4~20개 후보 슬롯을 반환한다. 슬롯은 아이디어가 아니며 Codex가 실제 원문과 창업자 조건을 사용해 작성한다.

## 2. 후보 발산

기본 12개 후보는 같은 AI 서비스의 이름만 바꾸지 않는다. 문제 중심, 행동 변화, 수작업, 정책 시점,
지역·현장, 산업 간 이전, 공급 병목, 신뢰·거래비용 렌즈를 섞는다. B2B/B2C/B2G와 서비스·오프라인·하드웨어 가능성을 검토한다.
각 후보에는 다음을 모두 작성한다.

- key, title, target, problem, solution, business_model, first_users, domain_ids.
- dossier_id. 기존 dossier와 고객·문제가 정확히 같을 때만 연결한다. 새 후보는 null로 시작할 수 있지만 최종 후보가 되려면 조사 dossier가 필요하다.
- problem/current_alternative/willingness_to_pay/why_now/differentiation/korea_fit 주장. 각 주장은 status, text, evidence_ids를 가진다.
- founder_fit: confirmed 또는 unknown, statement, basis. 단순 자신감이나 AI의 추정은 confirmed가 아니다.
- demo: method, timebox_days, budget_krw, pass_condition, stop_condition.
- criterion_mapping: 실제 공고 criterion마다 criterion, status, text, evidence_ids. 배점이 없는 평가항목에 배점을 만들지 않는다.
- risks, assumptions 각각 1~12개.

FACT/INFERENCE와 평가항목 대응에는 현재 유효한 원문 검토 근거가 필요하다. 탐색 후보의 미확인은 UNKNOWN으로 둔다.

## 3. 압축과 반대 심사

```text
competition evaluate --file candidates.json
```

검사 항목은 현재 공고 자격·접수 상태·조건 완전성, 평가항목 누락, 원문 검토 신선도, 6개 핵심 주장,
동일 고객·문제 dossier, 창업자 적합성, 시연 예산·기간·통과/중단 기준이다.
결과의 shortlist는 구조상 차단 사유와 근거 공백이 없는 후보다. 실제 수상 후보 인증은 아니다.
pareto_frontier는 평가항목/핵심 주장 근거가 더 많으면서 시연 비용과 기간이 더 나쁘지 않은 비지배 후보만 보여 준다.
심사위원 선호나 사업 성공을 수치화하지 않는다.

후보별 hard_blocks와 evidence_gaps를 먼저 처리한다. 좋은 문장으로 자격 미확인, 공고 누락, 고객 근거 공백을 덮지 않는다.
공고가 정정됐거나 원문이 오래됐으면 다시 준비·평가한다. 평가 이력은 `competition status [--grant-id grant-ID]`로 확인한다.

## 4. 제출물로 발전

압축된 후보를 `research-work save`로 조사하고 `venture-review`로 현 상태 유지·수작업·비AI 대안과 실패 경로를 검토한다.
값싼 실험은 `validation plan`에 사전 등록한다. 검토가 끝난 후보만 `application prepare --dossier-id ... --grant-id ...`로 넘긴다.
사업계획서 본문·예산·발표·Q&A를 작성한 뒤 application check와 실제 공식 양식 렌더 검수를 수행한다.
신청·제출·고객 연락·비용 지출은 사용자의 별도 요청이 필요하다.

