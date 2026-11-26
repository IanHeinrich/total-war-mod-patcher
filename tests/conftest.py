"""Outside-in test harness: every test drives the real ``tw-patcher`` CLI in a
subprocess, against a throwaway config/modding root and a fake RPFM server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from .fake_rpfm import FakeRPFM

GAME = "warhammer_3"


def tsv(table: str, name: str, header: list[str], rows: list[list[str]], version: int = 0) -> str:
    """Build a table file the way RPFM exports it: column names on line 1,
    ``#table;version;db/table/name`` metadata on line 2, then data rows."""
    lines = ["\t".join(header)]
    metadata = [f"#{table};{version};db/{table}/{name}"] + [""] * (len(header) - 1)
    lines.append("\t".join(metadata))
    lines += ["\t".join(r) for r in rows]
    return "\n".join(lines) + "\n"


@dataclass
class Result:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


@dataclass
class Workspace:
    """A modding root plus the env that points tw-patcher at it."""

    home: Path
    root: Path
    env: dict[str, str]
    schemas: Path

    @property
    def sources(self) -> Path:
        return self.root / "sources"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def output(self) -> Path:
        return self.root / "output"

    def run(self, *args: str, input: str | None = None, timeout: float = 60) -> Result:
        proc = subprocess.run(
            [sys.executable, "-m", "tw_patcher", *args],
            env=self.env,
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        return Result(proc.returncode, proc.stdout, proc.stderr)

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path


@pytest.fixture(params=["legacy", "jsonrpc"], ids=["rpfm-legacy", "rpfm-jsonrpc"])
def rpfm(request: pytest.FixtureRequest) -> Iterator[FakeRPFM]:
    """A fake RPFM server; every test using it runs once per server protocol."""
    server = FakeRPFM(dialect=request.param).start()
    yield server
    server.stop()


def _make_workspace(tmp_path: Path, rpfm_port: int | None) -> Workspace:
    home = tmp_path / "home"
    root = tmp_path / "modding"
    schemas = tmp_path / "schemas"
    for d in (home, root, schemas):
        d.mkdir()
    (home / "config.json").write_text(json.dumps({"selected_game": GAME, "modding_root": str(root)}), encoding="utf-8")
    env = {
        **os.environ,
        "TW_PATCHER_HOME": str(home),
        # Empty by default so tests never pick up a real RPFM schema from this machine;
        # a test opts in by writing schema_wh3.ron into Workspace.schemas.
        "TW_PATCHER_SCHEMA_DIR": str(schemas),
        "PYTHONIOENCODING": "",  # exercise tw-patcher's own stream handling
        "COLUMNS": "200",  # keep Rich from wrapping assertions apart
    }
    if rpfm_port is not None:
        env["TW_PATCHER_RPFM_PORT"] = str(rpfm_port)
    else:
        env["TW_PATCHER_RPFM_PORT"] = "9"  # discard port: nothing should try to reach RPFM
    return Workspace(home=home, root=root, env=env, schemas=schemas)


@pytest.fixture
def ws(tmp_path: Path, rpfm: FakeRPFM) -> Workspace:
    """Workspace wired to the fake RPFM server (runs once per RPFM protocol)."""
    return _make_workspace(tmp_path, rpfm.port)


@pytest.fixture
def offline_ws(tmp_path: Path) -> Workspace:
    """Workspace for commands that never talk to RPFM (tables, show, diff, validate, ...)."""
    return _make_workspace(tmp_path, None)
