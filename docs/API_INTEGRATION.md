# Tributary API integration

Source: Tributary's [public Query API route README](https://github.com/LucasGroves0102/tributary/blob/main/services/query-api/README.md) and source, inspected on 2026-11-09. The API's own `/docs` and `openapi.json` are not public. Runtime behavior still needs an authorized live smoke test.

Base URL: `https://tributary.lucasgroves.dev/api/query`. Routes used: `/v1/companies/search?q=&access=financials`, `/v1/companies/{company_id}/{financials,filings,segments,peers,earnings,events,data-notes}`, `/v1/companies/{company_id}/sections/{section_key}` for `1A` and `7` with `form=10-K`, and read-only `POST /v1/companies/{company_id}/model`. The financials call requests `view=quarter`, `quarters=20`, `basis=fiscal`, and `readings=true`. The engine never sends a user ID; the bearer token identifies the current user.

HTTP 401/403 fail closed. 404/422 become classified errors. 429 and 5xx are retried at most twice, honoring numeric or HTTP-date `Retry-After` within the overall run deadline. Timeouts and network errors are bounded. The client does not follow redirects, limits connections to three, and rejects responses over 25 MB.

Without an injected in-process test transport, the client sends a bearer token only to `tributary.lucasgroves.dev` or an explicitly configured localhost API endpoint under `/api/query`.

The financial extractor accepts rows with a metric name, decimal-string value, `period_end`, `unit`, `value_source`, and `citation.accession_no`. The section extractor accepts `sections` entries with text and nested citation character offsets. The model workflow obtains `cases.base.defaults` in one call, then requests server-computed bear/base/bull projections using those defaults. Placeholder discovery projections are never published as evidence. Model years are recorded as forecasts with assumptions and server preview labels. Unknown layouts are not interpreted. A live contract fixture is required before claiming broad coverage or production readiness. The CLI keeps raw authorized responses locally for resume, with owner-only filesystem permissions. It never sends those responses to an LLM.

Use `research-engine probe --company NVDA` with an authorized token to print field names and types for the currently used routes without printing scalar values. Review the output against Tributary's source contract before expanding extraction logic.
