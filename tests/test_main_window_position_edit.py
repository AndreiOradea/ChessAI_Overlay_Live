import chess

from src.ui.main_window import MainWindow
from src.utils.config import AppConfig


class StubEngine:
    ready = False

    def stop(self):
        pass


class StubCapture:
    def close(self):
        pass


class StubTemplates:
    ready = False


def test_position_editor_updates_tracker_and_blocks_invalid_analysis(
    qtbot, monkeypatch
):
    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)

    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)

    window.btn_edit_position.click()
    window.board_view.edit_square(chess.D4, "q")
    assert window.tracker.state.board.piece_at(chess.D4) == chess.Piece(
        chess.QUEEN, chess.BLACK
    )
    assert window.tracker.state.moves == []

    window.board_view.edit_square(chess.E8)
    window.btn_edit_position.click()
    window._analyze_now()

    assert not window.tracker.state.board.is_valid()
    assert "invalid" in window.lbl_status.text().lower()
    window.close()
