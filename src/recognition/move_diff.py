"""
Move detection: square-change + legal move match.
Special handling for opening double-pawn pushes (d2-d4, d7-d5, e2-e4, e7-e5)
so they are not mistaken for one-square steps (d3/e3).
"""

from __future__ import annotations

from typing import Optional, List, Set, Tuple
import numpy as np
import cv2
import chess


class MoveDiffTracker:
    def __init__(self):
        self._prev_sig: Optional[np.ndarray] = None
        self.orientation: str = "white"
        self._cooldown: int = 0

    def set_orientation(self, orientation: str):
        if orientation in ("white", "black"):
            self.orientation = orientation

    def reset(self):
        self._prev_sig = None
        self._cooldown = 0

    def _prepare_gray(self, bgr: np.ndarray) -> np.ndarray:
        h, w = bgr.shape[:2]
        size = min(h, w)
        g = cv2.cvtColor(bgr[:size, :size], cv2.COLOR_BGR2GRAY)
        return cv2.resize(g, (400, 400), interpolation=cv2.INTER_AREA)

    def _signatures(self, gray400: np.ndarray) -> np.ndarray:
        edges = cv2.Canny(gray400, 25, 80)
        sig = np.zeros((8, 8, 2), dtype=np.float32)
        sq, m = 50, 4
        for r in range(8):
            for c in range(8):
                y1, x1 = r * sq + m, c * sq + m
                y2, x2 = (r + 1) * sq - m, (c + 1) * sq - m
                patch = gray400[y1:y2, x1:x2]
                ep = edges[y1:y2, x1:x2]
                sig[r, c, 0] = float(np.mean(patch))
                sig[r, c, 1] = float(np.count_nonzero(ep)) / max(ep.size, 1)
        return sig

    def _rc_to_sq(self, r: int, c: int) -> chess.Square:
        if self.orientation == "white":
            return chess.square(c, 7 - r)
        return chess.square(7 - c, r)

    def force_snapshot(self, board_bgr: np.ndarray):
        if board_bgr is None:
            self.reset()
            return
        self._prev_sig = self._signatures(self._prepare_gray(board_bgr))
        self._cooldown = 0

    def detect_move(
        self,
        board_bgr: np.ndarray,
        board: chess.Board,
        mean_thr: float = 8.0,
        edge_thr: float = 0.025,
    ) -> Optional[chess.Move]:
        if board_bgr is None or board_bgr.size == 0:
            return None

        if self._cooldown > 0:
            self._cooldown -= 1
            return None

        gray = self._prepare_gray(board_bgr)
        cur = self._signatures(gray)

        if self._prev_sig is None:
            self._prev_sig = cur
            return None

        prev = self._prev_sig
        changed: List[Tuple[int, int, float]] = []
        for r in range(8):
            for c in range(8):
                dm = abs(float(cur[r, c, 0] - prev[r, c, 0]))
                de = abs(float(cur[r, c, 1] - prev[r, c, 1]))
                if dm >= mean_thr or de >= edge_thr:
                    strength = dm / 40.0 + de * 8.0
                    changed.append((r, c, strength))

        if not changed:
            return None
        if len(changed) > 12:
            self._prev_sig = cur
            return None

        changed_sqs: Set[chess.Square] = {self._rc_to_sq(r, c) for r, c, _ in changed}
        strength_map = {self._rc_to_sq(r, c): s for r, c, s in changed}

        scored: List[Tuple[float, chess.Move]] = []
        for move in board.legal_moves:
            frm, to = move.from_square, move.to_square
            if frm not in changed_sqs:
                continue

            score = 2.0 + strength_map.get(frm, 0)

            if to in changed_sqs:
                score += 2.0 + strength_map.get(to, 0)
            elif board.is_capture(move):
                score += 1.2
            else:
                continue

            piece = board.piece_at(frm)
            if piece and piece.piece_type == chess.PAWN:
                rank_from = chess.square_rank(frm)
                rank_to = chess.square_rank(to)
                steps = abs(rank_to - rank_from)
                # Opening double step: d2-d4, e2-e4, d7-d5, e7-e5
                if steps == 2 and rank_from in (1, 6):
                    score += 3.5  # strong preference over one-square (d3)
                    mid_rank = (rank_from + rank_to) // 2
                    mid = chess.square(chess.square_file(frm), mid_rank)
                    # Intermediate square often gets highlight noise – don't punish hard
                    if mid in changed_sqs:
                        score += 0.3
                elif steps == 1 and rank_from in (1, 6):
                    # One-square from base rank is less common early; slight penalty
                    # when a double-step is also legal to same file
                    score -= 0.8

            if board.is_castling(move):
                score += 1.0

            involved = {frm, to}
            extra = len(changed_sqs - involved)
            score -= 0.35 * extra

            scored.append((score, move))

        if not scored:
            if len(changed) >= 3:
                self._prev_sig = cur
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_move = scored[0]

        if best_score < 3.0:
            return None

        # If top is one-square pawn and second is double-step same file – pick double
        if len(scored) > 1:
            m0, m1 = scored[0][1], scored[1][1]
            p0 = board.piece_at(m0.from_square)
            p1 = board.piece_at(m1.from_square)
            if (
                p0 and p0.piece_type == chess.PAWN
                and p1 and p1.piece_type == chess.PAWN
                and m0.from_square == m1.from_square
            ):
                s0 = abs(chess.square_rank(m0.to_square) - chess.square_rank(m0.from_square))
                s1 = abs(chess.square_rank(m1.to_square) - chess.square_rank(m1.from_square))
                if s0 == 1 and s1 == 2 and scored[1][0] >= best_score - 2.0:
                    best_move = m1
                    best_score = scored[1][0]

        if len(scored) > 1 and scored[0][1].uci() != best_move.uci():
            pass  # chose double-step override
        elif len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 0.35:
            # Still ambiguous and not resolved – skip
            if scored[0][1].from_square != scored[1][1].from_square:
                return None

        self._prev_sig = cur
        self._cooldown = 1
        return best_move
