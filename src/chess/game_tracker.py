"""
Game state tracking: FEN, move history, legality, clocks, game phase.
"""

from __future__ import annotations

import chess
import chess.pgn
from typing import Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import io


@dataclass
class MoveRecord:
    san: str
    uci: str
    fen_after: str
    timestamp: datetime = field(default_factory=datetime.now)
    is_capture: bool = False
    is_check: bool = False
    is_mate: bool = False
    is_castle: bool = False
    is_promotion: bool = False


@dataclass
class GameState:
    board: chess.Board
    moves: List[MoveRecord] = field(default_factory=list)
    white_clock: Optional[float] = None  # seconds remaining
    black_clock: Optional[float] = None
    orientation: str = "white"
    game_id: str = ""
    start_time: datetime = field(default_factory=datetime.now)
    is_live: bool = True
    last_confidence: float = 1.0


class GameTracker:
    """
    Maintains the current game state from successive FEN observations.
    Detects moves by comparing positions, validates legality, builds history.
    """

    def __init__(self):
        self.state = GameState(board=chess.Board())
        self._last_accepted_fen: str = chess.STARTING_FEN

    def reset(self, fen: str = chess.STARTING_FEN, orientation: str = "white"):
        try:
            board = chess.Board(fen)
        except Exception:
            board = chess.Board()
        self.state = GameState(
            board=board,
            orientation=orientation,
            start_time=datetime.now()
        )
        self._last_accepted_fen = board.fen()

    def update_from_fen(self, new_fen: str, confidence: float = 1.0) -> Tuple[bool, str]:
        """
        Try to advance the game state with a newly detected FEN.
        Returns (accepted, message).
        """
        self.state.last_confidence = confidence

        if confidence < 0.40:
            return False, "Confidence too low – position not accepted"

        try:
            new_board = chess.Board(new_fen)
        except Exception as e:
            return False, f"Invalid FEN: {e}"

        # Exact same position
        if new_board.board_fen() == self.state.board.board_fen():
            # Update side-to-move / clocks if needed, but no move
            return True, "Position unchanged"

        # Check if this is a legal single move from current position
        move = self._find_move(self.state.board, new_board)
        if move is not None:
            return self._apply_move(move)

        # Maybe the user flipped the board or we lost track – allow force-set
        # only if confidence is high
        if confidence > 0.75:
            self.state.board = new_board
            self._last_accepted_fen = new_board.fen()
            return True, "Position forced (high confidence)"

        return False, "Could not find legal move – please correct FEN manually"

    def force_position(self, fen: str) -> bool:
        """User-corrected position."""
        try:
            board = chess.Board(fen)
            self.state.board = board
            self._last_accepted_fen = board.fen()
            # Clear move history if the position doesn't match last move
            return True
        except Exception:
            return False

    def _find_move(self, old: chess.Board, new: chess.Board) -> Optional[chess.Move]:
        """Find the unique legal move that turns old into new (piece placement)."""
        for move in old.legal_moves:
            old.push(move)
            if old.board_fen() == new.board_fen():
                old.pop()
                return move
            old.pop()
        return None

    def _apply_move(self, move: chess.Move) -> Tuple[bool, str]:
        board = self.state.board
        san = board.san(move)
        is_capture = board.is_capture(move)
        is_castle = board.is_castling(move)
        is_promotion = move.promotion is not None

        board.push(move)
        is_check = board.is_check()
        is_mate = board.is_checkmate()

        record = MoveRecord(
            san=san,
            uci=move.uci(),
            fen_after=board.fen(),
            is_capture=is_capture,
            is_check=is_check,
            is_mate=is_mate,
            is_castle=is_castle,
            is_promotion=is_promotion,
        )
        self.state.moves.append(record)
        self._last_accepted_fen = board.fen()

        msg = san
        if is_mate:
            msg += " #"
        elif is_check:
            msg += " +"
        return True, f"Move: {msg}"

    def get_move_history_san(self) -> List[str]:
        return [m.san for m in self.state.moves]

    def get_pgn(self, headers: Optional[dict] = None) -> str:
        game = chess.pgn.Game()
        if headers:
            for k, v in headers.items():
                game.headers[k] = str(v)
        game.headers["Date"] = self.state.start_time.strftime("%Y.%m.%d")
        node = game
        # Replay moves
        temp = chess.Board()
        for m in self.state.moves:
            try:
                move = temp.parse_san(m.san)
                node = node.add_variation(move)
                temp.push(move)
            except Exception:
                break
        return str(game)

    def side_to_move(self) -> str:
        return "White" if self.state.board.turn == chess.WHITE else "Black"

    def is_game_over(self) -> bool:
        return self.state.board.is_game_over()

    def result(self) -> str:
        if not self.is_game_over():
            return "*"
        return self.state.board.result()
