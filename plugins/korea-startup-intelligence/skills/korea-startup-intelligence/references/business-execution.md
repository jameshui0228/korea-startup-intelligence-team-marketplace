# 사업 실행·비디지털 시장·고객 검증

사업 아이디어를 실행안으로 바꿀 때 기존 dossier·venture-review·validation·application을 연결하고 아래 차이를 확인한다.
이 절차는 Codex가 실제 자료와 사용자 답으로 수행한다. 스크립트가 고객 인터뷰나 지원서를 스스로 완성했다는 뜻이 아니다.

## 후보별 실행안

`workbench template business`에 dossier_id와 다음을 작성한다.

- customer(문제 보유 조직/사람), user(사용자), buyer(지출자), approver(구매 승인자)를 분리한다. 예산 출처·구매 주기·권한을 모르면 UNKNOWN.
- beachhead는 이번 달 접근 가능한 좁은 집단·업무 한 가지다. reachable_this_month에 접근 경로와 확인 근거를 적는다. 막연한 전국 인구·TAM을 접근 가능한 고객 수로 쓰지 않는다.
- model은 서비스/유통/운영 대행/도구/제조/수수료/구독 중 적합한 대안들을 비교한다. AI가 필요 없는 대안과 현 상태 유지를 포함한다. 여러 후보가 모두 AI 플랫폼이면 동일 결론의 이유를 검토한다.
- mvp에는 가장 싼 검증 방식·소요 시간·준비물·실행자·통과/중단 기준을 적는다. 수작업 대행, 종이 모형, 기존 도구 조합, 업무 시간 관찰을 먼저 고려한다.
- gtm에는 대상·가설·메시지 초안·접근 채널·예산 상한·측정 기간·분모·전환 정의를 쓴다. 연락/게시/광고 집행은 이 문서 작성과 별개의 외부 행위다.
- bottlenecks에는 공급자·인력·시설·허가·재고·물류·구매 승인 중 가장 먼저 막히는 조건을 적는다. 운영 전문가·공식 자료 확인이 필요한 부분을 표시한다.
- stop_condition/reopen_condition에는 어떤 반증으로 기각하고 어떤 새 근거가 있어야 다시 검토할지 적는다. 기각 후보를 지우지 않는다.

포트폴리오는 후보별 창업자 적합성·검증 비용·심각한 위험·확인 가능한 반증을 비교한다. 모르는 값을 0점으로 처리해 자동 탈락시키지 않는다.
기존 wb_unknown의 우선순위와 wb_founder를 대조하고 추천 이유·탈락 이유를 설명한다. 추천 순위는 지원사업 선정 확률이 아니다.

## 실행 명령

다음 명령은 `ksi.py --workspace WORKSPACE workbench` 뒤에 붙인다. Codex가 자연어 요구와 실제 근거로 입력을 작성한다.

### business-check --file FILE

입력은 business 객체와 선택적 available_budget_krw다. customer/user/buyer/approver, beachhead,
reachable_this_month, stop_condition/reopen_condition의 미확인을 찾아낸다.
mvp는 hypothesis/method/owner/materials/metric/pass_rule/stop_rule/minimum_sample/budget_krw/starts_at/ends_at,
gtm은 target/channel/message_draft/conversion_definition/denominator_definition/budget_krw/starts_at/ends_at를 받는다.
alternatives는 kind가 status_quo/manual/non_ai인 대안들을 포함해 현 상태·수작업·비AI 비교 누락을 찾는다.
MVP와 GTM 예산은 합산한다. 중복 비용이 있다면 입력에서 중복을 제거하고 가정을 기록한다.
양의 최소 표본, 시작/종료 순서, 같은 통과/중단 기준, 가용 예산 초과를 검사한다.
wb_business 저장 시에도 plan_check를 생성하고 alternatives를 보존한다.
structured_plan_complete는 구조 검사가 통과했다는 뜻뿐이다. 실제 수요·계획의 타당성·외부 실행 승인을 뜻하지 않는다.

### portfolio --file FILE

