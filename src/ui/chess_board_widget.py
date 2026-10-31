"""Internal chess board: position + best-move arrows/highlights."""
from __future__ import annotations
from typing import List, Optional, Tuple
import chess
from PySide6.QtCore import Qt, QRect, QPointF, Signal
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPainterPath
from PySide6.QtWidgets import QMenu, QWidget

UNICODE = {
    "P": "♙", "N": "♘", "B": "♗", "R": "♖", "Q": "♕", "K": "♔",
    "p": "♟", "n": "♞", "b": "♝", "r": "♜", "q": "♛", "k": "♚",
}

LIGHT = QColor(240, 217, 181)
DARK = QColor(181, 136, 99)
BG = QColor(32, 34, 40)
PURPLE = QColor(155, 89, 182)
GREEN = QColor(46, 204, 113)


class ChessBoardWidget(QWidget):
    move_requested = Signal(object)
    position_edited = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280, 280)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(True)
        self._board = chess.Board()
        self._orientation = "white"  # side at bottom
        self._arrows: List[Tuple[str, str, QColor]] = []  # from,to,color
        self._highlights: List[Tuple[str, QColor]] = []
        self._last_move: Optional[Tuple[str, str]] = None
        self._selected_square: Optional[chess.Square] = None
        self._pressed_square: Optional[chess.Square] = None
        self._dragging = False
        self._mouse_pos = QPointF()
        self._edit_mode = False

    @property
    def edit_mode(self) -> bool:
        return self._edit_mode

    def set_edit_mode(self, enabled: bool):
        self._edit_mode = bool(enabled)
        self._selected_square = None
        self._pressed_square = None
        self._dragging = False
        self.update()

    def edit_square(self, square: chess.Square, piece_symbol: Optional[str] = None):
        if not self._edit_mode:
            return
        piece = chess.Piece.from_symbol(piece_symbol) if piece_symbol else None
        self._board.set_piece_at(square, piece)
        self._board.castling_rights = 0
        self._commit_position_edit()

    def edit_set_turn(self, turn: bool):
        if not self._edit_mode or self._board.turn == turn:
            return
        self._board.turn = turn
        self._commit_position_edit(clear_castling=False)

    def _commit_position_edit(self, clear_castling: bool = True):
        if clear_castling:
            self._board.castling_rights = 0
        self._board.ep_square = None
        self._board.halfmove_clock = 0
        self._board.fullmove_number = 1
        self._board.clear_stack()
        self._fen = self._board.fen()
        self.update()
        self.position_edited.emit(self._board.copy())

    def _show_edit_menu(self, square: chess.Square, global_pos):
        self._create_edit_menu(square).exec(global_pos)

    def _create_edit_menu(self, square: chess.Square) -> QMenu:
        menu = QMenu(self)
        remove_action = menu.addAction("Remove piece")
        remove_action.setEnabled(self._board.piece_at(square) is not None)
        remove_action.triggered.connect(lambda: self.edit_square(square))

        for color, label in ((chess.WHITE, "Add white piece"), (chess.BLACK, "Add black piece")):
            submenu = menu.addMenu(label)
            for piece_type, name in (
                (chess.QUEEN, "Queen"),
                (chess.ROOK, "Rook"),
                (chess.BISHOP, "Bishop"),
                (chess.KNIGHT, "Knight"),
                (chess.PAWN, "Pawn"),
                (chess.KING, "King"),
            ):
                piece = chess.Piece(piece_type, color)
                action = submenu.addAction(f"{UNICODE[piece.symbol()]}  {name}")
                action.triggered.connect(
                    lambda checked=False, symbol=piece.symbol(): self.edit_square(
                        square, symbol
                    )
                )

        turn_menu = menu.addMenu("Set side to move")
        for turn, label in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
            action = turn_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(self._board.turn == turn)
            action.triggered.connect(
                lambda checked=False, side=turn: self.edit_set_turn(side)
            )
        return menu

    def set_board(self, board: chess.Board):
        fen = board.fen()
        if getattr(self, "_fen", None) == fen:
            return
        self._fen = fen
        self._board = board.copy()
        self.update()

    def set_orientation(self, orientation: str):
        if orientation in ("white", "black"):
            self._orientation = orientation
            self.update()

    def set_analysis_arrows(self, best_uci: Optional[str], alt_uci: Optional[List[str]] = None):
        self._arrows = []
        self._highlights = []
        if best_uci and len(best_uci) >= 4:
            frm, to = best_uci[:2], best_uci[2:4]
            self._arrows.append((frm, to, PURPLE))
            self._highlights.append((frm, QColor(155, 89, 182, 100)))
            self._highlights.append((to, QColor(46, 204, 113, 120)))
        if alt_uci:
            for i, u in enumerate(alt_uci[:2]):
                if u and len(u) >= 4:
                    self._arrows.append((u[:2], u[2:4], QColor(142, 68, 173, 140 - i * 30)))
        self.update()

    def clear_analysis(self):
        self._arrows = []
        self._highlights = []
        self.update()

    def set_last_move(self, uci: Optional[str]):
        if uci and len(uci) >= 4:
            self._last_move = (uci[:2], uci[2:4])
        else:
            self._last_move = None
        self.update()

    def _sq_rect(self, square: str, tile: int, ox: int, oy: int) -> QRect:
        file = ord(square[0]) - ord("a")
        rank = int(square[1]) - 1
        if self._orientation == "white":
            col, row = file, 7 - rank
        else:
            col, row = 7 - file, rank
        return QRect(ox + col * tile, oy + row * tile, tile, tile)

    def _board_geometry(self) -> Tuple[int, int, int]:
        side = min(self.width(), self.height()) - 8
        tile = side // 8
        board_px = tile * 8
        ox = (self.width() - board_px) // 2
        oy = (self.height() - board_px) // 2
        return tile, ox, oy

    def _square_at(self, pos) -> Optional[chess.Square]:
        tile, ox, oy = self._board_geometry()
        col = int(pos.x() - ox) // tile
        row = int(pos.y() - oy) // tile
        if not (0 <= col < 8 and 0 <= row < 8):
            return None
        if self._orientation == "white":
            file, rank = col, 7 - row
        else:
            file, rank = 7 - col, row
        return chess.square(file, rank)

    def _legal_move(self, from_square: chess.Square, to_square: chess.Square):
        moves = [
            move for move in self._board.legal_moves
            if move.from_square == from_square and move.to_square == to_square
        ]
        if not moves:
            return None
        return next((move for move in moves if move.promotion == chess.QUEEN), moves[0])

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self._edit_mode:
            square = self._square_at(event.position())
            if square is not None:
                self._show_edit_menu(square, event.globalPosition().toPoint())
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        square = self._square_at(event.position())
        self._pressed_square = square
        self._dragging = False
        if square is None:
            self._selected_square = None
            self.update()
            return

        if self._edit_mode:
            self._selected_square = (
                square if self._board.piece_at(square) is not None else None
            )
            self._mouse_pos = event.position()
            self.update()
            return

        if self._selected_square is not None and square != self._selected_square:
            self._dragging = True
            self._mouse_pos = event.position()
            return

        piece = self._board.piece_at(square)
        if piece is not None and piece.color == self._board.turn:
            self._selected_square = square
        else:
            self._selected_square = None
        self.update()

    def mouseMoveEvent(self, event):
        if self._selected_square is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._dragging = True
            self._mouse_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        target = self._square_at(event.position())
        source = self._selected_square
        if self._edit_mode:
            if source is not None and target is not None and source != target:
                piece = self._board.piece_at(source)
                if piece is not None:
                    self._board.remove_piece_at(source)
                    self._board.set_piece_at(target, piece)
                    self._commit_position_edit()
            self._selected_square = None
            self._pressed_square = None
            self._dragging = False
            self.update()
            return

        if source is not None and target is not None and source != target:
            move = self._legal_move(source, target)
            if move is not None:
                self.move_requested.emit(move)
        elif target is not None and self._board.piece_at(target) is not None:
            piece = self._board.piece_at(target)
            if piece and piece.color == self._board.turn:
                self._selected_square = target
                self.update()
                return

        self._selected_square = None
        self._pressed_square = None
        self._dragging = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), BG)
        tile, ox, oy = self._board_geometry()
        board_px = tile * 8

        # squares
        for r in range(8):
            for c in range(8):
                light = (r + c) % 2 == 0
                p.fillRect(ox + c * tile, oy + r * tile, tile, tile, LIGHT if light else DARK)

        # analysis highlights
        for sq, col in self._highlights:
            p.fillRect(self._sq_rect(sq, tile, ox, oy), col)

        # Keep the actual last move visible even when analysis highlights overlap it.
        if self._last_move:
            for sq in self._last_move:
                rect = self._sq_rect(sq, tile, ox, oy)
                p.fillRect(rect, QColor(255, 255, 0, 125))

        # pieces
        font = QFont("Segoe UI Symbol", max(14, int(tile * 0.65)))
        p.setFont(font)
        for sq in chess.SQUARES:
            piece = self._board.piece_at(sq)
            if not piece:
                continue
            if sq == self._selected_square and self._dragging:
                continue
            name = piece.symbol()
            ch = UNICODE.get(name, name)
            rect = self._sq_rect(chess.square_name(sq), tile, ox, oy)
            p.setPen(QColor(30, 30, 30) if piece.color == chess.WHITE else QColor(15, 15, 15))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, ch)

        if self._selected_square is not None:
            selected = self._sq_rect(
                chess.square_name(self._selected_square), tile, ox, oy
            )
            p.setPen(QPen(QColor(255, 215, 0), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(selected)
        if self._dragging and self._selected_square is not None:
            piece = self._board.piece_at(self._selected_square)
            if piece is not None:
                p.setFont(QFont("Segoe UI Symbol", max(14, int(tile * 0.65))))
                p.setPen(QColor(30, 30, 30) if piece.color else QColor(15, 15, 15))
                rect = QRect(
                    int(self._mouse_pos.x() - tile / 2),
                    int(self._mouse_pos.y() - tile / 2),
                    tile,
                    tile,
                )
                p.drawText(rect, Qt.AlignmentFlag.AlignCenter, UNICODE[piece.symbol()])

        # arrows
        for frm, to, col in self._arrows:
            self._draw_arrow(p, frm, to, col, tile, ox, oy)

        # frame
        p.setPen(QPen(QColor(241, 196, 15) if self._edit_mode else PURPLE, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(ox, oy, board_px, board_px)

    def _draw_arrow(self, p: QPainter, frm: str, to: str, col: QColor, tile: int, ox: int, oy: int):
        a = self._sq_rect(frm, tile, ox, oy).center()
        b = self._sq_rect(to, tile, ox, oy).center()
        pen = QPen(col, max(3, tile // 10), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(QBrush(col))
        p.drawLine(a, b)
        # arrow head
        import math
        ang = math.atan2(b.y() - a.y(), b.x() - a.x())
        size = tile * 0.28
        p1 = QPointF(b.x() - size * math.cos(ang - 0.4), b.y() - size * math.sin(ang - 0.4))
        p2 = QPointF(b.x() - size * math.cos(ang + 0.4), b.y() - size * math.sin(ang + 0.4))
        path = QPainterPath()
        path.moveTo(b)
        path.lineTo(p1)
        path.lineTo(p2)
        path.closeSubpath()
        p.drawPath(path)
