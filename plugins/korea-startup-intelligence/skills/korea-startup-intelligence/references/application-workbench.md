# API 없는 지원사업·사업계획·발표 작업대

지원사업용 실물을 작성할 때 사용한다. 현재 Codex가 조사와 글쓰기를 수행하고 Python CLI는 근거·구조·합계·일관성을 검사한다.
네이버·YouTube·기업마당·별도 LLM API 키가 없어도 사용할 수 있다. 최신 공고 확인에는 공개 공식 페이지/첨부 또는 사용자 제공 최신 자료를 쓴다.

## 실제 작성 흐름

1. 기존 dossier와 FOUNDER_CONTEXT.md를 읽는다. 필요한 정보가 없으면 중요한 항목만 1~3개 묻고,
   확정되지 않은 팀·업력·매출·협약·특허·예산은 빈 사실을 만들어 채우지 않는다. 답을 기다리는 동안 조사와 가설 초안을 진행한다.
2. 목표 공고가 있으면 korea-grants.md와 grant-matching.md대로 현재 공고/정정/첨부/평가표를 검토한다.
   공고가 없으면 범용 사업계획 초안을 먼저 쓴다. 특정 사업의 배점·서식·자격이라고 이름 붙이지 않는다.
3. `application prepare --dossier-id dossier-ID [--grant-id grant-ID]`로 조사 기반 초안을 가져온다.
   **prepare는 최종 문서 생성기가 아니다.** 아래 입력의 sections를 실제 설득력 있는 문단으로 다시 쓰고 발표·Q&A까지 작성한다.
   이미 작성한 문서는 `application resume application-ID`의 input_template을 편집한다. prepare로 다시 시작해 기존 본문·근거·예산을 지우지 않는다.
4. `application save --file 작성.json`으로 본문·공식 평가항목 대응·예산·일정·발표·Q&A·준비물을 저장한다.
5. 반대 심사 관점으로 읽는다. 문제의 크기/반복성, 경쟁 대안, 차별화 근거, 고객 접근, 팀의 수행 증거,
   예산의 필요성과 지원 종료 후 지속 가능성에 대해 가장 까다로운 질문과 정직한 답변을 쓴다.
6. `application check application-ID`로 현재 근거와 공고를 재검사한다. 실제 공식 서식으로 변환·렌더링은
   사용 가능한 문서/PDF/발표 스킬로 수행한다. 이 CLI는 Markdown/JSON을 만들며 HWP/HWPX·PPTX 자동 생성/제출기가 아니다.
   revision_tasks의 자격/공고·원문 변경을 먼저 처리하고 본문·예산·발표를 고친다. 사업 근거 공백은 문서 미비와 별도 과제다.
7. 수정한 버전의 문서·공식 양식·첨부·분량을 실제로 검토한 뒤, check의 attestation_template에서
   실제 확인한 항목만 checked=true와 구체적인 note로 바꾸고 `application attest --file 검토기록.json`을 실행한다.
   content_fingerprint는 검토한 문서 버전이다. 새 내용이 저장됐거나 공고/근거 해석이 바뀌면 이전 검토를 재사용하지 않는다.

## 작성 입력

- key, dossier_id, grant_id(null 가능), title.
- profile: 선택한 공고의 조건에 필요한 confirmed/value/basis/as_of_basis 필드만. 미확인은 넣지 않는다.
  수치는 유한한 정수/소수를 그대로 사용하며 문자열 나이·true 등을 숫자로 강제 변환하지 않는다.
- founder_facts: 비식별 키 → {statement, status: user_confirmed, basis}. 실제 사용자 진술/제공 자료로 확인한 것만.
  이름·주민번호·계좌·주소·전화·이메일은 기록하지 않는다. user_confirmed는 외부 감사가 아니다.
- sections: problem / solution / market / business_model / competition / execution / team / funding / risk.
  각 값은 1~12개 문단이며 문단은 text, status(FACT/INFERENCE/ASSUMPTION/UNKNOWN), evidence_ids, founder_fact_ids.
  FACT/INFERENCE는 원문 검토된 dossier/공고 근거나 사용자 확인 사실에 연결해야 한다.
  미래 계획은 ASSUMPTION, 정보 공백은 UNKNOWN. 글에만 근거 없는 수치를 끼워 넣고 별도 필드에서 숨기지 않는다.
