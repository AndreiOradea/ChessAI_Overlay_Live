"""
Analyze resync: screenshot the selected region and read piece placement.

Tuned for Chess.com **green board + Classic pieces**:
- empty squares = green (high saturation, low texture)
- white pieces = bright / light gray-white
- black pieces = dark charcoal
"""

from __future__ import annotations

from typing import Optional, List, Tuple
import numpy as np
import chess
from src.recognition.move_diff import visual_occupancy

EMPTY, WHITE, BLACK = 0, 1, 2


def expected_occupancy(board: chess.Board, orientation: str = "white") -> np.ndarray:
    grid = np.zeros((8, 8), np.int32)
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        f, rk = chess.square_file(sq), chess.square_rank(sq)
        if orientation == "white":
            r, c = 7 - rk, f
        else:
            r, c = rk, 7 - f
        if piece is None:
            grid[r, c] = EMPTY
        elif piece.color == chess.WHITE:
            grid[r, c] = WHITE
        else:
            grid[r, c] = BLACK
    return grid


def mismatch(board: chess.Board, vis: np.ndarray, orientation: str) -> int:
    return int(np.sum(expected_occupancy(board, orientation) != vis))


def resync_board(
    board: chess.Board,
    bgr,
    orientation: str = "white",
    max_depth: int = 2,
) -> Tuple[chess.Board, List[chess.Move], int, str]:
    """
    Search legal move sequences for an exact match to the screen occupancy.
    Ambiguous or approximate matches leave the current position unchanged.
    """
    vis = visual_occupancy(bgr)
    if vis is None:
        return board, [], 64, "No screenshot"

    beam_width = 128
    max_ply = min(12, max(2, max_depth * 4))
    roots = [(board.copy(), "current position")]
    if board.board_fen() != chess.Board().board_fen():
        roots.append((chess.Board(), "starting position"))
    closest = 64

    for root, root_label in roots:
        root_mm = mismatch(root, vis, orientation)
        closest = min(closest, root_mm)
        if root_mm <= 1:
            side = "White" if root.turn == chess.WHITE else "Black"
            return (
                root,
                [],
                0,
                f"Screen board synced · {side} to move · matched {root_label}",
            )

        beam: List[Tuple[int, chess.Board, List[chess.Move]]] = [(root_mm, root, [])]
        for _ in range(max_ply):
            candidates: List[Tuple[int, chess.Board, List[chess.Move]]] = []
            for _, position, path in beam:
                for move in position.legal_moves:
                    next_position = position.copy(stack=False)
                    next_position.push(move)
                    mm = mismatch(next_position, vis, orientation)
                    closest = min(closest, mm)
                    candidates.append((mm, next_position, path + [move]))

            candidates.sort(key=lambda item: (item[0], len(item[2])))
            matches = [item for item in candidates if item[0] <= 1]
            if matches:
                best_mm = min(item[0] for item in matches)
                best_matches = [item for item in matches if item[0] == best_mm]
                positions = {
                    (position.board_fen(), position.turn)
                    for _, position, _ in best_matches
                }
                if len(positions) == 1:
                    mm, position, path = best_matches[0]
                    side = "White" if position.turn == chess.WHITE else "Black"
                    detail = f" · {mm} uncertain square" if mm else ""
                    return (
                        position,
                        path,
                        0,
                        f"Screen board synced{detail} · {side} to move · {len(path)} moves from {root_label}",
                    )
                return (
                    board,
                    [],
                    1,
                    "Screen position is ambiguous; board unchanged",
                )

            seen = set()
            next_beam = []
            for mm, position, path in candidates:
                key = (position.board_fen(), position.turn, position.castling_rights)
                if key in seen:
                    continue
                seen.add(key)
                if len(next_beam) < beam_width:
                    next_beam.append((mm, position, path))
            beam = next_beam
            if not beam:
                break

    return (
        board,
        [],
        max(1, closest),
        "No exact screen match found; board unchanged. Check the region or paste moves.",
    )
