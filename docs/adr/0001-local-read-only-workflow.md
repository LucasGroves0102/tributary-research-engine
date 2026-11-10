# ADR 0001: Local read-only workflow first

Status: accepted for the initial implementation.

The engine uses a Python CLI, a deterministic task graph, and owner-only local JSON checkpoints. This makes authorization, evidence rules, and interruption behavior testable without adding a server or an agent framework. All production-data reads go through Tributary's Query API. The architecture leaves room for a stronger planner and durable service storage after real integration is validated. A local process can be interrupted safely; cross-host coordination and workspace write-back are outside the current implementation.
