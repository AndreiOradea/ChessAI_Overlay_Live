"""
Move detection with STABILITY confirmation.

A move is accepted only after the visual board stays unchanged
for several frames (piece dropped / animation finished).
This avoids false moves while the user is still dragging.
"""

from __future__ import annotations

from typing import Optional, List, Tuple
import numpy as np
import chess

try:
    import cv2
except ImportError:
    cv2 = None

EMPTY, WHITE, BLACK = 0, 1, 2

# Frames the board must stay identical before we accept a move
STABLE_FRAMES_REQUIRED = 2
PIECE_COLOR_LUMINANCE_THRESHOLD = 60


class MoveDiffTracker:
    def __init__(self):
        self.orientation = "white"
        self._prev_vis = None
        self._stable_vis = None
        self._stable_count = 0
        self._cooldown = 0
        self._pending_move: Optional[chess.Move] = None
        self._pending_count = 0

    def set_orientation(self, o: str):
        if o in ("white", "black"):
            self.orientation = o

    def reset(self):
        self._prev_vis = None
        self._stable_vis = None
        self._stable_count = 0
        self._cooldown = 0
        self._pending_move = None
        self._pending_count = 0

    def force_snapshot(self, bgr):
        if bgr is None or cv2 is None:
            self.reset()
            return
        g = self._visual_grid(bgr)
        self._prev_vis = g
        self._stable_vis = g.copy()
        self._stable_count = STABLE_FRAMES_REQUIRED
        self._cooldown = 0
        self._pending_move = None
        self._pending_count = 0

    def _bgr400(self, bgr):
        h, w = bgr.shape[:2]
        s = min(h, w)
        return cv2.resize(bgr[:s, :s], (400, 400), interpolation=cv2.INTER_AREA)

    def _sq_to_rc(self, sq: chess.Square) -> Tuple[int, int]:
        f, r = chess.square_file(sq), chess.square_rank(sq)
        if self.orientation == "white":
            return 7 - r, f
        return r, 7 - f

    def _classify_square(self, bgr, r: int, c: int) -> int:
        y1, x1 = r * 50, c * 50
        square = bgr[y1 : y1 + 50, x1 : x1 + 50]
        if square.shape[:2] != (50, 50):
            return EMPTY

        corners = np.concatenate(
            (
                square[3:10, 3:10].reshape(-1, 3),
                square[3:10, 40:47].reshape(-1, 3),
                square[40:47, 3:10].reshape(-1, 3),
                square[40:47, 40:47].reshape(-1, 3),
            )
        )
        background = np.median(corners, axis=0)
        center = square[8:42, 8:42]
        foreground = np.linalg.norm(center.astype(np.float32) - background, axis=2) > 32
        blue, green, red = cv2.split(square)
        yellow_highlight = (
            (red > 170)
            & (green > 170)
            & (red.astype(np.int16) - blue.astype(np.int16) > 55)
            & (green.astype(np.int16) - blue.astype(np.int16) > 55)
        )
        foreground &= ~yellow_highlight[8:42, 8:42]
        if float(np.mean(foreground)) < 0.12:
            return EMPTY

        center_gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
        piece_luminance = float(np.median(center_gray[foreground]))
        return WHITE if piece_luminance >= PIECE_COLOR_LUMINANCE_THRESHOLD else BLACK

    def _visual_grid(self, bgr) -> np.ndarray:
        b = self._bgr400(bgr)
        grid = np.zeros((8, 8), np.int32)
        for r in range(8):
            for c in range(8):
                grid[r, c] = self._classify_square(b, r, c)
        return grid

    def _expected_grid(self, board: chess.Board) -> np.ndarray:
        grid = np.zeros((8, 8), np.int32)
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            r, c = self._sq_to_rc(sq)
            if piece is None:
                grid[r, c] = EMPTY
            elif piece.color == chess.WHITE:
                grid[r, c] = WHITE
            else:
                grid[r, c] = BLACK
        return grid

    def _find_candidate(self, vis: np.ndarray, board: chess.Board) -> Optional[chess.Move]:
        exp = self._expected_grid(board)
        baseline = self._prev_vis if self._prev_vis is not None else exp
        observed_changes = baseline != vis
        if not np.any(observed_changes):
            return None

        candidates: List[Tuple[int, chess.Move]] = []
        for move in board.legal_moves:
            after = board.copy(stack=False)
            after.push(move)
            after_grid = self._expected_grid(after)
            expected_changes = exp != after_grid
            missing = int(np.count_nonzero(expected_changes & ~observed_changes))
            extra = int(np.count_nonzero(observed_changes & ~expected_changes))
            if missing == 0 and extra <= 1:
                if np.all(vis[expected_changes] == after_grid[expected_changes]):
                    candidates.append((extra, move))

        if not candidates:
            return None

        candidates.sort(key=lambda candidate: candidate[0])
        best_difference = candidates[0][0]
        best_moves = [move for difference, move in candidates if difference == best_difference]
        return best_moves[0] if len(best_moves) == 1 else None

    def detect_move(self, bgr, board: chess.Board, mean_thr=12.0, edge_thr=0.04) -> Optional[chess.Move]:
        """
        Returns a move only when:
        - a legal move matches the visual board, AND
        - the same visual state (and same candidate move) is seen for STABLE_FRAMES_REQUIRED frames.
        """
        if bgr is None or cv2 is None:
            return None
        if self._cooldown > 0:
            self._cooldown -= 1
            return None

        vis = self._visual_grid(bgr)
        if self._prev_vis is None:
            self._prev_vis = vis.copy()
            self._stable_vis = vis.copy()
            self._stable_count = 1
            return None

        # Track visual stability
        if self._stable_vis is not None and np.array_equal(vis, self._stable_vis):
            self._stable_count += 1
        else:
            self._stable_vis = vis.copy()
            self._stable_count = 1
            # Board still moving (drag / animation) – clear pending
            self._pending_move = None
            self._pending_count = 0
            return None

        # Not stable long enough yet
        if self._stable_count < STABLE_FRAMES_REQUIRED:
            return None

        # Board is stable – try to read a move
        candidate = self._find_candidate(vis, board)
        if candidate is None:
            self._prev_vis = vis
            self._pending_move = None
            self._pending_count = 0
            return None

        # Same candidate must repeat while stable
        if self._pending_move is not None and self._pending_move == candidate:
            self._pending_count += 1
        else:
            self._pending_move = candidate
            self._pending_count = 1

        # Need the move hypothesis confirmed on consecutive stable reads
        if self._pending_count < STABLE_FRAMES_REQUIRED:
            return None

        # Accept move
        self._prev_vis = vis
        self._cooldown = 1  # brief ignore after accept
        self._pending_move = None
        self._pending_count = 0
        self._stable_count = 0
        return candidate


