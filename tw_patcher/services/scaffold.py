from pathlib import Path


class ScaffoldService:
    def __init__(self, target: Path):
        self._target = target

    def scaffold(self) -> list[Path]:
        """Create directory structure and AI helper docs. Returns list of created files."""
        created: list[Path] = []
        self._ensure_dirs()
        created.extend(self._write_modding_docs())
        created.extend(self._write_ai_instructions())
        return created

    def _ensure_dirs(self) -> None:
        (self._target / "sources").mkdir(parents=True, exist_ok=True)
        (self._target / "workspace").mkdir(parents=True, exist_ok=True)
        (self._target / "output").mkdir(parents=True, exist_ok=True)
        (self._target / "modding_docs").mkdir(parents=True, exist_ok=True)

    def _write_if_missing(self, rel_path: str, content: str) -> Path | None:
        path = self._target / rel_path
        if path.exists():
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _write_modding_docs(self) -> list[Path]:
        created: list[Path] = []
        files = {
            "modding_docs/README.md": _DOCS_README,
            "modding_docs/WORKFLOW.md": _DOCS_WORKFLOW,
            "modding_docs/TSV_FORMAT.md": _DOCS_TSV_FORMAT,
            "modding_docs/SCHEMA_BASICS.md": _DOCS_SCHEMA_BASICS,
        }
        for rel_path, content in files.items():
            if result := self._write_if_missing(rel_path, content):
                created.append(result)
        return created

    def _write_ai_instructions(self) -> list[Path]:
        created: list[Path] = []
        files = {
            ".github/copilot-instructions.md": _AI_COPILOT,
            "CLAUDE.md": _AI_CLAUDE,
            ".cursorrules": _AI_CURSOR,
        }
        for rel_path, content in files.items():
            if result := self._write_if_missing(rel_path, content):
                created.append(result)
        return created


# ---------------------------------------------------------------------------
# Template content
# ---------------------------------------------------------------------------

_AI_INSTRUCTIONS_CORE = """\
## Context

This is a Total War modding workspace. It contains extracted game data (TSV files) \
and patch mod projects that will be repacked into .pack files.

## Directory Layout

| Directory      | Purpose                                       |
|---------------|-----------------------------------------------|
| `sources/`    | Extracted TSVs from source mods (read-only reference) |
| `workspace/`  | Your patch mod projects (editable)            |
| `output/`     | Repacked .pack files (generated)              |
| `modding_docs/` | Reference guides for modding concepts       |

## Workflow

```
extract (mods → TSV) → compare in editor → create patch → repack (TSV → .pack)
```

## TSV Rules (CRITICAL)

- **Never** edit the `#` metadata header line (line 1)
- **Never** add, remove, or rename columns
- **Always** use tabs as delimiters (not spaces)
- **Always** keep primary key values unique per table
- Respect data types: integers stay integers, floats stay floats
- Folder structure in `workspace/<patch>/db/...` must mirror `sources/<mod>/db/...` exactly

## What You Can Safely Do

- Modify cell values (stats, names, costs, etc.)
- Add new rows (with unique primary keys)
- Delete rows
- Copy rows between extracted mods into a patch

## What You Should NOT Do

- Add new columns to a TSV
- Rename column headers
- Change the metadata line
- Use spaces instead of tabs
- Duplicate primary key values

## Reference

See `modding_docs/` for detailed guides:
- `WORKFLOW.md` — Step-by-step patching guide
- `TSV_FORMAT.md` — Safe editing rules
- `SCHEMA_BASICS.md` — Tables, keys, and data types
"""

_AI_COPILOT = f"""\
# Copilot Instructions — Total War Modding Workspace

{_AI_INSTRUCTIONS_CORE}
"""

_AI_CLAUDE = f"""\
# Claude Code Context — Total War Modding Workspace

{_AI_INSTRUCTIONS_CORE}
"""

_AI_CURSOR = f"""\
# Cursor Rules — Total War Modding Workspace

{_AI_INSTRUCTIONS_CORE}
"""

_DOCS_README = """\
# Modding Docs — Overview

Reference material for Total War modding with the TW Mod Patcher tool.

## Files

- **WORKFLOW.md** — Step-by-step guide to creating a patch mod
- **SCHEMA_BASICS.md** — Understanding tables, rows, columns, and keys
- **TSV_FORMAT.md** — How to read and safely edit TSV files

## Key Concepts

**Pack Files (.pack)** — Containers for mod data (database tables, text, images).

**Database Tables (.db)** — Structured game data (units, buildings, factions). Exported as TSV by RPFM.

**TSV Files** — Tab-Separated Values. One row = one game entry. Must preserve schema structure.

**Patch Mods** — New .pack files containing only changed/added data. Load on top of base mods.

## Typical Workflow

1. **Extract** — Unpack mods to TSV files (`sources/`)
2. **Compare** — Diff tables between mods
3. **Patch** — Copy/edit tables into `workspace/<patch_name>/db/...`
4. **Repack** — Build .pack file (`output/`)
5. **Verify** — Load in RPFM or test in-game
"""

