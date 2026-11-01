import chess
import threading
from unittest.mock import Mock

from src.engine.stockfish_wrapper import AnalysisResult, EngineLine
from src.ui.main_window import AnalysisWorker, MainWindow
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


def test_manual_piece_correction_is_kept_after_resync(qtbot, monkeypatch):
    recognized_board = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4"):
        recognized_board.push_san(san)
    recognized_board.set_piece_at(chess.A4, chess.Piece(chess.PAWN, chess.WHITE))

    class RecognizedTemplates:
        ready = True

        def to_board(self, _image, _orientation, turn=None):
            return recognized_board.copy(), "Templates recognized", True

    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr(
        "src.ui.main_window.PieceTemplateMatcher", RecognizedTemplates
    )
    monkeypatch.setattr(
        "src.ui.main_window.highlighted_last_move",
        lambda _image, _orientation: None,
    )

    config = AppConfig(mode="LIVE")
    config.board_region.calibrated = True
    window = MainWindow(config)
    qtbot.addWidget(window)
    window.capture.capture_region = Mock(return_value=object())
    window.move_diff.force_snapshot = Mock()
    window.tracker.state.board = recognized_board.copy()
    window.board_view.set_board(recognized_board)

    window._toggle_position_edit()
    window.board_view.edit_square(chess.A4, "B")
    window._toggle_position_edit()

    assert window._resync_from_screen()
    assert window.tracker.state.board.piece_at(chess.A4) == chess.Piece(
        chess.BISHOP, chess.WHITE
    )
    assert window.tracker.state.board.is_valid()
    assert "kept 1 manual piece correction" in window.lbl_status.text()
    assert window._resync_from_screen()
    assert window.tracker.state.board.piece_at(chess.A4) == chess.Piece(
        chess.BISHOP, chess.WHITE
    )
    window.close()


def test_analyze_button_runs_one_shot_analysis_in_live_mode(qtbot, monkeypatch):
    class WorkingEngine:
        ready = True

        def stop(self):
            pass

        def analyze(self, fen, depth, movetime_ms, multipv):
            return AnalysisResult(
                fen=fen,
                lines=[
                    EngineLine(
                        rank=1,
                        score_cp=25,
                        score_mate=None,
                        pv_san=["e4"],
                        pv_uci=["e2e4"],
                    )
                ],
                best_san="e4",
                best_uci="e2e4",
                evaluation="+0.25",
            )

    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: WorkingEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)

    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)

    window._request_analysis()
    assert not window._analyzing

    window.btn_analyze.click()
    qtbot.waitUntil(lambda: window.lbl_best.text() == "BEST: e4", timeout=3000)

    assert window.cmb_mode.currentText() == "LIVE"
    assert window.lbl_eval.text() == "+0.25"
    assert "e4" in window.lst_lines.item(0).text()
    assert window.lbl_analysis_eval.text() == "+0.25"
    assert "e4" in window.lst_analysis_lines.item(0).text()
    window.close()


def test_analysis_worker_uses_configured_multipv_count():
    engine = Mock()
    engine.analyze.return_value = AnalysisResult(fen="position")
    worker = AnalysisWorker(engine, "position", 18, 900, multipv=4)

    worker.run()

    engine.analyze.assert_called_once_with(
        "position", depth=18, movetime_ms=900, multipv=4
    )


def test_stopping_engine_waits_for_active_analysis_to_finish(qtbot, monkeypatch):
    class CountingEngine:
        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)
    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)
    engine = CountingEngine()
    window.engine = engine
    window._analyzing = True
    window._analysis_fen = window.tracker.state.board.fen()

    window._stop_engine()

    assert engine.stop_calls == 0
    assert window._stop_engine_after_analysis

    window._engine_thread_done()

    assert engine.stop_calls == 1
    assert not window._stop_engine_after_analysis
    window.close()


def test_window_close_waits_for_active_analysis_to_finish(qtbot, monkeypatch):
    analysis_started = threading.Event()
    finish_analysis = threading.Event()

    class DelayedEngine:
        ready = True
        stop_calls = 0

        def start(self, _threads, _hash_mb):
            return True

        def analyze(self, fen, depth, movetime_ms, multipv):
            analysis_started.set()
            assert finish_analysis.wait(timeout=3)
            return AnalysisResult(fen=fen)

        def stop(self):
            self.stop_calls += 1

    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)
    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)
    engine = DelayedEngine()
    window.engine = engine
    window.show()
    window._request_analysis(force=True)
    assert analysis_started.wait(timeout=3)

    window.close()

    assert window.isVisible()
    assert window._close_when_idle
    assert engine.stop_calls == 0

    finish_analysis.set()
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=3000)

    assert engine.stop_calls == 1


