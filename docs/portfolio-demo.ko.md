# 처음 보는 분을 위한 실행 예제

**한국어** | [English](portfolio-demo.md)

## 어떤 도구인가

공개 원문을 조사하는 Codex 작업과, 근거·가정·반대 근거·다음 행동을 기록하는 Python 도구를 연결합니다. 이 저장소는 모델 학습 프로젝트보다 **조사·검토 업무를 일관된 절차와 데이터 구조로 옮긴 사례**입니다.

## 네트워크 없이 확인하기

Python 3.10 이상, macOS/Linux에서 저장소 루트의 명령을 실행합니다.

```bash
python3 scripts/portfolio_demo.py
```

이 스크립트는 기존 CLI로 임시 작업공간을 초기화하고 조사 질문을 생성합니다. 실제 사용자 작업공간, 인증정보, 원문 수집은 사용하지 않으며 임시 파일은 실행 후 정리합니다.

[실제 실행 출력 JSON](portfolio-demo-output.json)

출력에서 확인할 항목:

| 항목 | 기대 결과 | 의미 |
|---|---|---|
| generated_research_prompts | 30 | 생성한 조사 질문 수 |
| reviewed_sources | 0 | 아직 읽고 검토한 원문이 없음 |
| all_prompts_unanchored | true | 질문을 검증된 시장 기회로 승격하지 않음 |

실제 조사에서는 원문을 읽고 출처와 근거를 연결하는 과정이 추가로 필요합니다. 30개 질문 생성만으로 30개 사업 아이디어가 검증되었다고 설명하지 않습니다.

## 코드 읽는 순서

1. [CLI 진입점](../plugins/korea-startup-intelligence/scripts/ksi.py): 사용자 명령과 기능 연결
2. [저장 계층](../plugins/korea-startup-intelligence/scripts/ksi_lib/model.py): SQLite 기반 상태·기록 관리
3. [주장별 근거 관리](../plugins/korea-startup-intelligence/scripts/ksi_lib/claim_ledger.py): 판단 근거와 변경 이력
4. [검증 테스트](../plugins/korea-startup-intelligence/tests/test_frontier.py): 근거 없는 질문을 검증된 가설과 구분

## 검증 범위

2026-10-13 로컬 Python 3.13에서 기존 테스트 586개가 통과했습니다. 전체 테스트는 다음 명령으로 실행합니다.

```bash
cd plugins/korea-startup-intelligence
python3 -m unittest discover -s tests -v
```

이 결과는 소프트웨어의 검증 시점 기록입니다. 시장 예측력, 창업 성공률, 외부 서비스의 현재 정상 동작을 대신 증명하지 않습니다.

[저장소 소개](../README.ko.md) · [상세 사용법](../plugins/korea-startup-intelligence/README.md)
