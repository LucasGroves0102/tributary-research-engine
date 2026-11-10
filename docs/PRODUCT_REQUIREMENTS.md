# Product requirements

## Purpose

Given a company and a bounded research objective, the engine must produce an evidence-backed research artifact using only Tributary's authorized Query API. It must never use direct database access or Tributary's own assistant as a proxy.

## Current release contract

- Read-only CLI with plan inspection, execution, resume, inspect, and cancel.
- Resolve an exact company match, then fetch financials, data notes, and optional filings, filing sections, segments, peers, earnings, and events selected by the objective.
- Publish only historical financial figures that have a valid value, unit, period, source type, and SEC filing accession. Derived figures without component inputs are marked unverified.
- Keep user identity in the bearer token. Stop on 401/403. Bound HTTP retries, request time, total run time, and tool calls.
- For scenario objectives, obtain bear/base/bull projections from Tributary's read-only model endpoint and label them as forecasts, separate from reported figures.
- Persist owner-only, atomic checkpoints and a metadata-only trace. Do not persist tokens or objective text.

## Target release contract

The target design calls for an LLM planner constrained to a validated task schema, interpreted narrative evidence with section offsets, peer analysis, verified claims, a complete multi-section memo, and stable trace fixtures for an independent evaluation framework. The current release does not yet meet that target. Live contract validation and an authorized smoke test are required before a production-readiness claim.

## Acceptance gates

1. A permitted identity can run the CLI against live Tributary data.
2. A denied identity cannot obtain financial data and the run stops.
3. An interrupted run resumes without repeating completed tasks.
4. Every published numeric claim links to a structured evidence record, or is visibly unverified.
5. Published narrative claims link to precise filing passages or are visibly unverified.
6. Bearer tokens and private user content do not appear in reports, checkpoints, or traces.
7. A separate evaluation runner can consume the versioned run, finding, evidence, and trace schemas.