def test_dead_engine_is_restarted_and_analysis_retried_once(qtbot, monkeypatch):
    class RecoverableEngine:
        def __init__(self):
            self.stop_calls = 0
            self.start_calls = 0

        def stop(self):
            self.stop_calls += 1

        def start(self, _threads, _hash_mb):
            self.start_calls += 1
            return True

    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)
    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)
    engine = RecoverableEngine()
    window.engine = engine
    window._analyzing = True
    window._analysis_fen = window.tracker.state.board.fen()
    retry = Mock()
    window._request_analysis = retry

    window._on_analysis(
        AnalysisResult(
            fen=window.tracker.state.board.fen(),
            error="Engine process died unexpectedly (exit code: 1)",
        )
    )

    assert window._restart_engine_when_idle
    assert window._analysis_pending

    window._engine_thread_done()

    assert engine.stop_calls == 1
    assert engine.start_calls == 1
    retry.assert_called_once_with(force=True)
    window.close()


def test_resync_requests_fresh_analysis_in_live_mode(qtbot, monkeypatch):
    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)

    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)
    window._resync_from_screen = Mock(return_value=True)
    window._request_analysis = Mock()
    window._stop_engine()
    window.lbl_eval.setText("+9.99")
    window.lbl_best.setText("BEST: stale move")
    window.lst_lines.addItem("stale line")

    window._on_resync_clicked()

    assert not window._paused
    assert not window.timer_eng.isActive()
    assert window.lbl_eval.text() == "—"
    assert window.lbl_best.text() == "BEST: —"
    assert window.lst_lines.count() == 0
    window._request_analysis.assert_called_once_with(force=True)
    window.close()


def test_resync_button_displays_analysis_of_recognized_position(qtbot, monkeypatch):
    analyzed_fens = []

    class WorkingEngine:
        ready = True

        def stop(self):
            pass

        def analyze(self, fen, depth, movetime_ms, multipv):
            analyzed_fens.append(fen)
            return AnalysisResult(
                fen=fen,
                lines=[
                    EngineLine(
                        rank=1,
                        score_cp=-20,
                        score_mate=None,
                        pv_san=["e5"],
                        pv_uci=["e7e5"],
                    )
                ],
                best_san="e5",
                best_uci="e7e5",
                evaluation="-0.20",
            )

    class RecognizedTemplates:
        ready = True

        def to_board(self, _image, _orientation, turn=None):
            board = chess.Board()
            board.push_san("e4")
            return board, "Templates: 32 pieces · Black to move", True

    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: WorkingEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr(
        "src.ui.main_window.PieceTemplateMatcher", RecognizedTemplates
    )
    monkeypatch.setattr(
        "src.ui.main_window.highlighted_last_move", lambda _image, _orientation: None
    )

    config = AppConfig(mode="LIVE ENGINE")
    config.board_region.calibrated = True
    window = MainWindow(config)
    qtbot.addWidget(window)
    window.capture.capture_region = Mock(return_value=object())
    window.move_diff.force_snapshot = Mock()

    window.btn_resync.click()
    expected_board = chess.Board()
    expected_board.push_san("e4")
    expected_board.castling_rights = 0
    qtbot.waitUntil(
        lambda: expected_board.fen() in analyzed_fens
        and window.lbl_status.text() == "Analysis ready"
        and window.lbl_best.text() == "BEST: e5",
        timeout=3000,
    )

    assert analyzed_fens[-1] == expected_board.fen()
    assert window.lbl_eval.text() == "-0.20"
    assert window.lbl_best.text() == "BEST: e5"
    assert "e5" in window.lst_lines.item(0).text()
    window.close()


def test_stale_analysis_result_is_not_displayed_after_resync(qtbot, monkeypatch):
    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)

    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)
    updated_board = chess.Board()
    updated_board.push_san("e4")
    window.tracker.state.board = updated_board
    window.lbl_eval.setText("—")
    window.lbl_best.setText("BEST: —")

    stale_result = AnalysisResult(
        fen=chess.Board().fen(),
        best_san="d4",
        evaluation="+0.10",
    )
    window._on_analysis(stale_result)

    assert window.lbl_eval.text() == "—"
    assert window.lbl_best.text() == "BEST: —"
    window.close()


