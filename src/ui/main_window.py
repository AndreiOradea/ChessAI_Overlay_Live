"""Main always-on-top window: internal board mirrors screen game + analysis."""
from __future__ import annotations
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QThread, QObject, Signal, Slot, QPoint
from PySide6.QtGui import QGuiApplication, QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QListWidget, QSpinBox, QCheckBox, QLineEdit, QApplication, QFrame,
)

import chess

from src.utils.config import AppConfig, save_config
from src.utils.screen_capture import ScreenCapture
from src.chess.game_tracker import GameTracker
from src.chess.move_list_sync import sync_from_text
from src.recognition.move_diff import MoveDiffTracker
from src.recognition.board_sync import resync_board, mismatch, visual_occupancy
from src.recognition.piece_templates import PieceTemplateMatcher
from src.engine.stockfish_wrapper import StockfishEngine, AnalysisResult
from src.ui.chess_board_widget import ChessBoardWidget

PURPLE = "#9B59B6"
BG = "#1a1b20"
CARD = "#25262e"
TEXT = "#ECECF1"
GREEN = "#2ECC71"
YELLOW = "#F1C40F"
RED = "#E74C3C"


class AnalysisWorker(QObject):
    done = Signal(object)

    def __init__(self, engine: StockfishEngine, fen: str, depth: int, ms: int):
        super().__init__()
        self.engine, self.fen, self.depth, self.ms = engine, fen, depth, ms

    @Slot()
    def run(self):
        self.done.emit(self.engine.analyze(self.fen, depth=self.depth, movetime_ms=self.ms, multipv=3))


class RegionSelector(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        screen = QGuiApplication.primaryScreen()
        vg = screen.virtualGeometry() if screen else QGuiApplication.screens()[0].geometry()
        self.setGeometry(vg)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._o = self._c = None
        self.region = (0, 0, 0, 0)
        self._ok = False
        tip = QLabel("Drag around the LIVE chessboard only.\nEsc = cancel", self)
        tip.setStyleSheet("color:white;background:rgba(0,0,0,180);padding:10px;font-size:16px;")
        tip.adjustSize()
        tip.move(max(20, (vg.width() - tip.width()) // 2), 40)

    def exec_select(self) -> bool:
        self.show()
        self.raise_()
        from PySide6.QtCore import QEventLoop
        self._loop = QEventLoop()
        self._loop.exec()
        return self._ok

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._o = self._c = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._o is not None:
            self._c = e.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._o and self._c:
            x1, y1 = min(self._o.x(), self._c.x()), min(self._o.y(), self._c.y())
            x2, y2 = max(self._o.x(), self._c.x()), max(self._o.y(), self._c.y())
            w, h = x2 - x1, y2 - y1
            if w > 60 and h > 60:
                self.region = (x1, y1, w, h)
                self._ok = True
            self._loop.quit()
            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._ok = False
            self._loop.quit()
            self.close()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 70))
        if self._o and self._c:
            x1, y1 = min(self._o.x(), self._c.x()), min(self._o.y(), self._c.y())
            x2, y2 = max(self._o.x(), self._c.x()), max(self._o.y(), self._c.y())
            tl = self.mapFromGlobal(QPoint(x1, y1))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(tl.x(), tl.y(), x2 - x1, y2 - y1, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(155, 89, 182), 3))
            p.setBrush(QBrush(QColor(155, 89, 182, 40)))
            p.drawRect(tl.x(), tl.y(), x2 - x1, y2 - y1)


