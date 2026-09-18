#!/usr/bin/env python3
"""Fail release validation when any user audit item loses its explicit status."""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "ACCEPTANCE_76.md"
PATTERN = re.compile(r"^\|\s*(\d+)\s*\|\s*(구현|부분|무키 구현|실측 대기|범위 제외)\s*\|(.+)\|$")


def main():
    matches = [PATTERN.fullmatch(line) for line in TABLE.read_text().splitlines()]
    rows = [(int(match.group(1)), match.group(2), match.group(3).strip())
            for match in matches if match]
    ids = [row[0] for row in rows]
    missing = sorted(set(range(1, 77)) - set(ids))
    duplicate = sorted(number for number, count in Counter(ids).items() if count != 1)
    unexpected = sorted(set(ids) - set(range(1, 77)))
    empty = [number for number, _, detail in rows if len(detail) < 20]
    result = {"status": "pass" if not (missing or duplicate or unexpected or empty) else "fail",
              "items": len(rows), "statuses": dict(Counter(status for _, status, _ in rows)),
              "missing": missing, "duplicate": duplicate, "unexpected": unexpected,
              "insufficient_detail": empty,
              "boundary": "목록의 누락 검사이지 각 기능의 라이브 성능·시장성과 증명은 아닙니다."}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
