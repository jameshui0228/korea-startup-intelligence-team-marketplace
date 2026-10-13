# Korea Startup Intelligence

**An evidence-tracking research workflow for Codex.**

Version **0.8.2** connects Codex-led review of public sources with Python and SQLite tooling for evidence, assumptions, candidate ideas, and decision history. API keys and scheduled automation are not prerequisites for the core workflow.

[Case study & my role](https://github.com/jameshui0228/data-analysis-portfolio/blob/main/projects/startup-intelligence.md) · [Offline demo](docs/portfolio-demo.md) · [Detailed guide (Korean)](plugins/korea-startup-intelligence/README.md) · [한국어](README.ko.md)

## What It Does

| Workflow | Implementation |
|---|---|
| Structure research | Record sources and review scope; separate facts, inferences, assumptions, and unknowns |
| Review candidates | Track supporting evidence, counterevidence, comparison criteria, and open questions |
| Manage next steps | Connect actions, time and budget constraints, proceed or hold status, and decision history |
| Verify software behavior | Standard-library Python CLI, storage layer, and feature-level tests |

Built with AI assistance. The tool structures research; it does not predict or guarantee business success or investment returns. Public-web research is not represented as exhaustive real-time monitoring.

The product's research prompts and detailed operating instructions are primarily in Korean. The English overview and demo guide explain the architecture, behavior, and limits.

## Try It Before Installing

Use Python 3.10 or later on macOS or Linux. This example requires no network access or API keys after cloning.

```bash
git clone https://github.com/jameshui0228/korea-startup-intelligence-team-marketplace.git
cd korea-startup-intelligence-team-marketplace
python3 scripts/portfolio_demo.py
```

The demo initializes a temporary workspace, generates **30 research questions**, and verifies that the reviewed-source count is zero and all questions remain unverified. It demonstrates workflow behavior, not completed market research.

[Recorded JSON output](docs/portfolio-demo-output.json) · [Implementation status (Korean)](plugins/korea-startup-intelligence/ACCEPTANCE_76.md)

## Tests

```bash
cd plugins/korea-startup-intelligence
python3 -m unittest discover -s tests -v
```

**586 existing tests passed** locally with Python 3.13 on 2026-10-13. This verifies tested code paths, not market viability or the availability of every external service.

## Install as a Codex Plugin

Run the existing marketplace installation commands in your Codex terminal:

```bash
codex plugin marketplace add jameshui0228/korea-startup-intelligence-team-marketplace --ref main
codex plugin add korea-startup-intelligence@korea-startup-team
```

Open a new Codex task after installation. For installation from a local checkout, run `bash install.sh` from the repository root.

## Update

```bash
codex plugin marketplace upgrade korea-startup-team
codex plugin add korea-startup-intelligence@korea-startup-team
```

## Private by Default

The repository does not include:

- API keys or `.secrets.env`.
- Telegram tokens or `.telegram.env`.
- Personal workspace SQLite databases.
- Personal founder context or research history.

Core functionality does not require separate credentials. Personal workspaces remain on the user's computer. Optional connectors require their own explicitly configured credentials.
