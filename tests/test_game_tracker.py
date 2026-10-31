import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chess
from src.chess.game_tracker import GameTracker


def test_start_position():
    t = GameTracker()
    assert t.side_to_move() == "White"
    assert len(t.state.moves) == 0


def test_apply_sequence_updates_history_and_turn():
    t = GameTracker()
    for san in ["e4", "e5", "Nf3"]:
        move = t.state.board.parse_san(san)
        ok, _ = t._apply_move(move)
        assert ok
    assert t.get_move_history_san() == ["e4", "e5", "Nf3"]
    assert t.side_to_move() == "Black"
    assert len(t.state.moves) == 3


def test_reset_clears_history():
    t = GameTracker()
    t._apply_move(t.state.board.parse_san("e4"))
    t.reset(chess.STARTING_FEN, "white")
    assert t.state.moves == []
    assert t.side_to_move() == "White"


def test_force_position():
    t = GameTracker()
    fen = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2"
    assert t.force_position(fen)
    assert t.state.board.piece_at(chess.E4) is not None


if __name__ == "__main__":
    test_start_position()
    test_apply_sequence_updates_history_and_turn()
    test_reset_clears_history()
    test_force_position()
    print("test_game_tracker: ALL PASSED")
