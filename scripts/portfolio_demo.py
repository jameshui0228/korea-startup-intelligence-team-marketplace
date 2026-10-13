#!/usr/bin/env python3
"""Exercise the existing CLI in an isolated, offline temporary workspace."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "plugins/korea-startup-intelligence/scripts/ksi.py"


def main():
    with tempfile.TemporaryDirectory(prefix="ksi-portfolio-") as workspace:
        def run(*args):
            result = subprocess.run(
                [sys.executable, str(CLI), "--workspace", workspace, *args],
                check=True, capture_output=True, text=True, timeout=30,
            )
            return json.loads(result.stdout)

        run("init")
        packet = run("blue-ocean", "frontier", "--topic", "기업·시장 조사", "--limit", "30")
        prompts = packet["generation_prompts"]
        coverage = packet["coverage"]
        if len(prompts) != 30 or coverage["reviewed_atoms"] != 0:
            raise ValueError("Unexpected prompt count or source coverage in empty workspace")
        if any(p["trend_anchor_status"] != "unanchored_research_prompt" for p in prompts):
            raise ValueError("Unreviewed prompts must not be promoted to evidence-backed hypotheses")
        print(json.dumps({
            "demo": "offline_empty_workspace",
            "mode": packet["mode"],
            "generated_research_prompts": len(prompts),
            "reviewed_sources": coverage["reviewed_atoms"],
            "all_prompts_unanchored": True,
            "meaning": "Research questions generated. No original sources have been reviewed and no market opportunity has been validated.",
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
