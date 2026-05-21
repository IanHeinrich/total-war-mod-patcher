#!/usr/bin/env python3
"""Post-install utility to write initial config.json with workspace path.

Called by platform installers after file installation to persist the
user's chosen modding workspace directory into the app's config file.

Usage:
    python config_writer.py <workspace_path>
"""

import json
import os
import platform
import sys
from pathlib import Path


def get_config_dir() -> Path:
    """Get the platform-specific config directory."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        return Path(base) / "tw-patcher"
    elif system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "tw-patcher"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
        return Path(xdg) / "tw-patcher"


def write_config(workspace_path: str) -> None:
    """Write or update config.json with the modding_root setting."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"

    config: dict = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    config["modding_root"] = str(Path(workspace_path).resolve())

    config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Config written to: {config_file}")
    print(f"  modding_root = {config['modding_root']}")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <workspace_path>", file=sys.stderr)
        sys.exit(1)

    workspace_path = sys.argv[1]
    workspace = Path(workspace_path)
    workspace.mkdir(parents=True, exist_ok=True)

    write_config(workspace_path)


if __name__ == "__main__":
    main()
