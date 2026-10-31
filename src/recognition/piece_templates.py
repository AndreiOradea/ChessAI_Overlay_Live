"""
Template-based piece recognition for Chess.com Classic on green boards.

1) User selects board region at the STARTING position.
2) We crop the 12 piece types from known start squares + empty samples.
3) On Analyze / scan, each of 64 squares is matched to the best template → FEN.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import numpy as np
import chess
from src.recognition.move_diff import visual_occupancy

try:
    import cv2
except ImportError:
    cv2 = None

# Starting-square → piece symbol (FEN char). orientation = white at bottom.
START_PIECES_WHITE_BOTTOM = {
    (7, 0): "R", (7, 1): "N", (7, 2): "B", (7, 3): "Q",
    (7, 4): "K", (7, 5): "B", (7, 6): "N", (7, 7): "R",
    (6, 0): "P", (6, 1): "P", (6, 2): "P", (6, 3): "P",
    (6, 4): "P", (6, 5): "P", (6, 6): "P", (6, 7): "P",
    (1, 0): "p", (1, 1): "p", (1, 2): "p", (1, 3): "p",
    (1, 4): "p", (1, 5): "p", (1, 6): "p", (1, 7): "p",
    (0, 0): "r", (0, 1): "n", (0, 2): "b", (0, 3): "q",
    (0, 4): "k", (0, 5): "b", (0, 6): "n", (0, 7): "r",
}

TEMPLATE_SIZE = 40
STORE = Path.home() / ".chessai_board_live" / "templates"


def _board400(bgr: np.ndarray) -> np.ndarray:
    h, w = bgr.shape[:2]
    s = min(h, w)
    img = bgr[:s, :s]
    return cv2.resize(img, (400, 400), interpolation=cv2.INTER_AREA)


def _cell(img400: np.ndarray, row: int, col: int) -> np.ndarray:
    y1, x1 = row * 50 + 5, col * 50 + 5
    patch = img400[y1 : y1 + 40, x1 : x1 + 40]
    if patch.shape[0] != TEMPLATE_SIZE or patch.shape[1] != TEMPLATE_SIZE:
        patch = cv2.resize(patch, (TEMPLATE_SIZE, TEMPLATE_SIZE))
    return patch


def _gray_norm(bgr_cell: np.ndarray) -> np.ndarray:
    g = cv2.cvtColor(bgr_cell, cv2.COLOR_BGR2GRAY)
    g = cv2.equalizeHist(g)
    return g


class PieceTemplateMatcher:
    def __init__(self):
        # symbol -> list of gray templates
        self.templates: Dict[str, List[np.ndarray]] = {}
        self.empty: List[np.ndarray] = []
        self.ready = False
        self._load()

    def _load(self):
        if cv2 is None:
            return
        meta = STORE / "meta.json"
        if not meta.exists():
            return
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            if data.get("schema_version") != 2:
                return
            self.templates = {}
            for sym, files in data.get("pieces", {}).items():
                self.templates[sym] = []
                for f in files:
                    p = STORE / f
                    if p.exists():
                        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                        if img is not None:
                            self.templates[sym].append(img)
            self.empty = []
            for f in data.get("empty", []):
                p = STORE / f
                if p.exists():
                    img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                    if img is not None:
                        self.empty.append(img)
            self.ready = bool(self.empty) and all(
                self.templates.get(sym) for sym in "PNBRQKpnbrqk"
            )
        except Exception as e:
            print(f"[templates] load failed: {e}")

    def save(self):
        STORE.mkdir(parents=True, exist_ok=True)
        meta = {"schema_version": 2, "pieces": {}, "empty": []}
        for sym, imgs in self.templates.items():
            meta["pieces"][sym] = []
            for i, img in enumerate(imgs):
                name = f"{sym}_{i}.png"
                cv2.imwrite(str(STORE / name), img)
                meta["pieces"][sym].append(name)
        for i, img in enumerate(self.empty):
            name = f"empty_{i}.png"
            cv2.imwrite(str(STORE / name), img)
            meta["empty"].append(name)
        (STORE / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    def learn_from_start_position(self, bgr: np.ndarray, orientation: str = "white") -> str:
        """
        Call when the selected region shows the starting position.
        Extracts templates for all 12 piece types + empty squares.
        """
        if cv2 is None or bgr is None:
            return "OpenCV/image missing"
        img = _board400(bgr)
        self.templates = {s: [] for s in "PNBRQKpnbrqk"}
        self.empty = []

        # Map display row/col → piece depending on orientation
        for row in range(8):
            for col in range(8):
                if orientation == "white":
                    key = (row, col)
                else:
                    key = (7 - row, 7 - col)
                cell = _gray_norm(_cell(img, row, col))
                sym = START_PIECES_WHITE_BOTTOM.get(key)
                if sym:
                    self.templates[sym].append(cell)
                else:
                    self.empty.append(cell)

        # Keep max 2 samples per piece / 4 empties
        for sym in list(self.templates.keys()):
            self.templates[sym] = self.templates[sym][:2]
        self.empty = self.empty[:4]
        self.ready = True
        self.save()
        n = sum(len(v) for v in self.templates.values())
        return f"Learned {n} piece templates + {len(self.empty)} empty (Classic)"

    def _score(self, cell: np.ndarray, tmpl: np.ndarray) -> float:
        if cell.shape != tmpl.shape:
            cell = cv2.resize(cell, (tmpl.shape[1], tmpl.shape[0]))
        if float(cell.std()) < 1.0 or float(tmpl.std()) < 1.0:
            difference = np.abs(cell.astype(np.float32) - tmpl.astype(np.float32))
            return 1.0 - float(difference.mean()) / 255.0
        r = cv2.matchTemplate(cell, tmpl, cv2.TM_CCOEFF_NORMED)
        return float(r.max())

    def classify_square(
        self, bgr_cell: np.ndarray, color: Optional[bool] = None
    ) -> Tuple[Optional[str], float]:
        """Return (fen_char or None if empty, confidence)."""
        if not self.ready:
            return None, 0.0
        cell = _gray_norm(bgr_cell)
        if color is not None:
            scores = {}
            for symbol, templates in self.templates.items():
                if symbol.isupper() != color:
                    continue
                score = max(
                    (self._score(cell, template) for template in templates),
                    default=-1.0,
                )
                scores[symbol.upper()] = max(scores.get(symbol.upper(), -1.0), score)
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            if not ranked:
                return None, 0.0
            best_type, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else -1.0
            if best_score < 0.55 or best_score - second_score < 0.04:
                return None, max(0.0, best_score)
            symbol = best_type if color else best_type.lower()
            return symbol, best_score

        best_sym = None
        best_sc = -1.0
        for sym, tmpls in self.templates.items():
            for tmpl in tmpls:
                sc = self._score(cell, tmpl)
                if sc > best_sc:
                    best_sc = sc
                    best_sym = sym
        empty_sc = -1.0
        for tmpl in self.empty:
            empty_sc = max(empty_sc, self._score(cell, tmpl))
        # Empty if empty template clearly wins
        if empty_sc >= 0.60 and empty_sc >= best_sc + 0.05:
            return None, empty_sc
        # Piece only if strong match
        if best_sc >= 0.62 and best_sc >= empty_sc + 0.03:
            return best_sym, best_sc
        if best_sc >= 0.70:
            return best_sym, best_sc
        # Default empty when unsure (better than filling board with knights)
        return None, max(best_sc, empty_sc)

    def board_to_piece_map(
        self, bgr: np.ndarray, orientation: str = "white"
    ) -> Tuple[Dict[chess.Square, str], float]:
        """
        Scan 64 squares → {square: fen_char}.
        Returns map + average confidence.
        """
        if cv2 is None or bgr is None or not self.ready:
            return {}, 0.0
        img = _board400(bgr)
        occupancy = visual_occupancy(bgr)
        if occupancy is None:
            return {}, 0.0
        result: Dict[chess.Square, str] = {}
        scores = []
        for row in range(8):
            for col in range(8):
                piece_color = int(occupancy[row, col])
                if piece_color == 0:
                    continue
                cell = _cell(img, row, col)
                sym, sc = self.classify_square(
                    cell, color=piece_color == 1
                )
                scores.append(sc)
                if orientation == "white":
                    sq = chess.square(col, 7 - row)
                else:
                    sq = chess.square(7 - col, row)
                if sym:
                    result[sq] = sym
        avg = float(np.mean(scores)) if scores else 0.0
        return result, avg

    def to_board(
        self, bgr: np.ndarray, orientation: str = "white", turn: Optional[bool] = None
    ) -> Tuple[Optional[chess.Board], str, bool]:
        """
        Build a chess.Board from screenshot via templates.
        Returns the board, status, and whether its side to move is known.
        An ambiguous turn uses White only as a placeholder; callers must not
        treat that placeholder as a detected turn.
        """
        if not self.ready:
            return None, "No verified templates – select region at the starting position", False
        pieces, avg = self.board_to_piece_map(bgr, orientation)
        occupancy = visual_occupancy(bgr)
        if occupancy is not None:
            occupied_count = int(np.count_nonzero(occupancy))
            if len(pieces) != occupied_count:
                return (
                    None,
                    f"Piece recognition uncertain ({len(pieces)}/{occupied_count} pieces classified) – keeping previous board",
                    False,
                )
        n = len(pieces)
        if n < 8:
            return None, f"Too few pieces ({n}) – not applying", False
        if n > 32:
            return None, f"Impossible piece count ({n}) – not applying (re-learn templates at START)", False
        if avg < 0.50:
            return None, f"Low confidence ({avg:.2f}) – not applying", False
        # Reject if one piece type dominates (classic broken-template symptom)
        from collections import Counter
        counts = Counter(pieces.values())
        for sym, cnt in counts.items():
            limit = 8 if sym.lower() == "p" else 2
            if sym.lower() == "p":
                limit = 8
            elif sym.lower() in ("n", "b", "r"):
                limit = 2
            else:
                limit = 1
            # allow a bit of noise
            if cnt > limit + 2:
                return None, f"Bad read: too many '{sym}' ({cnt}) – re-learn at START position", False
        board = chess.Board(None)
        board.clear_board()
        for sq, sym in pieces.items():
            board.set_piece_at(sq, chess.Piece.from_symbol(sym))
        # Clear castling if kings/rooks moved from start – simple check
        board.castling_rights = 0
        if board.piece_at(chess.E1) == chess.Piece.from_symbol("K"):
            if board.piece_at(chess.H1) == chess.Piece.from_symbol("R"):
                board.castling_rights |= chess.BB_H1
            if board.piece_at(chess.A1) == chess.Piece.from_symbol("R"):
                board.castling_rights |= chess.BB_A1
        if board.piece_at(chess.E8) == chess.Piece.from_symbol("k"):
            if board.piece_at(chess.H8) == chess.Piece.from_symbol("r"):
                board.castling_rights |= chess.BB_H8
            if board.piece_at(chess.A8) == chess.Piece.from_symbol("r"):
                board.castling_rights |= chess.BB_A8
        valid_turns = []
        for candidate_turn in (chess.WHITE, chess.BLACK):
            board.turn = candidate_turn
            if board.is_valid():
                valid_turns.append(candidate_turn)
        if turn is not None:
            if turn not in valid_turns:
                return None, "Invalid position detected – keeping previous board", False
            board.turn = turn
            turn_known = True
        elif len(valid_turns) == 1:
            board.turn = valid_turns[0]
            turn_known = True
        elif len(valid_turns) == 2:
            board.turn = chess.WHITE
            turn_known = False
        else:
            return None, "Invalid position detected – keeping previous board", False
        n = len(pieces)
        side = "White" if board.turn == chess.WHITE else "Black"
        turn_status = f"{side} to move" if turn_known else "side to move is ambiguous"
        return board, f"Templates: {n} pieces · conf {avg:.2f} · {turn_status}", turn_known
