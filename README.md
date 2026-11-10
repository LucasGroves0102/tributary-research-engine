# Tributary Research Engine

> **🚧 Work in progress.** This is an experimental research project under active development. The core workflow runs end to end, but much of the target design is not built yet (see [Status](#status)), and it has not yet been validated against the live API with an authorized smoke test. Expect breaking changes.

An evidence-grounded financial research engine built on [Tributary](https://github.com/LucasGroves0102/tributary), an SEC-filings data platform. You give it a company and a research objective. It plans a bounded set of read-only tasks, runs them through Tributary's permission-checked Query API, and writes a report in which every published figure links back to an SEC filing. Anything it can't support is shown as unverified, never filled in.

The aim is to explore what a research agent needs beyond a chat wrapper: an explicit task plan, budgets, resumable runs, an evidence trail for every claim, and traces that a separate evaluation framework can grade.

## Status

**Working now**

- Resolves a company, then picks read-only sources from the objective's wording: financials and data notes always, plus filings, risk and MD&A sections, segments, peers, earnings releases and material events when the objective calls for them.
- Publishes a figure only when it has a filing accession, period end, unit and parseable value. Everything else is listed as unverified.
- For scenario objectives, calls Tributary's server-side forecast model and reports bear/base/bull projections in their own section, labeled as forecasts.
- Checkpoints each task, so an interrupted run resumes without repeating finished work. Tool-call and time budgets are enforced.
- Writes an evidence manifest and a redacted, metadata-only execution trace.
- Stops on authentication or permission errors. No direct database access, web-app scraping, or calls to Tributary's own assistant.

**Not built yet**

- LLM-based planning (the current planner is deterministic)
- Narrative analysis of filings (sections are shown as source excerpts, not interpreted)
- Peer comparison and earnings/event analysis
- Parallel task execution and pagination
- A live smoke test and recorded live contract fixtures
- A separate evaluation framework that grades runs
- Scoped API keys and MCP (waiting on Tributary to ship them)

Complex objectives finish with `partial` status and list their unmet requirements, so a completed HTTP workflow is never mistaken for a finished research thesis.

## Setup

Requires Python 3.12+.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Get a token through your authorized Tributary account and set `TRIBUTARY_TOKEN` in your shell. Don't put it in a command argument or commit it. Until Tributary ships scoped API keys, a password-account token is the available programmatic path.

```bash
export TRIBUTARY_TOKEN='...'
.venv/bin/research-engine run --company NVDA \
  --objective 'Analyze financial performance and major risks since FY2022'
```

The command prints a run ID and output directory. Each run contains `run.json`, `results.json`, `evidence.json`, `findings.json`, `report.md`, and `trace.jsonl`. Run directories are owner-only. `results.json` contains retrieved public-catalog company data, so keep the `runs/` directory private. Tokens and objective text are not stored, and `trace.jsonl` contains metadata only.

```bash
.venv/bin/research-engine run --company NVDA --objective 'Financial summary' --dry-run
.venv/bin/research-engine run --company NVDA --objective 'Financial summary and bear/base/bull scenarios' --forecast-years 3
.venv/bin/research-engine inspect RUN_ID
.venv/bin/research-engine resume RUN_ID
.venv/bin/research-engine cancel RUN_ID
.venv/bin/research-engine probe --company NVDA
.venv/bin/research-engine demo
```

- `--dry-run` prints the validated task plan without calling the API.
- Scenario requests first read the model's server defaults, then make a second read-only model call with them. Bear and bull use Tributary's preview policy.
- Optional source failures are reported as limitations; authentication or permission failures stop the run.
- `probe` prints only the shapes of live API responses (field names and types), not values or filing text. It supports contract validation with an authorized token.
- `demo` runs the same workflow against a pinned, explicitly synthetic ACME fixture with no network access or token. Its output is labeled `fixture`. It's for reviewing the CLI and output format, not for financial conclusions.

## Design docs

- [Architecture](docs/ARCHITECTURE.md): components, trust boundary, run lifecycle and known gaps
- [Product requirements](docs/PRODUCT_REQUIREMENTS.md): current and target release contracts
- [API integration notes](docs/API_INTEGRATION.md): which Tributary routes are used, and what still needs live validation
- [ADRs](docs/adr/)

This is research tooling, not investment advice. It has no brokerage or trading integration.

## License

No license has been chosen yet; see [docs/LICENSING.md](docs/LICENSING.md).
