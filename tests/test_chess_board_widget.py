import chess
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from src.ui.chess_board_widget import ChessBoardWidget


def square_center(file, rank):
    tile = (400 - 8) // 8
    return QPoint(4 + file * tile + tile // 2, 4 + (7 - rank) * tile + tile // 2)


def test_internal_board_drag_moves_piece(qtbot):
    widget = ChessBoardWidget()
    widget.resize(400, 400)
    qtbot.addWidget(widget)
    widget.show()
    moves = []
    widget.move_requested.connect(moves.append)

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        pos=square_center(chess.FILE_NAMES.index("e"), 1),
    )
    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        pos=square_center(chess.FILE_NAMES.index("e"), 3),
    )

    assert moves == [chess.Move.from_uci("e2e4")]


def test_internal_board_allows_capture(qtbot):
    board = chess.Board()
    for san in ("e4", "d5"):
        board.push_san(san)

    widget = ChessBoardWidget()
    widget.resize(400, 400)
    widget.set_board(board)
    qtbot.addWidget(widget)
    widget.show()
    moves = []
    widget.move_requested.connect(moves.append)

    QTest.mouseClick(
        widget,
        Qt.MouseButton.LeftButton,
        pos=square_center(chess.FILE_NAMES.index("e"), 3),
    )
    QTest.mouseClick(
        widget,
        Qt.MouseButton.LeftButton,
        pos=square_center(chess.FILE_NAMES.index("d"), 4),
    )

    assert moves == [board.parse_san("exd5")]


def test_internal_board_updates_when_only_turn_changes(qtbot):
    board = chess.Board()
    board.turn = chess.BLACK

    widget = ChessBoardWidget()
    widget.resize(400, 400)
    widget.set_board(chess.Board())
    widget.set_board(board)
    qtbot.addWidget(widget)
    widget.show()
    moves = []
    widget.move_requested.connect(moves.append)

    QTest.mouseClick(
        widget,
        Qt.MouseButton.LeftButton,
        pos=square_center(chess.FILE_NAMES.index("e"), 6),
    )
    QTest.mouseClick(
        widget,
        Qt.MouseButton.LeftButton,
        pos=square_center(chess.FILE_NAMES.index("e"), 4),
    )

    assert moves == [chess.Move.from_uci("e7e5")]


def test_last_move_highlights_both_squares_over_analysis(qtbot):
    board = chess.Board()
    board.push_san("e4")
    widget = ChessBoardWidget()
    widget.resize(400, 400)
    widget.set_board(board)
    widget.set_analysis_arrows("e2e4")
    qtbot.addWidget(widget)
    widget.show()
    qtbot.wait(10)

    before = widget.grab().toImage()
    widget.set_last_move("e2e4")
    after = widget.grab().toImage()
    tile, ox, oy = widget._board_geometry()

    for square in ("e2", "e4"):
        rect = widget._sq_rect(square, tile, ox, oy)
        point = rect.topLeft() + QPoint(3, 3)
        before_color = before.pixelColor(point)
        after_color = after.pixelColor(point)
        assert after_color.red() > before_color.red()
        assert after_color.green() > before_color.green()


def test_analysis_arrows_animate_smoothly_and_stop_when_cleared(qtbot):
    widget = ChessBoardWidget()
    qtbot.addWidget(widget)

    widget.set_analysis_arrows("e2e4", ["d2d4"])
    assert widget._arrow_progress == 0

    qtbot.wait(70)
    assert 0 < widget._arrow_progress < 1
    qtbot.wait(220)
    assert widget._arrow_progress == 1
    assert not widget._arrow_animation_timer.isActive()

    widget.set_analysis_arrows("e2e4")
    widget.clear_analysis()
    assert widget._arrow_progress == 1
    assert not widget._arrow_animation_timer.isActive()


def test_edit_mode_allows_free_placement_without_legal_move(qtbot):
    widget = ChessBoardWidget()
    widget.resize(400, 400)
    qtbot.addWidget(widget)
    widget.show()
    widget.set_edit_mode(True)
    moves = []
    positions = []
    widget.move_requested.connect(moves.append)
    widget.position_edited.connect(positions.append)

    QTest.mousePress(
        widget,
        Qt.MouseButton.LeftButton,
        pos=square_center(chess.FILE_NAMES.index("e"), 1),
    )
    QTest.mouseRelease(
        widget,
        Qt.MouseButton.LeftButton,
        pos=square_center(chess.FILE_NAMES.index("e"), 4),
    )

    assert moves == []
    assert widget._board.piece_at(chess.E2) is None
    assert widget._board.piece_at(chess.E5) == chess.Piece(chess.PAWN, chess.WHITE)
    assert len(positions) == 1


def test_edit_mode_adds_removes_and_changes_turn(qtbot):
    widget = ChessBoardWidget()
    qtbot.addWidget(widget)
    widget.set_edit_mode(True)
    positions = []
    widget.position_edited.connect(positions.append)

    widget.edit_square(chess.D4, "q")
    assert widget._board.piece_at(chess.D4) == chess.Piece(chess.QUEEN, chess.BLACK)
    widget.edit_square(chess.D4)
    assert widget._board.piece_at(chess.D4) is None
    widget.edit_set_turn(chess.BLACK)

    assert widget._board.turn == chess.BLACK
    assert len(positions) == 3


def test_piece_placement_is_disabled_outside_edit_mode(qtbot):
    widget = ChessBoardWidget()
    qtbot.addWidget(widget)

    widget.edit_square(chess.D4, "q")

    assert widget._board.piece_at(chess.D4) is None


def test_right_click_menu_places_piece(qtbot):
    widget = ChessBoardWidget()
    qtbot.addWidget(widget)
    widget.set_edit_mode(True)
    menu = widget._create_edit_menu(chess.D4)
    menu.actions()[1].menu().actions()[0].trigger()

    assert widget._board.piece_at(chess.D4) == chess.Piece(chess.QUEEN, chess.WHITE)
