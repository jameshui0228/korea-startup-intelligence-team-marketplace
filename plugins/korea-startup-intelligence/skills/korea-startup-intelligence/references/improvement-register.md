# 100개 개선 항목 추적

2026-09-18 감사 번호를 유지한다. 구현 위치는 scripts/ksi_lib/workbench.py, insights.py 및 명시된 기존 모듈이다.
절차는 team-workbench.md, business-execution.md에 연결한다. 코드·절차·측정 도구 반영과 실제 검증 완료는 다르다.
아래 모든 요구를 추적하되, 외부 승인·팀 실사용·실제 사업 성과가 없는 항목을 완료했다고 보고하지 않는다.

| ID | 개선 | 반영 | 추가 완료 증거/한계 |
|---|---|---|---|
| 01 | 한국어 시작 | start 네 가지 메뉴 | 신규 사용자 완주 시험 |
| 02 | 점진적 설정 | founder 재사용·최소 질문 절차 | 실제 중복 질문률 |
| 03 | 자연어 입력 | Codex가 template/save 초안 작성 | 실제 사용자 시험 |
| 04 | 연결 표시판 | capabilities 구현/키/활성/수집/검토 분리 | 공급자별 실제 연결 |
| 05 | 조사 시작 화면 | start의 미지수/댓글/세션/변경 + 통합 team-queue 상위 작업 | 실제 정보 탐색 시간 |
| 06 | 요약·근거 분리 | 판단·반례·행동→원문 위치 절차 | 실제 이해도 시험 |
| 07 | 공통 접수 | intake URL/파일·해시·권한·not_read | 파일 실제 열람 별도 |
| 08 | 수정 안내 | CLI 오류 분류·한국어 다음 행동·JSON 행/열·민감 경로 제외 | 원래 검증 메시지 전체 번역은 추가 작업 |
| 09 | 중단 인계 | checkpoint·start 재개 목록 | 실제 장기 재개 시험 |
| 10 | 첫 사용 시험 | usability 시간/오류/완주 기록 | 실제 팀원 참여 대기 |
| 11 | 편집 충돌 | 공개 CLI와 도메인 저장기의 expected_revision·checkout·diff | 내부 호출은 expected_revision 전달 필요 |
| 12 | 담당자·인계 | agenda actor/handoff·24시간 점유 | 실제 다인 협업 시험 |
| 13 | 역할 구분 | workbench 로컬 역할 검사 | 원격 인증/RBAC 미구현 |
| 14 | 독립 검토 | review 작성자/검토자·자기검토 차단 + research-qa 핵심 주장 원생산자 수 | 실제 독립성 확인 필요 |
| 15 | 문장 코멘트 | comment claim_locator | 팀 실사용 대기 |
| 16 | 변경 비교 | revision diff | 의미 요약은 Codex 검토 |
| 17 | 공통 용어집 | glossary/queries | 실제 분야별 용어·적합률 |
| 18 | 공유 패키지 | 검토한 요약만 export·민감 패턴 검사 | 완전한 개인정보 탐지 아님 |
| 19 | 복구·기기 병합 | backup/restore-copy/merge-preview | 원격 동기화 미구현 |
| 20 | 결정 이력 | actor·subject revision/digest | 조직별 실제 사용 |
| 21 | 선행 관찰 목록 | watchlist·benchmark/ablation + trend-forecast prepare/status | 실측 선행 가치 |
| 22 | YouTube 업로드 | youtube_uploads 상한·캐시·회전 | 실제 목록 설정/연결 시험 |
| 23 | 영상 형식 | compare 형식 미확인/불일치 차단 | 형식은 실제 확인 필요 |
| 24 | 댓글 문제 조사 | comment-sample 공식 API·20개 표본·중복/시간 한도·프로필 제외 | 라이브 연결·내용 분류 검증 대기 |
| 25 | 영상 내용 | 시청/허용 자막 구간→claim_review | 실제 권한·열람 필요 |
| 26 | Instagram 범위 | social-import 도메인·비식별·일괄 원자성·중복 보호 | 직접 어댑터·승인 대기 |
| 27 | X 범위 | x-preview·x-status·명시적 x-recover·한도·실패 이력 보존 | 라이브 승인/연결 대기; 429·전송 불명 자동 해제 없음 |
| 28 | 다른 SNS | social-import 6플랫폼 + watchlist/signal/ablation | 직접 수집 승인·추가 가치 검증 |
| 29 | 사람 발견 신호 | intake→signal | 실제 원문 검토 필요 |
| 30 | 비SNS 행동 | 가격/납품/조달/채용 대조 절차 | 실제 지출/행동 자료 |
| 31 | 시간별 관측 | metric_samples·이전·만료 | 장기 실제 시계열 |
| 32 | 증가 속도 | velocity 실제 경과 시간 | 수요 해석은 별도 |
| 33 | 동종 비교 | 정의/모집단/정규화/형식/연령/채널 비교 | 코호트 실제 정의 |
| 34 | 단계별 지연 | latency·미확인 null | 공급자 공개 시각 미확인 가능 |
| 35 | 교란 요인 | forecast별 confounders·counter_search·반증 근거 고정 | 자동 계절/광고 분리 미구현 |
| 36 | 독립 확산 | origin 생산자/관계/확인 상태 | 재인용 의미 검토 |
| 37 | 탐색·추천 분리 | signal exploration·기존 opportunity gate 유지 | 실측 추천 품질 |
| 38 | 감소·포화 | 음의 카운터 표시·불만/가격 반례 절차 | 카운터 정정과 수요 감소 구분 |
| 39 | 해외→한국 | transfer 제약/대안/기한/반증 | 실제 채택 결과 |
| 40 | 점수 보정 | trend-forecast precision/recall/Brier·기준확률·구간 보정 | 실제 만기 사전등록 결과 |
| 41 | 분야 범위·목표 | market-map + market_scope | 전 분야 심층 조사 미완료 |
| 42 | 넓이·깊이 | unknown 우선순위·기존 agenda 배분 | 가정의 실제 효용 |
| 43 | 신조어·별칭 | glossary/queries | 실제 적합률 수집 |
| 44 | 교차 분야 | dossier 다중 domain_ids·독립 분모 절차 | 의미 중복 병합은 수동 |
| 45 | 지역 | market_scope/competitor region | 실제 지역 표본 |
| 46 | B2B | 양식/결재/입찰/납품 playbook | 실제 현장 자료 |
| 47 | 통계 분모 | metric_definition/compare | 공식 원문 대조 |
| 48 | 경쟁 이력 | competitor revision/diff | 가격/기능 정기 확인 |
| 49 | 정책 단계 | policy 단계 enum | 공식 단계 대조 |
| 50 | 비디지털 실무 | 제조/식품/돌봄/교육/로컬/B2B playbook | 분야별 현장 검토 |
| 51 | 의미 대조 | claim_review·주장 범위 대조 절차 + research-qa 주장 연결/집중도 감사 | 스키마는 진실성 증명 아님 |
| 52 | 원 생산자 | origin + duplicates URL/제목 유사 후보 | 의미·원 생산자 최종 확인은 별도 |
| 53 | 단위·기간 | metric_definition/compare | 입력 정의 실제 검토 |
| 54 | 신선도 | 기존 TTL + due-reviews 재검토 대기열 | 원문 재열람 없이 검토일 갱신하지 않음 |
| 55 | 변경 영향 | impact 다단계 참조·순환 종료·source_change | 미연결 자연어 참조 미탐지 |
| 56 | 첨부/OCR | attachment_review·파일 해시 | 실제 렌더/숫자 대조 |
| 57 | 발언자 구분 | claim_review speaker_role | 실제 발언자 확인 |
| 58 | 반례 조사 | counter_search·실패/불만 검색 절차 + dossier별 반박 근거 누락 큐 | 실제 열람 필요 |
| 59 | 문제 해석 | 상황/빈도/피해/지불자 질문 절차 | 키워드 수는 고객 수 아님 |
| 60 | 미지수 우선 | unknown 영향/불확실성/적합성/비용 | 우선순위는 성공확률 아님 |
| 61 | 창업자 적합 | portfolio + competition evaluate의 적합성·근거·시연 비용/기간 비교 | 평가 가정의 실제 근거 확인 |
| 62 | 발상 다양성 | business-check 현 상태·수작업·비AI 대안 누락 탐지 | 대안의 내용·실효성 검토 |
| 63 | 구매 역할 | business customer/user/buyer/approver | 실제 승인/예산 |
| 64 | 좁은 진입 | beachhead/reachable_this_month | 접근 가능성 증거 |
| 65 | BM 숫자 | economics 다중 시나리오 | 실제 가격/원가/반복 구매 |
| 66 | 단위경제성 | economics + cashflow 기간별 입출금·최대 자금 부족 | 실제 지급 시점·세무·자금조달 확인 필요 |
| 67 | 값싼 MVP | business-check 가설/담당/표본/시간/예산/통과·중단 검사 | 실제 승인된 실행 |
| 68 | GTM | business-check 대상/채널/초안/전환/분모/예산 검사 | 발송/광고 실행 안 함 |
| 69 | 운영 병목 | bottlenecks·분야별 playbook | 현장/공식 자료 확인 |
| 70 | 후보·기각 | portfolio + 공모전 후보 2~20개 파레토 비교·차단/미확인 별도 | 실제 포트폴리오 판단 |
| 71 | 인터뷰 패키지 | interview-pack dossier 기반 질문/동의 준비/기록표 | 실제 인터뷰 대기 |
| 72 | 실험 설계 | 기존 validation 불변 계획·안내형 절차 | 실제 사전 등록 필요 |
| 73 | 결과 연결 | 기존 result/evidence_links | 비식별 측정 원자료 |
| 74 | 표본 편향 | sampling 응답·적격·완료·편향 비중 계산 | 실제 대표성 검토 |
| 75 | 피드백→수정 | feedback-queue 버전 대조·거절 보존·diff 연결 | 변경 발생과 실제 제안 반영 구분 |
| 76 | 평가표→작성 | competition prepare/evaluate→application의 자격·마감·평가항목·근거 흐름 | 해당 공고 실제 대조 |
| 77 | 제출 파일 검수 | document_qa·문서 도구 렌더 절차 | 실제 DOCX/HWPX/PDF 검수 대기 |
| 78 | 예산 교차 | budget_link·기존 합계 검사 | 견적/허용 비목 대조 |
| 79 | 심사 연습 | 공모전 hard_blocks/evidence_gaps + 원문→대안→반증→실패 대응 | 실제 심사 예측 아님 |
| 80 | 성과 학습 | outcome 불변 기록·근거 | 실제 선정/탈락/매출 필요 |
| 81 | 단일 흐름 | competition 공고→후보→shortlist→dossier/application + workflow/team-queue | 외부 행위 무인 실행 아님 |
| 82 | 장애 대안 | capabilities fallback/intake·기존 실패 기록 | 실패를 변화 없음으로 해석 금지 |
| 83 | 비용 상한 | session/checkpoint 시간/요청/컨텍스트/용량/비용 | 전체 Codex 자동 계측 아님 |
| 84 | 갱신 간격 | TTL/한도 + forecast review_schedule_days와 team-queue 재검토 | 실제 정책 운영 검증 |
| 85 | 재개·실패 시험 | 기존 radar reliability·충돌/복원 테스트 | 장기 실제 장애 훈련 별도 |
| 86 | 대기열 처리량 | 기존 agenda + 미지수/체크포인트 + QA/재검토/피드백/코멘트 통합 큐 | 실제 읽기 처리량 |
| 87 | 변경 요약 | diff/recent_changes·판단 변화 우선 절차 | 의미 판단은 Codex 검토 |
| 88 | 이전·복구 | 이전 전 백업·무결성·새 폴더 복원 | 다른 기기 실제 시험 |
| 89 | 비밀·보존 | 선택적 macOS keychain 읽기·요약 export·만료 | 키 이전/공급자 계약 별도 |
| 90 | 실행 경계 | 로컬 의존·외부 보류 명시 | 클라우드/텔레그램 보류 유지 |
| 91 | 선행 기준선 | benchmark + forecast baseline_probability/decision_threshold/기한 고정 | 실제 비교 시험 필요 |
| 92 | 과거 재현 | cutoff 이후 근거 거부·회고 표시 | 사후 키워드 선택 자료 감사 |
| 93 | 오답 포함 분모 | trend-forecast TP/FP/FN/TN/pending/failed 불변 분모 | 전체 트렌드 정답 집합 아님 |
| 94 | 확률 보정 | trend-forecast 확률 구간·Brier·기준선 대비 개선 | 실제 만기 판정 자료 |
| 95 | 그룹별 오차 | domain/stage/horizon 그룹 평가 | 충분한 관측 필요 |
| 96 | 추가 소스 가치 | ablation-compare 조건 불일치 차단·증분 계산 | 실제 비교 실험 대기 |
| 97 | 팀 효율 | usability 조건별 완료율·시간·누락·재작업·오인용 집계 | 실제 팀원 과제 대기 |
| 98 | 개입·완주 | checkpoint/usability | 실제 과제 계측 필요 |
| 99 | 적대적 입력 | 비밀 URL/단위 불일치/미래 근거/충돌/리셋 회귀 | 허위 원문 의미 탐지 완전 자동 아님 |
| 100 | 출시 기준 | 이 등록부·자동 시험·패키지 검증 | 실사용/사업 결과 별도 판정 |

합성 시험을 실데이터 시험으로, 데이터 수집을 고객 수요로, 절차를 구현된 수집 어댑터로 보고하지 않는다.
이 표는 100/100 완료 인증서가 아니라 요구사항 반영과 남은 검증을 공개하는 추적표다.
