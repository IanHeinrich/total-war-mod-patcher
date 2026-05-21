from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import platform
import re

from .models.game import GameDef, GAMES, get_game
from .models.workshop import WorkshopMod


@dataclass
class Settings:
    max_mods: int = 6
    rpfm_host: str = "127.0.0.1"
    rpfm_port: int = 45127
    rpfm_timeout: int = 60
    rpfm_startup_attempts: int = 10
    rpfm_startup_wait_seconds: float = 1.0

    selected_game: str | None = field(default=None)
    game_dirs: dict[str, Path] = field(default_factory=dict)
    modding_root: Path | None = field(default=None)
    rpfm_path: Path | None = field(default=None)

    def __post_init__(self):
        self._load_user_config()
        if not self.selected_game:
            self._auto_select_first_game()

    @staticmethod
    def _app_data_dir() -> Path:
        """Platform-appropriate application data directory."""
        system = platform.system()
        if system == "Windows":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        elif system == "Darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        return base / "tw-patcher"

    @property
    def config_file(self) -> Path:
        return self._app_data_dir() / "config.json"

    @property
    def _modding_base(self) -> Path:
        return self.modding_root or self._app_data_dir()

    @property
    def sources_dir(self) -> Path:
        return self._modding_base / "sources"

    @property
    def workspace_dir(self) -> Path:
        return self._modding_base / "workspace"

    @property
    def output_dir(self) -> Path:
        return self._modding_base / "output"

    @property
    def selected_game_def(self) -> GameDef | None:
        if self.selected_game:
            return GAMES.get(self.selected_game)
        return None

    @property
    def game_dir(self) -> Path | None:
        if self.selected_game:
            return self.game_dirs.get(self.selected_game)
        return None

    @game_dir.setter
    def game_dir(self, path: Path | None) -> None:
        if self.selected_game and path:
            self.game_dirs[self.selected_game] = path
        elif self.selected_game and not path:
            self.game_dirs.pop(self.selected_game, None)

    @property
    def game_data_dir(self) -> Path | None:
        if self.game_dir:
            return self.game_dir / "data"
        return None

    @property
    def game_workshop_dir(self) -> Path | None:
        game_def = self.selected_game_def
        if not self.game_dir or not game_def or not game_def.steam_app_id:
            return None
        steamapps = self.game_dir.parent.parent
        workshop = steamapps / "workshop" / "content" / str(game_def.steam_app_id)
        if workshop.exists():
            return workshop
        return None

    @property
    def rpfm_search_paths(self) -> list[Path]:
        paths: list[Path] = []
        # User-configured path takes priority
        if self.rpfm_path:
            paths.append(self.rpfm_path)
            # Also check for rpfm_server.exe in the same directory
            if self.rpfm_path.is_dir():
                paths.append(self.rpfm_path / "rpfm_server.exe")
                paths.append(self.rpfm_path / "rpfm_ui.exe")
            elif self.rpfm_path.is_file():
                paths.append(self.rpfm_path.parent / "rpfm_server.exe")

        system = platform.system()
        if system == "Windows":
            paths.extend([
                Path(r"C:\Program Files\RPFM\rpfm_server.exe"),
                Path(r"C:\Program Files\RPFM\rpfm_ui.exe"),
                Path(r"C:\Program Files (x86)\RPFM\rpfm_server.exe"),
                Path.home() / "AppData" / "Local" / "RPFM" / "rpfm_server.exe",
                Path.home() / "AppData" / "Local" / "RPFM" / "rpfm_ui.exe",
            ])
        elif system == "Linux":
            paths.extend([
                Path("/usr/bin/rpfm"),
                Path("/usr/local/bin/rpfm"),
                Path.home() / ".local" / "bin" / "rpfm",
            ])
        elif system == "Darwin":
            paths.extend([
                Path("/Applications/RPFM.app/Contents/MacOS/rpfm"),
                Path.home() / "Applications" / "RPFM.app" / "Contents" / "MacOS" / "rpfm",
            ])
        return paths

    def ensure_dirs(self) -> None:
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def workshop_cache_file(self) -> Path:
        return self._app_data_dir() / "workshop_cache.json"

    @property
    def workshop_thumbs_dir(self) -> Path:
        return self._app_data_dir() / "workshop_thumbs"

    @property
    def game_art_dir(self) -> Path:
        return self._app_data_dir() / "game_art"

    def list_workshop_mods(self) -> list[WorkshopMod]:
        workshop_dir = self.game_workshop_dir
        if not workshop_dir or not workshop_dir.exists():
            return []

        mods: list[WorkshopMod] = []
        for entry in sorted(workshop_dir.iterdir()):
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            packs = sorted(entry.glob("*.pack"))
            if packs:
                mods.append(WorkshopMod(workshop_id=entry.name, pack_paths=packs))
        return mods

    def list_patch_mods(self) -> list[str]:
        if not self.workspace_dir.exists():
            return []
        return sorted(
            d.name for d in self.workspace_dir.iterdir()
            if d.is_dir() and not d.name.startswith('.')
        )

    def get_patch_mod_path(self, name: str) -> Path:
        if not name or any(c in name for c in ('..', '/', '\\', '\x00')):
            raise ValueError(f"Invalid patch mod name: {name!r}")
        result = self.workspace_dir / name
        
        if not result.resolve().is_relative_to(self.workspace_dir.resolve()):
            raise ValueError(f"Invalid patch mod name: {name!r}")
        return result

    def select_game(self, game_key: str) -> None:
        get_game(game_key)  # validates
        self.selected_game = game_key
        if game_key not in self.game_dirs:
            detected = self._detect_game_dir(game_key)
            if detected:
                self.game_dirs[game_key] = detected

    def _auto_select_first_game(self) -> None:
        """Auto-select the first detected installed game on fresh installs."""
        installed = self.detect_installed_games()
        if installed:
            first_key = next(iter(installed))
            self.selected_game = first_key
            self.game_dirs.update(installed)
            self.save_user_config()

    def detect_installed_games(self) -> dict[str, Path]:
        installed: dict[str, Path] = {}
        for key, game_def in GAMES.items():
            if key in self.game_dirs:
                installed[key] = self.game_dirs[key]
            else:
                detected = self._detect_game_dir(key)
                if detected:
                    installed[key] = detected
        return installed

    def _detect_game_dir(self, game_key: str) -> Path | None:
        game_def = GAMES.get(game_key)
        if not game_def or not game_def.folder_name or not game_def.steam_app_id:
            return None

        for vdf_path in self._steam_vdf_paths():
            if result := self._find_game_in_vdf(vdf_path, game_def):
                return result

        candidates: list[Path] = []
        system = platform.system()
        if system == "Windows":
            candidates = [
                Path(r"C:\Program Files (x86)\Steam\steamapps\common") / game_def.folder_name,
                Path(r"C:\Program Files\Steam\steamapps\common") / game_def.folder_name,
                Path(r"D:\SteamLibrary\steamapps\common") / game_def.folder_name,
                Path(r"D:\Steam\steamapps\common") / game_def.folder_name,
                Path(r"E:\SteamLibrary\steamapps\common") / game_def.folder_name,
            ]
        elif system == "Linux":
            candidates = [
                Path.home() / ".steam" / "steam" / "steamapps" / "common" / game_def.folder_name,
                Path.home() / ".local" / "share" / "Steam" / "steamapps" / "common" / game_def.folder_name,
            ]

        for path in candidates:
            if path.exists() and (path / "data").is_dir():
                return path
        return None

    def _steam_vdf_paths(self) -> list[Path]:
        system = platform.system()
        if system == "Windows":
            steam_path = self._read_steam_registry_path()
            paths = []
            if steam_path:
                paths.append(steam_path / "steamapps" / "libraryfolders.vdf")
            paths.extend([
                Path(r"C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf"),
                Path(r"C:\Program Files\Steam\steamapps\libraryfolders.vdf"),
            ])
            return paths
        elif system == "Linux":
            return [
                Path.home() / ".steam" / "steam" / "steamapps" / "libraryfolders.vdf",
                Path.home() / ".local" / "share" / "Steam" / "steamapps" / "libraryfolders.vdf",
            ]
        return []

    @staticmethod
    def _read_steam_registry_path() -> Path | None:
        if platform.system() != "Windows":
            return None
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")
            value, _ = winreg.QueryValueEx(key, "InstallPath")
            winreg.CloseKey(key)
            return Path(value)
        except OSError:
            return None

    @staticmethod
    def _find_game_in_vdf(vdf_path: Path, game_def: GameDef) -> Path | None:
        if not vdf_path.exists() or not game_def.steam_app_id or not game_def.folder_name:
            return None
        try:
            content = vdf_path.read_text(encoding="utf-8")
        except OSError:
            return None

        app_id_str = str(game_def.steam_app_id)
        libraries = re.findall(r'"path"\s+"([^"]+)"', content)
        app_sections = content.split('"path"')

        for i, lib_path_str in enumerate(libraries):
            section = app_sections[i + 1] if i + 1 < len(app_sections) else ""
            if f'"{app_id_str}"' in section:
                game_path = Path(lib_path_str) / "steamapps" / "common" / game_def.folder_name
                if game_path.exists() and (game_path / "data").is_dir():
                    return game_path

        return None

    def _load_user_config(self) -> None:
        config_path = self.config_file
        # Migrate legacy config from project root
        legacy_path = Path(__file__).resolve().parent.parent / ".tw_patcher.json"
        if not config_path.exists() and legacy_path.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(legacy_path.read_text())
            legacy_path.unlink()
        if not config_path.exists():
            return
        try:
            data = json.loads(config_path.read_text())

            # Migrate legacy wh3_dir → game_dirs
            if wh3 := data.get("wh3_dir"):
                path = Path(wh3)
                if path.exists():
                    self.game_dirs["warhammer_3"] = path

            if game_dirs := data.get("game_dirs"):
                for key, dir_str in game_dirs.items():
                    if key in GAMES:
                        path = Path(dir_str)
                        if path.exists():
                            self.game_dirs[key] = path

            if sg := data.get("selected_game"):
                if sg in GAMES:
                    self.selected_game = sg

            if mr := data.get("modding_root"):
                path = Path(mr)
                if path.exists():
                    self.modding_root = path

            if rp := data.get("rpfm_path"):
                path = Path(rp)
                if path.exists():
                    self.rpfm_path = path
        except (json.JSONDecodeError, OSError):
            pass

    def save_user_config(self) -> None:
        data: dict = {}
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # Remove legacy key
        data.pop("wh3_dir", None)

        if self.selected_game:
            data["selected_game"] = self.selected_game
        if self.game_dirs:
            data["game_dirs"] = {k: str(v) for k, v in self.game_dirs.items()}
        if self.modding_root:
            data["modding_root"] = str(self.modding_root)
        if self.rpfm_path:
            data["rpfm_path"] = str(self.rpfm_path)
        self.config_file.write_text(json.dumps(data, indent=2))


settings = Settings()