- criterion_mapping: {criterion, section_ids, rationale}. 선택 공고의 실제 평가항목 이름만 사용한다. 배점 합산으로 자격 탈락을 상쇄하지 않는다.
- budget: 미확인 null 또는 items, requested_krw, own_krw, basis. 항목은 name, quantity, unit_cost_krw, total_krw, basis.
  수량×단가=항목 합계, 항목 총합=신청+자체자금을 검사한다. 견적 없는 예상 비용은 그 가정을 명시한다.
  인건비·현물·부가세·자부담·허용 비목의 인정 여부는 실제 공고를 별도로 대조한다.
- milestones: start_week, end_week(1~260), deliverable, measurement, pass_condition, stop_condition.
- pitch: {title, answer}. answer는 본문과 같은 근거/상태 문단이다. 실제 발표시간/장수는 공고에 맞춘다.
- judge_qa: {question, answer}. 중요한 반대 질문을 충분히 다루되 임의 개수를 공식 조건으로 취급하지 않는다.
  두 목록이 비었는지는 자동 점검하지만 개수만으로 설명의 충실도나 공고 적합성을 보장하지 않는다. 실적 없는 계획을 실적처럼 대답하지 않는다.
- attachments: name, status(missing/prepared/not_applicable), basis. 실제 파일이 없으면 prepared로 표시하지 않는다.
- final_checks: truthfulness / official_form / attachments / length_limits 각각 {checked, note}.
  실제 본문·공식 양식·첨부·분량을 검토한 뒤만 true. 자동 완성되었다고 한꺼번에 true로 바꾸지 않는다.
  신규 저장 시 명시적인 검토 선언은 그 내용 버전에 연결된다. 기존 문서를 수정하면 이전 선언은 무효화된다.
  저장기가 붙인 content_fingerprint를 조작해 검토를 생략하지 않는다. 이후에는 실제 검토 후 attest로 해당 항목만 확인한다.
  예전 버전의 식별값 없는 검토 기록은 현재 버전 검토를 다시 요구한다. 검토 선언 자체는 사람/에이전트의 진술이지 자동 사실 감사가 아니다.

일부만 작성한 초안도 저장되며 부족한 부분이 다음 작성 작업으로 남는다. 문단 검증기는 의미적 진실성까지 증명하지 못한다.

## 판정과 산출물

reports/applications/에 사업계획 문단, 평가 대응, 예산, 실행 일정, 발표 구성, 심사 Q&A, 준비물과 점검표가 함께 저장된다.
본문뿐 아니라 발표/Q&A도 근거 ID를 표시하고 출처 색인에서 URL·사건/발행일·검토일·읽기 범위·한계를 확인한다.
현재 보유하지 않거나 만료된 원문은 재검토 필요로 남긴다. 사용자 확인 사실은 외부 출처와 별도로 표시한다.
claim_status_counts는 문단의 FACT/INFERENCE/ASSUMPTION/UNKNOWN 분류 건수이지 사실 정확도나 선정 확률이 아니다.
`working_draft`는 부족한 근거/공고/자격/필수 작성/검토가 남았다는 뜻이다.
`ready_for_human_submission_review`는 기록상 검사와 선언된 수동 검토를 통과했다는 뜻이지 선정/수상/자동 제출 완료가 아니다.
시장 근거 공백은 문서 형식 준비와 별도로 business_evidence_gaps에 남긴다. 이를 숨긴 채 “합격할 계획서”라고 표현하지 않는다.
공고나 dossier가 바뀌면 기존 초안을 재점검한다. 실제 신청 버튼, 서류 발송, 기관 문의는 사용자의 별도 명시적 요청이 필요하다.
원문을 다시 읽어 해석이 달라진 경우도 초안과 비교한다. 재저장으로 최신 지문을 연결하는 것만으로 잘못된 문장이 저절로 수정되지는 않는다.
