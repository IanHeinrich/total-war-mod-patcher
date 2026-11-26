"""RPFM table files (TSV) with an exact read/write round trip.

RPFM exports a DB table as::

    key<TAB>cost                                   <- line 1: column names
    #units_tables;3;db/units_tables/my_mod<TAB>    <- line 2: metadata (table;version;pack path), padded with tabs
    unit_a<TAB>800                                 <- data rows
    ...

``TableFile.to_text(TableFile.parse(text).…) == text`` for any file RPFM wrote:
line endings, a UTF-8 BOM, the metadata line's padding and a missing final
newline are all preserved, so editing a few rows never rewrites the rest.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

BOM = "﻿"


class TableFormatError(ValueError):
    """The file is not an RPFM table export (bad or missing metadata line)."""


@dataclass
class Metadata:
    table: str  # e.g. "units_tables" (or "Loc" for loc files)
    version: int
    pack_path: str  # e.g. "db/units_tables/my_mod"

    @classmethod
    def parse(cls, line: str, source: str = "<tsv>") -> Metadata:
        first_cell = line.split("\t", 1)[0]
        if not first_cell.startswith("#"):
            raise TableFormatError(f"{source}: line 2 must be RPFM's '#table;version;path' metadata line")
        parts = first_cell[1:].split(";")
        if len(parts) < 3 or not parts[0] or not parts[2]:
            raise TableFormatError(f"{source}: metadata line 2 must have 3 ';'-separated fields: {first_cell!r}")
        try:
            version = int(parts[1])
        except ValueError:
            raise TableFormatError(f"{source}: metadata version is not a number: {parts[1]!r}") from None
        return cls(table=parts[0], version=version, pack_path=parts[2])

    @property
    def fragment(self) -> str:
        """The file name inside the table folder (``my_mod`` for ``db/units_tables/my_mod``)."""
        return self.pack_path.rsplit("/", 1)[-1]


@dataclass
class TableFile:
    header: list[str]
    metadata: Metadata
    rows: list[list[str]]
    path: Path | None = None
    # Round-trip details
    metadata_line: str = ""
    newline: str = "\n"
    trailing_newline: bool = True
    bom: bool = False
    _index: dict[str, int] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ io
    @classmethod
    def parse(cls, text: str, path: Path | None = None) -> TableFile:
        source = str(path) if path else "<tsv>"
        bom = text.startswith(BOM)
        if bom:
            text = text[1:]
        newline = "\r\n" if "\r\n" in text[:4096] else "\n"
        trailing = text.endswith("\n")
        lines = text.split("\n")
        if trailing:
            lines.pop()
        lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
        if len(lines) < 2:
            raise TableFormatError(f"{source}: expected a column-name line and a metadata line")
        metadata = Metadata.parse(lines[1], source)
        return cls(
            header=lines[0].split("\t"),
            metadata=metadata,
            rows=[ln.split("\t") for ln in lines[2:]],
            path=path,
            metadata_line=lines[1],
            newline=newline,
            trailing_newline=trailing,
            bom=bom,
        )

    @classmethod
    def read(cls, path: Path) -> TableFile:
        return cls.parse(path.read_bytes().decode("utf-8"), path)

    def to_text(self) -> str:
        meta = self.metadata_line or self._default_metadata_line()
        lines = ["\t".join(self.header), meta, *("\t".join(r) for r in self.rows)]
        text = self.newline.join(lines) + (self.newline if self.trailing_newline else "")
        return (BOM if self.bom else "") + text

    def write(self, path: Path | None = None) -> Path:
        target = path or self.path
        if target is None:
            raise ValueError("No path to write the table to")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.to_text().encode("utf-8"))
        self.path = target
        return target

    def _default_metadata_line(self) -> str:
        m = self.metadata
        return "\t".join([f"#{m.table};{m.version};{m.pack_path}"] + [""] * (len(self.header) - 1))

    # ------------------------------------------------------------------ access
    @property
    def table(self) -> str:
        return self.metadata.table

    @property
    def version(self) -> int:
        return self.metadata.version

    def column(self, name: str) -> int:
        """Index of column ``name``; raises KeyError listing the real columns."""
        if not self._index:
            self._index = {h: i for i, h in enumerate(self.header)}
        try:
            return self._index[name]
        except KeyError:
            raise KeyError(f"No column {name!r} in {self.table}; columns: {', '.join(self.header)}") from None

    def has_column(self, name: str) -> bool:
        try:
            self.column(name)
            return True
        except KeyError:
            return False

    def cell(self, row: list[str], name: str) -> str:
        i = self.column(name)
        return row[i] if i < len(row) else ""

    def as_dict(self, row: list[str]) -> dict[str, str]:
        return {h: (row[i] if i < len(row) else "") for i, h in enumerate(self.header)}

    def from_dict(self, values: dict[str, str]) -> list[str]:
        unknown = set(values) - set(self.header)
        if unknown:
            raise KeyError(f"Unknown column(s) for {self.table}: {', '.join(sorted(unknown))}")
        return [str(values.get(h, "")) for h in self.header]

    def iter_dicts(self) -> Iterator[dict[str, str]]:
        for row in self.rows:
            yield self.as_dict(row)

    @classmethod
    def new(cls, table: str, version: int, pack_path: str, header: list[str]) -> TableFile:
        return cls(header=list(header), metadata=Metadata(table, version, pack_path), rows=[])
