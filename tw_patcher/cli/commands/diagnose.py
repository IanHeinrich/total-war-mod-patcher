"""tw-patcher diagnose: RPFM 5 diagnostics for a pack or patch."""

import asyncio
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import click

from ...clients.rpfm import RPFMClient
from ...clients.rpfm_protocols import DIAGNOSTIC_LEVELS, DIAGNOSTICS_UNSUPPORTED
from ...config import settings
from ...console import console
from ...exceptions import RPFMError
from ...services.repacking import RepackingService
from ...utils import normalize_rpfm_path
from .._data import emit_json, fail, json_option
from .._helpers import create_client, create_system_service, report_failures, require_game
from ..main import cli


@cli.command()
@click.option(
    "--pack",
    "-p",
    "pack",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=".pack file to diagnose",
)
@click.option("--patch", "patch", type=str, default=None, help="Patch mod in workspace/ to repack and diagnose")
@click.option(
    "--level",
    type=click.Choice(DIAGNOSTIC_LEVELS),
    default="info",
    show_default=True,
    help="Lowest level to report",
)
@json_option
def diagnose(pack: Path | None, patch: str | None, level: str, as_json: bool) -> None:
    """Run RPFM's diagnostics (invalid references, outdated tables, ...) on a pack. Needs RPFM 5+.

    With --patch, the patch is first repacked into a temporary pack. Exits 1 if any
    error-level problem is found.

    Examples:\b

        tw-patcher diagnose --patch empire_rebalance
        tw-patcher diagnose --pack output/elf_fix.pack --level warning --json
    """
    if (pack is None) == (patch is None):
        fail("Give exactly one of --pack or --patch")
    require_game()
    patch_path = _patch_path(patch) if patch is not None else None
    levels = list(DIAGNOSTIC_LEVELS[DIAGNOSTIC_LEVELS.index(level) :])

    try:
        items = asyncio.run(_run(pack, patch, levels))
    except Exception as e:
        console.error(f"Diagnostics failed: {e}")
        report_failures(getattr(e, "failed_tables", []), "file(s)")
        sys.exit(1)

    # The server is asked for these levels only; filter again in case it ignores the request.
    items = [i for i in items if i["level"] in levels or level == "info"]
    target = str(pack) if pack is not None else str(patch_path)
    counts = {lvl: sum(1 for i in items if i["level"] == lvl) for lvl in reversed(DIAGNOSTIC_LEVELS)}

    if as_json:
        emit_json({"target": target, "counts": counts, "diagnostics": items})
    else:
        _print_report(target, items, counts)
    if counts["error"]:
        sys.exit(1)


def _patch_path(patch: str) -> Path:
    try:
        path = settings.get_patch_mod_path(patch)
    except ValueError as e:
        fail(str(e))
    if not path.is_dir():
        fail(f"Patch mod '{patch}' not found in {settings.workspace_dir}")
    return path


async def _run(pack: Path | None, patch: str | None, levels: list[str]) -> list[dict[str, Any]]:
    system = create_system_service()
    client = create_client()
    await system.connect_client(client)
    try:
        if not client.supports_diagnostics:
            raise RPFMError(DIAGNOSTICS_UNSUPPORTED)
        if pack is not None:
            assert settings.selected_game
            await client.set_game_selected(settings.selected_game)
            return await _diagnose(client, pack, levels)
        assert patch is not None
        with tempfile.TemporaryDirectory(prefix="tw-patcher-diagnose-", ignore_cleanup_errors=True) as tmp:
            temp_pack = Path(tmp) / f"{patch}.pack"
            await RepackingService(settings, client).repack(patch, temp_pack, allow_partial=False)
            return await _diagnose(client, temp_pack, levels)
    finally:
        await client.disconnect()


async def _diagnose(client: RPFMClient, pack: Path, levels: list[str]) -> list[dict[str, Any]]:
    handle = await client.open_pack_file(normalize_rpfm_path(pack))
    try:
        with console.status("Running RPFM diagnostics..."):
            return await client.run_diagnostics(handle, levels if len(levels) < len(DIAGNOSTIC_LEVELS) else None)
    finally:
        try:
            await client.close_pack_file(handle)
        except Exception as e:
            console.warning(f"Could not close pack {handle}: {e}")


def _print_report(target: str, items: list[dict[str, Any]], counts: dict[str, int]) -> None:
    if not items:
        console.success(f"No problems reported for {target}")
        return
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_path[item["path"] or "(whole pack)"].append(item)
    for path in sorted(by_path):
        console.header(path)
        for item in sorted(by_path[path], key=lambda i: -_rank(i["level"])):
            columns = f" [columns: {', '.join(item['columns'])}]" if item.get("columns") else ""
            console.item(f"{item['level']:<7} {item['report_type']}: {item['message']}{columns}")
    summary = ", ".join(f"{n} {lvl}(s)" for lvl, n in counts.items() if n) or f"{len(items)} item(s)"
    if counts["error"]:
        console.error(f"{target}: {summary}")
    else:
        console.warning(f"{target}: {summary}")


def _rank(level: str) -> int:
    return DIAGNOSTIC_LEVELS.index(level) if level in DIAGNOSTIC_LEVELS else -1
