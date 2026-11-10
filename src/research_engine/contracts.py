"""Versioned contracts shared by the CLI, persistence, and future evaluators."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class RunStatus(StrEnum):
    CREATED = "created"
    PLANNED = "planned"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Budget:
    max_tool_calls: int = 30
    max_duration_seconds: int = 300

    def __post_init__(self) -> None:
        if not 1 <= self.max_tool_calls <= 1000:
            raise ValueError("max_tool_calls must be between 1 and 1000")
        if not 1 <= self.max_duration_seconds <= 86400:
            raise ValueError("max_duration_seconds must be between 1 and 86400")


@dataclass(frozen=True)
class Objective:
    company: str
    request: str
    budget: Budget = field(default_factory=Budget)

    def __post_init__(self) -> None:
        if not self.company.strip() or len(self.company) > 120:
            raise ValueError("company must contain 1 to 120 characters")
        if not self.request.strip() or len(self.request) > 2000:
            raise ValueError("request must contain 1 to 2000 characters")


@dataclass(frozen=True)
class Task:
    id: str
    tool: str
    depends_on: tuple[str, ...] = ()
    required: bool = True
    description: str = ""
    completion_criteria: str = ""


@dataclass
class Evidence:
    id: str
    kind: str
    company_id: str
    source_path: str
    retrieved_at: str
    payload: dict[str, Any]


@dataclass
class Finding:
    id: str
    category: str
    statement: str
    evidence_ids: list[str]
    verification: str
    reason: str | None = None


@dataclass
class Run:
    id: str
    objective: Objective
    plan: list[Task]
    topics: list[str] = field(default_factory=list)
    data_mode: str = "live"
    status: RunStatus = RunStatus.CREATED
    schema_version: str = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    company_id: str | None = None
    tool_calls: int = 0
    elapsed_seconds: float = 0.0
    task_status: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    unfulfilled: list[str] = field(default_factory=list)
    _last_status: RunStatus | None = field(default=None, repr=False, compare=False)
    _last_tick: float | None = field(default=None, repr=False, compare=False)

    @classmethod
    def new(cls, objective: Objective, plan: list[Task], topics: list[str], data_mode: str = "live") -> Run:
        if data_mode not in {"live", "fixture"}:
            raise ValueError("Unsupported data mode")
        return cls(id=str(uuid4()), objective=objective, plan=plan, topics=topics,
                   data_mode=data_mode)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["objective"]["request"] = "[redacted]"
        data.pop("_last_status")
        data.pop("_last_tick")
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Run:
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported run schema version")
        obj = data["objective"]
        data = dict(data)
        data["objective"] = Objective(
            company=obj["company"], request=obj["request"], budget=Budget(**obj["budget"])
        )
        data["plan"] = [Task(
            id=item["id"], tool=item["tool"], depends_on=tuple(item["depends_on"]),
            required=item["required"], description=item.get("description", ""),
            completion_criteria=item.get("completion_criteria", ""),
        ) for item in data["plan"]]
        data["status"] = RunStatus(data["status"])
        return cls(**data)
