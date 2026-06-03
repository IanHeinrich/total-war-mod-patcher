from pathlib import Path
from typing import Optional

from ..clients.rpfm import RPFMClient
from ..config import Settings
from ..console import console
from ..exceptions import NoGameSelectedError, RepackError
from ..models.pack import RepackResult
from ..utils import normalize_rpfm_path, to_rpfm_container_path


class RepackingService:
    def __init__(self, settings: Settings, client: RPFMClient):
        self.settings = settings
        self.client = client

    def find_tsv_files(self, input_dir: Path) -> list[Path]:
        return sorted(input_dir.glob("**/*.tsv"))

    def find_script_files(self, input_dir: Path) -> list[Path]:
        script_dir = input_dir / "script"
        if not script_dir.exists():
            return []
        return sorted(f for f in script_dir.rglob("*") if f.is_file())

    async def repack(
        self,
        patch_name: str,
        output_path: Optional[Path] = None,
        pack_name: Optional[str] = None,
        workspace_dir: Optional[Path] = None,
    ) -> RepackResult:
        if workspace_dir:
            source_dir = workspace_dir / patch_name
        else:
            source_dir = self.settings.get_patch_mod_path(patch_name)

        if not source_dir.exists():
            raise FileNotFoundError(f"Patch mod directory not found: {source_dir}")
        if not source_dir.is_dir():
            raise ValueError(f"Source must be a directory: {source_dir}")

        resolved_output = output_path or self._resolve_output_path(patch_name, pack_name)
        resolved_output.parent.mkdir(parents=True, exist_ok=True)

        tsv_files = self.find_tsv_files(source_dir)
        script_files = self.find_script_files(source_dir)

        if not tsv_files and not script_files:
            raise ValueError(f"No TSV or script files found in {source_dir}")

        console.info(f"Found {len(tsv_files)} TSV files and {len(script_files)} script files to repack")

        with console.status("Creating pack file..."):
            if not self.settings.selected_game:
                raise NoGameSelectedError()
            await self.client.set_game_selected(self.settings.selected_game)
            pack_handle = await self.client.new_pack()
        console.info(f"Created pack: {pack_handle}")

        result = RepackResult(
            pack_name=pack_name or patch_name,
            output_path=resolved_output,
        )

        if tsv_files:
            with console.status("Importing tables..."):
                for tsv_file in tsv_files:
                    relative_path = tsv_file.relative_to(source_dir)
                    table_path = to_rpfm_container_path(relative_path)

                    try:
                        await self.client.add_packed_file(
                            pack_handle,
                            normalize_rpfm_path(tsv_file),
                            table_path,
                        )
                        result.tables_imported.append(table_path)
                        console.info(f"Imported {table_path}")
                    except Exception as e:
                        result.tables_failed.append((table_path, str(e)))
                        console.error(f"Failed to import {table_path}: {e}")

        if script_files:
            with console.status("Importing scripts..."):
                for script_file in script_files:
                    relative_path = script_file.relative_to(source_dir)
                    container_path = str(relative_path).replace('\\', '/')

                    try:
                        await self.client.add_packed_file(
                            pack_handle,
                            normalize_rpfm_path(script_file),
                            container_path,
                        )
                        result.scripts_imported.append(container_path)
                        console.info(f"Imported {container_path}")
                    except Exception as e:
                        result.scripts_failed.append((container_path, str(e)))
                        console.error(f"Failed to import {container_path}: {e}")

        if result.success_count == 0:
            raise RepackError(
                "No files were successfully imported",
                failed_tables=result.tables_failed + result.scripts_failed,
            )

        with console.status("Saving pack..."):
            await self.client.save_pack_as(pack_handle, normalize_rpfm_path(resolved_output))
        console.info(f"Pack saved to: {resolved_output}")

        if result.failure_count > 0:
            console.warning(f"{result.failure_count} tables failed to import")

        return result

    def _resolve_output_path(self, patch_name: str, pack_name: Optional[str]) -> Path:
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{pack_name or patch_name}.pack"
        return self.settings.output_dir / filename