candidates에 2~20개 후보를 넣는다. 각 후보는 id/basis와 founder_fit/customer_access/evidence_strength(0~1 또는 null),
test_cost_krw/test_days(0 이상 또는 null)를 받는다. basis에 실제 근거와 평가자의 가정을 구분해 쓴다.
모든 값이 있는 후보끼리만 파레토 비교한다. 다른 후보보다 모든 항목이 같거나 좋고 하나 이상 더 좋은 경우에만
dominated_by를 표시한다. 가중 총점·자동 기각·성공확률을 만들지 않는다. null이 있는 후보는 needs_research에 남긴다.
comparable_frontier는 가정 내 비열등 후보 집합이며 최종 추천·시장 검증 결과가 아니다.

### interview-pack --file FILE

입력 dossier_id에서 고객·문제·현재 revision을 읽어 여섯 비유도 질문, 관찰 기록 항목, 동의 준비안과 표본 확인 과제를 만든다.
입력 양식의 actor, 선정/제외 조건, 보관 기간은 실제로 확인해서 채운다. 자동 저장·연락·녹취는 하지 않는다.
execution_status는 planned이며 고객의 답변이나 실제 동의를 생성하지 않는다. 사용자가 저장을 요청하면 검토 후 workbench save로 저장한다.

### feedback-queue

저장된 wb_feedback_action과 현재 대상 revision을 대조해 수정 검토 대기열을 만든다.
버전 변경은 제안이 반영됐다는 증거가 아니므로 implementation_verified=false를 유지한다.
거절된 피드백은 적용하지 않고 이유를 보존한다. 채택한 항목은 diff로 실제 변경과 근거를 대조한다.

## 숫자 비교

`workbench economics --file FILE`의 scenarios에 1~12개 가정 시나리오를 넣는다. 각 시나리오는 name, basis와
price_krw, variable_cost_krw, service_cost_krw, cac_krw, orders_per_customer, customers, fixed_cost_krw, working_capital_krw를 포함한다.
모든 숫자는 같은 기간·원화 기준이다. basis에 기간과 가격/반복 구매/원가의 출처, 미검증 가정을 명시한다.
보수/기준/낙관 가정은 관측된 범위나 명시적인 가정이어야 한다. 중간값이 예상 매출이라고 주장하지 않는다.
건당 공헌이익 = 가격−변동비−지원비, 고객당 공헌이익 = 건당 공헌이익×기간 주문 수−CAC.
고객당 공헌이익이 0 이하면 손익분기 고객 수는 null이다. 반복 구매가 확인되지 않으면 이를 가정으로 적는다.
운전자금 차감값은 완전한 현금흐름표가 아니다. 세금·환불·결제 시차·설비 투자·차입을 별도로 확인한다.

## 비디지털 시장별 조사 질문

| 시장 | 현재 업무·현장 근거 | 운영 병목 | 가장 싼 첫 검증 |
|---|---|---|---|
| 제조 | 불량·재작업·납기·발주 최소량·작업일보 | 금형/설비·소재 리드타임·품질 보증·인증 | 허용된 한 공정의 시간/불량 관찰, 소량 견적 비교 |
| 식품 | 재고 폐기·원가·반품·재구매·유통 수수료 | 제조 시설·표시·위생·보관 온도·유통 기한 | 적법한 제공 범위 확인 후 소량 모형/구매 상황 조사 |
| 돌봄 | 이용자·보호자·기관 구매자의 다른 요구, 인수인계 | 자격·현장 인력·책임·개인정보·안전 | 민감정보 없는 업무 흐름 인터뷰, 실제 케어 제공 없이 검증 |
| 교육 | 학생/교사/학부모/기관의 과제·구매 승인 | 학사 일정·보호자 동의·접근성·성과 측정 | 수업 도구 모형과 업무 시간 비교 계획, 학습 효과는 별도 실험 |
| 로컬 서비스 | 예약 공백·노쇼·재방문·이동 동선 | 상권/임대·인력·영업 시간·지역 수요 | 한 동네의 공개 가격/대안 조사와 허용된 수작업 테스트 |
| B2B 전문 서비스 | 양식·결재·반복 보고·입찰·납품·채용 요구 | 보안 심사·통합·예산 주기·담당자 변경 | 익명 업무 샘플의 처리 시간 비교·담당자 문제 인터뷰 |

