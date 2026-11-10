# Tributary Research Engine

A read-only, resumable research workflow over Tributary's permission-checked Query API. The current implementation is a conservative foundation: it resolves a company, fetches financials and objective-selected research sources, emits a sourced historical-figure report, and records an evidence manifest and redacted execution trace. It does not yet synthesize narrative filings, compute forecasts, or use an LLM.

## Setup

Requires Python 3.12+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Get a token through your authorized Tributary account. Set `TRIBUTARY_TOKEN` in your shell; do not put it in a command argument or commit it. Until scoped API keys ship, the password-account token flow described in [TRIBUTARY_CONTEXT.md](TRIBUTARY_CONTEXT.md) is the available programmatic path.

```bash
export TRIBUTARY_TOKEN='...'
.venv/bin/research-engine run --company NVDA \
  --objective 'Analyze financial performance and major risks since FY2022'
```

The command prints a run ID and output directory. Each run contains `run.json`, `results.json`, `evidence.json`, `findings.json`, `report.md`, and `trace.jsonl`. Run directories are owner-only. `results.json` contains retrieved public-catalog company data; keep the `runs/` directory private. Tokens and objective text are not stored. `trace.jsonl` contains metadata only.

```bash
.venv/bin/research-engine run --company NVDA --objective 'Financial summary' --dry-run
.venv/bin/research-engine inspect RUN_ID
.venv/bin/research-engine resume RUN_ID
.venv/bin/research-engine cancel RUN_ID
.venv/bin/research-engine probe --company NVDA
.venv/bin/research-engine demo
```

The CLI uses a deterministic, objective-aware fallback plan and intentionally does not claim a complete investment thesis. Verified figures require a filing accession, period end, unit, and parseable numeric value. Optional source failures are surfaced as limitations. Authentication or permission failures stop the run. A live smoke test requires a user-provided token and should be run manually.

Complex objectives currently finish with `partial` status and list unmet requirements in the report. This prevents a completed HTTP workflow from being mistaken for a completed research thesis.

`probe` prints only the shapes of live API responses (field names and types), not values or filing text. It is intended to support contract validation with an authorized token.

`demo` runs the same workflow against a pinned, explicitly synthetic ACME fixture without network access or a token. Its artifact is labeled `fixture`; it is useful for reviewing the CLI and output format, not for financial conclusions.

## Design and current limits

The [project plan](TRIBUTARY_RESEARCH_ENGINE_PLAN.md) describes the target design and development phases. [API integration notes](docs/API_INTEGRATION.md) distinguish documented routes from response shapes that still need live contract validation. No direct database access, web-app scraping, or calls to Tributary's own assistant are used.
