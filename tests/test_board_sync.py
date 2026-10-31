import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import chess
import cv2
import numpy as np

from src.recognition.board_sync import resync_board
from src.recognition.move_diff import MoveDiffTracker, highlighted_last_move
from src.recognition import piece_templates
from src.recognition.piece_templates import PieceTemplateMatcher
from src.chess.move_list_sync import sync_from_text
from src.chess.game_tracker import GameTracker


def make_board_image(board):
    image = np.zeros((400, 400, 3), dtype=np.uint8)
    dark_square = (115, 149, 82)
    light_square = (235, 236, 208)
    for row in range(8):
        for col in range(8):
            color = light_square if (row + col) % 2 else dark_square
            image[row * 50 : (row + 1) * 50, col * 50 : (col + 1) * 50] = color

    for square, piece in board.piece_map().items():
        row = 7 - chess.square_rank(square)
        col = chess.square_file(square)
        center = (col * 50 + 25, row * 50 + 25)
        if piece.color == chess.BLACK:
            cv2.circle(image, center, 15, (0, 0, 0), -1)
        else:
            cv2.circle(image, center, 15, (0, 0, 0), -1)
            cv2.circle(image, center, 12, (255, 255, 255), -1)
    return image


def add_move_highlight(image, square, orientation="white"):
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    if orientation == "white":
        row, col = 7 - rank, file
    else:
        row, col = rank, 7 - file
    tile = image[row * 50 : (row + 1) * 50, col * 50 : (col + 1) * 50]
    original = tile.copy()
    corners = np.concatenate(
        (
            tile[3:10, 3:10].reshape(-1, 3),
            tile[3:10, 40:47].reshape(-1, 3),
            tile[40:47, 3:10].reshape(-1, 3),
            tile[40:47, 40:47].reshape(-1, 3),
        )
    )
    background = np.median(corners, axis=0)
    foreground = np.linalg.norm(tile.astype(np.float32) - background, axis=2) > 32
    tile[:] = (0, 255, 255)
    tile[foreground] = original[foreground]


def image_with_highlighted_last_move():
    board = chess.Board()
    board.push_san("e4")
    board.push_san("f5")
    image = make_board_image(board)
    add_move_highlight(image, chess.F7)
    add_move_highlight(image, chess.F5)
    return image


def test_visual_grid_classifies_piece_squares():
    board = chess.Board()
    board.push_san("e4")
    board.push_san("c5")
    detector = MoveDiffTracker()

    assert np.array_equal(
        detector._visual_grid(make_board_image(board)),
        detector._expected_grid(board),
    )


def test_color_classifier_separates_dark_piece_with_bright_outline():
    detector = MoveDiffTracker()

    def piece_image(white_piece):
        background = (115, 149, 82)
        square = np.full((50, 50, 3), background, dtype=np.uint8)
        cv2.ellipse(square, (25, 25), (14, 17), 0, 0, 360, (0, 0, 0), -1)
        if white_piece:
            cv2.ellipse(square, (25, 25), (10, 13), 0, 0, 360, (255, 255, 255), -1)
        else:
            cv2.line(square, (25, 16), (25, 22), (255, 255, 255), 2)
            cv2.line(square, (20, 26), (30, 26), (255, 255, 255), 2)
        image = np.full((400, 400, 3), background, dtype=np.uint8)
        image[:50, :50] = square
        return image

    black_piece = piece_image(False)
    white_piece = piece_image(True)
    assert detector._classify_square(black_piece, 0, 0) == 2
    assert detector._classify_square(white_piece, 0, 0) == 1


def test_yellow_last_move_highlight_infers_side_to_move():
    result = highlighted_last_move(image_with_highlighted_last_move())

    assert result == (chess.Move.from_uci("f7f5"), chess.WHITE)
    assert type(result[1]) is bool


def test_yellow_last_move_highlight_respects_black_orientation():
    image = cv2.rotate(
        image_with_highlighted_last_move(), cv2.ROTATE_180
    )

    assert highlighted_last_move(image, orientation="black") == (
        chess.Move.from_uci("f7f5"),
        chess.WHITE,
    )


