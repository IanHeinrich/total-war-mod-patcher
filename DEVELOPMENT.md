# Development Guide

Architecture, codebase structure, and development details for TW Mod Patcher.

## Architecture

```
tw_patcher/
├── config.py                 ← Settings dataclass (persistence, game detection)
├── console.py                ← Rich console output helpers
├── constants.py              ← Named constants (ports, timeouts, limits)
├── exceptions.py             ← Custom exception hierarchy
├── cli/
│   ├── __init__.py           ← Re-exports cli group (entry point: tw_patcher.cli:cli)
│   ├── _rich.py              ← RichCommand/RichGroup (formatted help output)
│   ├── _helpers.py           ← Shared CLI helpers (client/service factories)
│   ├── main.py               ← Root @click.group definition + global options
│   └── commands/
│       ├── extract.py        ← extract command
│       ├── repack.py         ← repack command
│       ├── replace.py        ← replace-table command
│       ├── list.py           ← list command
│       ├── check.py          ← check command
│       ├── clean.py          ← clean command
│       ├── scaffold.py       ← scaffold command
│       ├── ui.py             ← ui command (launches GUI)
│       └── config.py         ← config subgroup (show, set-rpfm)
├── clients/
│   ├── rpfm.py               ← WebSocket client for RPFM server
│   └── steam.py              ← Steam Workshop API client
├── models/
│   ├── game.py               ← Game registry (14 games, Steam IDs, folder names)
│   ├── pack.py               ← ExtractionResult / RepackResult dataclasses
│   └── workshop.py           ← WorkshopMod dataclass
├── services/
│   ├── extraction.py         ← ExtractionService (pack → TSV)
│   ├── repacking.py          ← RepackingService (TSV → pack)
│   ├── scaffold.py           ← Workspace scaffolding & docs generation
│   └── system.py             ← SystemService (RPFM lifecycle management)
├── utils/
│   └── rpfm_utils.py         ← Path normalization for RPFM protocol
└── ui/
    ├── app.py                ← QApplication launcher
    ├── main_window.py        ← MainWindow layout
    ├── state.py              ← AppState (signals: game_changed, busy, etc.)
    ├── styles.py             ← Shared CSS constants
    ├── dialogs/
    │   ├── game_browser.py   ← Game selection dialog (detected games + manual)
    │   └── workshop_browser.py ← Steam Workshop mod browser
    ├── panels/
    │   ├── game_panel.py     ← Compact game display + change button
    │   ├── settings_panel.py ← Workspace + game install settings
    │   ├── extract_panel.py  ← Source pack selection + extract
    │   └── repack_panel.py   ← Patch mod selection + repack
    ├── widgets/
    │   ├── game_card.py      ← Clickable game tile with artwork
    │   ├── log_viewer.py     ← Log output widget
    │   ├── thumbnail.py      ← Workshop thumbnail loader
    │   └── workshop_mod.py   ← Workshop mod list item widget
    └── workers/
        ├── artwork.py        ← Steam CDN artwork downloader + cache
        ├── extract.py        ← QThread extraction worker
        ├── repack.py         ← QThread repack worker
        └── workshop.py       ← Workshop metadata fetcher
```

## Key Design Decisions

### Game Agnostic

The tool supports all 14 Total War games that RPFM handles. The game registry (`models/game.py`) maps each game to its RPFM key, Steam app ID, and folder name. RPFM uses the game key to load the correct schema for table decoding.

### RPFM Communication

RPFM exposes a WebSocket server on `localhost:45127` (see `constants.py` for defaults). The protocol is JSON-based:
- Request: `{"id": <u64>, "data": {"CommandName": [args]}}`
- Response: `{"id": <u64>, "data": "Success" | {"Error": "..."} | {result}}`

Key commands used:
- `SetGameSelected` — set active game schema
- `OpenPackFiles` — open a .pack file, returns handle
- `GetPackedFilesPathsByType` — list files by type (DB, Loc, etc.)
- `ExportTSV` — export a DB table to TSV
- `NewPack` — create empty pack
- `AddPackedFileFromExternalFile` — import TSV into pack
- `SavePackFileAs` — save pack to disk

### Configuration Persistence

All user data is stored in the platform-standard app data directory:
- **Windows**: `%LOCALAPPDATA%\tw-patcher\`
- **Linux**: `~/.local/share/tw-patcher/`
- **macOS**: `~/Library/Application Support/tw-patcher/`

Config file (`config.json`):
```json
{
  "selected_game": "warhammer_3",
  "game_dirs": {
    "warhammer_3": "E:\\SteamLibrary\\steamapps\\common\\Total War WARHAMMER III"
  },
  "modding_root": "D:\\Modding\\my_project"
}
```

On first launch, auto-detects installed games via Steam's `libraryfolders.vdf` and common install paths.

### UI Architecture

PyQt6 with a signal-based state pattern:
- `AppState` holds signals (`game_changed`, `busy_changed`, `modding_root_changed`)
- Panels connect to signals and update independently
- Workers (`QThread`) run async RPFM operations off the main thread
- Artwork loaded lazily from Steam CDN and cached to `<data_dir>/game_art/`

## Runtime Directories

When `modding_root` is set in config, working directories are created there. Otherwise they default to the app data directory.

| Directory | Purpose | Location |
|-----------|---------|----------|
| `sources/` | Extracted TSVs from source mods | `<modding_root>/` |
| `workspace/` | Patch mod projects (editable) | `<modding_root>/` |
| `output/` | Built .pack files | `<modding_root>/` |
| `game_art/` | Cached Steam header images | `<data_dir>/` |
| `workshop_thumbs/` | Cached workshop thumbnails | `<data_dir>/` |
| `config.json` | User settings | `<data_dir>/` |

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
```

## Running

```bash
tw-patcher --help             # CLI
tw-patcher ui                 # GUI
tw-patcher --game attila check  # Set game + verify RPFM
```

## Adding a New Game

If RPFM adds support for a new game:

1. Add entry to `GAMES` dict in `tw_patcher/models/game.py` with key, display name, Steam app ID, folder name, and executable
2. That's it — the rest is driven by the registry

## Dependencies

- **websockets** — async WebSocket client for RPFM protocol
- **click** — CLI framework
- **rich** — Terminal formatting (tables, panels, spinners)
- **PyQt6** — GUI framework
- **RPFM** (external) — provides the server that does actual pack file manipulation