_DOCS_WORKFLOW = """\
# Workflow: Creating a Patch Mod

## Step 1: Extract Source Mods

Extract mods you want to compare/merge:

```bash
tw-patcher extract -s path/to/mod1.pack -s path/to/mod2.pack
```

Results appear in `sources/` named after each pack file:
```
sources/
├── mod1/db/units_tables/main_units.tsv
└── mod2/db/units_tables/main_units.tsv
```

## Step 2: Compare in Your Editor

- Open `sources/` in your editor
- Use side-by-side diff to compare the same table from different mods
- Identify which rows/values differ and what you want in your patch

## Step 3: Create Your Patch Mod

Create a named folder under `workspace/`:

```
workspace/
└── my_patch/
    └── db/
        └── <table folders go here>
```

**Critical**: The `db/...` structure must mirror the original exactly:
- Source: `sources/mod1/db/units_tables/main_units.tsv`
- Patch: `workspace/my_patch/db/units_tables/main_units.tsv`

## Step 4: Populate Your Patch

For each table you want to include:

**Copy as-is** — Use one mod's version directly:
```bash
cp sources/mod1/db/units_tables/main_units.tsv workspace/my_patch/db/units_tables/
```

**Merge/modify** — Copy then edit:
1. Copy a table to your workspace patch
2. Edit values, add rows from the other mod, delete unwanted rows
3. Keep the metadata header (line 1) unchanged
4. Keep column structure unchanged

## Step 5: Repack

```bash
tw-patcher repack --patch my_patch
```

Output: `output/my_patch.pack`

## Step 6: Verify

Load `output/my_patch.pack` in RPFM to confirm tables imported correctly.

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Missing `db/` level | Tables not found during repack | Use `workspace/<name>/db/<table>/file.tsv` |
| Wrong folder name | Table imports to wrong location | Mirror the exact path from sources |
| Edited metadata line | Import fails | Restore original line 1 from sources |
| Spaces instead of tabs | Columns parsed incorrectly | Use actual tab characters |
| Duplicate primary keys | Import error or game crash | Ensure unique IDs per table |
"""

_DOCS_TSV_FORMAT = """\
# TSV Format: Reading and Editing Files Safely

## Structure

```
#metadata_line (RPFM internal — DO NOT EDIT)
column1\\tcolumn2\\tcolumn3
value1\\tvalue2\\tvalue3
```

- **Line 1**: Metadata header (starts with `#`) — never modify
- **Line 2**: Column names — never modify
- **Lines 3+**: Data rows — safe to edit

## Safe Edits

✅ **Modify a value** — Change stats, names, costs
✅ **Add a row** — New entry with a unique primary key
✅ **Delete a row** — Remove an entry entirely
✅ **Copy rows between files** — Merge data from different mods

## Dangerous Edits

❌ **Add/remove columns** — Breaks schema
❌ **Rename columns** — Breaks schema
❌ **Edit metadata header** — Breaks import
❌ **Use spaces instead of tabs** — Breaks parsing
❌ **Duplicate primary keys** — Causes errors

## Identifying Tabs in Your Editor

Enable whitespace rendering in your editor:
- Tabs appear as `→` arrows
- Spaces appear as `·` dots
- You should see: `value1→value2→value3`

## Data Types

| Type | Examples | Rules |
|------|----------|-------|
| Integer | `100`, `-5`, `0` | Whole numbers only |
| Float | `10.5`, `3.14` | Decimals allowed |
| String | `State Troops` | Text values |
| Boolean | `true`, `false` | Only true/false |

Put the right type in the right column — integers where integers are expected, etc.
"""

_DOCS_SCHEMA_BASICS = """\
# Schema Basics: Tables and Keys

## Tables, Rows, Columns

A database table is like a spreadsheet:

| unit_id | unit_name    | hit_points | armour | cost |
|---------|--------------|------------|--------|------|
| 1       | State Troops | 100        | 10     | 800  |
| 2       | Crossbowmen  | 80         | 5      | 600  |

- **Table** — The whole group (e.g., `main_units`)
- **Row** — One entry (one unit, one building, etc.)
- **Column** — A field/property (hit_points, cost, etc.)

## Primary Keys

A column (or group of columns) that uniquely identifies each row.

Rules:
- No two rows can have the same primary key value
- When copying rows between mods, don't create duplicates
- Updating a row = same key, different values (safe)
- Adding a row = new unique key required

## Foreign Keys

Some columns reference rows in other tables:
- `faction_id` in a units table → references the factions table
- If you change a reference, make sure the target exists
- Usually safe to copy values from original tables as-is

## Common Tables (Total War Games)

| Table Path | Contains |
|-----------|----------|
| `db/units_tables/main_units` | Unit definitions (HP, armour, cost) |
| `db/factions/factions` | Faction definitions |
| `db/buildings_tables/buildings` | Building definitions |
| `db/text/` | UI strings and names |

## Validation During Repack

RPFM checks:
1. Correct number of columns matching schema
2. Data types match (integers where expected, etc.)
3. Primary keys are unique
4. Foreign key references exist (warnings only)

Common errors and fixes:

| Error | Fix |
|-------|-----|
| Column not found | Don't add/remove columns |
| Type mismatch | Use correct data type |
| Duplicate key | Make IDs unique |
| Table not found | Check folder structure matches exactly |
"""
