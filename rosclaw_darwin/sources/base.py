"""Base importer for external task sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from rosclaw_darwin.tdl.schema import Task


class SourceImporter(ABC):
    """Base class for importing tasks from external repositories."""

    name: str = "base"

    def __init__(self, repo_path: Path | None = None, config: dict | None = None):
        self.repo_path = repo_path
        self.config = config or {}

    @abstractmethod
    def scan(self) -> list[dict]:
        """Return raw task records discovered from source repo."""

    @abstractmethod
    def import_task(self, record: dict) -> Task:
        """Convert one source task record into ROSClaw-TDL."""

    def import_all(self, limit: int | None = None) -> list[Task]:
        records = self.scan()
        if limit is not None:
            records = records[:limit]
        return [self.import_task(r) for r in records]