def test_queued_resync_analysis_runs_after_active_analysis_finishes(
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
    window._analyzing = True

    window._request_analysis(force=True)

    assert window._analysis_pending
    result = AnalysisResult(fen=window.tracker.state.board.fen())
    window._on_analysis(result)
    assert window._analyzing

    request_analysis = Mock()
    window._request_analysis = request_analysis
    window._engine_thread_done()

    assert not window._analysis_pending
    request_analysis.assert_called_once_with(force=True)
    window.close()


def test_active_old_search_is_replaced_with_analysis_of_resynced_position(
    qtbot, monkeypatch
):
    first_started = threading.Event()
    release_first = threading.Event()
    analyzed_fens = []

    class DelayedEngine:
        ready = True

        def stop(self):
            release_first.set()

        def analyze(self, fen, depth, movetime_ms, multipv):
            analyzed_fens.append(fen)
            if len(analyzed_fens) == 1:
                first_started.set()
                assert release_first.wait(timeout=3)
                san, uci = "e4", "e2e4"
            else:
                san, uci = "e5", "e7e5"
            return AnalysisResult(
                fen=fen,
                lines=[
                    EngineLine(
                        rank=1,
                        score_cp=10,
                        score_mate=None,
                        pv_san=[san],
                        pv_uci=[uci],
                    )
                ],
                best_san=san,
                best_uci=uci,
                evaluation="+0.10",
            )

    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: DelayedEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)

    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)
    window._request_analysis(force=True)
    assert first_started.wait(timeout=3)

    resynced_board = chess.Board()
    resynced_board.push_san("e4")
    window.tracker.state.board = resynced_board
    window._request_analysis(force=True)
    assert window._analysis_pending

    release_first.set()
    qtbot.waitUntil(
        lambda: len(analyzed_fens) == 2
        and analyzed_fens[-1] == resynced_board.fen()
        and window.lbl_status.text() == "Analysis ready"
        and window.lbl_best.text() == "BEST: e5",
        timeout=3000,
    )
    assert window.lbl_eval.text() == "+0.10"
    window.close()


def test_last_move_highlight_and_owner_follow_selected_player(
    qtbot, monkeypatch
):
    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)

    window = MainWindow(AppConfig(mode="LIVE", my_color="white"))
    qtbot.addWidget(window)
    window.txt_moves.setText("1. e4 e5 2. Nf3 Nf6")

    window._sync_moves()

    assert window.board_view._last_move == ("g8", "f6")
    assert "Last: Nf6 (opponent)" in window.lbl_turn.text()

    window.cmb_color.setCurrentText("Black")

    assert "Last: Nf6 (you)" in window.lbl_turn.text()
    assert window.board_view._last_move == ("g8", "f6")

    resynced_board = chess.Board()
    resynced_board.push_san("e4")
    resynced_board.push_san("f5")
    window.tracker.state.board = resynced_board.copy()
    window.tracker.state.moves = []
    last_move = chess.Move.from_uci("f7f5")
    window._refresh(last_move)
    assert window.board_view._last_move == ("f7", "f5")
    assert "Last: f7-f5 (you)" in window.lbl_turn.text()

    window.cmb_color.setCurrentText("White")
    window._refresh(last_move)
    assert "Last: f7-f5 (opponent)" in window.lbl_turn.text()
    window.close()


def test_resync_uses_highlights_to_update_turn_without_changing_pieces(
    qtbot, monkeypatch
):
    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)

    recognized_board = chess.Board()
    recognized_board.push_san("e4")
    recognized_board.push_san("f5")

    class ReadyTemplates:
        ready = True

        def __init__(self):
            self.turn = None

        def to_board(self, _image, _orientation, turn=None):
            self.turn = turn
            return recognized_board.copy(), "Templates: 32 pieces", True

    templates = ReadyTemplates()
    monkeypatch.setattr(
        "src.ui.main_window.PieceTemplateMatcher", lambda: templates
    )
    monkeypatch.setattr(
        "src.ui.main_window.highlighted_last_move",
        lambda _image, _orientation: (
            chess.Move.from_uci("f7f5"),
            chess.WHITE,
        ),
    )

    config = AppConfig(mode="LIVE", my_color="white")
    config.board_region.calibrated = True
    window = MainWindow(config)
    qtbot.addWidget(window)
    window.capture.capture_region = Mock(return_value=object())
    window.move_diff.force_snapshot = Mock()
    current_board = recognized_board.copy()
    current_board.turn = chess.BLACK
    window.tracker.state.board = current_board

    assert window._resync_from_screen()

    assert templates.turn == chess.WHITE
    assert window.tracker.state.board.board_fen() == recognized_board.board_fen()
    assert window.tracker.state.board.turn == chess.WHITE
    assert window.board_view._last_move == ("f7", "f5")
    assert "Last: f7-f5 (opponent)" in window.lbl_turn.text()
    assert "turn synced" in window.lbl_status.text().lower()
    window.close()
