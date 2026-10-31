"""
Chessboard detection and piece recognition using OpenCV.

Strategy:
1. User selects a screen region containing the board (manual).
2. Detect 8x8 grid via line detection / adaptive thresholding.
3. Classify each square (empty / piece type + color) using color histograms
   and simple template matching / dominant color analysis.
4. Output FEN and confidence score.
5. Support manual correction and orientation flip.

This is intentionally robust rather than perfect: when confidence is low
the UI asks the user to correct the position.
"""

from __future__ import annotations

import cv2
import numpy as np
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass
import chess


# Piece symbols for FEN
PIECE_SYMBOLS = {
    ("white", "pawn"): "P",
    ("white", "knight"): "N",
    ("white", "bishop"): "B",
    ("white", "rook"): "R",
    ("white", "queen"): "Q",
    ("white", "king"): "K",
    ("black", "pawn"): "p",
    ("black", "knight"): "n",
    ("black", "bishop"): "b",
    ("black", "rook"): "r",
    ("black", "queen"): "q",
    ("black", "king"): "k",
}


@dataclass
class DetectionResult:
    fen: str
    confidence: float          # 0.0 – 1.0
    board_image: Optional[np.ndarray] = None
    squares: Optional[List[List[str]]] = None  # 8x8 piece symbols or ""
    orientation: str = "white"  # side at bottom
    message: str = ""


