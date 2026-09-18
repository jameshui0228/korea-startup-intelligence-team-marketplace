# 허구김 — Public Codex Marketplace

누구나 **허구김**(`korea-startup-intelligence`) 플러그인 0.5.1을 Codex에 설치할 수 있도록 만든 공개 마켓플레이스입니다.
한국의 초기 시장공백 탐지부터 근거 검토, 아이디어 검증, 창업자 시간·예산 배분, 실행·보류·폐기 관리까지 다룹니다. 공모전·텔레그램은 선택 기능입니다. 직접 연결되지 않은 SNS·공식 통계 등을 실시간 수집하거나 사업 성공을 보장하지는 않습니다. [76개 개선 항목의 구현·대기 상태](plugins/korea-startup-intelligence/ACCEPTANCE_76.md)를 확인해 주세요.

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

각 팀원은 필요한 인증정보와 개인 작업공간을 자신의 컴퓨터에서 별도로 설정해야 합니다.
