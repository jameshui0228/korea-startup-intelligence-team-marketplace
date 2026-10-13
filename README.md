# 허구김 | 근거를 관리하는 AI 조사 도구

정보의 출처, 해석, 아직 확인하지 않은 가정과 다음 행동을 함께 남기는 **Codex 플러그인 0.8.2**입니다.
Codex가 공개 원문을 조사하고, Python·SQLite 도구가 검토 근거와 후보별 판단 이력을 관리합니다. API 키나 예약 자동화는 핵심 기능의 선행 조건이 아닙니다.

[제작 배경·개인 역할](https://github.com/jameshui0228/data-analysis-portfolio/blob/main/projects/startup-intelligence.md) · [오프라인 실행 예제](docs/portfolio-demo.md) · [상세 사용법](plugins/korea-startup-intelligence/README.md) · [구현·대기 상태](plugins/korea-startup-intelligence/ACCEPTANCE_76.md)

## 무엇을 보여주는가

| 작업 | 구현 내용 |
|---|---|
| 자료 조사 구조화 | 원문과 검토 범위, 사실·추론·가정·미확인 내용을 구분 |
| 후보 검토 | 지지·반대 근거, 비교 기준, 검증할 질문을 함께 기록 |
| 실행 관리 | 다음 행동, 시간·예산, 진행·보류 상태와 판단 이력 연결 |
| 소프트웨어 검증 | Python 표준 라이브러리 기반 CLI·저장 계층과 기능별 테스트 |

AI 보조 도구를 활용해 제작했습니다. 사업 성공이나 투자 수익을 예측·보장하는 시스템이 아니며, 공개 웹 조사를 플랫폼 전체 실시간 수집으로 표현하지 않습니다.

## 설치 전에 1분 확인

Python 3.10 이상, macOS/Linux에서 저장소를 내려받아 실행합니다. 이 예제는 네트워크나 API 키를 사용하지 않습니다.

```bash
git clone https://github.com/jameshui0228/korea-startup-intelligence-team-marketplace.git
cd korea-startup-intelligence-team-marketplace
python3 scripts/portfolio_demo.py
```

빈 임시 작업공간에서 **조사 질문 30개**를 생성하고, 검토한 원문은 0개이며 결과가 미검증 조사 질문임을 확인합니다. 실제 시장조사를 마친 사례와 구분하기 위한 예제입니다. [실행 출력](docs/portfolio-demo-output.json)

## 테스트

```bash
cd plugins/korea-startup-intelligence
python3 -m unittest discover -s tests -v
```

2026-10-13, Python 3.13 로컬 환경에서 기존 **586개 테스트 통과**를 확인했습니다. 테스트는 코드 동작을 검증하며 사업성이나 모든 외부 서비스의 연결 상태를 입증하지는 않습니다.

## Codex에 플러그인으로 설치

GitHub 권한 요청이나 별도 파일 다운로드 없이 Codex 터미널에서 다음 명령을 실행합니다.

```bash
codex plugin marketplace add jameshui0228/korea-startup-intelligence-team-marketplace --ref main
codex plugin add korea-startup-intelligence@korea-startup-team
```

설치가 끝나면 Codex에서 새 작업을 열어 플러그인을 사용합니다.

로컬 복사본으로 설치해야 하는 경우에만 저장소 폴더에서 `bash install.sh`를 실행합니다.

## 업데이트

마켓플레이스와 플러그인을 새로 받아 설치합니다.

```bash
codex plugin marketplace upgrade korea-startup-team
codex plugin add korea-startup-intelligence@korea-startup-team
```

## 공유되지 않는 정보

다음 정보는 저장소에 포함하지 않습니다.

- API 키와 `.secrets.env`
- 텔레그램 토큰과 `.telegram.env`
- 개인 작업공간의 SQLite 데이터
- 개인 창업자 컨텍스트와 조사 이력

핵심 기능에는 별도 인증정보가 필요하지 않습니다. 각 팀원의 개인 작업공간은 자신의 컴퓨터에만 남고, 선택 connector를 명시적으로 사용할 때만 해당 인증정보를 별도로 설정합니다.
