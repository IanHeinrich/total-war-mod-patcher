from pathlib import Path

LOC_SUFFIX = ".loc"


def normalize_rpfm_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def to_rpfm_container_path(relative_path: Path) -> str:
    return str(relative_path.with_suffix("")).replace("\\", "/")


def is_loc_path(container_path: str) -> bool:
    """A localisation file inside a pack: ``text/**/*.loc``."""
    return container_path.startswith("text/") and container_path.endswith(LOC_SUFFIX)


def tsv_to_container_path(relative_path: Path) -> str:
    """Pack path for a TSV relative to a patch folder.

    ``text/db/foo.tsv`` -> ``text/db/foo.loc`` (loc files keep their extension in
    the pack); ``db/units_tables/foo.tsv`` -> ``db/units_tables/foo`` (DB tables
    have none).
    """
    if relative_path.parts and relative_path.parts[0] == "text":
        return relative_path.with_suffix(LOC_SUFFIX).as_posix()
    return to_rpfm_container_path(relative_path)