def test_yellow_last_move_highlight_rejects_ambiguous_squares():
    image = image_with_highlighted_last_move()
    add_move_highlight(image, chess.A3)

    assert highlighted_last_move(image) is None


def test_template_resync_retries_small_square_crop_offsets():
    matcher = PieceTemplateMatcher()
    matcher.ready = True
    image = np.indices((400, 400)).sum(axis=0).astype(np.uint8)
    image = np.repeat(image[:, :, None], 3, axis=2)
    original_cell = piece_templates._cell(image, 0, 0)
    matcher.classify_square = Mock(
        side_effect=lambda cell, color=None: (
            (None, 0.8)
            if np.array_equal(cell, original_cell)
            else ("r", 0.95)
        )
    )
    occupancy = np.zeros((8, 8), dtype=np.int32)
    occupancy[0, 0] = 2

    with patch(
        "src.recognition.piece_templates.visual_occupancy",
        return_value=occupancy,
    ):
        pieces, confidence = matcher.board_to_piece_map(image)

    assert pieces == {chess.A8: "r"}
    assert confidence == 0.95


def test_move_detection_rejects_misaligned_board():
    board = chess.Board()
    for san in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6"):
        board.push_san(san)
    after_move = board.copy()
    after_move.push_san("Ba4")

    detector = MoveDiffTracker()
    correctly_aligned = detector._expected_grid(after_move)
    shifted = np.roll(detector._expected_grid(after_move), -2, axis=0)

    assert detector._find_candidate(correctly_aligned, board) == board.parse_san(
        "Ba4"
    )
    assert detector._find_candidate(shifted, board) is None


def test_move_detection_uses_last_stable_board():
    before = chess.Board()
    after = before.copy()
    after.push_san("e4")
    detector = MoveDiffTracker()
    before_image = make_board_image(before)
    after_image = make_board_image(after)
    detector.force_snapshot(before_image)

    assert detector.detect_move(after_image, before) is None
    assert detector.detect_move(after_image, before) is None
    assert detector.detect_move(after_image, before) == before.parse_san("e4")


def test_move_detection_tracks_both_players():
    board = chess.Board()
    detector = MoveDiffTracker()
    before = make_board_image(board)
    detector.force_snapshot(before)

    after_white = board.copy()
    after_white.push_san("e4")
    e4_image = make_board_image(after_white)
    assert detector.detect_move(e4_image, board) is None
    assert detector.detect_move(e4_image, board) is None
    move = detector.detect_move(e4_image, board)
    assert move == chess.Move.from_uci("e2e4")
    board.push(move)
    detector.force_snapshot(e4_image)

    after_black = board.copy()
    after_black.push_san("c5")
    c5_image = make_board_image(after_black)
    assert detector.detect_move(c5_image, board) is None
    assert detector.detect_move(c5_image, board) is None
    move = detector.detect_move(c5_image, board)
    assert move == chess.Move.from_uci("c7c5")
    board.push(move)
    assert board.board_fen() == after_black.board_fen()


def test_no_match_keeps_current_position():
    current = chess.Board()
    start_fen = chess.Board().board_fen()

    def fake_mismatch(candidate, _vis, _orientation):
        if candidate.board_fen() == start_fen:
            return 5
        return 6

    with (
        patch(
            "src.recognition.board_sync.visual_occupancy",
            return_value=np.ones((8, 8), dtype=np.int32),
        ),
        patch("src.recognition.board_sync.mismatch", side_effect=fake_mismatch),
    ):
        synced, moves, difference, status = resync_board(
            current, np.zeros((400, 400, 3), dtype=np.uint8)
        )

    assert synced.fen() == current.fen()
    assert moves == []
    assert difference == 5
    assert "No exact" in status


def test_resync_finds_exact_opening_position():
    expected = chess.Board()
    expected.push_san("e4")
    expected.push_san("c5")

    synced, moves, difference, status = resync_board(
        chess.Board(), make_board_image(expected)
    )

    assert difference == 0
    assert synced.board_fen() == expected.board_fen()
    assert [move.uci() for move in moves] == ["e2e4", "c7c5"]
    assert "synced" in status.lower()


