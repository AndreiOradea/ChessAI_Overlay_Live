import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.chess.move_list_sync import extract_san_tokens, replay_moves, sync_from_text
import chess


def test_extract_simple():
    toks = extract_san_tokens("1. e4 e5 2. Nf3 Nc6")
    assert toks == ["e4", "e5", "Nf3", "Nc6"]


def test_extract_caro_kann():
    toks = extract_san_tokens("1. e4 c6 2. d4 d5 3. Nf3 dxe4")
    assert toks == ["e4", "c6", "d4", "d5", "Nf3", "dxe4"]


def test_replay_turn_after_black_move():
    board, applied, err = replay_moves(["e4", "e5"])
    assert err is None
    assert len(applied) == 2
    assert board.turn == chess.WHITE


def test_sync_from_text_status():
    board, applied, msg = sync_from_text("1. e4 e5 2. Nf3")
    assert board is not None
    assert len(applied) == 3
    assert board.turn == chess.BLACK
    assert "Black to move" in msg


def test_castling_token():
    toks = extract_san_tokens("1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O")
    assert "O-O" in toks


if __name__ == "__main__":
    test_extract_simple()
    test_extract_caro_kann()
    test_replay_turn_after_black_move()
    test_sync_from_text_status()
    test_castling_token()
    print("test_move_list_sync: ALL PASSED")
