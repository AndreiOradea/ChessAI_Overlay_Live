from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

APP_NAME = "ChessAI Board LIVE"
CONFIG_DIR = Path.home() / ".chessai_board_live"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class BoardRegion:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    calibrated: bool = False


@dataclass
class EngineSettings:
    path: str = ""
    depth: int = 15
    movetime_ms: int = 800
    threads: int = 2
    hash_mb: int = 128


@dataclass
class AppConfig:
    mode: str = "LIVE ENGINE"  # LIVE | LIVE ENGINE
    my_color: str = "white"
    board_orientation: str = "white"
    board_region: BoardRegion = field(default_factory=BoardRegion)
    engine: EngineSettings = field(default_factory=EngineSettings)
    opacity: float = 0.95
    theme: str = "Midnight"
    accent: str = "Violet"
    custom_accent: str = ""
    background_image: str = ""
    background_opacity: int = 100
    background_tint: int = 60
    background_blur: int = 0
    background_fit: str = "Fill"
    show_coordinates: bool = True
    always_on_top: bool = True
    multipv: int = 3
    pos_x: int = 80
    pos_y: int = 80


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        return AppConfig()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        br = data.get("board_region", {})
        eng = data.get("engine", {})
        return AppConfig(
            mode=data.get("mode", "LIVE ENGINE"),
            my_color=data.get("my_color", "white"),
            board_orientation=data.get("board_orientation", "white"),
            board_region=BoardRegion(**{**BoardRegion().__dict__, **br}),
            engine=EngineSettings(**{**EngineSettings().__dict__, **eng}),
            opacity=float(data.get("opacity", 0.95)),
            theme=data.get("theme", "Midnight"),
            accent=data.get("accent", "Violet"),
            custom_accent=str(data.get("custom_accent", "")),
            background_image=str(data.get("background_image", "")),
            background_opacity=max(
                0, min(100, int(data.get("background_opacity", 100)))
            ),
            background_tint=max(
                0, min(100, int(data.get("background_tint", 60)))
            ),
            background_blur=max(
                0, min(30, int(data.get("background_blur", 0)))
            ),
            background_fit=data.get("background_fit", "Fill"),
            show_coordinates=bool(data.get("show_coordinates", True)),
            always_on_top=bool(data.get("always_on_top", True)),
            multipv=max(1, min(5, int(data.get("multipv", 3)))),
            pos_x=int(data.get("pos_x", 80)),
            pos_y=int(data.get("pos_y", 80)),
        )
    except Exception:
        return AppConfig()


def save_config(cfg: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
