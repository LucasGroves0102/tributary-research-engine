"""Command line interface. Tokens are read from the environment, never arguments."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from .client import TributaryClient, TributaryError
from .contract_probe import probe
from .contracts import SCHEMA_VERSION, Budget, Objective, Run, RunStatus, utc_now
from .demo import demo_transport
from .engine import ResearchEngine
from .planner import analyze_objective, make_plan
from .storage import RunStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-engine")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Start read-only company research")
    run.add_argument("--company", required=True)
    run.add_argument("--objective", required=True)
    run.add_argument("--max-tool-calls", type=int, default=30)
    run.add_argument("--max-duration-seconds", type=int, default=300)
    run.add_argument("--forecast-years", type=int, default=3)
    run.add_argument("--dry-run", action="store_true")
    resume = commands.add_parser("resume", help="Resume an interrupted run")
    resume.add_argument("run_id")
    inspect = commands.add_parser("inspect", help="Show saved run metadata")
    inspect.add_argument("run_id")
    cancel = commands.add_parser("cancel", help="Cancel an unfinished run")
    cancel.add_argument("run_id")
    contract = commands.add_parser("probe", help="Inspect live API field shapes without values")
    contract.add_argument("--company", required=True)
    demo = commands.add_parser("demo", help="Run a pinned synthetic offline fixture")
    demo.add_argument("--objective", default="Financial summary")
    demo.add_argument("--forecast-years", type=int, default=3)
    return parser


async def _execute(engine: ResearchEngine, run: Run) -> int:
    result = await engine.execute(run)
    print(json.dumps({
        "run_id": result.id,
        "status": result.status,
        "company_id": result.company_id,
        "tool_calls": result.tool_calls,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "output": str(engine.store.directory(result.id)),
        "errors": result.errors,
    }, indent=2))
    return 0 if result.status == RunStatus.COMPLETED else 1


async def _main(args: argparse.Namespace) -> int:
    if args.command == "run":
        objective = Objective(
            args.company, args.objective,
            Budget(args.max_tool_calls, args.max_duration_seconds),
            forecast_years=args.forecast_years,
        )
        plan = make_plan(objective)
        if args.dry_run:
            print(json.dumps({"schema_version": SCHEMA_VERSION,
                              "topics": sorted(analyze_objective(objective.request)),
                              "tasks": [asdict(t) for t in plan]}, indent=2))
            return 0
    if args.command == "probe":
        token = os.environ.get("TRIBUTARY_TOKEN", "")
        if not token:
            print("TRIBUTARY_TOKEN is required for live probes", file=sys.stderr)
            return 2
        base_url = os.environ.get("TRIBUTARY_BASE_URL", "https://tributary.lucasgroves.dev/api/query")
        async with TributaryClient(token, base_url) as client:
            print(json.dumps(await probe(client, args.company), indent=2))
        return 0
    store = RunStore(args.runs_dir)
    if args.command == "inspect":
        run = store.load_run(args.run_id)
        print(json.dumps({
            "id": run.id, "status": run.status, "company_id": run.company_id,
            "created_at": run.created_at, "updated_at": run.updated_at,
            "tool_calls": run.tool_calls, "task_status": run.task_status,
            "elapsed_seconds": round(run.elapsed_seconds, 3),
            "plan": [asdict(task) for task in run.plan],
            "topics": run.topics,
            "errors": run.errors,
        }, indent=2))
        return 0
    if args.command == "cancel":
        with store.lock(args.run_id):
            run = store.load_run(args.run_id)
            if run.status in {RunStatus.COMPLETED, RunStatus.PARTIAL}:
                raise ValueError("Finished runs cannot be cancelled")
            run.status = RunStatus.CANCELLED
            run.updated_at = utc_now()
            store.save_run(run)
            store.append_trace(run.id, {
                "schema_version": SCHEMA_VERSION, "at": run.updated_at,
                "run_id": run.id, "task_id": "run", "event": "state",
                "status": RunStatus.CANCELLED,
            })
        print(json.dumps({"run_id": run.id, "status": run.status}))
        return 0
    if args.command == "demo":
        async with TributaryClient("fixture-only", "https://fixture.invalid/api/query",
                                   transport=demo_transport()) as client:
            engine = ResearchEngine(client, store)
            run = engine.create(Objective("ACME", args.objective,
                                          forecast_years=args.forecast_years), data_mode="fixture")
            return await _execute(engine, run)
    token = os.environ.get("TRIBUTARY_TOKEN", "")
    if not token:
        print("TRIBUTARY_TOKEN is required for live runs", file=sys.stderr)
        return 2
    base_url = os.environ.get("TRIBUTARY_BASE_URL", "https://tributary.lucasgroves.dev/api/query")
    async with TributaryClient(token, base_url) as client:
        engine = ResearchEngine(client, store)
        if args.command == "run":
            run = engine.create(objective)
        else:
            run = store.load_run(args.run_id)
        return await _execute(engine, run)


def main() -> None:
    try:
        code = asyncio.run(_main(build_parser().parse_args()))
    except (ValueError, FileNotFoundError, TributaryError) as exc:
        print(str(exc), file=sys.stderr)
        code = 2
    except Exception:  # noqa: BLE001 - CLI boundary must not print sensitive exception data
        print("Research run failed unexpectedly; inspect run.json and trace.jsonl", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
