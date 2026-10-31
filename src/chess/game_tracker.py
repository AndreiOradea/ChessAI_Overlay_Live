from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import chess


@dataclass
class MoveRecord:
    san: str
    uci: str


@dataclass
class GameState:
    board: chess.Board = field(default_factory=chess.Board)
    moves: List[MoveRecord] = field(default_factory=list)
    orientation: str = "white"


class GameTracker:
    def __init__(self):
        self.state = GameState()

    def reset(self, fen: str = chess.STARTING_FEN, orientation: str = "white"):
        self.state = GameState(board=chess.Board(fen), moves=[], orientation=orientation)

    def side_to_move(self) -> str:
        return "White" if self.state.board.turn == chess.WHITE else "Black"

    def apply_move(self, move: chess.Move) -> Tuple[bool, str]:
        board = self.state.board
        if move not in board.legal_moves:
            return False, "Illegal"
        san = board.san(move)
        board.push(move)
        self.state.moves.append(MoveRecord(san=san, uci=move.uci()))
        return True, san

    def apply_san(self, san: str) -> Tuple[bool, str]:
        try:
            move = self.state.board.parse_san(san)
        except Exception as e:
            return False, str(e)
        return self.apply_move(move)

    def set_from_sans(self, sans: List[str]) -> Tuple[int, Optional[str]]:
        self.reset(chess.STARTING_FEN, self.state.orientation)
        for san in sans:
            ok, msg = self.apply_san(san)
            if not ok:
                return len(self.state.moves), msg
        return len(self.state.moves), None

    def history_pairs(self) -> List[str]:
        out = []
        moves = [m.san for m in self.state.moves]
        for i in range(0, len(moves), 2):
            n = i // 2 + 1
            w = moves[i]
            b = moves[i + 1] if i + 1 < len(moves) else ""
            out.append(f"{n}. {w}  {b}".rstrip())
        return out