법·인허가 세부사항은 현재 공식 자료로 확인하며 위 표는 법률 결론이 아니다.

## 바로 쓰는 인터뷰 패키지

wb_interview의 selection에는 목표 고객 조건, 제외 조건, 지인/자기선택/보상 표본 여부를 적는다.
consent에는 목적·기록 범위·익명화·중단 가능·보관 기간을 설명하는 문안을 작성한다. 동의를 실제 받았다고 미리 표시하지 않는다.
nonleading_questions는 다음을 출발점으로 상황에 맞춰 조정한다.

1. 최근 이 일을 했던 실제 사례를 시간 순서대로 설명해 주세요.
2. 어떤 도구와 사람을 거쳤고, 어디서 시간이 걸렸나요?
3. 그때 비용이나 손해가 있었다면 어떤 기록으로 확인할 수 있나요?
4. 이미 시도한 대안은 무엇이고 계속 쓰거나 그만둔 이유는 무엇인가요?
5. 바꾸려면 누구의 승인과 어떤 조건이 필요한가요?
6. 문제가 발생하지 않았던 경우는 언제이며 무엇이 달랐나요?

‘이 앱이면 돈을 내겠죠?’처럼 해답을 유도하지 않는다. 미래 구매 의향은 실제 구매와 다르다.
observation_fields에는 비식별 역할/상황/실제 행동/빈도/피해/현재 비용/지불자/대안/원자료 위치/반례를 둔다.
execution_status는 planned/not_run/completed 중 실제 상태를 명시한다. 수행 전에는 planned다.
긍정 답변 수만 보고하지 않고 연락·응답·탈락·측정·누락 분모와 표본 편향을 함께 기록한다.

## 실험·피드백·지원서 연결

실험은 validation.md의 미래 기간·고정 지표·최소 표본·통과/중단/애매한 구간을 Codex가 안내형으로 작성한다.
원자료 연결은 허용된 비식별 측정만 사용한다. 계획을 completed 결과로 저장하지 않는다.
고객 반례가 생기면 wb_feedback_action에 subject_id, feedback_ids, affected_sections, proposed_change, decision, reason을 남긴다.
문제·가격·MVP·발표의 실제 변경은 해당 도메인 저장기로 수행하고 diff로 확인한다. 거절한 피드백도 이유를 보존한다.
지원서 보완은 application check의 자격/마감/공고 변경→큰 근거 공백→평가항목별 본문→예산/일정 순서로 한다.
wb_budget_link로 예산 항목마다 견적 근거·일정·성과물·허용 비목·공식 위치를 대조한다. 합계 통과만으로 허용 비용으로 확정하지 않는다.
심사 연습은 약한 주장 하나에서 ‘원문 위치→수치의 분모→경쟁 대안→반증→계획 실패 시 대응’으로 후속 질문을 이어간다.
모르는 것은 모른다고 답하고 검증 계획을 설명한다. 같은 모델 역할극 점수는 실제 심사 예측이 아니다.

DOCX/HWPX/PDF는 사용 가능한 해당 문서 도구로 실제 파일을 생성하고 렌더링한다. 지원 도구가 없으면 변환/시각 검수 미완료다.
파일 SHA256·형식·페이지 수/제한·실제 확인 페이지·표 잘림·글자 크기·공식 서식·한계를 wb_document_qa에 연결한다.
JSON 필드 통과나 Markdown 출력만으로 실제 제출 가능 상태라고 말하지 않는다. 문서 변경 뒤에는 파일 해시를 새로 확인한다.
선정/탈락/평가 의견/매출 결과는 wb_outcome에 근거와 함께 별도로 기록한다. 플러그인 덕분이라는 인과관계는 비교 없이 단정하지 않는다.
