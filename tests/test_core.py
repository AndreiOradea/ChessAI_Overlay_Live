import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chess
from src.chess.game_tracker import GameTracker
from src.chess.move_list_sync import sync_from_text, extract_san_tokens


def test_tracker_sequence():
    t = GameTracker()
    for san in ["e4", "c6", "d4", "d5"]:
        ok, _ = t.apply_san(san)
        assert ok
    assert t.side_to_move() == "White"
    assert "1. e4  c6" in t.history_pairs()[0]


def test_sync_caro():
    applied, msg = sync_from_text("1. e4 c6 2. d4 d5 3. Nf3 dxe4")
    assert applied == ["e4", "c6", "d4", "d5", "Nf3", "dxe4"]
    assert "White to move" in msg


def test_tokens():
    assert extract_san_tokens("1. d4 d5 2. c4") == ["d4", "d5", "c4"]


if __name__ == "__main__":
    test_tracker_sequence()
    test_sync_caro()
    test_tokens()
    print("ALL TESTS PASSED")