def test_template_resync_rejects_position_without_kings():
    matcher = PieceTemplateMatcher()
    matcher.ready = True
    pieces = {chess.square(file, 1): "P" for file in range(8)}
    matcher.board_to_piece_map = Mock(return_value=(pieces, 0.9))

    board, status, turn_known = matcher.to_board(None)

    assert board is None
    assert not turn_known
    assert "Invalid position" in status


def test_template_resync_normalizes_numpy_boolean_turn():
    matcher = PieceTemplateMatcher()
    matcher.ready = True
    pieces = {
        square: piece.symbol()
        for square, piece in chess.Board().piece_map().items()
    }
    matcher.board_to_piece_map = Mock(return_value=(pieces, 0.9))

    board, status, turn_known = matcher.to_board(None, turn=np.bool_(True))

    assert board is not None
    assert board.turn is chess.WHITE
    assert turn_known
    assert "White to move" in status


def test_template_resync_does_not_guess_side_to_move():
    matcher = PieceTemplateMatcher()
    matcher.ready = True
    pieces = {
        square: piece.symbol()
        for square, piece in chess.Board().piece_map().items()
    }
    matcher.board_to_piece_map = Mock(return_value=(pieces, 0.9))

    board, status, turn_known = matcher.to_board(None)

    assert board is not None
    assert not turn_known
    assert "ambiguous" in status
    assert board.turn == chess.WHITE


def test_template_resync_infers_turn_when_only_one_is_legal():
    matcher = PieceTemplateMatcher()
    matcher.ready = True
    position = chess.Board(None)
    for square, symbol in {
        "e1": "K",
        "e8": "k",
        "e7": "R",
        "a2": "P",
        "b2": "P",
        "c2": "P",
        "a7": "p",
        "b7": "p",
    }.items():
        position.set_piece_at(chess.parse_square(square), chess.Piece.from_symbol(symbol))
    matcher.board_to_piece_map = Mock(
        return_value=(
            {square: piece.symbol() for square, piece in position.piece_map().items()},
            0.9,
        )
    )

    board, status, turn_known = matcher.to_board(None)

    assert board is not None
    assert turn_known
    assert board.turn == chess.BLACK
    assert "Black to move" in status


def test_unverified_saved_templates_are_not_loaded():
    with tempfile.TemporaryDirectory() as directory:
        store = Path(directory)
        (store / "meta.json").write_text(
            json.dumps({"pieces": {"P": ["missing.png"]}, "empty": []}),
            encoding="utf-8",
        )
        with patch.object(piece_templates, "STORE", store):
            matcher = PieceTemplateMatcher()

    assert not matcher.ready


def test_flat_empty_template_does_not_match_every_square_perfectly():
    matcher = PieceTemplateMatcher()
    empty_template = np.full((40, 40), 131, dtype=np.uint8)
    piece_cell = np.tile(np.arange(40, dtype=np.uint8), (40, 1))

    assert matcher._score(piece_cell, empty_template) < 1.0
    assert matcher._score(empty_template.copy(), empty_template) == 1.0


