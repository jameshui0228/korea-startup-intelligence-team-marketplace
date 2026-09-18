# 사업 가설의 창업자·제품·반대 관점 검토

전 분야의 탐색을 유지하면서, 각 가설의 고객은 좁고 구체적으로 정의한다. 연구 대상의 폭과 초기 제품의 폭은 다르다.
아이디어 발굴·기존 가설 개선·자동 분석에서 dossier의 근거를 아래 질문에 대조한다.

## 여섯 질문

1. 관심·검색·가입을 넘어서는 실제 수요 행동은 무엇인가? 실제 이용·지출·손해 근거가 없으면 UNKNOWN.
2. 고객은 지금 어떤 순서와 도구로 해결하며 무엇을 잃는가? 아무 대안도 없다고 단정하지 않는다.
3. 가장 절실한 고객의 역할·상황·책임은 무엇인가? 관찰하지 않은 사람·인터뷰를 만들어내지 않는다.
4. 가장 작게 검증할 유료 가치 한 가지는 무엇인가? 플랫폼 전체보다 한 업무의 결정적 개선을 찾는다.
5. 사용 관찰 중 예상과 달랐던 점은 무엇인가? 관찰 전에는 인터뷰/테스트 계획으로 남긴다.
6. 3년 뒤 어떤 변화가 이 제품을 더 필요하거나 불필요하게 만드는가? 예측과 현재 사실을 구분한다.

질문마다 conclusion, status(FACT/INFERENCE/ASSUMPTION/UNKNOWN), evidence_ids를 남긴다.
이미 알려진 답을 다시 묻지 않는다. 자동 실행은 사용자 응답을 지어내지 않고 미지수를 후속 조사로 보낸다.
`prepare --stage pre_product|users|paying|unknown`은 확인된 제품 단계에 맞춰 질문 우선순위를 정한다.
현재 검토의 유효한 답/대안/결정을 재사용하고, 오래된 답은 재확인 대상으로 돌린다. 보류·기각 결정은 자동 해제하지 않는다.
단계별 판단과 실행 흐름은 [gstack 적용 방식](gstack-operating-model.md)에 있다.

## 비교와 반대 검토

- 아무것도 바꾸지 않기/현재 도구 유지, 최소 서비스, 장기 확장 제품 중 적어도 두 대안을 비교한다.
- 비교에는 해결되는 업무, 첫 고객 경로, 필요한 시간·자본·공급, 전환 비용, 실패 조건을 포함한다.
- 먼저 사업을 실패시키는 가장 강한 이유를 찾는다. 고객의 반복 문제·예산·국내 대안·권한·규제 공백을 구체화한다.
- 한국에 경쟁이 없다는 주장은 실제 검색과 대안 검토가 있어야 한다. 지원사업 자격과 시장성을 구분한다.
- 작은 실험의 통과/중단 기준과 다음 행동 하나를 정한다. 제안한 실험은 실행 결과가 아니다.

`venture-review prepare --dossier-id dossier-ID`로 기존 조사와 미확인 질문 틀을 읽고, 실제 검토 후
`venture-review save --file 검토.json`으로 아래 계약을 저장한다. prepare의 틀은 완성된 검토가 아니다.
`venture-review status`는 조사 내용 변경·원문 만료와 남은 질문을 확인한다.

필수: dossier_id, mode(explore/hold/narrow), six_questions, alternatives(2~3개),
failure_modes(1~8개), next_action, decision(research/test/park/reject).
선택: product_stage(unknown/pre_product/users/paying). 단계 진술 자체는 고객·매출 근거가 아니다.
six_questions 키는 demand, workaround, specific_customer, smallest_wedge, observation_surprise, future_fit.
각 답은 status, conclusion, evidence_ids를 가진다. FACT/INFERENCE의 근거는 같은 dossier의 본문 검토 자료여야 한다.
alternatives의 각 항목은 kind(status_quo/minimal/expanded), name, approach, tradeoff, smallest_test, failure_condition 문자열.
kind는 서로 달라야 하며 현재 방식 유지(status_quo)를 반드시 비교한다.
failure_modes의 각 항목은 risk, detection, response 문자열. 점검 결과를 증명한 성공 확률로 쓰지 않는다.

현재 Codex 작업에서 원문 조사 → 질문·대안 구조화 → 반대 검토를 수행한다. 외부 LLM 서버를 연결한 기능이 아니다.
저장된 검토의 park/reject 결정이나 오래된 검토는 해당 후보의 기회 알림 검사를 차단한다.
검토를 통과했다고 고객 수요가 증명되지는 않으며, 기존 고객 근거 검사를 우회하지 않는다.
같은 모델의 역할별 검토는 독립 전문가 합의가 아니다. 원문 자료·고객 결과·후속 반증으로 평가한다.
다음 실험은 [사전 실험과 결과](validation.md)로 연결한다. 준비만 했는데 실행했다고 저장하지 않는다.

## 설계 출처와 적용 범위

2026-09-17에 [garrytan/gstack](https://github.com/garrytan/gstack/tree/a6b3a57512ca6d5c6aa5b68f74f736195021f96e)의
office-hours, plan-ceo-review, plan-eng-review, review, QA의 관련 절과 ETHOS/ARCHITECTURE를 검토했다.
고객 질문·대안 비교·오류 경로·검증 증거 원칙을 이 플러그인의 데이터 계약과 실행기에 맞춰 재작성했다.
상세 읽기 범위는 assets/gstack-study.json에 있다. 전 코드를 실행/검증하거나 모델 가중치를 학습시킨 것은 아니다.
gstack의 설치 훅·자동 업그레이드·쿠키 접근·분석 수집·별도 CLI 실행을 설치하거나 활성화하지 않는다.
원 저장소의 개발 생산성·YC 평가 표현을 우리 시스템의 검증된 성능이나 추천으로 인용하지 않는다.
