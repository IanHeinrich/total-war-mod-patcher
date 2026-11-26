from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ExtractionPlan:
    """What extracting one pack would produce (``extract --dry-run``)."""

    pack_path: Path
    output_dir: Path
    tables: list[str]
    scripts: list[str]
    replaces_existing: bool
    locs: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    mod_name: str
    output_dir: Path
    tables_exported: list[str] = field(default_factory=list)
    tables_failed: list[tuple[str, str]] = field(default_factory=list)
    scripts_extracted: list[str] = field(default_factory=list)
    scripts_failed: list[tuple[str, str]] = field(default_factory=list)
    locs_exported: list[str] = field(default_factory=list)
    locs_failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.tables_exported) + len(self.scripts_extracted) + len(self.locs_exported)

    @property
    def failure_count(self) -> int:
        return len(self.tables_failed) + len(self.scripts_failed) + len(self.locs_failed)

    @property
    def failures(self) -> list[tuple[str, str]]:
        return self.tables_failed + self.scripts_failed + self.locs_failed


@dataclass
class SourceStatus:
    """Whether an extracted source in ``sources/`` still matches the pack it came from.

    ``state`` is ``current``, ``changed`` (pack size/mtime differ), ``missing``
    (pack gone) or ``unknown`` (no ``.tw-source.json``).
    """

    name: str
    path: Path
    state: str
    info: dict[str, Any] | None = None

    @property
    def pack(self) -> str | None:
        return self.info.get("pack") if self.info else None


@dataclass
class TableChangeSummary:
    table: str
    added: int
    removed: int
    changed: int


@dataclass
class RefreshResult:
    """One re-extracted source, and the row changes in tables a workspace patch also has."""

    source: SourceStatus
    result: ExtractionResult | None = None
    error: str | None = None
    table_changes: list[TableChangeSummary] = field(default_factory=list)


@dataclass
class RepackResult:
    pack_name: str
    output_path: Path
    tables_imported: list[str] = field(default_factory=list)
    tables_failed: list[tuple[str, str]] = field(default_factory=list)
    scripts_imported: list[str] = field(default_factory=list)
    scripts_failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.tables_imported) + len(self.scripts_imported)

    @property
    def failure_count(self) -> int:
        return len(self.tables_failed) + len(self.scripts_failed)

    @property
    def failures(self) -> list[tuple[str, str]]:
        return self.tables_failed + self.scripts_failed