def test_template_matcher_recognizes_white_outlined_piece():
    matcher = PieceTemplateMatcher()
    silhouette = np.zeros((40, 40), dtype=np.uint8)
    knight = np.asarray(
        [
            (8, 29),
            (12, 20),
            (17, 15),
            (15, 8),
            (23, 8),
            (27, 16),
            (32, 24),
            (31, 34),
            (8, 34),
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(silhouette, [knight], 255)
    matcher.templates = {
        "N": [np.where(silhouette > 0, 0, 235).astype(np.uint8)]
    }
    matcher.ready = True

    target = np.full((40, 40, 3), (82, 149, 115), dtype=np.uint8)
    target[silhouette > 0] = (255, 255, 255)
    contours, _ = cv2.findContours(
        silhouette, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(target, contours, -1, (0, 0, 0), thickness=2)

    assert matcher.classify_square(target, color=True)[0] == "N"


def test_template_conflict_prefers_raw_bishop_match_over_pawn_silhouette():
    matcher = PieceTemplateMatcher()
    matcher.templates = {
        "P": [np.full((40, 40), 1, dtype=np.uint8)],
        "B": [np.full((40, 40), 2, dtype=np.uint8)],
    }
    matcher.ready = True
    matcher._score = Mock(
        side_effect=lambda _cell, template: {1: 0.26, 2: 0.40}[int(template[0, 0])]
    )

    with (
        patch.object(piece_templates, "_gray_norm", side_effect=lambda cell: cell),
        patch.object(
            piece_templates,
            "_shape_mask",
            side_effect=lambda cell: np.full((1, 1), int(cell.flat[0])),
        ),
        patch.object(
            piece_templates,
            "_shape_similarity",
            side_effect=lambda _shape, template: {1: 0.80, 2: 0.61}[
                int(template[0, 0])
            ],
        ),
    ):
        symbol, _ = matcher.classify_square(
            np.full((40, 40, 3), 9, dtype=np.uint8), color=True
        )

    assert symbol == "B"


def test_strong_king_silhouette_is_not_overridden_by_pawn_template():
    matcher = PieceTemplateMatcher()
    matcher.templates = {
        "P": [np.full((40, 40), 1, dtype=np.uint8)],
        "K": [np.full((40, 40), 2, dtype=np.uint8)],
    }
    matcher.ready = True
    matcher._score = Mock(
        side_effect=lambda _cell, template: {1: 0.36, 2: 0.25}[int(template[0, 0])]
    )

    with (
        patch.object(piece_templates, "_gray_norm", side_effect=lambda cell: cell),
        patch.object(
            piece_templates,
            "_shape_mask",
            side_effect=lambda cell: np.full((1, 1), int(cell.flat[0])),
        ),
        patch.object(
            piece_templates,
            "_shape_similarity",
            side_effect=lambda _shape, template: {1: 0.77, 2: 0.98}[
                int(template[0, 0])
            ],
        ),
    ):
        symbol, _ = matcher.classify_square(
            np.full((40, 40, 3), 9, dtype=np.uint8), color=True
        )

    assert symbol == "K"


def test_template_resync_rejects_unclassified_occupied_squares():
    matcher = PieceTemplateMatcher()
    matcher.ready = True
    matcher.board_to_piece_map = Mock(
        return_value=(
            {chess.E1: "K", chess.E8: "k"},
            0.9,
        )
    )
    occupancy = np.zeros((8, 8), dtype=np.int32)
    occupancy[0, 4] = 2
    occupancy[7, 4] = 1
    occupancy[3, 3] = 1

    with patch(
        "src.recognition.piece_templates.visual_occupancy",
        return_value=occupancy,
    ):
        board, status, turn_known = matcher.to_board(
            np.zeros((400, 400, 3), dtype=np.uint8)
        )

    assert board is None
    assert not turn_known
    assert "2/3 pieces classified" in status
    assert "d5" in status


def test_sync_moves_from_current_game_history():
    applied, status = sync_from_text(
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 Nf6 4. Nxe5 Nxe5"
    )
    tracker = GameTracker()
    move_count, error = tracker.set_from_sans(applied)

    assert applied == ["e4", "e5", "Nf3", "Nc6", "Bb5", "Nf6", "Nxe5", "Nxe5"]
    assert "White to move" in status
    assert move_count == 8
    assert error is None
    assert tracker.state.board.piece_at(chess.B5) == chess.Piece(chess.BISHOP, chess.WHITE)
    assert tracker.state.board.piece_at(chess.E5) == chess.Piece(chess.KNIGHT, chess.BLACK)


if __name__ == "__main__":
    test_visual_grid_classifies_piece_squares()
    test_move_detection_rejects_misaligned_board()
    test_move_detection_uses_last_stable_board()
    test_move_detection_tracks_both_players()
    test_no_match_keeps_current_position()
    test_resync_finds_exact_opening_position()
    test_template_resync_rejects_position_without_kings()
    test_unverified_saved_templates_are_not_loaded()
    test_sync_moves_from_current_game_history()
    print("test_board_sync: ALL PASSED")
