# Tributary API integration

Source available in this repository: [TRIBUTARY_CONTEXT.md](../TRIBUTARY_CONTEXT.md), dated 2026-11-09. The service's source and route README are outside this repository and were not inspected because this work was restricted to this directory. Treat current response-shape support as provisional until those contracts can be brought into this repository or checked in an authorized live smoke test.

Base URL: `https://tributary.lucasgroves.dev/api/query`. Routes used: `/v1/companies/search?q=`, `/v1/companies/{company_id}/{financials,filings,segments,peers,earnings,events,data-notes}`, and `/v1/companies/{company_id}/sections/{section_key}` for `item_1a` and `item_7`. The financials call requests `view=quarter`, `quarters=20`, `basis=fiscal`, and `readings=true`. The engine never sends a user ID; the bearer token identifies the current user.

HTTP 401/403 fail closed. 404/422 become classified errors. 429 and 5xx are retried at most twice, honoring numeric or HTTP-date `Retry-After` within the overall run deadline. Timeouts and network errors are bounded. The client does not follow redirects, limits connections to three, and rejects responses over 25 MB.

Without an injected in-process test transport, the client sends a bearer token only to `tributary.lucasgroves.dev` or an explicitly configured localhost API endpoint under `/api/query`.

The financial extractor accepts nested records with a metric name, decimal-string value, `period_end`, `unit`, `value_source`, and `citation.accession_no`. The section extractor accepts section text plus an accession and records exact character offsets for bounded excerpts. Unknown layouts are not interpreted. A live contract fixture is required before claiming broad coverage or production readiness. The CLI keeps the raw authorized responses locally for resume, with owner-only filesystem permissions. It never sends those responses to an LLM.

Use `research-engine probe --company NVDA` with an authorized token to print field names and types for the currently used routes without printing scalar values. Review the output against Tributary's source contract before expanding extraction logic.
