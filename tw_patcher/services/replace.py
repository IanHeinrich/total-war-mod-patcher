"""Swap DB tables inside an existing pack (``tw-patcher replace-table``)."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..clients.rpfm import RPFMClient
from ..config import Settings
from ..console import console
from ..exceptions import NoGameSelectedError, TWPatcherError
from ..utils import normalize_rpfm_path


class ReplaceError(TWPatcherError):
    pass


@dataclass
class ReplaceResult:
    saved_to: Path
    backup: Path | None
    replaced: list[str] = field(default_factory=list)


def read_table_path(tsv_path: Path) -> str:
    """The pack path a TSV belongs to, from RPFM's metadata on line 2
    (``#table_name;version;db/table_name/file``)."""
    with open(tsv_path, encoding="utf-8") as f:
        f.readline()  # column names
        metadata = f.readline().strip()
    if not metadata.startswith("#"):
        raise ReplaceError(f"Invalid TSV metadata in {tsv_path.name}: line 2 must start with '#'")
    parts = metadata.lstrip("#").split("\t")[0].split(";")
    if len(parts) < 3 or not parts[2].strip():
        raise ReplaceError(f"Invalid TSV metadata in {tsv_path.name}: expected 3 semicolon-separated fields")
    return parts[2].strip()


class ReplaceService:
    def __init__(self, settings: Settings, client: RPFMClient):
        self.settings = settings
        self.client = client

    async def replace_tables(
        self, pack: Path, tsv_files: list[Path], output: Path | None = None, backup: bool = True
    ) -> ReplaceResult:
        entries = [(tsv, read_table_path(tsv)) for tsv in tsv_files]
        for tsv, table_path in entries:
            console.info(f"  {tsv.name} → {table_path}")

        if not self.settings.selected_game:
            raise NoGameSelectedError()
        await self.client.set_game_selected(self.settings.selected_game)

        with console.status("Opening pack file..."):
            handle = await self.client.open_pack_file(normalize_rpfm_path(pack))
        try:
            present = set(await self.client.list_paths(handle))
            missing = [table_path for _, table_path in entries if table_path not in present]
            if missing:
                raise ReplaceError(
                    f"Not in {pack.name}: {', '.join(missing)}. "
                    "replace-table only swaps tables the pack already has; check line 2 of the TSV."
                )

            result = ReplaceResult(saved_to=output or pack, backup=None)
            for tsv, table_path in entries:
                with console.status(f"Replacing {table_path}..."):
                    await self.client.import_tsv(handle, table_path, normalize_rpfm_path(tsv))
                result.replaced.append(table_path)
                console.info(f"Replaced: {table_path}")

            with console.status("Saving pack..."):
                if output:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    await self.client.save_pack_as(handle, normalize_rpfm_path(output))
                else:
                    if backup:
                        result.backup = pack.with_name(pack.name + ".bak")
                        shutil.copy2(pack, result.backup)
                    await self.client.save_pack(handle)
            return result
        finally:
            try:
                await self.client.close_pack_file(handle)
            except Exception as e:
                console.warning(f"Could not close pack {handle}: {e}")
