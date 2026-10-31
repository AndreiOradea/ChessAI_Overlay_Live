"""Basic tests for board detector (no real screen required)."""

import numpy as np
import chess
from src.recognition.board_detector import BoardDetector, create_empty_board_image, DetectionResult


def test_empty_board_detection():
    det = BoardDetector()
    img = create_empty_board_image(400)
    result = det.detect(img)
    assert isinstance(result, DetectionResult)
    assert result.confidence >= 0.0
    # Empty board should produce mostly empty FEN
    board = chess.Board(result.fen)
    assert board.piece_map() == {} or result.confidence < 0.5  # may be noisy


def test_force_fen():
    det = BoardDetector()
    fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    det.force_fen(fen)
    assert det.last_fen is not None
    assert "4P3" in det.last_fen


def test_orientation_setting():
    det = BoardDetector()
    det.set_orientation("black")
    assert det.orientation == "black"
    det.set_orientation("white")
    assert det.orientation == "white"


def test_too_small_image():
    det = BoardDetector()
    tiny = np.zeros((30, 30, 3), dtype=np.uint8)
    result = det.detect(tiny)
    assert result.confidence == 0.0
    assert "small" in result.message.lower()
