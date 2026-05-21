from pathlib import Path


def normalize_rpfm_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def to_rpfm_container_path(relative_path: Path) -> str:
    return str(relative_path.with_suffix('')).replace('\\', '/')
