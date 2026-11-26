"""Unit tests for the offline RPFM schema reader (tw_patcher.data.ron / tw_patcher.data.schema)."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from tw_patcher.data import ron
from tw_patcher.data.schema import (
    SCHEMA_FILES,
    Field,
    SchemaNotFoundError,
    default_schema_dirs,
    load_schema,
)

FIXTURE = Path(__file__).parent / "fixtures" / "schema_test.ron"


@pytest.fixture
def schema_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "schemas"
    folder.mkdir()
    shutil.copy(FIXTURE, folder / SCHEMA_FILES["warhammer_3"])
    return folder


def _real_wh3() -> Path | None:
    for folder in default_schema_dirs():
        candidate = folder / SCHEMA_FILES["warhammer_3"]
        if candidate.is_file():
            return candidate
    return None


# --- ron ---------------------------------------------------------------------------------------


def test_ron_scalars_and_containers() -> None:
    text = """
    // comment
    (
        a: 1, b: -2, c: 1.5, d: -2.5e3, e: 0x1F, f: true, g: false,
        h: None, i: Some(3), j: StringU8, k: "x", /* block
        comment */ l: [1, 2,], m: {"k": "v", 2: [],}, n: (1, "two"), o: (),
    )
    """
    assert ron.loads(text) == {
        "a": 1,
        "b": -2,
        "c": 1.5,
        "d": -2500.0,
        "e": 31,
        "f": True,
        "g": False,
        "h": None,
        "i": 3,
        "j": "StringU8",
        "k": "x",
        "l": [1, 2],
        "m": {"k": "v", 2: []},
        "n": [1, "two"],
        "o": [],
    }


def test_ron_string_escapes() -> None:
    text = r'["a\"b", "back\\slash", "new\nline", "it\'s", "nb\u{a0}sp", "tab\t", "é"]'
    assert ron.loads(text) == ['a"b', "back\\slash", "new\nline", "it's", "nb sp", "tab\t", "é"]


def test_ron_variants_with_payload() -> None:
    assert ron.loads('Some(("units", "key"))') == ["units", "key"]
    assert ron.loads("SequenceU32((version: 1, fields: []))") == {"SequenceU32": {"version": 1, "fields": []}}
    assert ron.loads("Pair(1, 2)") == {"Pair": [1, 2]}
    assert ron.loads('Some(["a", "b"])') == ["a", "b"]


def test_ron_parses_the_fixture() -> None:
    data = ron.loads(FIXTURE.read_text(encoding="utf-8"))

    units = data["definitions"]["units_tables"]
    key = units[0]["fields"][0]
    assert key["lookup"] == ["name", "category"]
    assert key["description"] == 'The unit\'s key, see "units"\\keys'
    assert units[1]["fields"][3]["field_type"]["SequenceU32"]["fields"][0]["name"] == "x"
    assert data["patches"]["unit_ability_links_tables"]["ability"]["is_key"] == "true"


@pytest.mark.parametrize(
    ("text", "line", "column", "fragment"),
    [
        ("(\n  a: 1,\n  b: ]\n)", 3, 6, "unexpected ']'"),
        ("(a: 1 b: 2)", 1, 7, "expected ','"),
        ('[\n"open', 2, 1, "unterminated string"),
        ("(a: [1, 2)", 1, 10, "expected ',' or ']'"),
        ("{1, 2}", 1, 3, "expected ':'"),
        ("[1, 2", 1, 6, "expected ',' or ']'"),
        ("[1] [2]", 1, 5, "after the end of the document"),
        ("(a: 1, 2)", 1, 8, "expected a field name"),
    ],
)
def test_ron_malformed_input_reports_position(text: str, line: int, column: int, fragment: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        ron.loads(text)

    error = excinfo.value
    assert isinstance(error, ron.RonError)
    assert (error.line, error.column) == (line, column)
    assert fragment in str(error)
    assert f"line {line}, column {column}" in str(error)


# --- schema ------------------------------------------------------------------------------------


def test_tables_and_versions(schema_dir: Path) -> None:
    schema = load_schema("warhammer_3", schema_dir=schema_dir)

    assert schema.game == "warhammer_3"
    assert schema.source == schema_dir / "schema_wh3.ron"
    assert schema.tables() == ["abilities_tables", "unit_ability_links_tables", "units_tables"]
    assert schema.versions("units_tables") == [1, 2]
    assert schema.versions("units") == [1, 2]
    assert schema.versions("nope") == []


def test_definition_lookup_by_name_and_version(schema_dir: Path) -> None:
    schema = load_schema("warhammer_3", schema_dir=schema_dir)

    latest = schema.definition("units")
    assert latest is not None
    assert latest == schema.definition("units_tables")
    assert (latest.table, latest.version) == ("units_tables", 2)
    assert [f.name for f in latest.fields] == ["key", "ability", "cost", "waypoints"]

    old = schema.definition("units_tables", 1)
    assert old is not None
    assert [f.name for f in old.fields] == ["key", "ability"]

    assert schema.definition("units", 7) is None
    assert schema.definition("missing") is None


def test_fields_types_keys_and_references(schema_dir: Path) -> None:
    schema = load_schema("warhammer_3", schema_dir=schema_dir)
    units = schema.definition("units")
    assert units is not None

    assert units.key_columns == ["key"]
    assert units.field("key") == Field("key", "StringU8", True, None, ca_order=0)
    assert units.field("ability") == Field(
        "ability", "OptionalStringU8", False, ("abilities_tables", "key"), ca_order=1
    )
    assert units.field("cost") == Field("cost", "I32", False, None, ca_order=2)
    assert units.field("waypoints") == Field("waypoints", "SequenceU32", False, None, ca_order=3)
    assert units.field("onscreen_name") is None  # localised fields are not table columns


def test_schema_patches_are_applied(schema_dir: Path) -> None:
    schema = load_schema("warhammer_3", schema_dir=schema_dir)
    links = schema.definition("unit_ability_links")
    assert links is not None

    assert links.key_columns == ["unit", "ability"]


def test_references_to(schema_dir: Path) -> None:
    schema = load_schema("warhammer_3", schema_dir=schema_dir)

    assert schema.references_to("abilities") == [
        ("unit_ability_links_tables", "ability", "key"),
        ("units_tables", "ability", "key"),
    ]
    assert schema.references_to("units_tables") == [("unit_ability_links_tables", "unit", "key")]
    assert schema.references_to("unit_ability_links") == []


def test_cache_hit_skips_parsing(schema_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = tmp_path / "cache"
    first = load_schema("warhammer_3", schema_dir=schema_dir, cache_dir=cache_dir)
    assert len(list(cache_dir.glob("schema_wh3-*.json"))) == 1

    def must_not_parse(text: str) -> Any:
        raise AssertionError("the cached schema should have been used")

    monkeypatch.setattr(ron, "loads", must_not_parse)
    second = load_schema("warhammer_3", schema_dir=schema_dir, cache_dir=cache_dir)

    assert second.tables() == first.tables()
    for table in first.tables():
        assert second.versions(table) == first.versions(table)
        for version in first.versions(table):
            assert second.definition(table, version) == first.definition(table, version)


def test_stale_cache_is_reparsed(schema_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = tmp_path / "cache"
    load_schema("warhammer_3", schema_dir=schema_dir, cache_dir=cache_dir)

    source = schema_dir / "schema_wh3.ron"
    source.write_text(source.read_text(encoding="utf-8").replace('"cost"', '"price"'), encoding="utf-8")
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    calls: list[int] = []
    real_loads = ron.loads

    def counting_loads(text: str) -> Any:
        calls.append(len(text))
        return real_loads(text)

    monkeypatch.setattr(ron, "loads", counting_loads)
    schema = load_schema("warhammer_3", schema_dir=schema_dir, cache_dir=cache_dir)

    assert len(calls) == 1
    units = schema.definition("units")
    assert units is not None and units.field("price") is not None


def test_corrupt_cache_is_reparsed_silently(schema_dir: Path, tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    load_schema("warhammer_3", schema_dir=schema_dir, cache_dir=cache_dir)
    (cache_file,) = cache_dir.glob("schema_wh3-*.json")
    cache_file.write_text('{"format": 1, "stamp": ', encoding="utf-8")

    schema = load_schema("warhammer_3", schema_dir=schema_dir, cache_dir=cache_dir)

    assert schema.versions("units") == [1, 2]
    assert load_schema("warhammer_3", schema_dir=schema_dir, cache_dir=cache_dir).versions("units") == [1, 2]


def test_missing_schema_explains_how_to_fix(tmp_path: Path) -> None:
    with pytest.raises(SchemaNotFoundError) as excinfo:
        load_schema("warhammer_3", schema_dir=tmp_path)

    message = str(excinfo.value)
    assert "schema_wh3.ron" in message
    assert str(tmp_path) in message
    assert "RPFM" in message
    assert "TW_PATCHER_SCHEMA_DIR" in message


def test_schema_dir_env_var_is_searched_first(schema_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TW_PATCHER_SCHEMA_DIR", str(schema_dir))

    assert default_schema_dirs()[0] == schema_dir
    assert load_schema("warhammer_3").source == schema_dir / "schema_wh3.ron"


def test_every_game_has_a_schema_file() -> None:
    from tw_patcher.models.game import GAME_KEYS

    assert sorted(SCHEMA_FILES) == sorted(GAME_KEYS)


@pytest.mark.skipif(_real_wh3() is None, reason="RPFM's schema_wh3.ron is not installed")
def test_real_warhammer_3_schema(tmp_path: Path) -> None:
    real = _real_wh3()
    assert real is not None

    started = time.perf_counter()
    schema = load_schema("warhammer_3", schema_dir=real.parent, cache_dir=tmp_path)
    uncached = time.perf_counter() - started
    started = time.perf_counter()
    cached = load_schema("warhammer_3", schema_dir=real.parent, cache_dir=tmp_path)
    cached_seconds = time.perf_counter() - started

    assert uncached < 15
    assert cached_seconds < 2
    assert cached.tables() == schema.tables()
    for table in ("main_units_tables", "land_units_tables"):
        definition = schema.definition(table)
        assert definition is not None, table
        assert definition.key_columns, table
    assert ("main_units_tables", "land_unit", "key") in schema.references_to("land_units")
