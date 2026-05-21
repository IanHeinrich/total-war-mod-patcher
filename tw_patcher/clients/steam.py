from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import TypedDict


STEAM_API_URL = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
BATCH_SIZE = 100


class WorkshopDetails(TypedDict):
    name: str | None
    thumbnail_url: str | None
    cached_at: float


class SteamWorkshopClient:
    def __init__(self, cache_file: Path):
        self._cache_file = cache_file
        self._cache: dict[str, WorkshopDetails] = self._load_cache()

    def get_details(self, workshop_ids: list[str]) -> dict[str, WorkshopDetails]:
        stale_ids = [
            wid for wid in workshop_ids
            if wid not in self._cache or self._is_stale(self._cache[wid])
        ]

        if stale_ids:
            fetched = self._fetch_batch(stale_ids)
            self._cache.update(fetched)
            self._save_cache()

        return {wid: self._cache[wid] for wid in workshop_ids if wid in self._cache}

    def get_cached(self, workshop_ids: list[str]) -> dict[str, WorkshopDetails]:
        return {wid: self._cache[wid] for wid in workshop_ids if wid in self._cache}

    def _is_stale(self, entry: WorkshopDetails) -> bool:
        return time.time() - entry["cached_at"] > CACHE_TTL_SECONDS

    def _fetch_batch(self, ids: list[str]) -> dict[str, WorkshopDetails]:
        results: dict[str, WorkshopDetails] = {}
        for i in range(0, len(ids), BATCH_SIZE):
            batch = ids[i:i + BATCH_SIZE]
            results.update(self._fetch_chunk(batch))
        return results

    def _fetch_chunk(self, ids: list[str]) -> dict[str, WorkshopDetails]:
        results: dict[str, WorkshopDetails] = {}
        try:
            form_data = f"itemcount={len(ids)}"
            for idx, wid in enumerate(ids):
                form_data += f"&publishedfileids[{idx}]={wid}"

            req = urllib.request.Request(
                STEAM_API_URL,
                data=form_data.encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            now = time.time()
            for item in data.get("response", {}).get("publishedfiledetails", []):
                if item.get("result") != 1:
                    continue
                wid = str(item["publishedfileid"])
                results[wid] = WorkshopDetails(
                    name=item.get("title"),
                    thumbnail_url=item.get("preview_url"),
                    cached_at=now,
                )
        except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
            pass

        return results

    def _load_cache(self) -> dict[str, WorkshopDetails]:
        if not self._cache_file.exists():
            return {}
        try:
            data = json.loads(self._cache_file.read_text(encoding="utf-8"))
            return {k: WorkshopDetails(**v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError, TypeError):
            return {}

    def _save_cache(self) -> None:
        try:
            self._cache_file.write_text(
                json.dumps(self._cache, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
