# 기존 GitHub 조사에서 반영한 설계

기존 1,984개 후보 중 정제된 177개 저장소의 **메타데이터 참고 색인**을 `assets/research_index.json`으로 연결했다.
색인 기준일은 2026-09-17이다. 외부 저장소 코드를 복제/설치한 번들이 아니며 README 주장·기능·성공률을 독립 검증한 것은 아니다.
`research --query "korea"` 또는 이름/용도/분류로 검색한다. license_metadata는 배포 허가 판정이 아니라 API 메타데이터다.
코드를 가져올 때는 root license·개별 파일·하위 의존성·콘텐츠 권리를 다시 검토한다. NOASSERTION/미지정은 복제 허가가 아니다.

## 적용한 패턴과 출처

| 패턴 | 참고 원천 | 이 플러그인의 적용 |
|---|---|---|
| 사실/가정/미지수와 검증 증거 분리 | [ajstars1/startup-coach](https://github.com/ajstars1/startup-coach), [wanikua/OpenBusiness](https://github.com/wanikua/OpenBusiness) | claim 상태 + 출처 검증 메모 + 유효한 evidence ID |
| 공통 창업자 상태, 단계별 최소 작업 | [AIDevGTM/gtm-cofounder](https://github.com/AIDevGTM/gtm-cofounder), [heyparsadev/claude-venture-plugin](https://github.com/heyparsadev/claude-venture-plugin) | FOUNDER_CONTEXT와 작업별 참조, cache 밖 상태 |
| 산출물 품질·고객 문제·실험 중심 | [product-on-purpose/pm-skills](https://github.com/product-on-purpose/pm-skills), [lool-ventures/founder-skills](https://github.com/lool-ventures/founder-skills) | 필수 필드 검사, 반증 실험, 임의 점수 차단 |
| 한국 공고별 정규화·부분 수집 표시 | [djfksjd/ir-search](https://github.com/djfksjd/ir-search), [Choihello/grantcompass-korea](https://github.com/Choihello/grantcompass-korea) | 출처별 성공/장애/미연결, 공식 공고 자격 표 |
| 문서 결함 검토와 합격 예측 분리 | [Choihello/plan-lint](https://github.com/Choihello/plan-lint) | 문서 검토 절차만 적용; 외부 검사기 실행 여부를 허위 표시하지 않음 |
| 운영 상태·쓰기 범위·감사 이력 | [msolecki/founder-os](https://github.com/msolecki/founder-os), [OurThinkTank/founders-os](https://github.com/OurThinkTank/founders-os) | workspace lock, revisions, 인증정보/배포 폴더 분리 |
| 실제 결과로 누적하고 실패 보존 | [impactbrussels/FounderOS](https://github.com/impactbrussels/FounderOS), [gvkhosla/founder-skills](https://github.com/gvkhosla/founder-skills) | experiment/feedback/불변 forecast와 outcome ledger |
| 다중 채널은 수요 증명이 아님 | [jain-eshan/gutcheck](https://github.com/jain-eshan/gutcheck), [dialog-tools/reddit-research-mcp](https://github.com/dialog-tools/reddit-research-mcp) | 자료 계열 비교, 원천 중복/표본 편향, 판매 증거 별도 |

추가 수집은 특정 산업에 매몰되지 않도록 실제 source coverage를 먼저 확인한다.
저장소 최신 commit·스타 수·도구 수는 실행 성능이나 창업 성공의 증거가 아니다.
전체 외부 SKILL을 실행 지침으로 로드하지 않고 검증 가능한 패턴을 직접 구현한다.
