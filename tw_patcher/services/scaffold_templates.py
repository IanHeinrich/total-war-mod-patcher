"""Text of the files `tw-patcher scaffold` generates. ``{marker}`` is replaced by
the generated-file marker line (see services/scaffold.py)."""

AI_CORE = """\
{marker}
# Total War modding workspace (tw-patcher)

This folder is managed by [tw-patcher](https://github.com/IanHeinrich/total-war-mod-patcher):
mods are extracted to editable tables, compared, patched, and repacked into `.pack` files.

## Layout

| Folder | What it holds |
|---|---|
| `sources/<mod>/` | Tables and scripts extracted from mod packs. Reference only: never edit. Grouped mods live one level deeper (`sources/<group>/<mod>/`). |
| `workspace/<patch>/` | Patch mods you build. `db/<table>/<fragment>.tsv` files, mirroring the source layout. |
| `output/` | Built `.pack` files. |
| `modding_docs/` | Background: workflow, table format, schema basics. |

Mods are named `sources/<name>` or `workspace/<name>`; a unique trailing part of the name also works.

## Use the tools, not raw file edits

Tables can be tens of megabytes, and the TSV format is fragile (tabs, a metadata line, exact columns).
Read and change data through tw-patcher, which keeps the format intact and only returns what you ask for.

**MCP tools** (server `tw-patcher` in `.mcp.json`):

| Tool | Use it to |
|---|---|
| `workspace_status` | See the game, folders, schema, RPFM state and every extracted mod / patch |
| `list_tables`, `describe_table` | See a mod's tables; a table's columns, key, types and references |
| `query_rows` | Read rows (filter by key or column values, pick columns, page) |
| `find_key` | Find which mods define a key, and which one wins |
| `diff` | Compare two mods or a patch with its source, row by row |
| `find_conflicts` | Overrides, key collisions and dangling references between mods in load order |
| `new_patch`, `copy_rows`, `upsert_rows`, `delete_rows` | Build and edit a patch in `workspace/` |
| `add_key_deletes` | Delete another mod's or vanilla's rows at load (Warhammer 3) |
| `validate_patch` | Check a patch before building it |
| `extract_packs`, `repack`, `rpfm_status` | Talk to RPFM: extract packs, build the patch |

**Same operations on the command line** (add `--json` for machine-readable output):
`tw-patcher tables`, `show`, `find-key`, `diff`, `conflicts`, `validate`, `new-patch`,
`extract`, `status`, `repack`, `diagnose`, `replace-table`, `check`, `config`. Run
`tw-patcher <command> --help` for options.

**RPFM's own MCP server** (`rpfm` in `.mcp.json`, available while RPFM 5 is running) works inside
individual packs: decoding any file type, schema details, RPFM diagnostics, global search. Use it for
pack-level questions; use tw-patcher for anything spanning several mods or the patch project.

## Making a compatibility patch

1. `workspace_status`. Extract any mod you need with `extract_packs` (absolute `.pack` paths or Steam
   Workshop item IDs). For reference checks also extract vanilla (`extract_packs(vanilla=True)`, optionally
   limited with `tables=[...]`) and pass `sources/vanilla` as `context`. `tw-patcher status` shows which
   extractions are older than their pack (re-extract with `tw-patcher extract --refresh`).
2. `find_conflicts(mods=[...in load order, first wins...], context=[vanilla])` to see what clashes.
3. `new_patch(name)`, then `copy_rows` the rows to fix from the mod they come from, and adjust them with
   `upsert_rows`. Remove rows from your patch with `delete_rows`; remove another mod's rows at load with
   `add_key_deletes`, but only after `find_key` / `find_conflicts` show nothing else references them
   (a deleted row that is still referenced crashes the game on load).
4. `validate_patch` until it reports no errors.
5. `repack` builds `output/<name>.pack`. With RPFM 5, `tw-patcher diagnose --patch <name>` runs RPFM's own
   checks too. Ask the user before installing it into the game's `data/` folder
   (`tw-patcher repack --patch <name> --install`).

## How the game merges tables

- Two packs with the same table file (`db/<table>/<fragment>`): only the higher-priority pack's file loads.
- All other fragments of a table are merged in file-name byte order; for a duplicated primary key the
  first one wins. A patch meant to win should use a fragment name that sorts first (e.g. starting with `!`).
- Load order between packs is set in the launcher or a mod manager; patches usually load before
  (above) the mods they patch.
- `twad_key_deletes_tables` keys are the key columns concatenated in CA's column order; `add_key_deletes`
  handles that. `find_conflicts` and `validate_patch` flag deletes that remove still-referenced rows.

## If you must edit a TSV by hand

- Line 1 holds the column names, line 2 RPFM's metadata (`#table;version;db/table/file`). Never change either.
- Tabs separate cells. Never add, remove or reorder columns.
- Primary keys must stay unique; values must match the column type (integers, decimals, `true`/`false`).
- Run `validate_patch` (or `tw-patcher validate <patch>`) afterwards.
"""

DOCS_README = """\
{marker}
# Modding docs

Background for working in this folder with tw-patcher.

- **WORKFLOW.md**: building a patch mod, step by step, with the commands to use
- **TSV_FORMAT.md**: how extracted tables are laid out and how to edit them safely
- **SCHEMA_BASICS.md**: tables, rows, keys and references

## Key ideas

- **Pack files (`.pack`)** contain a mod's data: database tables, text, scripts, art.
- **Database tables** are structured game data (units, buildings, factions). tw-patcher extracts each
  one as a TSV file you can read and edit.
- **Patch mods** are small packs holding only changed or added rows. They load alongside the mods
  they fix.
"""

