import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..clients.rpfm import RPFMClient
from ..config import Settings
from ..console import console
from ..data.analysis import diff_mods
from ..data.index import Mod, ModIndex
from ..data.schema import Schema
from ..exceptions import ExtractionError, NoGameSelectedError
from ..models.pack import ExtractionPlan, ExtractionResult, RefreshResult, SourceStatus, TableChangeSummary
from ..utils import is_loc_path, normalize_rpfm_path

VANILLA_MOD_NAME = "vanilla"
SOURCE_INFO_FILE = ".tw-source.json"
SOURCE_STATES = ("current", "changed", "missing", "unknown")


def normalize_table_name(name: str) -> str:
    """``land_units``, ``land_units_tables`` and ``db/land_units_tables`` all mean ``land_units_tables``."""
    table = name.strip().replace("\\", "/").strip("/")
    if table.startswith("db/"):
        table = table[len("db/") :]
    if not table.endswith("_tables"):
        table += "_tables"
    return table


def _table_of(container_path: str) -> str | None:
    """``db/units_tables/mod`` -> ``units_tables``."""
    parts = container_path.split("/")
    return parts[1] if len(parts) > 2 and parts[0] == "db" else None


def vanilla_pack_path(settings: Settings) -> Path:
    """The selected game's ``data/db.pack``, or a ValueError saying why it can't be found."""
    data_dir = settings.game_data_dir
    if not data_dir:
        raise ValueError(
            f"No game directory configured for {settings.selected_game}. "
            "Set it with: tw-patcher config set-game-dir <game folder> (or in the UI)."
        )
    pack = data_dir / "db.pack"
    if not pack.is_file():
        raise ValueError(f"Vanilla db.pack not found: {pack}")
    return pack


def workshop_pack_paths(settings: Settings, workshop_ids: list[str]) -> list[Path]:
    """Every ``.pack`` in ``<workshop dir>/<id>/`` for each Workshop item ID."""
    if not workshop_ids:
        return []
    if not settings.game_dir:
        raise ValueError(
            f"No game directory configured for {settings.selected_game}, so the Workshop folder is unknown. "
            "Set it with: tw-patcher config set-game-dir <game folder> (or in the UI)."
        )
    workshop_dir = settings.game_workshop_dir
    if not workshop_dir:
        raise ValueError(
            f"No Steam Workshop folder found for {settings.selected_game} "
            f"(expected <steamapps>/workshop/content/<app id> next to {settings.game_dir})."
        )
    packs: list[Path] = []
    for workshop_id in workshop_ids:
        if not workshop_id.isdigit():
            raise ValueError(f"Invalid Workshop ID {workshop_id!r}: expected digits only.")
        item_dir = workshop_dir / workshop_id
        if not item_dir.is_dir():
            raise ValueError(f"Workshop item {workshop_id} is not downloaded: {item_dir} does not exist.")
        found = sorted(item_dir.glob("*.pack"))
        if not found:
            raise ValueError(f"Workshop item {workshop_id} has no .pack file in {item_dir}.")
        packs.extend(found)
    return packs


def workshop_id_from_path(pack_path: Path) -> str | None:
    """The item ID of a pack at ``.../workshop/content/<app id>/<id>/x.pack``, else None."""
    parts = pack_path.parts
    for i in range(len(parts) - 4):
        if parts[i].lower() == "workshop" and parts[i + 1].lower() == "content" and parts[i + 3].isdigit():
            return parts[i + 3]
    return None


