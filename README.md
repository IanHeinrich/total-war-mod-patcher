# Total War Mod Patcher

A CLI + GUI tool to extract and repack Total War mod pack files, making it easy to create patches using your editor of choice. Works with all modern Total War games supported by RPFM.

## Why?

[RPFM](https://github.com/Frodo45127/rpfm) is powerful but its built-in editor is basic for bulk table work. I find Editing TSV data in a proper IDE (with diff tools, multi-cursor, search/replace, and AI assistance) a fair bit easier. This tool wraps RPFM's headless server to automate the extract → edit → repack cycle.

## Supported Games

All Total War games supported by RPFM:

Pharaoh Dynasties, Pharaoh, **Warhammer 3**, Troy, Three Kingdoms, Warhammer 2, Warhammer, Thrones of Britannia, Attila, Rome 2, Shogun 2, Napoleon, Empire, Arena

The tool auto-detects games installed via Steam. You can also manually point it at any game folder.

## Prerequisites

- [RPFM](https://github.com/Frodo45127/rpfm/releases) installed (provides the server backend)
- Python 3.10+
- One or more `.pack` files to work with

## Installation

```bash
pip install -e .
```

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

- Python 3.10+
- RPFM ([github.com/Frodo45127/rpfm](https://github.com/Frodo45127/rpfm))
- Windows, Linux, or macOS
- Dependencies: `websockets`, `click`, `PyQt6`

## Development

See [DEVELOPMENT.md](DEVELOPMENT.md) for codebase structure, architecture, and contribution details.

## Acknowledgements

This tool is a thin automation layer on top of [RPFM](https://github.com/Frodo45127/rpfm) by Frodo45127. RPFM does all the heavy lifting — decoding CA's proprietary pack format, maintaining schemas for every game patch, handling binary↔TSV conversion, and exposing a WebSocket server for programmatic access.

Without RPFM and the tremendous amount of work behind it, none of this would exist. If you find this tool useful, the credit belongs to the RPFM team.
