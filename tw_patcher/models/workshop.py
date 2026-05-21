from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkshopMod:
    workshop_id: str
    pack_paths: list[Path] = field(default_factory=list)
    name: str | None = None
    thumbnail_url: str | None = None
