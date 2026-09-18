# 허구김 — Public Codex Marketplace

누구나 **허구김**(`korea-startup-intelligence`) 플러그인 0.6.0을 Codex에 설치할 수 있도록 만든 공개 마켓플레이스입니다.
API 키나 예약 자동화 없이 사용자가 호출한 현재 Codex 작업에서 공개 SNS·채용·특허·표준·논문·기술 가격·조달·앱·커머스·펀딩·규제·공식 통계 원문을 조사합니다. 검토 근거를 초기 시장공백, 아이디어 검증, 창업자 시간·예산, 실행·보류·폐기 관리에 연결합니다. 실험 결과가 없어도 공개자료·대안·채널·단위경제 가정·첫 검증 준비로 진행하되 가상 고객 결과는 만들지 않습니다. 공개 웹 표본은 플랫폼 전체 실시간 수집이 아니며 사업 성공을 보장하지 않습니다. [76개 개선 항목의 구현·대기 상태](plugins/korea-startup-intelligence/ACCEPTANCE_76.md)를 확인해 주세요.

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
