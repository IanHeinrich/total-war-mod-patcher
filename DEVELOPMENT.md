# Development Guide

Architecture, codebase structure, and development details for TW Mod Patcher.

## Architecture

```
tw_patcher/
├── __main__.py               ← `python -m tw_patcher` / PyInstaller console entry
├── __gui__.py                ← PyInstaller windowed (GUI) entry
├── config.py                 ← Settings dataclass (persistence, game detection, paths)
├── console.py                ← Rich console output helpers
├── constants.py              ← Named constants (ports, timeouts, limits)
├── exceptions.py             ← Custom exception hierarchy
├── mcp_server.py             ← MCP server (stdio): 16 tools over the workspace; needs the `mcp` extra
├── cli/
│   ├── __init__.py           ← Re-exports cli group (entry point: tw_patcher.cli:cli)
│   ├── _rich.py              ← RichCommand/RichGroup (formatted help output)
│   ├── _helpers.py           ← Shared CLI helpers (client/service factories)
│   ├── _data.py              ← Shared plumbing for the offline table commands (schema loading, JSON output)
│   ├── main.py               ← Root @click.group definition + global options
│   └── commands/
│       ├── extract.py        ← extract command
│       ├── status.py         ← status command (are extracted sources still current?)
│       ├── analyze.py        ← tables, show, find-key, diff, conflicts, validate
│       ├── new_patch.py      ← new-patch command
│       ├── repack.py         ← repack command (--install, --allow-partial, validation)
│       ├── replace.py        ← replace-table command
│       ├── diagnose.py       ← diagnose command (RPFM 5 diagnostics)
│       ├── list.py           ← list command
│       ├── check.py          ← check command (server, protocol, version)
│       ├── clean.py          ← clean command
│       ├── scaffold.py       ← scaffold command
│       ├── mcp.py            ← mcp command (runs mcp_server on stdio)
│       ├── ui.py             ← ui command (launches GUI)
│       └── config.py         ← config subgroup (show, set-rpfm, set-modding-root, set-game-dir)
├── clients/
│   ├── rpfm.py               ← RPFM server client: connection, protocol auto-detection, /version lookup
│   ├── rpfm_protocols.py     ← LegacyProtocol (RPFM 4.x) and JsonRpcProtocol (RPFM 5.x)
│   └── steam.py              ← Steam Workshop API client
├── data/                     ← Offline table analysis (no RPFM needed); see "Data layer" below
│   ├── tsv.py                ← TableFile: exact-round-trip reader/writer for RPFM's TSV exports
│   ├── ron.py                ← Small tolerant RON parser (for RPFM's schema files)
│   ├── schema.py             ← schema_<game>.ron loader + on-disk cache: columns, types, keys, references
│   ├── index.py              ← Finds mods (sources/, workspace/) and their table fragments
│   ├── analysis.py           ← Merge rules, diff, conflicts, dangling references, patch validation
│   └── queries.py            ← Read queries and safe patch edits shared by the CLI and MCP server
├── models/
│   ├── game.py               ← Game registry (14 games, Steam IDs, folder names)
│   ├── pack.py               ← ExtractionResult / RepackResult dataclasses
│   └── workshop.py           ← WorkshopMod dataclass
├── services/
│   ├── extraction.py         ← ExtractionService (pack → TSV), vanilla/Workshop lookup, source staleness
│   ├── repacking.py          ← RepackingService (TSV → pack)
│   ├── replace.py            ← ReplaceService (swap tables inside an existing pack)
│   ├── scaffold.py           ← Modding-folder scaffolding (files, .mcp.json)
│   ├── scaffold_templates.py ← Text of the generated docs and AI instruction files
│   └── system.py             ← SystemService (RPFM lifecycle management)
├── utils/
│   └── rpfm_utils.py         ← Path normalization for the RPFM protocols
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
    ├── widgets/              ← package
    │   ├── game_card.py      ← Clickable game tile with artwork
    │   ├── log_viewer.py     ← Log output widget
    │   ├── thumbnail.py      ← Workshop thumbnail loader
    │   └── workshop_mod.py   ← Workshop mod list item widget
    └── workers/              ← package
        ├── artwork.py        ← Steam CDN artwork downloader + cache
        ├── extract.py        ← QThread extraction worker
        ├── repack.py         ← QThread repack worker
        └── workshop.py       ← Workshop metadata fetcher
```

The layers depend downwards: `cli`, `mcp_server` and `ui` call `services` and `data`; `services` call `clients`; `data` has no dependency on RPFM or the network. The CLI is the reference interface: the MCP server and GUI reuse the same services.

