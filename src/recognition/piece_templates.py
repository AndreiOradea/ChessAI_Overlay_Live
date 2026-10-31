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
CELL_MATCH_OFFSETS = (
    (-2, -2),
    (-2, 0),
    (-2, 2),
    (0, -2),
    (0, 2),
    (2, -2),
    (2, 0),
    (2, 2),
)


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


def _shape_mask(cell: np.ndarray) -> np.ndarray:
    if cell.ndim == 3:
        corners = np.concatenate(
            (
                cell[1:5, 1:5].reshape(-1, 3),
                cell[1:5, -5:].reshape(-1, 3),
                cell[-5:, 1:5].reshape(-1, 3),
                cell[-5:, -5:].reshape(-1, 3),
            )
        )
        background = np.median(corners, axis=0)
        foreground = (
            np.linalg.norm(cell.astype(np.float32) - background, axis=2) > 32
        ).astype(np.uint8)
    else:
        corners = np.concatenate(
            (
                cell[1:5, 1:5].ravel(),
                cell[1:5, -5:].ravel(),
                cell[-5:, 1:5].ravel(),
                cell[-5:, -5:].ravel(),
            )
        )
        background = np.median(corners)
        foreground = (
            np.abs(cell.astype(np.float32) - background) > 32
        ).astype(np.uint8)

    contours, _ = cv2.findContours(
        foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    contours = [contour for contour in contours if cv2.contourArea(contour) > 8]
    if not contours:
        return np.zeros((TEMPLATE_SIZE, TEMPLATE_SIZE), dtype=np.uint8)

    contour = max(contours, key=cv2.contourArea)
    x, y, width, height = cv2.boundingRect(contour)
    silhouette = np.zeros_like(foreground)
    cv2.drawContours(silhouette, [contour], -1, 1, thickness=cv2.FILLED)
    silhouette = silhouette[y : y + height, x : x + width]

    scale = min(32 / width, 36 / height)
    width = max(1, round(width * scale))
    height = max(1, round(height * scale))
    silhouette = cv2.resize(
        silhouette, (width, height), interpolation=cv2.INTER_NEAREST
    )
    normalized = np.zeros((TEMPLATE_SIZE, TEMPLATE_SIZE), dtype=np.uint8)
    normalized[38 - height : 38, 20 - width // 2 : 20 - width // 2 + width] = (
        silhouette
    )
    return normalized


def _shape_similarity(first: np.ndarray, second: np.ndarray) -> float:
    first_mask = first > 0
    second_mask = second > 0
    overlap = int(np.count_nonzero(first_mask & second_mask))
    total = int(np.count_nonzero(first_mask)) + int(np.count_nonzero(second_mask))
    return 2 * overlap / total if total else 0.0


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
            shape = _shape_mask(bgr_cell)
            shape_scores = {}
            for symbol, templates in self.templates.items():
                if symbol.isupper() != color:
                    continue
                score = max(
                    (self._score(cell, template) for template in templates),
                    default=-1.0,
                )
                scores[symbol.upper()] = max(scores.get(symbol.upper(), -1.0), score)
                shape_score = max(
                    (
                        _shape_similarity(shape, _shape_mask(template))
                        for template in templates
                    ),
                    default=-1.0,
                )
                shape_scores[symbol.upper()] = max(
                    shape_scores.get(symbol.upper(), -1.0), shape_score
                )
            ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
            shape_ranked = sorted(
                shape_scores.items(), key=lambda item: item[1], reverse=True
            )
            if not ranked or not shape_ranked:
                return None, 0.0
            best_type, best_score = ranked[0]
            second_score = ranked[1][1] if len(ranked) > 1 else -1.0
            template_confident = best_score >= 0.55 and best_score - second_score >= 0.04

            best_shape_type, best_shape_score = shape_ranked[0]
            second_shape_score = (
                shape_ranked[1][1] if len(shape_ranked) > 1 else -1.0
            )
            shape_confident = (
                best_shape_score >= 0.80
                and best_shape_score - second_shape_score >= 0.04
            )

            if (
                template_confident
                and shape_confident
                and best_type != best_shape_type
            ):
                return None, max(best_score, best_shape_score)
            if template_confident:
                symbol = best_type if color else best_type.lower()
                return symbol, max(best_score, best_shape_score)
            if shape_confident:
                shape_template_score = scores.get(best_shape_type, -1.0)
                if (
                    best_type != best_shape_type
                    and best_shape_score < 0.88
                    and best_score >= 0.35
                    and best_score - shape_template_score >= 0.10
                ):
                    symbol = best_type if color else best_type.lower()
                    return symbol, best_score
                symbol = best_shape_type if color else best_shape_type.lower()
                return symbol, best_shape_score
            return None, max(0.0, best_score, best_shape_score)

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

    def _classify_aligned_square(
        self, img: np.ndarray, row: int, col: int, color: bool
    ) -> Tuple[Optional[str], float]:
        cell = _cell(img, row, col)
        symbol, confidence = self.classify_square(cell, color=color)
        if symbol is not None:
            return symbol, confidence

        y = row * 50 + 5
        x = col * 50 + 5
        alternatives: Dict[str, float] = {}
        for dy, dx in CELL_MATCH_OFFSETS:
            candidate = img[
                y + dy : y + dy + TEMPLATE_SIZE,
                x + dx : x + dx + TEMPLATE_SIZE,
            ]
            candidate_symbol, candidate_confidence = self.classify_square(
                candidate, color=color
            )
            if candidate_symbol is not None:
                alternatives[candidate_symbol] = max(
                    alternatives.get(candidate_symbol, -1.0), candidate_confidence
                )

        ranked = sorted(alternatives.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return None, confidence
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.04:
            return None, ranked[0][1]
        return ranked[0]

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
                sym, sc = self._classify_aligned_square(
                    img, row, col, color=piece_color == 1
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
        if turn is not None:
            turn = bool(turn)
        pieces, avg = self.board_to_piece_map(bgr, orientation)
        occupancy = visual_occupancy(bgr)
        if occupancy is not None:
            occupied_count = int(np.count_nonzero(occupancy))
            if len(pieces) != occupied_count:
                unclassified = []
                for row, col in zip(*np.nonzero(occupancy)):
                    if orientation == "white":
                        square = chess.square(int(col), 7 - int(row))
                    else:
                        square = chess.square(7 - int(col), int(row))
                    if square not in pieces:
                        unclassified.append(chess.square_name(square))
                missed_squares = (
                    f" Check these squares: {', '.join(unclassified)}."
                    if unclassified
                    else ""
                )
                return (
                    None,
                    f"Piece recognition uncertain ({len(pieces)}/{occupied_count} pieces classified).{missed_squares} Keeping previous board.",
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
                board.turn = turn
                return (
                    None,
                    self._invalid_position_status(board),
                    False,
                )
            board.turn = turn
            turn_known = True
        elif len(valid_turns) == 1:
            board.turn = valid_turns[0]
            turn_known = True
        elif len(valid_turns) == 2:
            board.turn = chess.WHITE
            turn_known = False
        else:
            return None, self._invalid_position_status(board), False
        n = len(pieces)
        side = "White" if board.turn == chess.WHITE else "Black"
        turn_status = f"{side} to move" if turn_known else "side to move is ambiguous"
        return board, f"Templates: {n} pieces · conf {avg:.2f} · {turn_status}", turn_known

    @staticmethod
    def _invalid_position_status(board: chess.Board) -> str:
        reasons = (
            (chess.STATUS_NO_WHITE_KING, "missing white king"),
            (chess.STATUS_NO_BLACK_KING, "missing black king"),
            (chess.STATUS_TOO_MANY_KINGS, "too many kings"),
            (chess.STATUS_PAWNS_ON_BACKRANK, "pawn on a back rank"),
            (chess.STATUS_TOO_MANY_WHITE_PAWNS, "too many white pawns"),
            (chess.STATUS_TOO_MANY_BLACK_PAWNS, "too many black pawns"),
            (chess.STATUS_TOO_MANY_WHITE_PIECES, "too many white pieces"),
            (chess.STATUS_TOO_MANY_BLACK_PIECES, "too many black pieces"),
            (chess.STATUS_OPPOSITE_CHECK, "both kings are in check"),
            (chess.STATUS_IMPOSSIBLE_CHECK, "impossible check"),
            (chess.STATUS_TOO_MANY_CHECKERS, "king is attacked by multiple pieces"),
        )
        status = board.status()
        details = [label for flag, label in reasons if status & flag]
        reason = ", ".join(details) if details else "piece placement is illegal"
        return (
            f"Invalid position: recognized board has {reason}. "
            "Use Edit Position to correct the pieces; previous board kept."
        )
