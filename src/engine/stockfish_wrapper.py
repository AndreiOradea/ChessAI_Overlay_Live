from __future__ import annotations
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import chess
import chess.engine


@dataclass
class EngineLine:
    rank: int
    score_cp: Optional[int]
    score_mate: Optional[int]
    pv_san: List[str] = field(default_factory=list)
    pv_uci: List[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    fen: str
    lines: List[EngineLine] = field(default_factory=list)
    best_san: Optional[str] = None
    best_uci: Optional[str] = None
    evaluation: str = ""
    error: Optional[str] = None


class StockfishEngine:
    def __init__(self, path: str = ""):
        self.path = (path or "").strip()
        if not self.path or not os.path.isfile(self.path):
            self.path = self._find()
        self._eng = None

    def _find(self) -> str:
        home = Path.home()
        project = Path(__file__).resolve().parents[2]
        cwd = Path.cwd()
        candidates: List[str] = []

        for name in ("stockfish", "stockfish.exe"):
            w = shutil.which(name)
            if w:
                candidates.append(w)

        search_dirs = [
            cwd,
            cwd / "stockfish",
            project,
            project / "stockfish",
            project / "Stockfish",
            Path(r"C:\stockfish"),
            Path(r"C:\Stockfish"),
            home / "stockfish",
            home / "Desktop",
            home / "Desktop" / "stockfish",
            home / "Desktop" / "ChessAI_Board_LIVE",
            home / "Desktop" / "ChessAI_Board_LIVE" / "stockfish",
            home / "Desktop" / "ChessAI_Overlay_LIVE",
            home / "Desktop" / "ChessAI_Overlay_LIVE" / "stockfish",
            home / "Desktop" / "ChessAI_Overlay_LIVE" / "ChessAI_Overlay_LIVE" / "stockfish",
            home / "OneDrive" / "Desktop",
            home / "OneDrive" / "Desktop" / "stockfish",
            home / "Downloads",
            home / "OneDrive" / "Downloads",
        ]

        for d in search_dirs:
            if not d.is_dir():
                continue
            try:
                for f in d.iterdir():
                    n = f.name.lower()
                    if f.is_file() and "stockfish" in n and (n.endswith(".exe") or n == "stockfish"):
                        candidates.append(str(f.resolve()))
                for f in d.glob("**/stockfish*.exe"):
                    candidates.append(str(f.resolve()))
            except Exception:
                pass

        seen = set()
        for c in candidates:
            key = c.lower()
            if key in seen:
                continue
            seen.add(key)
            if os.path.isfile(c):
                print(f"[Stockfish] Found: {c}")
                return c
        print("[Stockfish] Not found in common locations")
        return ""

    @property
    def ready(self) -> bool:
        return self._eng is not None

    def start(self, threads=2, hash_mb=128) -> bool:
        if not self.path or not os.path.isfile(self.path):
            self.path = self._find()
        if not self.path:
            return False
        try:
            if self._eng is not None:
                return True
            self._eng = chess.engine.SimpleEngine.popen_uci(self.path)
            self._eng.configure({"Threads": max(1, int(threads)), "Hash": max(16, int(hash_mb))})
            print(f"[Stockfish] Started: {self.path}")
            return True
        except Exception as e:
            print(f"[Stockfish] Start failed: {e}")
            self._eng = None
            return False

    def stop(self):
        if self._eng:
            try:
                self._eng.quit()
            except Exception:
                pass
            self._eng = None

    def analyze(self, fen: str, depth=15, movetime_ms=800, multipv=3) -> AnalysisResult:
        if not self.ready:
            if not self.start():
                return AnalysisResult(fen=fen, error="Stockfish not found")
        try:
            board = chess.Board(fen)
        except Exception as e:
            return AnalysisResult(fen=fen, error=str(e))
        limit = chess.engine.Limit(time=max(0.1, movetime_ms / 1000.0), depth=depth)
        try:
            infos = self._eng.analyse(board, limit, multipv=multipv)
        except Exception as e:
            return AnalysisResult(fen=fen, error=str(e))
        if not isinstance(infos, list):
            infos = [infos]
        lines: List[EngineLine] = []
        for i, info in enumerate(infos):
            sc = info.get("score")
            if not sc:
                continue
            rel = sc.pov(board.turn)
            mate = rel.mate()
            cp = rel.score(mate_score=100000)
            pv = info.get("pv", [])
            tmp = board.copy()
            sans = []
            for m in pv:
                try:
                    sans.append(tmp.san(m))
                    tmp.push(m)
                except Exception:
                    break
            lines.append(EngineLine(
                rank=i + 1,
                score_cp=None if mate is not None else cp,
                score_mate=mate,
                pv_san=sans,
                pv_uci=[m.uci() for m in pv],
            ))

        def key(L: EngineLine):
            if L.score_mate is not None:
                return (2, 1000 - L.score_mate) if L.score_mate > 0 else (0, L.score_mate)
            return (1, L.score_cp or -99999)

        lines.sort(key=key, reverse=True)
        for i, L in enumerate(lines):
            L.rank = i + 1
        best_san = lines[0].pv_san[0] if lines and lines[0].pv_san else None
        best_uci = lines[0].pv_uci[0] if lines and lines[0].pv_uci else None
        ev = ""
        if lines:
            if lines[0].score_mate is not None:
                ev = f"M{lines[0].score_mate}"
            elif lines[0].score_cp is not None:
                ev = f"{lines[0].score_cp / 100:+.2f}"
        return AnalysisResult(fen=fen, lines=lines, best_san=best_san, best_uci=best_uci, evaluation=ev)