## Key Design Decisions

### Game Agnostic

The tool supports all 14 Total War games that RPFM handles. The game registry (`models/game.py`) maps each game to its RPFM key, Steam app ID, and folder name. RPFM uses the game key to load the correct schema for table decoding; the offline analysis picks the matching `schema_<game>.ron` (the mapping is `SCHEMA_FILES` in `data/schema.py`).

### RPFM Communication

RPFM runs a headless server on `ws://127.0.0.1:45127/ws` (see `constants.py` for defaults; `TW_PATCHER_RPFM_PORT` overrides the port). It has spoken two wire protocols, and `RPFMClient` supports both behind one interface (`RPFMProtocol` in `clients/rpfm_protocols.py`). The protocol is auto-detected from the server's first frame (`detect_protocol`); an unrecognised greeting falls back to legacy. `tw-patcher check` reports the detected protocol and, on RPFM 5, the version from `GET /version`.

**Legacy protocol (RPFM 4.x)**: JSON with externally-tagged serde enums.
- Request: `{"id": <u64>, "data": {"CommandName": params}}` (or `"data": "CommandName"` when there are no params)
- Response: `{"id": <u64>, "data": <Response> | {"Error": "..."}}`
- Greeting: `{"id": 0, "data": {"SessionConnected": <session_id>}}`

Commands `LegacyProtocol` sends:
- `SetGameSelected`: set the active game (schema)
- `OpenPackFiles`, `NewPack`, `ClosePack`: open / create / close a pack (returns a handle string)
- `GetPackFileDataForTreeView`: list every file in a pack
- `ExtractPackedFiles`: extract files (scripts, loc and so on) to disk
- `ExportTSV`, `ImportTSV`: convert a DB table to / from TSV
- `AddPackedFiles`: add a file from disk to a pack
- `DeletePackedFiles`: remove files from a pack
- `SavePack`, `SavePackAs`: write the pack
- `ClientDisconnecting`: goodbye (a notification)

Diagnostics are not available over the legacy protocol (`diagnose` reports that it needs RPFM 5).

**JSON-RPC 2.0 (RPFM 5.x)**:
- Request: `{"jsonrpc": "2.0", "id": n, "method": "pack.open", "params": {...}}`
- Response: `{"jsonrpc": "2.0", "id": n, "result": ...}` or `{..., "error": {"code", "message", "data": {"kind": ...}}}`
- Greeting: a `session.connected` notification carrying the session id
- Packs are addressed by a UUID-like pack key (returned by `pack.open` / `pack.new`) rather than a handle
- Long-running methods answer `{"job": n}`; `JsonRpcProtocol.call_job` then polls `job.wait` until the job finishes, fails, is cancelled or the timeout expires

Methods `JsonRpcProtocol` uses:
- `session.set_game`, `session.status`, `session.disconnect`
- `pack.open`, `pack.new`, `pack.close`, `pack.save` (with `path` for save-as)
- `files.list` (paged), `files.extract`, `files.add_from_disk`, `files.delete`
- `table.export_tsv`, `table.import_tsv`
- `dependencies.rebuild`, `diagnostics.run`, `diagnostics.list` (for `diagnose`; `job.wait` drives the long ones)

