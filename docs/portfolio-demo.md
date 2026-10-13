# Offline Demo & Code Tour

[Repository](../README.md) · [한국어](portfolio-demo.ko.md)

## What This Demonstrates

The plugin connects Codex research of public sources with a Python workflow for recording evidence, assumptions, counterevidence, and follow-up actions. It is a **research-process and data-structure project**, not a model-training project.

## Run Without Network Access

Use Python 3.10 or later on macOS or Linux. From the repository root:

```bash
python3 scripts/portfolio_demo.py
```

The script initializes a temporary workspace through the existing CLI and generates research questions. It does not use personal workspaces, credentials, or source collection. Temporary files are removed after the run.

[Recorded JSON output](portfolio-demo-output.json)

| Field | Expected Value | Meaning |
|---|---|---|
| `generated_research_prompts` | 30 | Number of generated questions |
| `reviewed_sources` | 0 | No original sources have been read and reviewed |
| `all_prompts_unanchored` | true | Questions have not been promoted to evidence-backed opportunities |

Real research requires reading original sources and linking evidence to claims. Generating 30 questions does not validate 30 business ideas. The underlying prompts remain in Korean.

## Read the Code

1. [CLI entry point](../plugins/korea-startup-intelligence/scripts/ksi.py): connects user commands to functionality.
2. [Storage layer](../plugins/korea-startup-intelligence/scripts/ksi_lib/model.py): manages state and records in SQLite.
3. [Claim ledger](../plugins/korea-startup-intelligence/scripts/ksi_lib/claim_ledger.py): tracks evidence and claim history.
4. [Frontier tests](../plugins/korea-startup-intelligence/tests/test_frontier.py): distinguish ungrounded questions from validated hypotheses.

## Verification Scope

The existing suite passed **586 tests** locally with Python 3.13 on 2026-10-13. Run it with:

```bash
cd plugins/korea-startup-intelligence
python3 -m unittest discover -s tests -v
```

This is a record of software verification. It does not establish market forecasting accuracy, startup success rates, or current external-service availability.

[Detailed user guide (Korean)](../plugins/korea-startup-intelligence/README.md)