def read_source_info(mod_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((mod_dir / SOURCE_INFO_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("pack") else None


def source_state(mod_dir: Path) -> tuple[str, dict[str, Any] | None]:
    info = read_source_info(mod_dir)
    if info is None:
        return "unknown", None
    pack = Path(info["pack"])
    try:
        stat = pack.stat()
    except OSError:
        return "missing", info
    same_size = stat.st_size == info.get("size")
    same_mtime = abs(stat.st_mtime - float(info.get("mtime") or 0)) < 0.001
    return ("current" if same_size and same_mtime else "changed"), info


def source_statuses(index: ModIndex) -> list[SourceStatus]:
    """State of every extracted source the index finds (read-only)."""
    statuses: list[SourceStatus] = []
    for mod in index.sources:
        state, info = source_state(mod.root)
        statuses.append(SourceStatus(name=mod.name, path=mod.root, state=state, info=info))
    return statuses


class ExtractionService:
    def __init__(self, settings: Settings, client: RPFMClient):
        self.settings = settings
        self.client = client

    async def _open(self, pack_path: Path) -> str:
        if not self.settings.selected_game:
            raise NoGameSelectedError()
        await self.client.set_game_selected(self.settings.selected_game)
        return await self.client.open_pack_file(normalize_rpfm_path(pack_path))

    async def _list_extractable(
        self, pack_handle: str, tables: list[str] | None = None
    ) -> tuple[list[str], list[str], list[str]]:
        paths = await self.client.list_paths(pack_handle)
        db_tables = [p for p in paths if p.startswith("db/")]
        if tables:
            wanted = {normalize_table_name(t) for t in tables}
            db_tables = [p for p in db_tables if _table_of(p) in wanted]
        scripts = [p for p in paths if p.startswith("script/")]
        locs = [p for p in paths if is_loc_path(p)]
        return db_tables, scripts, locs

    async def extract_pack(
        self, pack_path: Path, output_dir: Path, tables: list[str] | None = None, mod_name: str | None = None
    ) -> ExtractionResult:
        if not pack_path.exists():
            raise FileNotFoundError(f"Pack file not found: {pack_path}")

        mod_name = mod_name or self._mod_name_from_path(pack_path)
        mod_output_dir = output_dir / mod_name
        mod_output_dir.mkdir(parents=True, exist_ok=True)

        console.info(f"Extracting {pack_path}...")

        with console.status("Opening pack file..."):
            pack_handle = await self._open(pack_path)
        console.info(f"Opened pack file: {pack_handle}")

        try:
            db_table_paths, script_paths, loc_paths = await self._list_extractable(pack_handle, tables)
            console.info(
                f"Found {len(db_table_paths)} database tables, {len(script_paths)} script files "
                f"and {len(loc_paths)} loc files"
            )

            result = ExtractionResult(mod_name=mod_name, output_dir=mod_output_dir)

            with console.status("Exporting tables..."):
                for table_path in db_table_paths:
                    await self._export(
                        pack_handle, table_path, mod_output_dir, result.tables_exported, result.tables_failed
                    )

            if loc_paths:
                with console.status("Exporting loc files..."):
                    for loc_path in loc_paths:
                        await self._export(
                            pack_handle, loc_path, mod_output_dir, result.locs_exported, result.locs_failed
                        )

            if script_paths:
                with console.status("Extracting scripts..."):
                    try:
                        await self.client.extract_packed_files(
                            pack_handle, script_paths, normalize_rpfm_path(mod_output_dir)
                        )
                        result.scripts_extracted.extend(script_paths)
                        for sp in script_paths:
                            console.info(f"Extracted {sp}")
                    except Exception as e:
                        for sp in script_paths:
                            result.scripts_failed.append((sp, str(e)))
                        console.error(f"Failed to extract scripts: {e}")
        finally:
            await self._close_quietly(pack_handle)

        self._write_source_info(pack_path, mod_output_dir, result, tables)
        console.info(
            f"Extraction complete: {len(result.tables_exported)} tables, {len(result.scripts_extracted)} scripts, "
            f"{len(result.locs_exported)} loc files"
        )
        return result

    async def _export(
        self, pack_handle: str, container_path: str, mod_dir: Path, ok: list[str], failed: list[tuple[str, str]]
    ) -> None:
        """Export one table or loc file to ``<mod_dir>/<container path>.tsv``."""
        relative_path = Path(container_path)
        output_tsv = mod_dir / relative_path.with_suffix(".tsv")
        output_tsv.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self.client.export_tsv(pack_handle, container_path, normalize_rpfm_path(output_tsv))
            ok.append(str(relative_path))
            console.info(f"Exported {container_path}")
        except Exception as e:
            failed.append((container_path, str(e)))
            console.error(f"Failed to export {container_path}: {e}")

    @staticmethod
    def _write_source_info(pack_path: Path, mod_dir: Path, result: ExtractionResult, tables: list[str] | None) -> None:
        """Record what was extracted from where, so ``status`` can tell when the pack changes."""
        from .. import __version__

        stat = pack_path.stat()
        info = {
            "pack": str(pack_path.resolve()),
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "workshop_id": workshop_id_from_path(pack_path.resolve()),
            "tables": len(result.tables_exported),
            "scripts": len(result.scripts_extracted),
            "locs": len(result.locs_exported),
            "table_filter": sorted({normalize_table_name(t) for t in tables}) if tables else None,
            "tw_patcher_version": __version__,
        }
        (mod_dir / SOURCE_INFO_FILE).write_text(json.dumps(info, indent=2), encoding="utf-8")

    async def _close_quietly(self, pack_handle: str) -> None:
        """Release the RPFM pack handle without masking the error that got us here."""
        try:
            await self.client.close_pack_file(pack_handle)
        except Exception as e:
            console.warning(f"Could not close pack {pack_handle}: {e}")

    def _jobs(self, pack_paths: list[Path], vanilla: Path | None) -> list[tuple[Path, str]]:
        """(pack, folder name) pairs; vanilla's db.pack goes to ``vanilla/``."""
        jobs = [(vanilla, VANILLA_MOD_NAME)] if vanilla else []
        return jobs + [(p, self._mod_name_from_path(p)) for p in dict.fromkeys(pack_paths)]

    def _check_batch(self, pack_paths: list[Path], vanilla: Path | None = None) -> None:
        if len(pack_paths) > self.settings.max_mods:
            raise ValueError(f"Too many source mods ({len(pack_paths)}). Maximum is {self.settings.max_mods}.")
        if not pack_paths and not vanilla:
            raise ValueError("At least one source pack file is required.")
        seen: dict[str, Path] = {}
        for pack_path, mod_name in self._jobs(pack_paths, vanilla):
            if mod_name in seen and seen[mod_name].resolve() != pack_path.resolve():
                raise ValueError(
                    f"{seen[mod_name].name} and {pack_path.name} would both extract to sources/{mod_name}/. "
                    "Extract them in separate runs with different --output folders."
                )
            seen[mod_name] = pack_path

    async def plan_batch(
        self,
        pack_paths: list[Path],
        output_dir: Path,
        tables: list[str] | None = None,
        vanilla: Path | None = None,
    ) -> list[ExtractionPlan]:
        """What extract_batch would do, without writing anything."""
        self._check_batch(pack_paths, vanilla)
        plans: list[ExtractionPlan] = []
        for pack_path, mod_name in self._jobs(pack_paths, vanilla):
            pack_handle = await self._open(pack_path)
            try:
                db_tables, scripts, locs = await self._list_extractable(pack_handle, tables)
            finally:
                await self._close_quietly(pack_handle)
            target = output_dir / mod_name
            plans.append(
                ExtractionPlan(
                    pack_path=pack_path,
                    output_dir=target,
                    tables=db_tables,
                    scripts=scripts,
                    replaces_existing=target.exists(),
                    locs=locs,
                )
            )
        return plans

    async def extract_batch(
        self,
        pack_paths: list[Path],
        output_dir: Path,
        tables: list[str] | None = None,
        vanilla: Path | None = None,
    ) -> list[ExtractionResult]:
        self._check_batch(pack_paths, vanilla)
        jobs = self._jobs(pack_paths, vanilla)

        output_dir.mkdir(parents=True, exist_ok=True)

        for _pack_path, mod_name in jobs:
            existing = output_dir / mod_name
            if existing.exists():
                console.warning(f"Removing existing {existing}")
                shutil.rmtree(existing)

        console.info(f"Extracting {len(jobs)} mod(s) to: {output_dir}")

        results: list[ExtractionResult] = []
        for pack_path, mod_name in jobs:
            result = await self.extract_pack(pack_path, output_dir, tables, mod_name)
            results.append(result)

        if tables:
            self._warn_unmatched_tables(tables, results)

        total_failed = sum(r.failure_count for r in results)
        total_exported = sum(r.success_count for r in results)

        if total_failed > 0 and total_exported == 0:
            raise ExtractionError(
                "All exports failed",
                failed_tables=[t for r in results for t in r.failures],
            )

        self._write_readme(output_dir, results)
        total_tables = sum(len(r.tables_exported) for r in results)
        total_scripts = sum(len(r.scripts_extracted) for r in results)
        total_locs = sum(len(r.locs_exported) for r in results)
        console.info(f"Extraction completed: {total_tables} tables, {total_scripts} scripts, {total_locs} loc files")
        return results

    @staticmethod
    def _warn_unmatched_tables(tables: list[str], results: list[ExtractionResult]) -> None:
        found = {
            _table_of(Path(p).as_posix())
            for r in results
            for p in [*r.tables_exported, *(f for f, _ in r.tables_failed)]
        }
        for table in sorted({normalize_table_name(t) for t in tables} - found):
            console.warning(f"No pack contained a {table} table")

    async def refresh(self, sources: list[SourceStatus], index: ModIndex, schema: Schema | None) -> list[RefreshResult]:
        """Re-extract each source from its recorded pack (with its recorded table filter) and
        summarise row changes in the tables that any of the index's patches also contains."""
        patch_tables: set[str] = set()
        for patch in index.patches:
            patch_tables.update(patch.tables())

        results: list[RefreshResult] = []
        for source in sources:
            results.append(await self._refresh_one(source, patch_tables, schema))
        return results

    async def _refresh_one(self, source: SourceStatus, patch_tables: set[str], schema: Schema | None) -> RefreshResult:
        outcome = RefreshResult(source=source)
        info = source.info or {}
        mod_dir = source.path
        old_dir = mod_dir.parent / f".{mod_dir.name}.tw-refresh-old"
        if old_dir.exists():
            shutil.rmtree(old_dir)
        mod_dir.rename(old_dir)
        try:
            try:
                outcome.result = await self.extract_pack(
                    Path(info["pack"]), mod_dir.parent, info.get("table_filter"), mod_dir.name
                )
            except Exception as e:
                outcome.error = str(e)
                console.error(f"Could not refresh {source.name}: {e}")
                if mod_dir.exists():
                    shutil.rmtree(mod_dir)
                old_dir.rename(mod_dir)
                return outcome

            old_mod = Mod(source.name, "source", old_dir)
            new_mod = Mod(source.name, "source", mod_dir)
            tables = sorted(patch_tables & (set(old_mod.tables()) | set(new_mod.tables())))
            if tables:
                for diff in diff_mods(old_mod, new_mod, schema, tables):
                    outcome.table_changes.append(
                        TableChangeSummary(diff.table, len(diff.added), len(diff.removed), len(diff.changed))
                    )
        finally:
            if old_dir.exists():
                shutil.rmtree(old_dir, ignore_errors=True)
        return outcome

    @staticmethod
    def _mod_name_from_path(pack_path: Path) -> str:
        name = pack_path.stem.lstrip("@").replace("-", "_")
        # Sanitize: remove any path separators or traversal sequences
        name = name.replace("..", "").replace("/", "").replace("\\", "")
        if not name:
            raise ValueError(f"Cannot derive a safe mod name from: {pack_path.name}")
        return name

    @staticmethod
    def _write_readme(output_dir: Path, results: list[ExtractionResult]) -> None:
        readme_path = output_dir / "README.txt"
        with open(readme_path, "w") as f:
            f.write("Extracted Mod Data\n")
            f.write("==================\n\n")
            for result in results:
                f.write(
                    f"{result.mod_name}/: "
                    f"{len(result.tables_exported)} tables, "
                    f"{len(result.scripts_extracted)} scripts, "
                    f"{len(result.locs_exported)} loc files\n"
                )
            f.write("\nNext steps:\n")
            f.write("1. Compare tables across extracted mods\n")
            f.write("2. Create a patch mod: tw-patcher repack --patch <name>\n")
