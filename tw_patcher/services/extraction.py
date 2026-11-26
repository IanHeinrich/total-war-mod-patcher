import shutil
from pathlib import Path

from ..clients.rpfm import RPFMClient
from ..config import Settings
from ..console import console
from ..exceptions import ExtractionError, NoGameSelectedError
from ..models.pack import ExtractionPlan, ExtractionResult
from ..utils import normalize_rpfm_path


class ExtractionService:
    def __init__(self, settings: Settings, client: RPFMClient):
        self.settings = settings
        self.client = client

    async def _open(self, pack_path: Path) -> str:
        if not self.settings.selected_game:
            raise NoGameSelectedError()
        await self.client.set_game_selected(self.settings.selected_game)
        return await self.client.open_pack_file(normalize_rpfm_path(pack_path))

    async def _list_extractable(self, pack_handle: str) -> tuple[list[str], list[str]]:
        paths = await self.client.list_paths(pack_handle)
        db_tables = [p for p in paths if p.startswith("db/")]
        scripts = [p for p in paths if p.startswith("script/")]
        return db_tables, scripts

    async def extract_pack(self, pack_path: Path, output_dir: Path) -> ExtractionResult:
        if not pack_path.exists():
            raise FileNotFoundError(f"Pack file not found: {pack_path}")

        mod_name = self._mod_name_from_path(pack_path)
        mod_output_dir = output_dir / mod_name
        mod_output_dir.mkdir(parents=True, exist_ok=True)

        console.info(f"Extracting {pack_path}...")

        with console.status("Opening pack file..."):
            pack_handle = await self._open(pack_path)
        console.info(f"Opened pack file: {pack_handle}")

        try:
            db_table_paths, script_paths = await self._list_extractable(pack_handle)
            console.info(f"Found {len(db_table_paths)} database tables and {len(script_paths)} script files")

            result = ExtractionResult(mod_name=mod_name, output_dir=mod_output_dir)

            with console.status("Exporting tables..."):
                for table_path in db_table_paths:
                    relative_path = Path(table_path)
                    output_tsv = mod_output_dir / relative_path.with_suffix(".tsv")
                    output_tsv.parent.mkdir(parents=True, exist_ok=True)

                    try:
                        await self.client.export_tsv(pack_handle, table_path, normalize_rpfm_path(output_tsv))
                        result.tables_exported.append(str(relative_path))
                        console.info(f"Exported {table_path}")
                    except Exception as e:
                        result.tables_failed.append((table_path, str(e)))
                        console.error(f"Failed to export {table_path}: {e}")

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

        console.info(
            f"Extraction complete: {len(result.tables_exported)} tables, {len(result.scripts_extracted)} scripts"
        )
        return result

    async def _close_quietly(self, pack_handle: str) -> None:
        """Release the RPFM pack handle without masking the error that got us here."""
        try:
            await self.client.close_pack_file(pack_handle)
        except Exception as e:
            console.warning(f"Could not close pack {pack_handle}: {e}")

    def _check_batch(self, pack_paths: list[Path]) -> None:
        if len(pack_paths) > self.settings.max_mods:
            raise ValueError(f"Too many source mods ({len(pack_paths)}). Maximum is {self.settings.max_mods}.")
        if not pack_paths:
            raise ValueError("At least one source pack file is required.")
        seen: dict[str, Path] = {}
        for pack_path in pack_paths:
            mod_name = self._mod_name_from_path(pack_path)
            if mod_name in seen and seen[mod_name].resolve() != pack_path.resolve():
                raise ValueError(
                    f"{seen[mod_name].name} and {pack_path.name} would both extract to sources/{mod_name}/. "
                    "Extract them in separate runs with different --output folders."
                )
            seen[mod_name] = pack_path

    async def plan_batch(self, pack_paths: list[Path], output_dir: Path) -> list[ExtractionPlan]:
        """What extract_batch would do, without writing anything."""
        self._check_batch(pack_paths)
        plans: list[ExtractionPlan] = []
        for pack_path in dict.fromkeys(pack_paths):
            mod_name = self._mod_name_from_path(pack_path)
            pack_handle = await self._open(pack_path)
            try:
                db_tables, scripts = await self._list_extractable(pack_handle)
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
                )
            )
        return plans

    async def extract_batch(self, pack_paths: list[Path], output_dir: Path) -> list[ExtractionResult]:
        self._check_batch(pack_paths)
        pack_paths = list(dict.fromkeys(pack_paths))

        output_dir.mkdir(parents=True, exist_ok=True)

        for pack_path in pack_paths:
            mod_name = self._mod_name_from_path(pack_path)
            existing = output_dir / mod_name
            if existing.exists():
                console.warning(f"Removing existing {existing}")
                shutil.rmtree(existing)

        console.info(f"Extracting {len(pack_paths)} mod(s) to: {output_dir}")

        results: list[ExtractionResult] = []
        for pack_path in pack_paths:
            result = await self.extract_pack(pack_path, output_dir)
            results.append(result)

        total_failed = sum(r.failure_count for r in results)
        total_exported = sum(r.success_count for r in results)

        if total_failed > 0 and total_exported == 0:
            raise ExtractionError(
                "All exports failed",
                failed_tables=[t for r in results for t in r.tables_failed + r.scripts_failed],
            )

        self._write_readme(output_dir, results)
        total_tables = sum(len(r.tables_exported) for r in results)
        total_scripts = sum(len(r.scripts_extracted) for r in results)
        console.info(f"Extraction completed: {total_tables} tables, {total_scripts} scripts")
        return results

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
                    f"{len(result.scripts_extracted)} scripts\n"
                )
            f.write("\nNext steps:\n")
            f.write("1. Compare tables across extracted mods\n")
            f.write("2. Create a patch mod: tw-patcher repack --patch <name>\n")
