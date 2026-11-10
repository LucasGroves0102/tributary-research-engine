# Architecture

The CLI creates a versioned `Run` with an objective-selected deterministic task DAG. `ResearchEngine` advances tasks in dependency order through `TributaryClient`. The client is the only production-data boundary and accepts only documented read routes. Run state, retrieved public-catalog responses, evidence, findings, report, and trace are stored in an owner-only local run directory. Writes use atomic replacement; a per-run lock prevents concurrent workers from advancing the same run.

```text
CLI -> planner -> engine -> TributaryClient -> authorized Query API
                   |                  |
                   v                  v
                RunStore         classified errors
                   |
                   v
             evidence extractor -> verifier -> report
```

The current planner is deterministic. It selects read tools from the objective's topic words; the selected topics are saved, while the original objective text is redacted from checkpoints. The engine publishes numeric claims only from structured financial records. Filing sections can yield bounded excerpts with exact offsets, but excerpts are not interpreted as claims. This prevents unsupported synthesis until the actual response contracts and source locators are verified.

The run schema and trace have version `1.0`. The validated task plan is saved with the run, so resume does not regenerate it from newer code. Every task result is checkpointed before its completion status. A crash between those writes may repeat a read request, which is safe but uses another tool call. Resume rejects a completed task with a missing result or mismatched company identity. Completed tasks are not repeated on resume. Persisted execution time and call counts accumulate across resumes.

An executed run is `completed` only when the current implementation can fulfill its selected objective topics with verified findings. Requests for narrative analysis, peer comparison, or scenarios finish as `partial` with explicit unmet requirements. `partial` is terminal for that run; a later engine revision should start a new run rather than silently revising old output.

## Trust boundary

Filings and API responses are untrusted data. No retrieved text is executed as an instruction. Authentication is always the current user's bearer token; the engine does not pass a user ID. The client rejects non-HTTPS remote URLs, follows no redirects, limits connections, and never retries 401/403. Trace events contain only identifiers, timing, status, and classified error kinds.

## Gaps

Routes and response shapes were taken from Tributary's public route README and source, not yet confirmed against live responses. Live credentials were not present during development, so no authorized smoke test has run. Server-side model scenarios and keyword-based objective planning are implemented. Narrative extraction, LLM-based planning, peer comparison, parallel task execution, pagination, and independent evaluation remain to be implemented after contract validation. See [API_INTEGRATION.md](API_INTEGRATION.md).
