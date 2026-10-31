"""
Tactical helpers: hanging pieces, checks, captures, basic threats.
Uses pure python-chess (no engine required).
"""

from __future__ import annotations

import chess
from typing import List, Tuple, Dict
from dataclasses import dataclass


@dataclass
class HangingPiece:
    square: str          # e.g. "e5"
    piece: str           # e.g. "P", "n"
    color: str           # "white" / "black"
    attackers: int
    defenders: int


@dataclass
class TacticalSummary:
    hanging: List[HangingPiece]
    checks: List[str]            # SAN of checking moves available
    captures: List[str]          # SAN of capture moves
    in_check: bool
    side_to_move: str


def analyze_tactics(board: chess.Board) -> TacticalSummary:
    """Return hanging pieces, available checks/captures for the side to move."""
    hanging: List[HangingPiece] = []
    checks: List[str] = []
    captures: List[str] = []

    # Hanging pieces for both sides
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue
        attackers = len(board.attackers(not piece.color, sq))
        defenders = len(board.attackers(piece.color, sq))
        # Simple hanging definition: attacked more than defended, or attacked and undefended
        if attackers > 0 and attackers > defenders:
            hanging.append(HangingPiece(
                square=chess.square_name(sq),
                piece=piece.symbol().upper() if piece.color == chess.WHITE else piece.symbol().lower(),
                color="white" if piece.color == chess.WHITE else "black",
                attackers=attackers,
                defenders=defenders,
            ))

    # Moves for side to move
    for move in board.legal_moves:
        san = board.san(move)
        if board.is_capture(move):
            captures.append(san)
        board.push(move)
        if board.is_check():
            checks.append(san)
        board.pop()

    return TacticalSummary(
        hanging=hanging,
        checks=checks[:8],
        captures=captures[:8],
        in_check=board.is_check(),
        side_to_move="White" if board.turn == chess.WHITE else "Black",
    )
