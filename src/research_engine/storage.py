"""Atomic, owner-only local checkpoints and redacted execution traces."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .contracts import Run


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def directory(self, run_id: str, *, create: bool = True) -> Path:
        from uuid import UUID

        try:
            UUID(run_id)
        except ValueError as exc:
            raise ValueError("Invalid run ID") from exc
        path = self.root / run_id
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
            path.chmod(0o700)
        return path

    def write_json(self, run_id: str, filename: str, value: Any) -> None:
        if filename not in {"run.json", "evidence.json", "findings.json", "results.json"}:
            raise ValueError("Invalid output filename")
        directory = self.directory(run_id)
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2, ensure_ascii=False, default=str)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory / filename)
            self._sync_directory(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def read_json(self, run_id: str, filename: str) -> Any:
        if filename not in {"run.json", "evidence.json", "findings.json", "results.json"}:
            raise ValueError("Invalid output filename")
        with (self.directory(run_id, create=False) / filename).open(encoding="utf-8") as stream:
            return json.load(stream)

    def save_run(self, run: Run) -> None:
        self.write_json(run.id, "run.json", run.to_dict())

    def load_run(self, run_id: str) -> Run:
        return Run.from_dict(self.read_json(run_id, "run.json"))

    def append_trace(self, run_id: str, event: dict[str, Any]) -> None:
        allowed = {"schema_version", "at", "run_id", "task_id", "event", "status", "duration_ms", "error_kind"}
        if not set(event) <= allowed:
            raise ValueError("Trace contains non-metadata fields")
        path = self.directory(run_id) / "trace.jsonl"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def write_report(self, run_id: str, markdown: str) -> None:
        directory = self.directory(run_id)
        fd, temporary = tempfile.mkstemp(prefix=".report-", dir=directory)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(markdown)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, directory / "report.md")
            self._sync_directory(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @contextmanager
    def lock(self, run_id: str) -> Iterator[None]:
        """Prevent two workers from advancing the same run concurrently."""
        path = self.directory(run_id) / ".lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Run is already being executed") from exc
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