def visual_occupancy(bgr) -> Optional[np.ndarray]:
    if bgr is None or cv2 is None:
        return None
    return MoveDiffTracker()._visual_grid(bgr)


def highlighted_last_move(
    bgr, orientation: str = "white"
) -> Optional[Tuple[chess.Move, bool]]:
    """Return a highlighted move and inferred side to move when unambiguous."""
    if bgr is None or cv2 is None or orientation not in ("white", "black"):
        return None

    detector = MoveDiffTracker()
    image = detector._bgr400(bgr)
    highlighted = []
    for row in range(8):
        for col in range(8):
            square = image[row * 50 : (row + 1) * 50, col * 50 : (col + 1) * 50]
            blue, green, red = cv2.split(square)
            yellow = (
                (red > 170)
                & (green > 170)
                & (red.astype(np.int16) - blue.astype(np.int16) > 55)
                & (green.astype(np.int16) - blue.astype(np.int16) > 55)
            )
            if float(np.mean(yellow)) >= 0.30:
                highlighted.append((row, col))

    if len(highlighted) != 2:
        return None

    occupancy = detector._visual_grid(bgr)
    empty_squares = [square for square in highlighted if occupancy[square] == EMPTY]
    occupied_squares = [
        square for square in highlighted if occupancy[square] in (WHITE, BLACK)
    ]
    if len(empty_squares) != 1 or len(occupied_squares) != 1:
        return None

    def to_square(position: Tuple[int, int]) -> chess.Square:
        row, col = position
        if orientation == "white":
            return chess.square(col, 7 - row)
        return chess.square(7 - col, row)

    source = to_square(empty_squares[0])
    target = to_square(occupied_squares[0])
    target_color = occupancy[occupied_squares[0]]
    side_to_move = bool(target_color == BLACK)
    return chess.Move(source, target), side_to_move
