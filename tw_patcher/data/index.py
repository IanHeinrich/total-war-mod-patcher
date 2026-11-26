"""Find extracted mods (``sources/``) and patch mods (``workspace/``) and their
table fragments.

A *mod* is a folder holding ``db/`` (and/or ``script/``, ``text/``): either a
direct child of ``sources/`` or ``workspace/``, or one level deeper when mods
are grouped (``sources/roc_sfo/!!roc_realms_ie``). A *fragment* is one table
file, ``db/<table>/<fragment>.tsv``; the game merges every fragment of a table.

Mods are named by their path relative to sources/ or workspace/
(``roc_sfo/!!roc_realms_ie``). ``ModIndex.resolve`` accepts that name, a
unique trailing part of it (``!!roc_realms_ie``), or a ``sources/`` /
``workspace/`` prefix to pick one when a source and a patch share a name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from .tsv import TableFile


class ModNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class Fragment:
    mod: Mod
    table: str  # folder name, e.g. "units_tables"
    name: str  # file stem, e.g. "my_mod"
    path: Path

    def load(self) -> TableFile:
        return self.mod.load(self.path)

    @property
    def label(self) -> str:
        return f"{self.mod.name}:{self.table}/{self.name}"


@dataclass(eq=False)
class Mod:
    name: str
    kind: str  # "source" | "patch"
    root: Path
    _cache: dict[Path, TableFile] = field(default_factory=dict, repr=False)

    @property
    def qualified(self) -> str:
        return f"{'sources' if self.kind == 'source' else 'workspace'}/{self.name}"

    @cached_property
    def fragments(self) -> dict[str, list[Fragment]]:
        """table -> fragments, each list sorted in the game's merge order (file name byte order)."""
        tables: dict[str, list[Fragment]] = {}
        db = self.root / "db"
        if db.is_dir():
            for tsv in db.glob("*/*.tsv"):
                tables.setdefault(tsv.parent.name, []).append(Fragment(self, tsv.parent.name, tsv.stem, tsv))
        for frags in tables.values():
            frags.sort(key=lambda f: f.name.encode("utf-8"))
        return dict(sorted(tables.items()))

    def tables(self) -> list[str]:
        return list(self.fragments)

    def load(self, path: Path) -> TableFile:
        if path not in self._cache:
            self._cache[path] = TableFile.read(path)
        return self._cache[path]


class ModIndex:
    def __init__(self, sources_dir: Path, workspace_dir: Path):
        self.sources_dir = sources_dir
        self.workspace_dir = workspace_dir

    @cached_property
    def mods(self) -> list[Mod]:
        return _discover(self.sources_dir, "source") + _discover(self.workspace_dir, "patch")

    @property
    def sources(self) -> list[Mod]:
        return [m for m in self.mods if m.kind == "source"]

    @property
    def patches(self) -> list[Mod]:
        return [m for m in self.mods if m.kind == "patch"]

    def resolve(self, name: str, kind: str | None = None) -> Mod:
        """Find a mod by name; see the module docstring for accepted forms."""
        wanted = name.replace("\\", "/").strip("/")
        candidates = self.mods
        for prefix, k in (("sources/", "source"), ("workspace/", "patch")):
            if wanted.startswith(prefix):
                wanted, kind = wanted[len(prefix) :], k
        if kind:
            candidates = [m for m in candidates if m.kind == kind]

        exact = [m for m in candidates if m.name == wanted]
        matches = exact or [m for m in candidates if m.name.endswith("/" + wanted)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            options = ", ".join(m.qualified for m in matches)
            raise ModNotFoundError(f"{name!r} is ambiguous: {options}")
        known = ", ".join(m.qualified for m in candidates) or "(none)"
        raise ModNotFoundError(f"No extracted mod or patch named {name!r}. Known: {known}")


def _is_mod_dir(path: Path) -> bool:
    """Holds extracted data itself. A bare ``db/`` folder isn't enough: a group
    folder can contain a mod *named* ``db`` (vanilla's db.pack extracts to
    ``<group>/db/db/...``), so require table files at ``db/<table>/*.tsv``."""
    if any((path / "db").glob("*/*.tsv")):
        return True
    return any((path / d).is_dir() and any((path / d).iterdir()) for d in ("script", "text"))


def _discover(base: Path, kind: str) -> list[Mod]:
    mods: list[Mod] = []
    if not base.is_dir():
        return mods
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if _is_mod_dir(child) or kind == "patch":
            # A patch folder counts even when still empty, so `list`/`validate` can see it.
            mods.append(Mod(child.name, kind, child))
            continue
        for grandchild in sorted(child.iterdir()):
            if grandchild.is_dir() and _is_mod_dir(grandchild):
                mods.append(Mod(f"{child.name}/{grandchild.name}", kind, grandchild))
    return mods
