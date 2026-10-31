import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import cv2
    import numpy as np
    HAS_CV = True
except ImportError:
    HAS_CV = False

def test_move_diff_basic():
    if not HAS_CV:
        print("skip test_move_diff (no cv2)")
        return
    import chess
    from src.recognition.move_diff import MoveDiffTracker
    m = MoveDiffTracker()
    img = np.full((400, 400, 3), 120, dtype=np.uint8)
    board = chess.Board()
    assert m.detect_move(img, board) is None
    assert m.detect_move(img, board) is None
    m.force_snapshot(img)
    assert m._prev_sig is not None

if __name__ == "__main__":
    test_move_diff_basic()
    print("test_move_diff: ALL PASSED")