class MainWindow(QWidget):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.tracker = GameTracker()
        self.tracker.state.orientation = config.board_orientation
        self.move_diff = MoveDiffTracker()
        self.templates = PieceTemplateMatcher()
        self.move_diff.set_orientation(config.board_orientation)
        self.capture = ScreenCapture()
        self.engine = StockfishEngine(config.engine.path)
        self._paused = False
        self._analyzing = False
        self._last_fen_analyzed = ""
        self._thread: Optional[QThread] = None
        self._worker = None
        self._analysis_fen = ""
        self._drag = None
        self._last_img = None

        self.setWindowTitle("ChessAI Board LIVE")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(f"""
            QWidget {{ background: {BG}; color: {TEXT}; font-family: Segoe UI; font-size: 12px; }}
            QFrame#card {{ background: {CARD}; border-radius: 8px; }}
            QPushButton {{ background: #333; border: 1px solid #444; padding: 6px 10px; border-radius: 6px; }}
            QPushButton:hover {{ border-color: {PURPLE}; }}
            QPushButton#accent {{ background: {PURPLE}; border: none; font-weight: 600; }}
            QComboBox, QSpinBox, QLineEdit {{ background: #1e1f26; border: 1px solid #444; padding: 4px; border-radius: 4px; }}
            QListWidget {{ background: #1e1f26; border: 1px solid #333; border-radius: 4px; }}
            QLabel#eval {{ color: {GREEN}; font-size: 22px; font-weight: 700; }}
            QLabel#best {{ color: {PURPLE}; font-size: 14px; font-weight: 600; }}
            QLabel#status {{ color: #aaa; }}
        """)
        self.resize(340, 720)
        self.move(config.pos_x, config.pos_y)
        self.setWindowOpacity(config.opacity)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # header
        head = QHBoxLayout()
        title = QLabel("ChessAI Board LIVE")
        title.setStyleSheet(f"font-weight:700;color:{PURPLE};font-size:14px;")
        head.addWidget(title)
        head.addStretch()
        self.lbl_dot = QLabel("●")
        self.lbl_dot.setStyleSheet(f"color:{YELLOW};")
        head.addWidget(self.lbl_dot)
        for txt, slot in [("–", self.showMinimized), ("✕", self.close)]:
            b = QPushButton(txt)
            b.setFixedWidth(28)
            b.clicked.connect(slot)
            head.addWidget(b)
        root.addLayout(head)

        self.lbl_status = QLabel("Select board region, then play")
        self.lbl_status.setObjectName("status")
        root.addWidget(self.lbl_status)

        # controls
        row = QHBoxLayout()
        row.addWidget(QLabel("Mode"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["LIVE", "LIVE ENGINE"])
        self.cmb_mode.setCurrentText(config.mode if config.mode in ("LIVE", "LIVE ENGINE") else "LIVE ENGINE")
        row.addWidget(self.cmb_mode)
        row.addWidget(QLabel("I play"))
        self.cmb_color = QComboBox()
        self.cmb_color.addItems(["White", "Black"])
        self.cmb_color.setCurrentText("White" if config.my_color == "white" else "Black")
        row.addWidget(self.cmb_color)
        root.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_region = QPushButton("Select Board Region")
        self.btn_region.setObjectName("accent")
        row2.addWidget(self.btn_region)
        self.btn_flip = QPushButton("Flip")
        row2.addWidget(self.btn_flip)
        self.btn_reset = QPushButton("Reset")
        row2.addWidget(self.btn_reset)
        root.addLayout(row2)

        # INTERNAL BOARD
        board_frame = QFrame()
        board_frame.setObjectName("card")
        bl = QVBoxLayout(board_frame)
        bl.setContentsMargins(6, 6, 6, 6)
        self.board_view = ChessBoardWidget()
        self.board_view.set_orientation(config.board_orientation)
        self.board_view.move_requested.connect(self._on_internal_move)
        self.board_view.position_edited.connect(self._on_position_edited)
        self.btn_edit_position = QPushButton("Edit Position")
        self.btn_edit_position.setToolTip(
            "Drag any piece to move it. Right-click a square to add/remove a piece or set the turn."
        )
        bl.addWidget(self.btn_edit_position)
        bl.addWidget(self.board_view)
        root.addWidget(board_frame, stretch=1)

        # eval panel
        eval_frame = QFrame()
        eval_frame.setObjectName("card")
        el = QVBoxLayout(eval_frame)
        self.lbl_eval = QLabel("—")
        self.lbl_eval.setObjectName("eval")
        self.lbl_eval.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(self.lbl_eval)
        self.lbl_best = QLabel("BEST: —")
        self.lbl_best.setObjectName("best")
        self.lbl_best.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.addWidget(self.lbl_best)
        self.lst_lines = QListWidget()
        self.lst_lines.setMaximumHeight(72)
        el.addWidget(self.lst_lines)
        root.addWidget(eval_frame)

        # game moves
        self.lbl_turn = QLabel("Turn: White | Moves: 0")
        root.addWidget(self.lbl_turn)
        self.lst_moves = QListWidget()
        self.lst_moves.setMaximumHeight(90)
        root.addWidget(self.lst_moves)

        # sync
        sync_row = QHBoxLayout()
        self.txt_moves = QLineEdit()
        self.txt_moves.setPlaceholderText(
            "Paste moves, e.g. 1. e4 e5 2. Nf3 Nc6, then click Sync"
        )
        sync_row.addWidget(self.txt_moves)
        self.btn_sync = QPushButton("Sync")
        sync_row.addWidget(self.btn_sync)
        root.addLayout(sync_row)

        # engine controls
        eng = QHBoxLayout()
        eng.addWidget(QLabel("Depth (engine)"))
        self.spn_depth = QSpinBox()
        self.spn_depth.setRange(6, 30)
        self.spn_depth.setValue(config.engine.depth)
        eng.addWidget(self.spn_depth)
        eng.addWidget(QLabel("ms"))
        self.spn_ms = QSpinBox()
        self.spn_ms.setRange(100, 5000)
        self.spn_ms.setValue(config.engine.movetime_ms)
        eng.addWidget(self.spn_ms)
        root.addLayout(eng)

        row3 = QHBoxLayout()
        self.btn_resync = QPushButton("Resync Board")
        row3.addWidget(self.btn_resync)
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze.setObjectName("accent")
        row3.addWidget(self.btn_analyze)
        self.btn_stop = QPushButton("Stop")
        row3.addWidget(self.btn_stop)
        root.addLayout(row3)

        # timers
        self.timer_cap = QTimer(self)
        self.timer_cap.timeout.connect(self._tick_capture)
        self.timer_cap.start(250)
        self.timer_eng = QTimer(self)
        self.timer_eng.timeout.connect(self._tick_engine)
        self.timer_eng.setInterval(1200)

        # signals
        self.btn_region.clicked.connect(self._select_region)
        self.btn_flip.clicked.connect(self._flip)
        self.btn_reset.clicked.connect(self._reset)
        self.btn_sync.clicked.connect(self._sync_moves)
        self.btn_analyze.clicked.connect(self._analyze_now)
        self.btn_resync.clicked.connect(self._on_resync_clicked)
        self.btn_stop.clicked.connect(self._stop_engine)
        self.btn_edit_position.clicked.connect(self._toggle_position_edit)
        self.cmb_mode.currentTextChanged.connect(self._on_mode)
        self.cmb_color.currentTextChanged.connect(self._on_color)

        self._refresh()
        self._on_mode(self.cmb_mode.currentText())

    # —— drag ——
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag and e.buttons() & Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None

    def _my_color(self) -> str:
        return "white" if self.cmb_color.currentText().lower().startswith("w") else "black"

    def _is_my_turn(self) -> bool:
        return (self.tracker.state.board.turn == chess.WHITE) == (self._my_color() == "white")

    def _turn_label(self) -> str:
        side = self.tracker.side_to_move()
        owner = "your turn" if self._is_my_turn() else "opponent's turn"
        return f"{side} to move ({owner})"

    def _select_region(self):
        self.hide()
        QApplication.processEvents()
        time.sleep(0.15)
        sel = RegionSelector()
        if sel.exec_select():
            x, y, w, h = sel.region
            self.config.board_region.x, self.config.board_region.y = x, y
            self.config.board_region.width, self.config.board_region.height = w, h
            self.config.board_region.calibrated = True
            save_config(self.config)
            self.move_diff.reset()
            img = self.capture.capture_region(x, y, w, h)
            learn_msg = "Could not read board; current position kept"
            if img is not None:
                try:
                    vis = visual_occupancy(img)
                    start_position = (
                        vis is not None
                        and mismatch(
                            chess.Board(), vis, self.config.board_orientation
                        ) == 0
                    )
                    if start_position:
                        self.tracker.reset(
                            chess.STARTING_FEN, self.config.board_orientation
                        )
                        learn_msg = self.templates.learn_from_start_position(
                            img, self.config.board_orientation
                        )
                    else:
                        learn_msg = (
                            "Not the starting position; current board/templates kept"
                        )
                    self.move_diff.force_snapshot(img)
                except Exception as e:
                    learn_msg = f"Template learn: {e}"
            self.board_view.set_orientation(self.config.board_orientation)
            self.board_view.clear_analysis()
            self.board_view.set_last_move(None)
            self.board_view.set_board(self.tracker.state.board)
            self._refresh()
            self.lbl_status.setText(
                f"Region {w}×{h} · {learn_msg}"
            )
            self.lbl_dot.setStyleSheet(f"color:{GREEN};")
        self.show()
        self.raise_()

    def _flip(self):
        o = "black" if self.config.board_orientation == "white" else "white"
        self.config.board_orientation = o
        self.tracker.state.orientation = o
        self.move_diff.set_orientation(o)
        self.move_diff.reset()
        self.board_view.set_orientation(o)
        save_config(self.config)
        self.lbl_status.setText(f"Orientation: {o} at bottom")

    def _reset(self):
        was_editing = self.board_view.edit_mode
        if self.board_view.edit_mode:
            self._set_position_edit_mode(False, resume_engine=False)
        self.tracker.reset(chess.STARTING_FEN, self.config.board_orientation)
        self.move_diff.reset()
        self.board_view.clear_analysis()
        self.board_view.set_last_move(None)
        self._last_fen_analyzed = ""
        self._refresh()
        self.lbl_status.setText("Reset to start")
        if was_editing:
            self._paused = False
        if self.cmb_mode.currentText() == "LIVE ENGINE" and not self._paused:
            self._request_analysis()

    def _on_color(self, label: str):
        self.config.my_color = "white" if label.lower().startswith("w") else "black"
        want = self.config.my_color
        if self.config.board_orientation != want:
            self.config.board_orientation = want
            self.move_diff.set_orientation(want)
            self.tracker.state.orientation = want
            self.board_view.set_orientation(want)
        save_config(self.config)
        self._refresh()
        self.lbl_status.setText(f"You play {label}")

    def _on_mode(self, mode: str):
        self.config.mode = mode
        save_config(self.config)
        if mode == "LIVE ENGINE":
            self._paused = False
            self.timer_eng.start()
            self.lbl_status.setText(f"LIVE ENGINE – {self._turn_label()}")
            self._request_analysis()
        else:
            self.timer_eng.stop()
            self.board_view.clear_analysis()
            self.lbl_eval.setText("—")
            self.lbl_best.setText("BEST: — (engine off)")
            self.lst_lines.clear()
            self.lbl_status.setText("LIVE – tracking only, no engine")

    def _stop_engine(self):
        self._paused = True
        self.timer_eng.stop()
        self._analyzing = False
        self.engine.stop()
        self.board_view.clear_analysis()
        self.lbl_status.setText("Engine stopped")

    def _on_resync_clicked(self):
        """Read the screen position without leaving stale engine lines visible."""
        if self.board_view.edit_mode:
            self._set_position_edit_mode(False, resume_engine=False)
        ok = self._resync_from_screen()
        if ok and self.cmb_mode.currentText() == "LIVE ENGINE":
            self._paused = False
            self.timer_eng.start()
            self._request_analysis(force=True)

    def _toggle_position_edit(self):
        self._set_position_edit_mode(not self.board_view.edit_mode)

    def _set_position_edit_mode(self, enabled: bool, resume_engine: bool = True):
        self.board_view.set_edit_mode(enabled)
        self.btn_edit_position.setText(
            "Finish Editing" if enabled else "Edit Position"
        )
        if enabled:
            self._paused = True
            self.timer_eng.stop()
            self.engine.stop()
            self.board_view.clear_analysis()
            self.lbl_eval.setText("—")
            self.lbl_best.setText("BEST: —")
            self.lst_lines.clear()
            self.lbl_status.setText(
                "Edit mode: drag pieces; right-click a square to add/remove pieces or set the turn"
            )
        else:
            self.move_diff.reset()
            if (
                resume_engine
                and self.cmb_mode.currentText() == "LIVE ENGINE"
            ):
                self._paused = False
                self.timer_eng.start()
                self._request_analysis(force=True)
            else:
                self.lbl_status.setText("Position editing finished")

    def _on_position_edited(self, board: chess.Board):
        self.tracker.state.board = board.copy()
        self.tracker.state.moves = []
        self._last_fen_analyzed = ""
        self.board_view.set_last_move(None)
        self.board_view.clear_analysis()
        self.lbl_eval.setText("—")
        self.lbl_best.setText("BEST: —")
        self.lst_lines.clear()
        self._refresh()
        if board.is_valid():
            self.lbl_status.setText(
                f"Position updated · {self._turn_label()} · move history cleared"
            )
        else:
            self.lbl_status.setText(
                f"Position updated · {self._turn_label()} · incomplete/invalid position; finish editing before analysis"
            )

    def _on_internal_move(self, move: chess.Move):
        ok, san = self.tracker.apply_move(move)
        if not ok:
            self.lbl_status.setText(f"Illegal move: {san}")
            self.board_view.update()
            return
        self.board_view.set_last_move(move.uci())
        self.board_view.clear_analysis()
        self._last_fen_analyzed = ""
        self._refresh()
        self.lbl_status.setText(f"Internal move {san}")
        if self.cmb_mode.currentText() == "LIVE ENGINE":
            self._paused = False
            self.timer_eng.start()
            self._request_analysis(force=True)

    def _analyze_now(self):

        """Run Stockfish on the CURRENT internal board only (never clears pieces)."""
        if self.board_view.edit_mode:
            self.lbl_status.setText("Finish position editing before analysis")
            return
        if not self.tracker.state.board.is_valid():
            self.lbl_status.setText(
                "Position is incomplete or invalid; edit the board before analysis"
            )
            return
        self._paused = False
        if self.cmb_mode.currentText() == "LIVE ENGINE" and not self.timer_eng.isActive():
            self.timer_eng.start()
        self.config.engine.depth = self.spn_depth.value()
        self.config.engine.movetime_ms = self.spn_ms.value()
        try:
            save_config(self.config)
        except Exception:
            pass
        n = len(self.tracker.state.board.piece_map())
        if n < 2:
            self.lbl_status.setText("Board empty – play moves or press Resync Board")
            return
        self.lbl_status.setText(f"Analyzing ({n} pieces, depth {self.spn_depth.value()})…")
        self._request_analysis(force=True)

    def _resync_from_screen(self) -> bool:
        """Screenshot selected region → recognize each Classic piece → internal board."""
        r = self.config.board_region
        if not r.calibrated:
            self.lbl_status.setText("Select Board Region first")
            return False
        self.lbl_status.setText("Screenshot + matching Classic pieces…")
        QApplication.processEvents()
        img = self.capture.capture_region(r.x, r.y, r.width, r.height)
        if img is None:
            self.lbl_status.setText("Capture failed")
            return False
        self._last_img = img

        template_warning = ""
        # 1) Prefer template matching (per-piece photos from start position)
        if self.templates.ready:
            try:
                new_board, status, turn_known = self.templates.to_board(
                    img, self.config.board_orientation
                )
                n_pieces = len(new_board.piece_map()) if new_board else 0
                if new_board is not None and 8 <= n_pieces <= 32:
                    if new_board.board_fen() == self.tracker.state.board.board_fen():
                        self.move_diff.force_snapshot(img)
                        self._refresh()
                        self.lbl_status.setText(
                            f"Screen matches current position · {self._turn_label()}"
                        )
                        return True
                    if turn_known:
                        new_board.castling_rights = 0
                        self.tracker.state.board = new_board
                        self.tracker.state.moves = []
                        self.move_diff.force_snapshot(img)
                        self.board_view.set_last_move(None)
                        self.board_view.clear_analysis()
                        self._last_fen_analyzed = ""
                        self._refresh()
                        self.lbl_status.setText(
                            f"{status} · history reset; verify the move list"
                        )
                        return True
                    template_warning = (
                        "Piece placement recognized, but side to move is ambiguous. "
                        "Previous position kept; sync the full move list."
                    )
                    print(f"[resync-templates] {template_warning}")
                else:
                    template_warning = (
                        f"{status}. Use Edit Position to correct the pieces manually."
                    )
                    self.lbl_status.setText(status + " · keeping previous board")
                    print(f"[resync-templates] reject: {status}")
            except Exception as e:
                template_warning = f"Template recognition failed: {e}"
                print(f"[templates] {e}")

        # 2) Fallback: occupancy beam search
        try:
            new_board, moves, mm, status = resync_board(
                self.tracker.state.board,
                img,
                orientation=self.config.board_orientation,
                max_depth=2,
            )
        except Exception as e:
            self.lbl_status.setText(f"Resync error: {e}")
            return False

        if mm != 0:
            self._paused = True
            self.timer_eng.stop()
            self.engine.stop()
            self.board_view.clear_analysis()
            self.lbl_eval.setText("—")
            self.lbl_best.setText("BEST: —")
            self.lst_lines.clear()
            self.lbl_status.setText(
                f"{template_warning or status} Paste the full move list below and press Sync."
            )
            return False

        n_new = len(new_board.piece_map()) if new_board else 0
        if n_new < 8:
            self.lbl_status.setText(status + " · board unchanged (too few pieces)")
            return False
        from_start = "from starting position" in status
        if from_start:
            self.tracker.reset(chess.STARTING_FEN, self.config.board_orientation)
        for move in moves:
            ok, _ = self.tracker.apply_move(move)
            if not ok:
                self.tracker.state.board = new_board.copy()
                self.tracker.state.moves = []
                break
        if self.tracker.state.board.fen() != new_board.fen():
            self.tracker.state.board = new_board.copy()
            if not from_start:
                self.tracker.state.moves = []

        try:
            self.move_diff.force_snapshot(img)
        except Exception:
            pass
        self.board_view.set_board(self.tracker.state.board)
        self.board_view.set_last_move(moves[-1].uci() if moves else None)
        self.board_view.clear_analysis()
        self._last_fen_analyzed = ""
        self._refresh()
        n = len(self.tracker.state.moves)
        last = self.tracker.state.moves[-1].san if n else "—"
        self.lbl_status.setText(status)
        self.lbl_turn.setText(f"{self._turn_label()} | Last: {last} | Moves: {n}")
        return mm <= 4

    def _sync_moves(self):
        if self.board_view.edit_mode:
            self._set_position_edit_mode(False, resume_engine=False)
        raw = self.txt_moves.text().strip() or QApplication.clipboard().text().strip()
        if not raw:
            self.lbl_status.setText("Paste moves or copy from Chess.com first")
            return
        applied, msg = sync_from_text(raw)
        if not applied:
            self.lbl_status.setText(msg)
            return
        n, err = self.tracker.set_from_sans(applied)
        self.move_diff.reset()
        if self._last_img is not None:
            self.move_diff.force_snapshot(self._last_img)
        self._refresh()
        self.lbl_status.setText(msg if not err else f"{msg} ({err})")
        if self.cmb_mode.currentText() == "LIVE ENGINE":
            self._paused = False
            self.timer_eng.start()
            self._request_analysis(force=True)

    def _tick_capture(self):
        if self.board_view.edit_mode:
            return
        r = self.config.board_region
        if not r.calibrated:
            self.lbl_dot.setStyleSheet(f"color:{RED};")
            return
        img = self.capture.capture_region(r.x, r.y, r.width, r.height)
        if img is None:
            return
        self._last_img = img
        self.lbl_dot.setStyleSheet(f"color:{GREEN};")
        try:
            move = self.move_diff.detect_move(img, self.tracker.state.board)
        except Exception:
            move = None
        if move is None:
            return
        ok, san = self.tracker.apply_move(move)
        if not ok:
            return
        self.move_diff.force_snapshot(img)
        self.board_view.set_board(self.tracker.state.board)
        self.board_view.set_last_move(move.uci())
        self._refresh()
        # Always update status; analysis draws BEST on the INTERNAL board
        self.lbl_status.setText(f"Move {san} · {self._turn_label()}")
        if self.cmb_mode.currentText() == "LIVE ENGINE" and not self._paused:
            self._request_analysis(force=True)

    def _tick_engine(self):
        if self._paused or self.cmb_mode.currentText() != "LIVE ENGINE":
            return
        if self._analyzing:
            return
        self._request_analysis()

    def _request_analysis(self, force: bool = False):
        if self.board_view.edit_mode:
            return
        if self.cmb_mode.currentText() != "LIVE ENGINE":
            return
        if self._paused and not force:
            return
        board = self.tracker.state.board
        if not board.is_valid():
            self.board_view.clear_analysis()
            self.lbl_eval.setText("—")
            self.lbl_best.setText("BEST: — (invalid position)")
            self.lst_lines.clear()
            self.lbl_status.setText(
                "Position is incomplete or invalid; edit it before engine analysis"
            )
            return
        fen = board.fen()
        if not force and fen == self._last_fen_analyzed:
            return
        if self._analyzing:
            return
        if not self.engine.ready:
            if not self.engine.start(self.config.engine.threads, self.config.engine.hash_mb):
                self.lbl_status.setText("Stockfish not found – put stockfish*.exe in stockfish\\ folder (or Desktop\\stockfish)")
                return
        self._analyzing = True
        self._last_fen_analyzed = fen
        self._analysis_fen = fen
        self.lbl_status.setText("Analyzing…")
        self._thread = QThread()
        self._worker = AnalysisWorker(self.engine, fen, self.spn_depth.value(), self.spn_ms.value())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_analysis)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._engine_thread_done)
        self._thread.start()

    def _engine_thread_done(self):
        self._analyzing = False
        self._thread = None
        self._worker = None
        if (
            not self._paused
            and self.cmb_mode.currentText() == "LIVE ENGINE"
            and self.tracker.state.board.fen() != self._analysis_fen
        ):
            self._request_analysis(force=True)

    @Slot(object)
    def _on_analysis(self, result: AnalysisResult):
        self._analyzing = False
        if (
            self._paused
            or self._analysis_fen != self.tracker.state.board.fen()
        ):
            return
        if result.error:
            err = str(result.error)
            self.lbl_status.setText(err)
            if "event loop" in err.lower() or "dead" in err.lower():
                try:
                    self.engine.stop()
                    self.engine.start(self.config.engine.threads, self.config.engine.hash_mb)
                    self.lbl_status.setText("Engine restarted – press Analyze again")
                except Exception:
                    pass
            return
        self.lbl_eval.setText(result.evaluation or "—")
        self.lbl_best.setText(f"BEST: {result.best_san or '—'}")
        self.lst_lines.clear()
        alts = []
        for line in result.lines[:3]:
            sc = f"M{line.score_mate}" if line.score_mate is not None else (
                f"{line.score_cp/100:+.2f}" if line.score_cp is not None else "?"
            )
            pv = " ".join(line.pv_san[:6])
            self.lst_lines.addItem(f"{'★' if line.rank==1 else line.rank} {sc}  {pv}")
            if line.rank > 1 and line.pv_uci:
                alts.append(line.pv_uci[0])
        # Draw on INTERNAL board
        self.board_view.set_analysis_arrows(result.best_uci, alts)
        self.lbl_status.setText("Analysis ready")

    def _refresh(self):
        b = self.tracker.state.board
        self.board_view.set_board(b)
        side = self.tracker.side_to_move()
        n = len(self.tracker.state.moves)
        last = self.tracker.state.moves[-1].san if n else "—"
        self.lbl_turn.setText(f"{self._turn_label()} | Last: {last} | Moves: {n}")
        self.lst_moves.clear()
        for line in self.tracker.history_pairs():
            self.lst_moves.addItem(line)
        self.lst_moves.scrollToBottom()

    def closeEvent(self, e):
        self.timer_cap.stop()
        self.timer_eng.stop()
        self.engine.stop()
        self.capture.close()
        self.config.pos_x, self.config.pos_y = self.x(), self.y()
        save_config(self.config)
        e.accept()
