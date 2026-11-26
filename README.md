# Total War Mod Patcher

A CLI + GUI tool to extract, compare and repack Total War mod pack files, making it easy to create patches using your editor of choice (or an AI assistant). Works with all modern Total War games supported by RPFM.

## Why?

[RPFM](https://github.com/Frodo45127/rpfm) is powerful but its built-in editor is basic for bulk table work. I find Editing TSV data in a proper IDE (with diff tools, multi-cursor, search/replace, and AI assistance) a fair bit easier. This tool wraps RPFM's headless server to automate the extract → edit → repack cycle, and adds offline analysis (conflicts, diffs, validation) on top of the extracted tables.

## Supported Games

All Total War games supported by RPFM:

Pharaoh Dynasties, Pharaoh, **Warhammer 3**, Troy, Three Kingdoms, Warhammer 2, Warhammer, Thrones of Britannia, Attila, Rome 2, Shogun 2, Napoleon, Empire, Arena

The tool auto-detects games installed via Steam. You can also manually point it at any game folder.

## Download

Grab the latest installer from the [Releases](https://github.com/IanHeinrich/total-war-mod-patcher/releases/latest) page:

- **Windows** — `tw-patcher-x.x.x-windows-setup.exe`
- **macOS** — `tw-patcher-x.x.x-macos.dmg`
- **Linux** — `tw-patcher-x.x.x-x86_64.AppImage`

## Prerequisites

- [RPFM](https://github.com/Frodo45127/rpfm/releases) installed (provides the server backend). RPFM 4.x and 5.x both work: tw-patcher detects which protocol the server speaks, and `tw-patcher check` reports it
- One or more `.pack` files to work with

## Running from source

I haven't done the steps to get my build verified by windows, so if you don't trust it, then here are the steps to run it directly from the source code:

### Prerequisites

- **Python 3.10 or later** — [python.org/downloads](https://www.python.org/downloads/)
- **Git** — [git-scm.com](https://git-scm.com/)
- **RPFM** (4.x or 5.x) — [github.com/Frodo45127/rpfm/releases](https://github.com/Frodo45127/rpfm/releases)

### Setup

**1. Clone the repository**

```bash
git clone https://github.com/IanHeinrich/total-war-mod-patcher.git
cd total-war-mod-patcher
```

**2. Create and activate a virtual environment**

Windows:
```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**3. Install the package**

```bash
pip install -e ".[dev]"     # tests and linting included
```

Or, for just the tool plus the [MCP server](#ai-assisted-patching-mcp):

```bash
pip install -e ".[mcp]"
```

### Running

Launch the GUI:
```bash
tw-patcher ui
```

Or use the CLI:
```bash
tw-patcher --help
```

> You need to activate the virtual environment (step 2) each time you open a new terminal before running `tw-patcher`.

---

## CLI Usage

Every command accepts `--help`. Commands that fail exit with status 1, so they are safe to use in scripts. The analysis commands (`status`, `tables`, `show`, `find-key`, `diff`, `conflicts`, `validate`, `diagnose`, `config show`) take `--json` for machine-readable output.

### Select a game (required on first use, remembered after)

```bash
tw-patcher --game warhammer_3 check
```

Available: `pharaoh_dynasties`, `pharaoh`, `warhammer_3`, `troy`, `three_kingdoms`, `warhammer_2`, `warhammer`, `thrones_of_britannia`, `attila`, `rome_2`, `shogun_2`, `napoleon`, `empire`, `arena`

`-v` / `--verbose` turns on debug logging.

Working folders live in your modding root (`sources/`, `workspace/`, `output/`). Set it once with `tw-patcher config set-modding-root <path>`, or run `tw-patcher scaffold` in the folder you want.

### Extract & inspect

**`extract`**: unpack mod packs into `sources/<mod>/`. Database tables and `text/**/*.loc` files become TSV; scripts are copied as files.

```bash
tw-patcher extract -s path\to\mod1.pack -s path\to\mod2.pack
tw-patcher extract --workshop-id 2789857397 --vanilla -t land_units
tw-patcher extract --refresh
tw-patcher extract -s mod.pack --dry-run
```

- `-s` / `--source`: a `.pack` file (up to 6)
- `--workshop-id`: a Steam Workshop item ID; extracts every `.pack` in its Workshop folder (repeatable)
- `--vanilla`: also extract the game's `data/db.pack` to `sources/vanilla/` (not counted in the 6), so references can be checked against the base game
- `-t` / `--table`: only export these tables, e.g. `land_units` or `land_units_tables` (repeatable). Vanilla has ~1600 tables, so this is worth using with `--vanilla`
- `--refresh`: re-extract every source whose pack has changed since it was extracted
- `--dry-run`: list what would be extracted and replaced, without writing anything
- `-o` / `--output` / `--sources-dir`: override the output directory

A partly failed extraction still writes the rest, then exits with status 1.

**`status`**: is each extracted source still current? Reports `current`, `changed` (pack size or date differ), `missing` (pack gone) or `unknown` (extracted before tw-patcher recorded where it came from).

**`tables [MOD]`**: with no argument, list the extracted mods and patches; with a mod, list its tables and table fragments. A mod is a name under `sources/` or `workspace/`; a unique trailing part is enough, and you can prefix `sources/` or `workspace/` when a source and a patch share a name.

**`show TABLE --mod MOD`**: print rows as the game would merge them. `TABLE` can be `units_tables`, `units` or `db/units_tables`.
- `-k` / `--key`: only this primary key (composite keys: `a|b`)
- `-w` / `--where COLUMN=VALUE`: filter (repeatable; all must match)
- `-c` / `--columns`: columns to print
- `-n` / `--limit`: maximum rows (default 50, 0 = all)

**`find-key KEY`**: every mod and patch that defines a key, with the rows listed in merge order (the first is the one the game uses). `-t` / `--table` restricts the search to given tables, which is much faster.

**`diff MOD_A MOD_B`**: row-level differences from A to B, matched by primary key. Works between any two mods or patches: a patch and its source, or two versions of a mod.
- `-t` / `--table`: only these tables
- `--shared`: only tables both sides contain
- `-n` / `--limit`: rows listed per table and change type (default 20, 0 = all)

**`conflicts MOD...`**: where mods step on each other, given in load order (first = highest priority). Reports whole-file overrides, primary keys defined by more than one mod (and which row wins), and references to keys that none of the mods define.
- `--context MOD`: also resolve references against this mod (e.g. extracted vanilla) without reporting its conflicts
- `--no-references`: skip the dangling-reference check (faster)
- `-n` / `--limit`: items listed per section (default 50, 0 = all)

```bash
tw-patcher conflicts roc_sfo/!!roc_realms_ie roc_sfo/!b_mixer roc_sfo/sfo_grimhammer_3_main --context roc_sfo/db
```

### Build patches

**`new-patch NAME`**: create `workspace/NAME/db/`, optionally seeded with tables copied from an extracted mod (`--from MOD`, `-t TABLE` repeatable). Copies keep their file names and metadata exactly.

```bash
tw-patcher new-patch sfo_roc_compat --from roc_sfo/sfo_grimhammer_3_main -t land_units -t main_units
```

**`validate PATCH`**: check a patch before repacking. Errors (exit status 1): unreadable or edited metadata lines, tables or versions the schema doesn't know, missing or extra columns, wrong cell counts, values of the wrong type, duplicate primary keys. Warnings: references to keys found nowhere, metadata paths that differ from the file location. `--against MOD` limits which mods references are resolved against (default: everything in `sources/`).

**`repack --patch NAME`**: build `output/NAME.pack` from `workspace/NAME`. Runs `validate` first and refuses on errors.
- `-p` / `--patch`: patch name (required)
- `-o` / `--output`: explicit output `.pack` path
- `-n` / `--name`: custom filename (without `.pack`)
- `--output-dir` / `--workspace-dir`: override the output / workspace directory
- `--install`: also copy the built pack into the selected game's `data/` folder (set it with `config set-game-dir` if it wasn't detected)
- `--no-validate`: skip the pre-repack checks
- `--allow-partial`: save the pack even if some files failed to import (by default nothing is saved, since a pack silently missing tables is worse than none)

**`replace-table`**: swap one or more DB tables inside an existing pack, keeping everything else (models, textures, scripts, other tables) intact. The internal table path is read from the TSV's metadata line, so each replacement file must correspond to a table already in the pack.
- `-p` / `--pack`: the pack to change (required)
- `-t` / `--tsv`: replacement TSV (repeatable, required)
- `-o` / `--output`: write a new file instead of editing in place
- `--no-backup`: when editing in place, skip the `<pack>.bak` copy that is otherwise made first

```bash
tw-patcher replace-table -p mod.pack -t fixed_table.tsv
tw-patcher replace-table -p mod.pack -t fix1.tsv -t fix2.tsv -o patched_mod.pack
```

**`diagnose`**: run RPFM's own diagnostics (invalid references, outdated tables, ...) on a pack. Needs RPFM 5+. Give `--pack FILE`, or `--patch NAME` to repack a patch into a temporary pack first. `--level info|warning|error` sets the lowest level reported. Exits 1 if any error-level problem is found.

### Setup

**`config`**: view or change settings.

```bash
tw-patcher config show                          # add --json for machine-readable output
tw-patcher config set-rpfm <path>               # RPFM install folder or executable
tw-patcher config set-modding-root <path>       # folder holding sources/, workspace/, output/ (created if missing)
tw-patcher config set-game-dir <path> [--game KEY]   # a game's install folder (the one containing data/)
```

**`check`**: verify the RPFM install and server, and report which protocol (4.x legacy or 5.x JSON-RPC) and version it speaks.

**`clean`**: remove `sources/` and `output/` to start fresh. Patches in `workspace/` are never touched. Asks for confirmation unless `-y` / `--yes` is given (non-interactive callers must pass it); `--dry-run` lists what would be deleted. `--sources-dir` / `--output-dir` override the folders.

**`scaffold`**: set up a modding folder: `sources/`, `workspace/`, `output/`, a `modding_docs/` folder with background docs, AI instruction files (`CLAUDE.md`, `.github/copilot-instructions.md`, `.cursorrules`) and a `.mcp.json`. Existing files are left alone unless you pass:
- `--update`: refresh generated files that still start with tw-patcher's marker line (delete that line to keep a file as your own)
- `--force`: overwrite generated files even if you edited them
- `--rpfm-mcp` / `--no-rpfm-mcp`: register RPFM 5's own MCP endpoint in `.mcp.json` (default: only if an RPFM 5 server is running)
- `-t` / `--target`: folder to scaffold (default: the modding root)

**`mcp`**: run tw-patcher's MCP server on stdio. See [AI-Assisted Patching](#ai-assisted-patching-mcp).

**`ui`**: launch the GUI.

---

## GUI Usage

```bash
tw-patcher ui
```

### Game Selection

The top panel shows the currently selected game with its Steam artwork. Click **Change Game...** to open the game browser, which shows all games detected on your PC. You can also manually select a folder for games not auto-detected.

The selected game and its install path are remembered between sessions.

### Settings

- **Modding Workspace** — folder where `sources/`, `workspace/`, and `output/` live
- **Game Install** — auto-detected or manually set; used for workshop browsing and output targeting

### Extract Panel

- **Browse Workshop** — browse installed Steam Workshop mods for the selected game
- **Add .pack File** — manually pick pack files from disk
- **Extract All** — extract database tables from selected packs to TSV

### Repack Panel

- **Patch Mod** dropdown — select from patch mods in `workspace/`
- **New Patch Mod** — create a new named workspace folder
- **Output Directory** — defaults to game's `data/` folder
- **Repack** — build the .pack file

---

## Workflow

1. **Extract**: `tw-patcher extract -s a.pack -s b.pack --vanilla -t <tables>` unpacks the mods into `sources/` as TSV (`tw-patcher status` later tells you if a pack has changed; `extract --refresh` updates it)
2. **Investigate**: `conflicts` shows where the mods collide; `diff`, `show` and `find-key` let you look at the rows involved without opening multi-megabyte files
3. **Create a patch**: `tw-patcher new-patch my_fix --from <mod> -t <table>` makes `workspace/my_fix/db/...`, seeded with the tables you need
4. **Edit**: change the TSVs in your editor (or let an assistant do it through [MCP](#ai-assisted-patching-mcp))
5. **Validate**: `tw-patcher validate my_fix` catches bad columns, types, duplicate keys and dangling references before RPFM does
6. **Repack**: `tw-patcher repack --patch my_fix --install` builds `output/my_fix.pack` (and with `--install` copies it into the game's `data/` folder)
7. **Test**: on RPFM 5, `tw-patcher diagnose --patch my_fix` runs RPFM's own checks too; then load the game

Multiple patches can coexist in `workspace/` and be repacked independently. As always, test the result in game before publishing.

---

## How It Works

**RPFM does the pack work.** tw-patcher talks to RPFM's headless server over a WebSocket (`ws://127.0.0.1:45127/ws`) and supports both of its protocols, picked automatically from the server's first message: the legacy command protocol of RPFM 4.x and the JSON-RPC 2.0 protocol of RPFM 5.x.

- **Extract**: opens the pack, lists its files, exports each DB table and loc file as TSV (preserving RPFM's metadata line for round-trip) and extracts scripts
- **Repack**: creates a new pack, imports the TSVs back to binary DB format, adds scripts and saves it as `.pack`

RPFM's server starts automatically when the tool connects, if RPFM is installed and not already running.

**The analysis is offline.** `tables`, `show`, `find-key`, `diff`, `conflicts`, `validate` and the MCP tools read the extracted TSVs directly, using RPFM's own `schema_<game>.ron` (found in RPFM's config folder, or via `TW_PATCHER_SCHEMA_DIR`) to know each table's columns, types, keys and references; without it they still work, but treat each whole row as its key and skip reference checks. They mimic how the game merges tables from several packs:

- if two packs contain the same table file, only the higher-priority pack's file is loaded (a whole-file override)
- the remaining fragments of a table are merged in fragment-name byte order
- when several rows share a primary key, the first one wins

Load order is the order you list mods in, first being highest priority.

---

## AI-Assisted Patching (MCP)

tw-patcher includes an [MCP](https://modelcontextprotocol.io) server, so Claude (or any MCP client)
can investigate and patch mods through tools rather than by reading and hand-editing multi-megabyte
TSV files.

```bash
tw-patcher scaffold                 # modding folder: modding_docs/, CLAUDE.md and .mcp.json
claude mcp add tw-patcher -- tw-patcher mcp   # or register it yourself (Claude Code)
```

The tools cover the workspace layer:
- **Inspect:** `workspace_status`, `list_tables`, `describe_table`, `query_rows`, `find_key`, `diff`,
  `find_conflicts`, `validate_patch`.
- **Edit patches safely:** `new_patch`, `copy_rows`, `upsert_rows`, `delete_rows`, `add_key_deletes`.
  These only write inside `workspace/<patch>` and always keep RPFM's file format intact.
- **Build:** `extract_packs`, `repack`, `rpfm_status`.

RPFM 5 also serves its own MCP endpoint (`http://127.0.0.1:45127/mcp`) for pack-level work.
`scaffold` registers it too when an RPFM 5 server is running (`--rpfm-mcp` forces it).
`scaffold --update` refreshes the generated files without touching ones you've edited. The generated `modding_docs/` and `CLAUDE.md` teach the assistant the layout, the workflow and the merge rules.

The MCP server needs the `mcp` extra when running from source: `pip install -e ".[mcp]"`.
As always, test the result in game before publishing.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot connect to RPFM server" | Install RPFM from [releases](https://github.com/Frodo45127/rpfm/releases) and ensure it's running |
| "No game selected" | Run `tw-patcher --game <key> check` or select in the UI |
| "No TSV files found" | Run `extract` first |
| Warning that the RPFM schema was not found | Analysis falls back to whole-row keys and skips reference checks. Open RPFM once so it downloads its schemas, or point `TW_PATCHER_SCHEMA_DIR` at the folder holding `schema_<game>.ron` |
| `diagnose` says it needs RPFM 5 | Diagnostics are an RPFM 5 feature; run `tw-patcher check` to see which version you have |
| Import fails with schema mismatch | You edited the TSV incorrectly — compare with original |
| Pack loads but data wrong | Check for duplicate primary keys |

---

## Requirements

- RPFM 4.x or 5.x ([github.com/Frodo45127/rpfm](https://github.com/Frodo45127/rpfm))
- Windows, Linux, or macOS
- (Source only) Python 3.10+ and dependencies: `websockets`, `click`, `rich`, `PyQt6`; plus `mcp` for the MCP server (`pip install -e ".[mcp]"`)

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for codebase structure, architecture, and contribution details.

## Acknowledgements

This tool is an automation layer on top of [RPFM](https://github.com/Frodo45127/rpfm). RPFM does all the heavy lifting: decoding CA's proprietary pack format, maintaining schemas for every game patch, handling binary↔TSV conversion, and exposing a WebSocket server for programmatic access.

Without RPFM and the tremendous amount of work behind it, none of this would exist. If you find this tool useful, the credit belongs to the RPFM contributors.
