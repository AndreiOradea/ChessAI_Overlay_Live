"""
Stockfish UCI engine wrapper.

Used in:
  - TRAINING mode
  - ANALYSIS mode
  - LIVE ENGINE mode (authorized / offline / private games only)

Never used for move suggestions in the fair-play LIVE mode.
"""

from __future__ import annotations

import chess
import chess.engine
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import os
import shutil
from pathlib import Path


@dataclass
class EngineLine:
    rank: int
    score_cp: Optional[int]
    score_mate: Optional[int]
    pv_san: List[str]
    pv_uci: List[str]
    depth: int


@dataclass
class AnalysisResult:
    fen: str
    lines: List[EngineLine]
    best_move_san: Optional[str] = None
    best_move_uci: Optional[str] = None
    evaluation: str = ""  # human readable e.g. "+0.45" or "M3"
    error: Optional[str] = None


class StockfishEngine:
    """Thin, safe wrapper around python-chess engine API."""

    def __init__(self, engine_path: str = ""):
        self.engine_path = engine_path.strip() if engine_path else ""
        if not self.engine_path or not os.path.isfile(self.engine_path):
            self.engine_path = self._find_stockfish()
        self._engine: Optional[chess.engine.SimpleEngine] = None
        self._is_ready = False

    def _find_stockfish(self) -> str:
        """Search PATH, project folder, Desktop, Downloads, C:\\stockfish, etc."""
        candidates: List[str] = []

        # 1) PATH
        for name in ("stockfish", "stockfish.exe"):
            found = shutil.which(name)
            if found:
                candidates.append(found)

        home = Path.home()
        project_root = Path(__file__).resolve().parent.parent.parent
        cwd = Path.cwd()

        search_dirs = [
            cwd,
            cwd / "stockfish",
            project_root,
            project_root / "stockfish",
            project_root / "Stockfish",
            Path(r"C:\stockfish"),
            Path(r"C:\Stockfish"),
            home / "stockfish",
            home / "Desktop",
            home / "Desktop" / "ChessAI_Overlay_LIVE",
            home / "Desktop" / "ChessAI_Overlay_LIVE" / "stockfish",
            home / "Desktop" / "stockfish",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Desktop" / "ChessAI_Overlay_LIVE",
            home / "OneDrive" / "Desktop" / "ChessAI_Overlay_LIVE" / "stockfish",
            home / "OneDrive" / "Desktop" / "stockfish",
            home / "Downloads",
            home / "OneDrive" / "Downloads",
        ]

        def add_exe_from_dir(d: Path, depth: int = 0):
            if depth > 2 or not d.is_dir():
                return
            try:
                for f in d.iterdir():
                    try:
                        if f.is_file():
                            n = f.name.lower()
                            if n.startswith("stockfish") and n.endswith(".exe"):
                                candidates.append(str(f.resolve()))
                        elif f.is_dir() and depth < 2:
                            # common extract folders
                            if "stockfish" in f.name.lower() or depth == 0:
                                add_exe_from_dir(f, depth + 1)
                    except Exception:
                        continue
            except Exception:
                pass

        for d in search_dirs:
            add_exe_from_dir(d, 0)

        # Deduplicate while preserving order
        seen = set()
        for c in candidates:
            if not c:
                continue
            key = c.lower()
            if key in seen:
                continue
            seen.add(key)
            if os.path.isfile(c):
                return c

        return ""

    def start(self, threads: int = 2, hash_mb: int = 128) -> bool:
        # Re-scan if missing (user may have added the file after launch)
        if not self.engine_path or not os.path.isfile(self.engine_path):
            self.engine_path = self._find_stockfish()

        if not self.engine_path:
            print("[Stockfish] No executable found. Place stockfish*.exe in the project stockfish\\ folder.")
            return False

        try:
            self._engine = chess.engine.SimpleEngine.popen_uci(self.engine_path)
            self._engine.configure({
                "Threads": max(1, int(threads)),
                "Hash": max(16, int(hash_mb)),
            })
            self._is_ready = True
            print(f"[Stockfish] Started: {self.engine_path}")
            return True
        except Exception as e:
            print(f"[Stockfish] Failed to start ({self.engine_path}): {e}")
            self._is_ready = False
            self.engine_path = ""
            return False

    def stop(self):
        if self._engine is not None:
            try:
                self._engine.quit()
            except Exception:
                pass
            self._engine = None
            self._is_ready = False

    @property
    def is_ready(self) -> bool:
        return self._is_ready and self._engine is not None

    def analyze(
        self,
        fen: str,
        depth: int = 18,
        movetime_ms: Optional[int] = None,
        multipv: int = 3,
    ) -> AnalysisResult:
        if not self.is_ready:
            return AnalysisResult(fen=fen, lines=[], error="Engine not ready")

        try:
            board = chess.Board(fen)
        except Exception as e:
            return AnalysisResult(fen=fen, lines=[], error=f"Invalid FEN: {e}")

        # Prefer time limit for responsive LIVE updates; depth is a soft cap
        if movetime_ms is not None and movetime_ms > 0:
            limit = chess.engine.Limit(time=movetime_ms / 1000.0, depth=depth)
        else:
            limit = chess.engine.Limit(depth=depth)

        try:
            info_list = self._engine.analyse(
                board,
                limit,
                multipv=multipv,
                info=chess.engine.INFO_ALL,
            )
        except Exception as e:
            return AnalysisResult(fen=fen, lines=[], error=str(e))

        lines: List[EngineLine] = []
        # Score relative to the side that is about to move:
        # positive = good for the player to move (best choice = highest number)
        for i, info in enumerate(info_list):
            score = info.get("score")
            if score is None:
                continue
            score_obj = score.pov(board.turn)
            mate = score_obj.mate()
            cp = score_obj.score(mate_score=100000)

            pv = info.get("pv", [])
            pv_uci = [m.uci() for m in pv]
            temp = board.copy()
            pv_san = []
            for m in pv:
                try:
                    pv_san.append(temp.san(m))
                    temp.push(m)
                except Exception:
                    break

            lines.append(EngineLine(
                rank=i + 1,
                score_cp=cp if mate is None else None,
                score_mate=mate,
                pv_san=pv_san,
                pv_uci=pv_uci,
                depth=info.get("depth", depth),
            ))

        # Ensure best-first: highest score for side to move
        def _sort_key(line: EngineLine):
            if line.score_mate is not None:
                # Mate in N for us = very good (prefer smaller N); mated = very bad
                if line.score_mate > 0:
                    return (2, 1000 - line.score_mate)
                return (0, line.score_mate)  # negative mate = we get mated
            return (1, line.score_cp or -99999)

        lines.sort(key=_sort_key, reverse=True)
        for i, line in enumerate(lines):
            line.rank = i + 1

        best_san = lines[0].pv_san[0] if lines and lines[0].pv_san else None
        best_uci = lines[0].pv_uci[0] if lines and lines[0].pv_uci else None

        evaluation = ""
        if lines:
            if lines[0].score_mate is not None:
                evaluation = f"M{lines[0].score_mate}"
            elif lines[0].score_cp is not None:
                evaluation = f"{lines[0].score_cp / 100:+.2f}"

        return AnalysisResult(
            fen=fen,
            lines=lines,
            best_move_san=best_san,
            best_move_uci=best_uci,
            evaluation=evaluation,
        )

    def evaluate_simple(self, fen: str, depth: int = 15) -> str:
        res = self.analyze(fen, depth=depth, multipv=1)
        if res.error:
            return "Error"
        return res.evaluation or "?"
