from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractionResult:
    mod_name: str
    output_dir: Path
    tables_exported: list[str] = field(default_factory=list)
    tables_failed: list[tuple[str, str]] = field(default_factory=list)
    scripts_extracted: list[str] = field(default_factory=list)
    scripts_failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.tables_exported) + len(self.scripts_extracted)

    @property
    def failure_count(self) -> int:
        return len(self.tables_failed) + len(self.scripts_failed)

    @property
    def total_count(self) -> int:
        return self.success_count + self.failure_count


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
    def total_count(self) -> int:
        return self.success_count + self.failure_count
