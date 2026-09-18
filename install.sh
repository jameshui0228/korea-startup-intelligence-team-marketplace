#!/usr/bin/env bash
set -euo pipefail

TEAM_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if ! command -v codex >/dev/null 2>&1; then
  echo "Codex CLI를 찾을 수 없습니다. Codex 앱을 설치하고 다시 실행해 주세요." >&2
  exit 1
fi

codex plugin marketplace add "$TEAM_ROOT"
codex plugin add korea-startup-intelligence@korea-startup-team

echo "korea-startup-intelligence 0.1.1 설치 완료"
echo "Codex에서 새 작업을 열어 사용해 주세요."

