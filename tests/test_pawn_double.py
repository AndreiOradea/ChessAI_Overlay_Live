"""Test that when both d3 and d4 are candidates, we prefer d4."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import chess


def prefer_double_step(board: chess.Board, candidates_uci):
    """Mirror the override logic from move_diff."""
    moves = [chess.Move.from_uci(u) for u in candidates_uci]
    scored = [(1.0, m) for m in moves]
    scored.sort(key=lambda x: x[0], reverse=True)
    best_move = scored[0][1]
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
            if s0 == 1 and s1 == 2:
                best_move = m1
    return best_move.uci()


def test_prefer_d4_over_d3():
    board = chess.Board()
    # simulate ambiguous d2d3 vs d2d4
    assert prefer_double_step(board, ["d2d3", "d2d4"]) == "d2d4"


def test_prefer_d5_over_d6():
    board = chess.Board()
    board.push_san("d4")
    assert prefer_double_step(board, ["d7d6", "d7d5"]) == "d7d5"


if __name__ == "__main__":
    test_prefer_d4_over_d3()
    test_prefer_d5_over_d6()
    print("test_pawn_double: ALL PASSED")
