"""tw-patcher status: which extracted sources are out of date."""

from ...config import settings
from ...console import console
from ...data.index import ModIndex
from ...services.extraction import SOURCE_INFO_FILE, SOURCE_STATES, source_statuses
from .._data import emit_json, json_option
from ..main import cli

_NOTES = {
    "current": "matches its pack",
    "changed": "pack changed since extraction",
    "missing": "pack no longer exists",
    "unknown": f"no {SOURCE_INFO_FILE} (extracted before tracking; re-extract to track it)",
}


@cli.command("status")
@json_option
def status_cmd(as_json: bool) -> None:
    """Show whether each extracted source still matches the pack it came from.

    States: current, changed (pack size/date differ), missing (pack gone),
    unknown (extracted before tw-patcher recorded where sources come from).
    Re-extract changed sources with: tw-patcher extract --refresh

    Examples:

        tw-patcher status
        tw-patcher status --json
    """
    sources_dir = settings.sources_dir
    statuses = source_statuses(ModIndex(sources_dir, settings.workspace_dir))
    counts = {state: sum(1 for s in statuses if s.state == state) for state in SOURCE_STATES}

    if as_json:
        emit_json(
            {
                "sources_dir": sources_dir,
                "sources": [
                    {
                        "name": s.name,
                        "path": s.path,
                        "state": s.state,
                        "pack": s.pack,
                        "workshop_id": (s.info or {}).get("workshop_id"),
                        "extracted_at": (s.info or {}).get("extracted_at"),
                    }
                    for s in statuses
                ],
                "summary": counts,
            }
        )
        return

    if not statuses:
        console.warning(f"No extracted sources in {sources_dir}")
        console.hint("Extract one: tw-patcher extract -s <mod.pack>")
        return

    console.header(f"Sources in {sources_dir} ({len(statuses)}):\n")
    for s in statuses:
        detail = f" — {s.pack}" if s.pack and s.state != "current" else ""
        console.item(f"{s.name}: {s.state} ({_NOTES[s.state]}){detail}")
    console.plain()
    console.plain("Summary: " + ", ".join(f"{counts[state]} {state}" for state in SOURCE_STATES))
    if counts["changed"]:
        console.hint("Re-extract changed sources: tw-patcher extract --refresh")
