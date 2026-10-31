"""
Configuration management for ChessAI Overlay LIVE.
Stores user preferences, board regions, engine settings, etc.
"""

import json
import os
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, Tuple, List, Dict, Any


APP_NAME = "ChessAI Overlay LIVE"
APP_VERSION = "1.0.0"
CONFIG_DIR = Path.home() / ".chessai_overlay"
CONFIG_FILE = CONFIG_DIR / "config.json"
GAMES_DIR = CONFIG_DIR / "games"
LOGS_DIR = CONFIG_DIR / "logs"


@dataclass
class BoardRegion:
    """Screen region of the chessboard."""
    x: int = 0
    y: int = 0
    width: int = 400
    height: int = 400
    calibrated: bool = False

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def is_valid(self) -> bool:
        return self.width > 50 and self.height > 50


@dataclass
class OverlaySettings:
    """Overlay window appearance and behavior."""
    always_on_top: bool = True
    opacity: float = 0.92
    width: int = 320
    height: int = 480
    pos_x: int = 50
    pos_y: int = 50
    dark_theme: bool = True
    accent_color: str = "#9B59B6"  # Purple
    hotkey_toggle: str = "ctrl+shift+h"
    hotkey_calibrate: str = "ctrl+shift+c"
    capture_fps: float = 4.0  # Screen capture frequency
    auto_hide_on_fullscreen: bool = False


@dataclass
class EngineSettings:
    """Stockfish engine configuration (Training / Analysis only)."""
    path: str = ""  # Path to stockfish executable
    depth: int = 18
    movetime_ms: int = 1000
    threads: int = 2
    hash_mb: int = 128
    multipv: int = 3
    enabled: bool = True


@dataclass
class LiveModeSettings:
    """Fair-play LIVE mode options."""
    show_move_history: bool = True
    show_clock: bool = True
    show_legal_moves_highlight: bool = False  # Accessibility only
    show_personal_checklist: bool = True
    personal_checklist: List[str] = field(default_factory=lambda: [
        "Check for hanging pieces",
        "Look for checks / captures / threats",
        "King safety",
        "Pawn structure",
        "Development / activity"
    ])
    record_positions: bool = True
    warn_on_low_confidence: bool = True


@dataclass
class AppConfig:
    """Root configuration object."""
    board_region: BoardRegion = field(default_factory=BoardRegion)
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    engine: EngineSettings = field(default_factory=EngineSettings)
    live: LiveModeSettings = field(default_factory=LiveModeSettings)
    last_fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    board_orientation: str = "white"  # "white" or "black" at bottom
    mode: str = "LIVE"  # "LIVE" or "TRAINING" or "ANALYSIS"
    version: str = APP_VERSION


def ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    ensure_dirs()
    if not CONFIG_FILE.exists():
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _dict_to_config(data)
    except Exception as e:
        print(f"[Config] Failed to load config: {e}. Using defaults.")
        return AppConfig()


def save_config(cfg: AppConfig):
    ensure_dirs()
    data = _config_to_dict(cfg)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _config_to_dict(cfg: AppConfig) -> Dict[str, Any]:
    return {
        "board_region": asdict(cfg.board_region),
        "overlay": asdict(cfg.overlay),
        "engine": asdict(cfg.engine),
        "live": asdict(cfg.live),
        "last_fen": cfg.last_fen,
        "board_orientation": cfg.board_orientation,
        "mode": cfg.mode,
        "version": cfg.version,
    }


def _dict_to_config(data: Dict[str, Any]) -> AppConfig:
    cfg = AppConfig()
    if "board_region" in data:
        cfg.board_region = BoardRegion(**data["board_region"])
    if "overlay" in data:
        cfg.overlay = OverlaySettings(**data["overlay"])
    if "engine" in data:
        cfg.engine = EngineSettings(**data["engine"])
    if "live" in data:
        live_data = data["live"]
        # Handle list field carefully
        checklist = live_data.pop("personal_checklist", None)
        cfg.live = LiveModeSettings(**live_data)
        if checklist is not None:
            cfg.live.personal_checklist = checklist
    cfg.last_fen = data.get("last_fen", cfg.last_fen)
    cfg.board_orientation = data.get("board_orientation", cfg.board_orientation)
    cfg.mode = data.get("mode", cfg.mode)
    cfg.version = data.get("version", APP_VERSION)
    return cfg