RPFM 5 also serves an [MCP](https://modelcontextprotocol.io) endpoint on the same port (`/mcp`) and a `/version` endpoint. tw-patcher doesn't call `/mcp` itself; `scaffold` probes `/version` and, for RPFM 5+, registers `http://127.0.0.1:45127/mcp` in the generated `.mcp.json`.

### Data layer (`tw_patcher/data`)

Everything the analysis commands and MCP tools do works on the extracted TSV files plus RPFM's schema, with no running RPFM. Each module has a narrow job:

- `tsv.py`: `TableFile` parses an RPFM table export (column line, `#table;version;path` metadata line, rows) and writes it back byte for byte: BOM, line endings, the metadata line's padding and a missing final newline survive an edit. All patch writes go through it.
- `ron.py`: a tolerant reader for RON, enough for RPFM's `schema_<game>.ron` (trailing commas, comments, `Some(x)`, enum variants).
- `schema.py`: finds the schema (`TW_PATCHER_SCHEMA_DIR`, else the `schema_dir` setting, else RPFM's config folder: `%APPDATA%\FrodoWazEre\rpfm\config\schemas` on Windows, `~/Library/Application Support/com.FrodoWazEre.rpfm/schemas` on macOS, `$XDG_CONFIG_HOME/rpfm/schemas` and `$XDG_DATA_HOME/rpfm/schemas` on Linux), parses it, and caches the compact form under `<data_dir>/cache/`. Gives per-table, per-version columns, types, key columns and references.
- `index.py`: discovers mods (a folder with `db/`, `script/` or `text/`, directly under `sources/` or `workspace/`, or one level deeper for grouped mods) and their fragments (`db/<table>/<fragment>.tsv`). Resolves mod names, including unique trailing parts and `sources/` / `workspace/` prefixes.
- `analysis.py`: the merge rules, row-level diff, load-order conflict detection, dangling-reference checks and `validate_patch`.
- `queries.py`: the read queries (`show`, `find-key`, table descriptions) and the safe patch edits (`new-patch`, copy/upsert/delete rows, `twad_key_deletes_tables`) shared by the CLI and the MCP server. Writes only ever touch `workspace/<patch>`.

**Merge rules** (how the game combines DB tables from several packs; "priority" is the order mods are listed in, first = highest):

1. If two packs contain the same table file (`db/<table>/<fragment>`), only the higher-priority pack's file is loaded: a whole-file override.
2. The surviving fragments of a table are merged in fragment-name byte order.
3. When several define the same primary key, the first one wins. A patch meant to win uses a fragment name that sorts first (for example starting with `!`).

If the schema can't be found, the commands still run but treat each whole row as its key and skip reference checks (with a warning).

### MCP server and scaffold

`mcp_server.py` exposes 16 tools: `workspace_status`, `list_tables`, `describe_table`, `query_rows`, `find_key`, `diff`, `find_conflicts`, `validate_patch`, `new_patch`, `upsert_rows`, `delete_rows`, `copy_rows`, `add_key_deletes`, `rpfm_status`, `extract_packs`, `repack`. The data tools are plain functions over `tw_patcher.data`; the last three talk to RPFM through the same services as the CLI. Results are capped by a `limit` with a `truncated` flag so large tables never flood a model's context. Expected problems (unknown mod, bad edit, RPFM refusing) are returned as tool errors with their message. The `mcp` package is an optional extra, imported only by this module.

`tw-patcher scaffold` (`services/scaffold.py`, texts in `scaffold_templates.py`) writes `sources/`, `workspace/`, `output/`, `modding_docs/*.md`, `CLAUDE.md`, `.github/copilot-instructions.md`, `.cursorrules` and `.mcp.json`. Generated text files start with a marker line; `--update` refreshes only files that still have it, `--force` overwrites everything. `.mcp.json` is merged, not replaced: it gets a `tw-patcher` stdio entry launching the running interpreter (or the frozen executable in installer builds) and, if an RPFM 5 server answers (or `--rpfm-mcp`), an `rpfm` HTTP entry. Edit the templates when the behaviour of a command changes, since an LLM reads them.

### Configuration Persistence

All user data is stored in the application data directory (`Settings._app_data_dir()` in `config.py`):
- **Windows**: `%LOCALAPPDATA%\tw-patcher\`
- **Linux**: `$XDG_DATA_HOME/tw-patcher/` (default `~/.local/share/tw-patcher/`)
- **macOS**: `~/Library/Application Support/tw-patcher/`

Set `TW_PATCHER_HOME` to use a different folder instead (all of the above, including config, moves there).

Config file (`config.json`):
```json
{
  "selected_game": "warhammer_3",
  "game_dirs": {
    "warhammer_3": "E:\\SteamLibrary\\steamapps\\common\\Total War WARHAMMER III"
  },
  "modding_root": "D:\\Modding\\my_project",
  "rpfm_path": "C:\\Program Files\\RPFM",
  "schema_dir": "D:\\rpfm\\schemas"
}
```

| Key | Meaning | Set with |
|-----|---------|----------|
| `selected_game` | Game key used by every command | `--game`, the GUI |
| `game_dirs` | Install folder per game key | `config set-game-dir`, the GUI |
| `modding_root` | Folder holding `sources/`, `workspace/`, `output/` | `config set-modding-root`, the GUI |
| `rpfm_path` | RPFM install folder or executable, used to start the server | `config set-rpfm` |
| `schema_dir` | Folder with RPFM's `schema_<game>.ron` files (used instead of RPFM's own folder; `TW_PATCHER_SCHEMA_DIR` overrides it) | edit `config.json` by hand |

Paths that no longer exist are ignored on load. On first launch, games are auto-detected via Steam's `libraryfolders.vdf` and common install paths.

Environment variables:

| Variable | Effect |
|----------|--------|
| `TW_PATCHER_HOME` | Replaces the application data directory (config, caches, default modding root) |
| `TW_PATCHER_RPFM_PORT` | Port of the RPFM server (default 45127) |
| `TW_PATCHER_SCHEMA_DIR` | Folder to read RPFM schemas from; overrides `schema_dir` and RPFM's own config folder, and is never written to `config.json` |

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
| `sources/` | Extracted TSVs from source mods (and `sources/vanilla/`) | `<modding_root>/` |
| `workspace/` | Patch mod projects (editable) | `<modding_root>/` |
| `output/` | Built .pack files | `<modding_root>/` |
| `modding_docs/` | Generated docs (`tw-patcher scaffold`) | `<modding_root>/` |
| `game_art/` | Cached Steam header images | `<data_dir>/` |
| `workshop_thumbs/` | Cached workshop thumbnails | `<data_dir>/` |
| `cache/` | Derived data that is safe to delete (parsed schemas) | `<data_dir>/` |
| `config.json` | User settings | `<data_dir>/` |

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows (source .venv/bin/activate elsewhere)
pip install -e ".[dev]"
```

Extras (see `pyproject.toml`): `dev` (pytest, ruff, pyright, and `mcp` so the MCP tests run), `mcp` (the MCP server only), `build` (PyInstaller, plus `mcp` so installers include the server). Runtime dependencies are `websockets`, `click`, `rich` and `PyQt6`.

## Running

```bash
tw-patcher --help             # CLI
tw-patcher ui                 # GUI
tw-patcher mcp                # MCP server on stdio
tw-patcher --game attila check  # Set game + verify RPFM
```

## Testing and Checks

```bash
pytest -q                     # outside-in tests, no RPFM needed
ruff check . && ruff format --check .
pyright
```

Tests are outside-in: each one runs `python -m tw_patcher ...` in a subprocess
against a temporary modding root and asserts on exit code, output and files on
disk. RPFM is replaced by `tests/fake_rpfm.py`, a small WebSocket server that
speaks both RPFM protocols and stores "packs" as JSON manifests, so a test can
build an input pack and inspect exactly what tw-patcher wrote. Write unit tests
only for logic that is genuinely intricate (the RON parser and schema reader are
the current examples; the merge rules are tested through the CLI).

Two environment variables keep tests away from your real setup and are also
usable by hand: `TW_PATCHER_HOME` replaces the app data directory (config,
caches, default modding root) and `TW_PATCHER_RPFM_PORT` points at a different
RPFM server. `TW_PATCHER_SCHEMA_DIR` points schema loading at a test schema.

Tooling expectations:
- **ruff** (configured in `pyproject.toml`): line length 120, target Python 3.10, rules `E4 E7 E9 F I UP B`. `ruff format` is the formatter; CI fails on unformatted code, so run `ruff format .` before committing.
- **pyright** (configured in `pyrightconfig.json`): `basic` mode against the project's `.venv`, with the "unknown type" reports switched off. Windows-only APIs are guarded with `sys.platform` checks so it passes on Linux too.
- Keep `README.md` and the generated texts in `services/scaffold_templates.py` in step with the CLI when options change (`tw-patcher <command> --help` is the source of truth for options).

CI (`.github/workflows/ci.yml`) runs lint (ruff, pyright) on Linux and the tests on Windows and Linux with Python 3.10 and 3.12, on every push to `main` and every pull request.

## Release

Pushing a tag `v*` (for example `v0.6.0`) triggers `.github/workflows/release.yml`. It first runs the CI workflow (`ci.yml`, via `workflow_call`); only if that passes does it build the Windows installer (NSIS), macOS DMG and Linux AppImage with PyInstaller (`pip install -e ".[build]"`, `tw-patcher.spec`) and publish a GitHub release with generated notes. Tags containing `rc`, `beta` or `alpha` are marked as prereleases.

The version is single-sourced from `pyproject.toml` (`version = ...`); `tw_patcher.__version__` reads it from the installed package metadata. The release workflow takes the installer version from the tag name, so bump `pyproject.toml` to match before tagging.

## Adding a New Game

If RPFM adds support for a new game:

1. Add entry to `GAMES` dict in `tw_patcher/models/game.py` with key, display name, Steam app ID, folder name, and executable
2. Add its schema file name to `SCHEMA_FILES` in `tw_patcher/data/schema.py` so the offline analysis can find it

The rest is driven by the registry.

## Dependencies

- **websockets**: async WebSocket client for the RPFM protocols
- **click**: CLI framework
- **rich**: Terminal formatting (tables, panels, spinners)
- **PyQt6**: GUI framework
- **mcp** (optional extra): MCP server (`tw-patcher mcp`)
- **RPFM** (external, 4.x or 5.x): provides the server that does the actual pack file manipulation