class BoardDetector:
    """
    Detects chessboard position from a cropped board image.
    """

    def __init__(self):
        self.last_fen: Optional[str] = None
        self.last_squares: Optional[List[List[str]]] = None
        self.orientation: str = "white"
        # Simple color thresholds (can be calibrated later)
        self.light_square_threshold = 160
        self.dark_square_threshold = 100

    def set_orientation(self, orientation: str):
        if orientation in ("white", "black"):
            self.orientation = orientation

    def detect(self, board_bgr: np.ndarray) -> DetectionResult:
        """
        Main entry point.
        board_bgr: BGR image of the (approximately square) chessboard region.
        """
        if board_bgr is None or board_bgr.size == 0:
            return DetectionResult(
                fen=self.last_fen or chess.STARTING_FEN,
                confidence=0.0,
                message="No image provided"
            )

        h, w = board_bgr.shape[:2]
        if min(h, w) < 80:
            return DetectionResult(
                fen=self.last_fen or chess.STARTING_FEN,
                confidence=0.0,
                message="Board region too small"
            )

        # Make square
        size = min(h, w)
        board = board_bgr[:size, :size].copy()

        # Resize to a working resolution for stability
        work_size = 400
        board = cv2.resize(board, (work_size, work_size), interpolation=cv2.INTER_AREA)

        # Detect grid and extract squares
        squares_img = self._extract_squares(board)
        if squares_img is None:
            return DetectionResult(
                fen=self.last_fen or chess.STARTING_FEN,
                confidence=0.15,
                board_image=board,
                message="Could not extract 8x8 grid – try recalibrating region"
            )

        # Classify each square
        piece_grid, confidences = self._classify_squares(squares_img)
        avg_conf = float(np.mean(confidences)) if confidences else 0.0

        # Build FEN (rank 8 to rank 1)
        fen = self._grid_to_fen(piece_grid)

        # Basic validation with python-chess
        try:
            board_obj = chess.Board(fen)
            # If invalid, fall back to last known
            if not board_obj.is_valid():
                fen = self.last_fen or chess.STARTING_FEN
                avg_conf *= 0.5
        except Exception:
            fen = self.last_fen or chess.STARTING_FEN
            avg_conf *= 0.4

        self.last_fen = fen
        self.last_squares = piece_grid

        msg = "OK" if avg_conf > 0.65 else "Low confidence – verify position"
        return DetectionResult(
            fen=fen,
            confidence=avg_conf,
            board_image=board,
            squares=piece_grid,
            orientation=self.orientation,
            message=msg
        )

    def _extract_squares(self, board: np.ndarray) -> Optional[List[List[np.ndarray]]]:
        """Split board image into 8x8 square images."""
        h, w = board.shape[:2]
        sq_h = h // 8
        sq_w = w // 8
        squares = []
        for r in range(8):
            row = []
            for c in range(8):
                y1 = r * sq_h
                x1 = c * sq_w
                sq = board[y1:y1 + sq_h, x1:x1 + sq_w]
                row.append(sq)
            squares.append(row)
        return squares

    def _classify_squares(self, squares: List[List[np.ndarray]]) -> Tuple[List[List[str]], List[float]]:
        """
        Classify each square.
        Returns 8x8 list of FEN symbols ("" for empty) and list of confidences.
        """
        grid = []
        confs = []
        for r in range(8):
            row = []
            for c in range(8):
                symbol, conf = self._classify_single_square(squares[r][c], r, c)
                row.append(symbol)
                confs.append(conf)
            grid.append(row)
        return grid, confs

    def _classify_single_square(self, sq: np.ndarray, rank: int, file: int) -> Tuple[str, float]:
        """
        Heuristic classification of a single square.
        Uses brightness, saturation and simple shape cues.
        This is deliberately conservative – better to mark empty than invent pieces.
        """
        if sq is None or sq.size == 0:
            return "", 0.3

        # Convert to HSV and grayscale
        hsv = cv2.cvtColor(sq, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(sq, cv2.COLOR_BGR2GRAY)

        # Average brightness and saturation
        mean_val = float(np.mean(gray))
        mean_sat = float(np.mean(hsv[:, :, 1]))
        std_val = float(np.std(gray))

        # Empty squares tend to be more uniform
        is_likely_empty = std_val < 28 and mean_sat < 45

        if is_likely_empty:
            return "", 0.75

        # Piece present – try to decide color and type
        # White pieces are brighter overall
        is_white = mean_val > 140

        # Very rough type estimation via contour area / aspect
        # (This is a placeholder; real systems use CNNs or template matching)
        piece_type = self._guess_piece_type(gray, std_val)

        color = "white" if is_white else "black"
        symbol = PIECE_SYMBOLS.get((color, piece_type), "")

        # Confidence is lower because type guessing is crude
        conf = 0.55 if symbol else 0.35
        return symbol, conf

    def _guess_piece_type(self, gray: np.ndarray, std_val: float) -> str:
        """
        Extremely simplified piece type guesser.
        In production this should be replaced by a trained classifier or templates.
        """
        # Edge density as a proxy for complexity
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.count_nonzero(edges) / edges.size

        if edge_density < 0.06:
            return "pawn"
        elif edge_density < 0.10:
            return "knight" if std_val > 40 else "bishop"
        elif edge_density < 0.14:
            return "rook"
        elif edge_density < 0.18:
            return "queen"
        else:
            return "king"

    def _grid_to_fen(self, grid: List[List[str]]) -> str:
        """Convert 8x8 symbol grid to FEN piece placement (ranks 8→1)."""
        fen_rows = []
        for r in range(8):
            empty = 0
            row_str = ""
            for c in range(8):
                sym = grid[r][c]
                if not sym:
                    empty += 1
                else:
                    if empty:
                        row_str += str(empty)
                        empty = 0
                    row_str += sym
            if empty:
                row_str += str(empty)
            fen_rows.append(row_str)

        # Orientation: if black is at bottom, the grid is already inverted visually
        # but we still output standard FEN (white at bottom of string = rank 1)
        if self.orientation == "black":
            # Reverse ranks and mirror files
            fen_rows = [row[::-1] for row in reversed(fen_rows)]

        placement = "/".join(fen_rows)
        # Default side to move, castling, etc. – will be refined by tracker
        return f"{placement} w KQkq - 0 1"

    def force_fen(self, fen: str):
        """Manually set the current position (user correction)."""
        try:
            b = chess.Board(fen)
            self.last_fen = b.fen()
        except Exception:
            pass


def create_empty_board_image(size: int = 400) -> np.ndarray:
    """Utility: generate a simple empty board for testing."""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    sq = size // 8
    for r in range(8):
        for c in range(8):
            color = (240, 217, 181) if (r + c) % 2 == 0 else (181, 136, 99)
            cv2.rectangle(img, (c * sq, r * sq), ((c + 1) * sq, (r + 1) * sq), color, -1)
    return img
