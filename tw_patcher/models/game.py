from dataclasses import dataclass


@dataclass(frozen=True)
class GameDef:
    key: str
    display_name: str
    steam_app_id: int | None
    folder_name: str | None
    executable: str | None

    @property
    def header_image_url(self) -> str | None:
        if not self.steam_app_id:
            return None
        return f"https://cdn.akamai.steamstatic.com/steam/apps/{self.steam_app_id}/header.jpg"


GAMES: dict[str, GameDef] = {}

def _register(*defs: GameDef) -> None:
    for g in defs:
        GAMES[g.key] = g

_register(
    GameDef("pharaoh_dynasties", "Pharaoh Dynasties", 2951630, "Total War PHARAOH DYNASTIES", "Pharaoh.exe"),
    GameDef("pharaoh", "Pharaoh", 1937780, "Total War PHARAOH", "Pharaoh.exe"),
    GameDef("warhammer_3", "Warhammer 3", 1142710, "Total War WARHAMMER III", "Warhammer3.exe"),
    GameDef("troy", "Troy", None, None, None),
    GameDef("three_kingdoms", "Three Kingdoms", 779340, "Total War THREE KINGDOMS", "ThreeKingdoms.exe"),
    GameDef("warhammer_2", "Warhammer 2", 594570, "Total War WARHAMMER II", "TotalWarhammer2.exe"),
    GameDef("warhammer", "Warhammer", 364360, "Total War WARHAMMER", "TotalWarhammer.exe"),
    GameDef("thrones_of_britannia", "Thrones of Britannia", 712100, "Total War Saga Thrones of Britannia", "ThronesOfBritannia.exe"),
    GameDef("attila", "Attila", 325610, "Total War Attila", "Attila.exe"),
    GameDef("rome_2", "Rome 2", 214950, "Total War Rome II", "Rome2.exe"),
    GameDef("shogun_2", "Shogun 2", 34330, "Total War SHOGUN 2", "Shogun2.exe"),
    GameDef("napoleon", "Napoleon", 34030, "Napoleon Total War", "Napoleon.exe"),
    GameDef("empire", "Empire", 10500, "Empire Total War", "Empire.exe"),
    GameDef("arena", "Arena", None, None, None),
)

GAME_KEYS: list[str] = list(GAMES.keys())


def get_game(key: str) -> GameDef:
    if key not in GAMES:
        raise ValueError(f"Unknown game key: '{key}'. Valid keys: {', '.join(GAME_KEYS)}")
    return GAMES[key]