DOCS_WORKFLOW = """\
{marker}
# Workflow: building a patch mod

## 1. Extract the mods involved

```bash
tw-patcher extract -s path/to/modA.pack -s path/to/modB.pack
tw-patcher extract --workshop-id 2789857397          # by Steam Workshop item
tw-patcher extract --vanilla -t land_units -t main_units   # the game's own tables, for reference
```

Each pack lands in `sources/<pack name>/` (`db/` tables and `text/` loc files as TSV, `script/` files
as-is). Add `--dry-run` to preview. Extraction exits with status 1 if anything failed, and lists the
failures. `tw-patcher status` shows extractions whose pack has changed since; `extract --refresh`
re-extracts them and summarises what changed in tables your patches use.

## 2. Find what clashes

```bash
tw-patcher conflicts modA modB --context <extracted vanilla>   # load order: first wins
tw-patcher diff modA modB --table land_units
tw-patcher show land_units --mod modA --key <unit key>
tw-patcher find-key <key>
```

## 3. Create the patch

```bash
tw-patcher new-patch my_patch --from modA --table land_units
```

This makes `workspace/my_patch/db/land_units_tables/<fragment>.tsv`, a byte-for-byte copy you then
edit. The `db/<table>/<file>.tsv` layout must mirror the source. With the MCP server, prefer
`copy_rows` and `upsert_rows`, which take only the rows you need and keep the format intact.

## 4. Validate

```bash
tw-patcher validate my_patch
```

Errors (exit status 1) include an edited metadata line, a table version the game doesn't know, wrong
columns, wrong cell counts, bad values and duplicate keys. Warnings flag references to keys that
neither the patch nor the extracted sources define.

## 5. Repack

```bash
tw-patcher repack --patch my_patch            # validates first; --no-validate skips it
```

Output: `output/my_patch.pack`. If any table fails to import, nothing is saved unless you pass
`--allow-partial`. `--install` also copies it into the game's `data/` folder (set the game folder once
with `tw-patcher config set-game-dir <folder>`). With RPFM 5, `tw-patcher diagnose --patch my_patch`
runs RPFM's own diagnostics on the built pack.

## Fixing a table inside an existing pack

```bash
tw-patcher replace-table -p mod.pack -t fixed_table.tsv               # keeps mod.pack.bak
tw-patcher replace-table -p mod.pack -t fixed_table.tsv -o output/mod.pack
```

Only the named tables change; models, textures and scripts are untouched. The table to replace is
read from line 2 of each TSV and must already exist in the pack.

## Housekeeping

```bash
tw-patcher list                 # patches in workspace/
tw-patcher tables               # everything extracted, with table counts
tw-patcher clean --dry-run      # what clean would delete from sources/ and output/
tw-patcher check                # RPFM installation, protocol and version
```
"""

DOCS_TSV_FORMAT = """\
{marker}
# TSV format: reading and editing tables safely

## Structure

```
key<TAB>cost<TAB>category                       <- line 1: column names
#land_units_tables;54;db/land_units_tables/mod  <- line 2: RPFM metadata (table;version;path)
unit_a<TAB>800<TAB>infantry                     <- line 3+: one row per entry
```

- **Line 1**: column names. Never modify.
- **Line 2**: metadata RPFM needs to import the file: table name, table version, path inside the pack.
  Never modify. It may be followed by empty tab-separated cells.
- **Line 3 onwards**: data rows. Safe to edit.

## Safe edits

- Change a value (stats, names, costs)
- Add a row with a new, unique primary key
- Delete a row
- Copy rows between files of the same table and version

## Edits that break things

- Adding, removing, renaming or reordering columns
- Touching lines 1 or 2
- Using spaces instead of tabs
- Duplicating a primary key
- Putting text in a number column

Colour columns: RPFM exports the red/green/blue fields of a colour as one column holding a hex value
such as `E58E3B`, named `<prefix>_hex` or `unnamed colour group_<n>`.

Check your work with `tw-patcher validate <patch>`.
"""

DOCS_SCHEMA_BASICS = """\
{marker}
# Schema basics: tables, keys and references

## Tables, rows, columns

A database table works like a spreadsheet. `land_units_tables` has one row per unit type, with
columns such as `key`, `num_men` and `category`.

## Versions

Each table has a version (line 2 of the TSV). Game patches add or remove columns and bump the
version. A TSV must match a version the game knows: `tw-patcher validate` reports one that doesn't,
and the MCP tool `describe_table` lists the known versions and their columns.

## Primary keys

One column, or several together, identify each row. No two rows may share a key. When several mods
define the same key, the game keeps one (see "How the game merges tables" in CLAUDE.md).

## References

Many columns point at a row of another table, for example `main_units_tables.land_unit` refers to
`land_units_tables.key`. If the target row doesn't exist, the game may crash or misbehave.
`tw-patcher validate` and `tw-patcher conflicts` flag references that resolve nowhere.

## Deleting rows of other mods (Warhammer 3)

`twad_key_deletes_tables` lists rows (table name plus key) the game removes at load. It replaces the
old "datacore" approach of shipping a whole copy of a table minus some rows. Never delete a row that
something still references.

## Where the schema comes from

tw-patcher reads RPFM's schema files (`schema_<game>.ron` in RPFM's config folder). Open RPFM once (or
update its schemas) so they exist; set `TW_PATCHER_SCHEMA_DIR` to use another folder.
"""
