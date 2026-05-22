# Total War Mod Patcher

A CLI + GUI tool to extract and repack Total War mod pack files, making it easy to create patches using your editor of choice. Works with all modern Total War games supported by RPFM.

## Why?

[RPFM](https://github.com/Frodo45127/rpfm) is powerful but its built-in editor is basic for bulk table work. I find Editing TSV data in a proper IDE (with diff tools, multi-cursor, search/replace, and AI assistance) a fair bit easier. This tool wraps RPFM's headless server to automate the extract → edit → repack cycle.

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

- [RPFM](https://github.com/Frodo45127/rpfm/releases) installed (provides the server backend)
- One or more `.pack` files to work with

## Running from source

I haven't done the steps to get my build verified by windows, so if you don't trust it, then here are the steps to run it directly from the source code:

### Prerequisites

- **Python 3.10 or later** — [python.org/downloads](https://www.python.org/downloads/)
- **Git** — [git-scm.com](https://git-scm.com/)
- **RPFM** — [github.com/Frodo45127/rpfm/releases](https://github.com/Frodo45127/rpfm/releases)

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
pip install -e .
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

### Select a game (required on first use, remembered after)

```bash
tw-patcher --game warhammer_3 check
```

Available: `pharaoh_dynasties`, `pharaoh`, `warhammer_3`, `troy`, `three_kingdoms`, `warhammer_2`, `warhammer`, `thrones_of_britannia`, `attila`, `rome_2`, `shogun_2`, `napoleon`, `empire`, `arena`

### Extract mods to TSV

```bash
tw-patcher extract -s path\to\mod1.pack -s path\to\mod2.pack
```

Extracts database tables from up to 6 pack files into `sources/` as TSV.

Options:
- `--output` / `--sources-dir` — override output directory

### List patch mods

```bash
tw-patcher list
```

### Repack a patch mod

```bash
tw-patcher repack --patch empire_rebalance
```

Options:
- `--output` — explicit output .pack path
- `--name` — custom filename (without .pack)
- `--output-dir` — override output directory
- `--workspace-dir` — override workspace directory

### Replace a table inside an existing pack

```bash
tw-patcher replace-table -p path\to\mod.pack -t path\to\fixed_table.tsv
```

Swaps one or more DB tables inside a `.pack` file while keeping all other content (models, textures, scripts, other tables) intact. The internal table path is read from the TSV's metadata line, so the replacement file must correspond to a table already in the pack.

Options:
- `-t` / `--tsv` — replacement TSV file (repeatable for multiple tables)
- `-o` / `--output` — write to a new file instead of editing the pack in-place

Examples:
```bash
# Fix a single table in-place
tw-patcher replace-table -p mod.pack -t fixed_table.tsv

# Fix multiple tables, save to a new file
tw-patcher replace-table -p mod.pack -t fix1.tsv -t fix2.tsv -o patched_mod.pack
```

### Other commands

```bash
tw-patcher check        # Verify RPFM server is running
tw-patcher clean        # Clear sources/ and output/
tw-patcher --help       # Full option list
```

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

1. **Extract** — unpack mods into `sources/` as TSV files
2. **Compare** — diff tables between mods in your editor
3. **Create Patch** — make a folder in `workspace/<name>/db/...`
4. **Edit** — copy/merge/modify tables in your patch
5. **Repack** — build the .pack file for the game
6. **Test** — load in RPFM or drop into the game's data folder

Multiple patches can coexist in `workspace/` and be repacked independently.

---

## How It Works

This tool communicates with RPFM's headless server via WebSocket (`localhost:45127`):

- **Extract**: Opens pack → lists DB tables → exports each as TSV (preserving RPFM metadata for round-trip)
- **Repack**: Creates new pack → imports TSVs back to binary DB format → saves as .pack

RPFM's server starts automatically when the tool connects or when RPFM is open.

---

## AI-Assisted Patching

The project includes instruction files that give AI assistants context about the modding workflow. AI is useful for comparing mods, explaining tables, and suggesting edits — but **always verify suggestions** before repacking, as AI frequently misaligns columns or invents non-existent keys.

See `modding_docs/` for reference documentation on TSV format, schemas, and workflow.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot connect to RPFM server" | Install RPFM from [releases](https://github.com/Frodo45127/rpfm/releases) and ensure it's running |
| "No game selected" | Run `tw-patcher --game <key> check` or select in the UI |
| "No TSV files found" | Run `extract` first |
| Import fails with schema mismatch | You edited the TSV incorrectly — compare with original |
| Pack loads but data wrong | Check for duplicate primary keys |

---

## Requirements

- RPFM ([github.com/Frodo45127/rpfm](https://github.com/Frodo45127/rpfm))
- Windows, Linux, or macOS
- (Source only) Python 3.10+ and dependencies: `websockets`, `click`, `PyQt6`

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for codebase structure, architecture, and contribution details.

## Acknowledgements

This tool is an automation layer on top of [RPFM](https://github.com/Frodo45127/rpfm). RPFM does all the heavy lifting: decoding CA's proprietary pack format, maintaining schemas for every game patch, handling binary↔TSV conversion, and exposing a WebSocket server for programmatic access.

Without RPFM and the tremendous amount of work behind it, none of this would exist. If you find this tool useful, the credit belongs to the RPFM contributors.
