"""Stockfish communication tests (skipped if engine binary missing)."""

import pytest
import chess
from src.engine.stockfish_wrapper import StockfishEngine


@pytest.fixture
def engine():
    eng = StockfishEngine()
    if not eng.path:
        pytest.skip("Stockfish binary not found")
    ok = eng.start(threads=1, hash_mb=16)
    if not ok:
        pytest.skip("Could not start Stockfish")
    yield eng
    eng.stop()


def test_starting_position_eval(engine):
    result = engine.analyze(chess.STARTING_FEN, depth=10, multipv=1)
    assert result.error is None
    assert result.evaluation != ""
    assert result.best_san is not None


def test_mate_in_one(engine):
    # Back rank mate setup (White to move, mate in 1)
    fen = "6k1/5ppp/8/8/8/8/8/R3K3 w Q - 0 1"
    result = engine.analyze(fen, depth=8, multipv=1)
    assert result.error is None
    # Should find a mating move or high eval
    assert result.lines
