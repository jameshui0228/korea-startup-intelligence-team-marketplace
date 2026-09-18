# 공식 공고 조건 대조

지원사업 원문을 읽고 조건별 점검표를 실행할 때 사용한다. 일반 사업계획 검토는 korea-grants.md를 따른다.
공고 검색 API와 이 매칭기는 별개다. API 키 없이도 실제 읽은 공식 공고를 입력할 수 있다.

## 원문 추출

해당 기관의 현재 공고·정정·첨부를 열어 `radar review-source`에 실제 범위를 기록한다.
PDF의 표/자격/마감은 관련 페이지를 이미지로도 확인한다. HWP/HWPX를 읽지 못하면 읽은 것으로 하지 않는다.
공식 링크가 여러 매체로 재인용돼도 같은 발행자다. 공고 내용을 아래 JSON으로 구조화한다.

- `key`, `title`, `issuer`, `notice_version`, `evidence_ids`.
- `official_notice_confirmed`: 직접 공식 공고임을 확인했을 때만 true.
- `conditions_complete`: 부록·예외·중복지원·제외 조건을 모두 검토했을 때만 true.
  부분 추출도 저장할 수 있으나 false 상태에서는 전체 자격을 충족한다고 출력하지 않는다.
- `coverage_note`: 실제 검토 페이지, 미검토 첨부, 조건부 추가 접수 등 한계.
- `opens_at`, `closes_at`: 명시적 시각/시간대 ISO 형식 또는 null. 날짜만 알면 개시/마감 시각을 임의로 정하지 않는다.
- `rules`: 아래 형식의 명시적 필수 조건 1~60개.
- `evaluation_criteria`: criterion, weight(공식 배점 또는 null), locator. 자격 조건과 평가 배점은 분리한다.

규칙 필드:

```text
field: 비식별 창업자/사업 필드 이름
operator: eq | in | not_in | gte | lte | between
value: 공고가 명시한 비교값 또는 구간
description: 조건 의미
locator: 페이지/표/절
as_of_basis: 업력·연령·확인서 유효 여부 등을 계산할 정확한 기준일/시점
evidence_ids: 해당 조건을 실제 읽은 공고 근거
```

현재 비교기는 AND로 결합된 명시적 조건이다. OR·여러 예외·소유구조·CN 코드 자동 판단기는 아니다.
예외가 있는 “세금 체납”을 무조건 부적격 boolean으로 단순화하지 않는다. 조건을 확실하게 추출할 수 없으면 completeness=false로 두고 수동 검토한다.
개인식별번호·계좌·연락처가 아닌 필요한 집계 사실만 다룬다.

`grants save --file "공고.json"`이 grant ID를 반환한다.

## 창업자 정보와 대조

프로필은 규칙의 field를 키로 쓰고 다음 항목을 가진다.

```json
{
  "value": true,
  "status": "confirmed",
  "basis": "사용자가 확인한 비식별 사업 사실과 확인 자료의 설명",
  "as_of_basis": "해당 공고에서 지정한 것과 동일한 기준일/시점"
}
```

위 객체는 개별 필드의 형식 예시이며 실제 창업자 상태가 아니다. 정보가 없으면 `{}` 프로필로 대조한다.
`grants match "grant-ID" --profile "확인된-프로필.json"`을 실행한다.
문자열 나이를 숫자로, true를 1년으로 바꾸지 않는다. 기준일이 다르면 미확인이다.

결과:

- 필수 조건 중 FAIL 존재 → INELIGIBLE_BY_RECORDED_RULE. 좋은 평가점수로 상쇄하지 않는다.
- 미확인 사실·오래된 공고·부분 검토 → UNKNOWN.
- 기록한 모든 조건 통과 → MATCHES_RECORDED_RULES. 기관 승인이나 선정 예측이 아니다.
- 정규 기간 경과·개시 미상·추가 접수 미확인 → 현재 신청을 자동 권하지 않는다.

출력의 coverage_note를 반드시 함께 읽는다. 과거 정규 기한이 지났어도 추가 접수 조항이 있으면 “완전히 마감”으로 단정하지 않는다.
최종 신청 직전에는 최신 공고와 첨부를 사람이 다시 확인한다. 신청·기관 문의·서류 발송은 별도 명시적 요청이 필요하다.
