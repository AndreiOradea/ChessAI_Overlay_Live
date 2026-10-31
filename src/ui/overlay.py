"""
Always-on-top floating overlay panel for ChessAI Overlay LIVE.

Modes:
  LIVE          – Fair-play tracking only (no engine)
  LIVE ENGINE   – Real-time Stockfish for authorized / offline / private games
  TRAINING      – Interactive training with engine
  ANALYSIS      – Full post-game / deep analysis
"""

from __future__ import annotations

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QSize, Signal, Slot, QThread, QObject, QRect
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QCursor, QPainter, QPen, QBrush,
    QGuiApplication, QPainterPath
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSlider, QCheckBox,
    QListWidget, QApplication, QGroupBox, QSpinBox, QFormLayout
)

from typing import Optional, List, Tuple
import time
import chess

from src.utils.config import AppConfig, save_config, APP_NAME, APP_VERSION
from src.chess.game_tracker import GameTracker
from src.chess.tactics import analyze_tactics
from src.chess.move_list_sync import sync_from_text
from src.recognition.board_detector import BoardDetector, DetectionResult
from src.recognition.move_diff import MoveDiffTracker
from src.recognition.moves_ocr import ocr_moves_image, tesseract_available
from src.utils.screen_capture import ScreenCapture
from src.engine.stockfish_wrapper import StockfishEngine, AnalysisResult


# ── Color palette ────────────────────────────────────────────────────────────
CHARCOAL = "#1E1E24"
CHARCOAL_LIGHT = "#2A2A33"
PURPLE = "#9B59B6"
PURPLE_DARK = "#7D3C98"
GREEN = "#2ECC71"
RED = "#E74C3C"
YELLOW = "#F1C40F"
TEXT = "#E8E8ED"
TEXT_DIM = "#9A9AA8"
ARROW_COLOR = QColor(155, 89, 182, 200)


class WorkerSignals(QObject):
    detection_done = Signal(object)
    analysis_done = Signal(object)
    status = Signal(str)


class RecognitionWorker(QObject):
    def __init__(self, detector: BoardDetector, capture: ScreenCapture, region):
        super().__init__()
        self.detector = detector
        self.capture = capture
        self.region = region
        self.signals = WorkerSignals()
        self._running = True
        self._last_hash = None

    def stop(self):
        self._running = False

    @Slot()
    def process(self):
        if not self._running:
            return
        r = self.region
        img = self.capture.capture_region(r.x, r.y, r.width, r.height)
        if img is None:
            self.signals.status.emit("Capture failed")
            return
        import hashlib
        h = hashlib.md5(img.tobytes()[::50]).hexdigest()
        if h == self._last_hash:
            # Still emit image for move-diff baseline updates when quiet
            return
        self._last_hash = h
        result = self.detector.detect(img)
        # Attach image for Neo move-diff tracking
        result.board_image = img
        self.signals.detection_done.emit(result)


class AnalysisWorker(QObject):
    """Runs Stockfish analysis off the UI thread."""

    def __init__(self, engine: StockfishEngine, fen: str, depth: int,
                 movetime_ms: int, multipv: int):
        super().__init__()
        self.engine = engine
        self.fen = fen
        self.depth = depth
        self.movetime_ms = movetime_ms
        self.multipv = multipv
        self.signals = WorkerSignals()

    @Slot()
    def process(self):
        result = self.engine.analyze(
            self.fen,
            depth=self.depth,
            movetime_ms=self.movetime_ms,
            multipv=self.multipv,
        )
        self.signals.analysis_done.emit(result)


class ArrowOverlay(QWidget):
    """
    Transparent always-on-top window that draws:
      - Highlighted squares (best-move from / to)
      - Move arrows
    directly over the chessboard region.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._arrows: List[Tuple[str, str, QColor]] = []  # (from_sq, to_sq, color)
        self._highlights: List[Tuple[str, QColor]] = []   # (square, color)
        self._orientation = "white"
        self.hide()

    def set_board_geometry(self, x: int, y: int, w: int, h: int):
        self.setGeometry(x, y, w, h)

    def set_orientation(self, orientation: str):
        self._orientation = orientation

    def set_arrows(self, arrows: List[Tuple[str, str, QColor]],
                   highlights: Optional[List[Tuple[str, QColor]]] = None):
        self._arrows = arrows
        self._highlights = highlights or []
        self.update()
        if arrows or self._highlights:
            self.show()
            self.raise_()
        else:
            self.hide()

    def clear(self):
        self._arrows = []
        self._highlights = []
        self.update()
        self.hide()

    def _sq_rect(self, square: str) -> QRect:
        """Pixel rectangle of a square inside this widget."""
        file = ord(square[0]) - ord("a")
        rank = int(square[1]) - 1
        if self._orientation == "black":
            file = 7 - file
            rank = 7 - rank
        w, h = self.width(), self.height()
        sq_w, sq_h = w / 8.0, h / 8.0
        x = int(file * sq_w)
        y = int((7 - rank) * sq_h)
        return QRect(x, y, int(sq_w), int(sq_h))

    def _sq_to_center(self, square: str) -> QPoint:
        r = self._sq_rect(square)
        return r.center()

    def paintEvent(self, event):
        if not self._arrows and not self._highlights:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. Draw highlighted squares first (under arrows)
        for sq, color in self._highlights:
            try:
                rect = self._sq_rect(sq)
            except Exception:
                continue
            # Soft fill
            fill = QColor(color)
            fill.setAlpha(90)
            painter.fillRect(rect, fill)
            # Bright border
            pen = QPen(color, 3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = rect.adjusted(2, 2, -2, -2)
            painter.drawRect(inset)

        # 2. Draw arrows
        import math
        for frm, to, color in self._arrows:
            try:
                p1 = self._sq_to_center(frm)
                p2 = self._sq_to_center(to)
            except Exception:
                continue
            pen = QPen(color, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(p1, p2)
            angle = math.atan2(p2.y() - p1.y(), p2.x() - p1.x())
            size = 14
            for da in (0.4, -0.4):
                x = p2.x() - size * math.cos(angle + da)
                y = p2.y() - size * math.sin(angle + da)
                painter.drawLine(p2, QPoint(int(x), int(y)))


class OverlayPanel(QWidget):
    """Main always-on-top overlay window."""

    MODES = ["LIVE", "LIVE ENGINE", "TRAINING", "ANALYSIS"]

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.tracker = GameTracker()
        self.detector = BoardDetector()
        self.move_diff = MoveDiffTracker()
        self.capture = ScreenCapture()
        self.engine = StockfishEngine(config.engine.path)
        self._last_board_img = None
        self.moves_region = None  # (x,y,w,h) or None
        self._auto_board_moves = False  # OFF by default – prevents invented moves
        self._last_synced_count = 0
        self._engine_paused = False
        self.my_color = 'white'  # side we play & show BEST for

        self._drag_pos: Optional[QPoint] = None
        self._recognition_timer = QTimer(self)
        self._analysis_timer = QTimer(self)  # auto re-analyze every 2s in LIVE ENGINE
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[RecognitionWorker] = None
        self._analysis_thread: Optional[QThread] = None
        self._analysis_worker = None
        self._last_analyzed_fen: str = ""
        self._current_analysis: Optional[AnalysisResult] = None
        self._analyzing: bool = False

        # Transparent arrow layer over the board
        self.arrow_overlay = ArrowOverlay()

        self._setup_window()
        self._build_ui()
        self._apply_theme()
        self._connect_signals()
        self._start_recognition_loop()

        self.tracker.reset(config.last_fen, config.board_orientation)
        self.detector.set_orientation(config.board_orientation)
        self._refresh_ui()
        self._update_mode_visibility()

    # ── Window setup ─────────────────────────────────────────────────────────
    def _setup_window(self):
        self.setWindowTitle(APP_NAME)
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self.config.overlay.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowOpacity(self.config.overlay.opacity)
        self.resize(max(340, self.config.overlay.width), max(520, self.config.overlay.height))
        self.move(self.config.overlay.pos_x, self.config.overlay.pos_y)

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {CHARCOAL};
                color: {TEXT};
                font-family: 'Segoe UI', 'Ubuntu', sans-serif;
                font-size: 12px;
            }}
            QLabel#title {{ font-size: 14px; font-weight: bold; color: {PURPLE}; }}
            QLabel#status {{ font-size: 11px; color: {TEXT_DIM}; }}
            QLabel#eval {{ font-size: 22px; font-weight: bold; color: {PURPLE}; }}
            QLabel#bestmove {{ font-size: 16px; font-weight: bold; color: {GREEN}; }}
            QPushButton {{
                background-color: {CHARCOAL_LIGHT};
                border: 1px solid {PURPLE_DARK};
                border-radius: 4px;
                padding: 5px 10px;
                color: {TEXT};
            }}
            QPushButton:hover {{ background-color: {PURPLE_DARK}; border-color: {PURPLE}; }}
            QPushButton:pressed {{ background-color: {PURPLE}; }}
            QPushButton#accent {{ background-color: {PURPLE_DARK}; border-color: {PURPLE}; font-weight: bold; }}
            QPushButton#danger {{ border-color: {RED}; }}
            QLineEdit, QComboBox, QSpinBox {{
                background-color: {CHARCOAL_LIGHT};
                border: 1px solid #444;
                border-radius: 3px;
                padding: 4px;
                color: {TEXT};
            }}
            QListWidget {{
                background-color: {CHARCOAL_LIGHT};
                border: 1px solid #444;
                border-radius: 3px;
            }}
            QGroupBox {{
                border: 1px solid #444;
                border-radius: 4px;
                margin-top: 8px;
                font-weight: bold;
                color: {PURPLE};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }}
            QSlider::groove:horizontal {{ height: 4px; background: #444; }}
            QSlider::handle:horizontal {{
                background: {PURPLE}; width: 14px; margin: -5px 0; border-radius: 7px;
            }}
        """)

    # ── UI construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(5)

        # Title bar
        title_row = QHBoxLayout()
        self.lbl_title = QLabel(APP_NAME)
        self.lbl_title.setObjectName("title")
        title_row.addWidget(self.lbl_title)
        title_row.addStretch()
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setFixedSize(28, 24)
        self.btn_pin.setToolTip("Toggle always-on-top")
        title_row.addWidget(self.btn_pin)
        self.btn_min = QPushButton("–")
        self.btn_min.setFixedSize(28, 24)
        title_row.addWidget(self.btn_min)
        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(28, 24)
        self.btn_close.setObjectName("danger")
        title_row.addWidget(self.btn_close)
        root.addLayout(title_row)

        # Status
        status_row = QHBoxLayout()
        self.lbl_mode = QLabel("MODE: LIVE")
        self.lbl_mode.setStyleSheet(f"color: {GREEN}; font-weight: bold;")
        status_row.addWidget(self.lbl_mode)
        status_row.addStretch()
        self.lbl_conn = QLabel("● Board")
        self.lbl_conn.setStyleSheet(f"color: {TEXT_DIM};")
        status_row.addWidget(self.lbl_conn)
        root.addLayout(status_row)

        self.lbl_status = QLabel("Ready – select board region")
        self.lbl_status.setObjectName("status")
        self.lbl_status.setWordWrap(True)
        root.addWidget(self.lbl_status)

        # Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(self.MODES)
        current = self.config.mode if self.config.mode in self.MODES else "LIVE"
        self.cmb_mode.setCurrentText(current)
        mode_row.addWidget(self.cmb_mode)
        root.addLayout(mode_row)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("I play:"))
        self.cmb_color = QComboBox()
        self.cmb_color.addItems(["White", "Black"])
        self.cmb_color.setCurrentText("White")
        self.cmb_color.setToolTip("Only show BEST moves when it is your turn")
        color_row.addWidget(self.cmb_color)
        root.addLayout(color_row)

        # Board controls
        board_group = QGroupBox("Board")
        bg = QVBoxLayout(board_group)
        btn_row = QHBoxLayout()
        self.btn_calibrate = QPushButton("Select Region")
        self.btn_calibrate.setObjectName("accent")
        btn_row.addWidget(self.btn_calibrate)
        self.btn_flip = QPushButton("Flip")
        btn_row.addWidget(self.btn_flip)
        self.btn_reset = QPushButton("Reset")
        self.btn_reset.setToolTip("Reset to starting position and re-sync board tracking")
        btn_row.addWidget(self.btn_reset)
        bg.addLayout(btn_row)
        fen_row = QHBoxLayout()
        fen_row.addWidget(QLabel("FEN:"))
        self.txt_fen = QLineEdit()
        self.txt_fen.setPlaceholderText("Paste or edit FEN…")
        fen_row.addWidget(self.txt_fen)
        self.btn_set_fen = QPushButton("Set")
        fen_row.addWidget(self.btn_set_fen)
        bg.addLayout(fen_row)

        # Sync from Chess.com move list (paste from the moves panel)
        moves_row = QHBoxLayout()
        self.txt_moves = QLineEdit()
        self.txt_moves.setPlaceholderText("Paste moves: 1. e4 e5 2. Nf3 …")
        moves_row.addWidget(self.txt_moves)
        self.btn_sync_moves = QPushButton("Sync Moves")
        self.btn_sync_moves.setObjectName("accent")
        self.btn_sync_moves.setToolTip(
            "Paste the move list from Chess.com (right panel) to sync position, turn, and history"
        )
        moves_row.addWidget(self.btn_sync_moves)
        bg.addLayout(moves_row)

        moves_row2 = QHBoxLayout()
        self.btn_moves_region = QPushButton("Select Moves Panel")
        self.btn_moves_region.setToolTip(
            "Drag over the Chess.com move list (right side). App will OCR it every 2s."
        )
        moves_row2.addWidget(self.btn_moves_region)
        self.chk_auto_board = QCheckBox("Auto moves from board")
        self.chk_auto_board.setChecked(False)
        self.chk_auto_board.setToolTip(
            "OFF recommended. ON can invent wrong moves on Neo pieces."
        )
        moves_row2.addWidget(self.chk_auto_board)
        bg.addLayout(moves_row2)
        root.addWidget(board_group)

        # Game info
        info_group = QGroupBox("Game")
        ig = QVBoxLayout(info_group)
        self.lbl_turn = QLabel("Turn: —")
        ig.addWidget(self.lbl_turn)
        self.lbl_result = QLabel("")
        ig.addWidget(self.lbl_result)
        self.lst_moves = QListWidget()
        self.lst_moves.setMaximumHeight(140)
        ig.addWidget(self.lst_moves)
        root.addWidget(info_group)

        # ── LIVE ENGINE panel ────────────────────────────────────────────────
        self.engine_live_group = QGroupBox("LIVE ENGINE (Authorized games only)")
        elg = QVBoxLayout(self.engine_live_group)

        self.lbl_eval = QLabel("Eval: —")
        self.lbl_eval.setObjectName("eval")
        self.lbl_eval.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elg.addWidget(self.lbl_eval)

        self.lbl_best = QLabel("Best: —")
        self.lbl_best.setObjectName("bestmove")
        self.lbl_best.setAlignment(Qt.AlignmentFlag.AlignCenter)
        elg.addWidget(self.lbl_best)

        self.lst_candidates = QListWidget()
        self.lst_candidates.setMaximumHeight(85)
        elg.addWidget(self.lst_candidates)

        self.lbl_threats = QLabel("Threats: —")
        self.lbl_threats.setWordWrap(True)
        self.lbl_threats.setObjectName("status")
        elg.addWidget(self.lbl_threats)

        # Engine settings row
        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Depth"))
        self.spn_depth = QSpinBox()
        self.spn_depth.setRange(6, 40)
        self.spn_depth.setValue(self.config.engine.depth)
        settings_row.addWidget(self.spn_depth)
        settings_row.addWidget(QLabel("ms"))
        self.spn_time = QSpinBox()
        self.spn_time.setRange(100, 10000)
        self.spn_time.setSingleStep(100)
        self.spn_time.setValue(self.config.engine.movetime_ms)
        settings_row.addWidget(self.spn_time)
        elg.addLayout(settings_row)

        threads_row = QHBoxLayout()
        threads_row.addWidget(QLabel("Threads"))
        self.spn_threads = QSpinBox()
        self.spn_threads.setRange(1, 16)
        self.spn_threads.setValue(self.config.engine.threads)
        threads_row.addWidget(self.spn_threads)
        threads_row.addWidget(QLabel("Hash MB"))
        self.spn_hash = QSpinBox()
        self.spn_hash.setRange(16, 2048)
        self.spn_hash.setSingleStep(16)
        self.spn_hash.setValue(self.config.engine.hash_mb)
        threads_row.addWidget(self.spn_hash)
        elg.addLayout(threads_row)

        self.chk_arrows = QCheckBox("Show BEST move on board (not last move)")
        self.chk_arrows.setChecked(True)
        elg.addWidget(self.chk_arrows)

        eng_btn_row = QHBoxLayout()
        self.btn_force_analyze = QPushButton("Analyze Now")
        eng_btn_row.addWidget(self.btn_force_analyze)
        self.btn_stop_eng = QPushButton("Stop Engine")
        eng_btn_row.addWidget(self.btn_stop_eng)
        elg.addLayout(eng_btn_row)

        root.addWidget(self.engine_live_group)

        # Classic Training/Analysis engine panel (simpler)
        self.engine_group = QGroupBox("Engine")
        eg = QVBoxLayout(self.engine_group)
        self.lbl_eval2 = QLabel("Eval: —")
        self.lbl_eval2.setObjectName("eval")
        eg.addWidget(self.lbl_eval2)
        self.lst_lines = QListWidget()
        self.lst_lines.setMaximumHeight(90)
        eg.addWidget(self.lst_lines)
        self.btn_analyze = QPushButton("Analyze")
        eg.addWidget(self.btn_analyze)
        root.addWidget(self.engine_group)

        # LIVE checklist
        self.checklist_group = QGroupBox("Personal Checklist (LIVE)")
        cg = QVBoxLayout(self.checklist_group)
        self.checklist_widgets = []
        for item in self.config.live.personal_checklist:
            cb = QCheckBox(item)
            cg.addWidget(cb)
            self.checklist_widgets.append(cb)
        root.addWidget(self.checklist_group)

        # Opacity
        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Opacity"))
        self.sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(40, 100)
        self.sld_opacity.setValue(int(self.config.overlay.opacity * 100))
        op_row.addWidget(self.sld_opacity)
        root.addLayout(op_row)

        self.lbl_footer = QLabel(f"v{APP_VERSION}  |  Fair-play aware")
        self.lbl_footer.setObjectName("status")
        self.lbl_footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.lbl_footer)

    def _connect_signals(self):
        self.btn_close.clicked.connect(self.close)
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_pin.clicked.connect(self._toggle_pin)
        self.btn_calibrate.clicked.connect(self._start_region_select)
        self.btn_flip.clicked.connect(self._flip_orientation)
        self.btn_reset.clicked.connect(self._reset_board_tracking)
        self.btn_set_fen.clicked.connect(self._apply_manual_fen)
        self.btn_sync_moves.clicked.connect(self._sync_from_move_list)
        self.btn_moves_region.clicked.connect(self._select_moves_region)
        self.chk_auto_board.toggled.connect(self._on_auto_board_toggled)
        self.cmb_mode.currentTextChanged.connect(self._on_mode_changed)
        self.cmb_color.currentTextChanged.connect(self._on_my_color_changed)
        self.sld_opacity.valueChanged.connect(self._on_opacity)
        self.btn_analyze.clicked.connect(self._run_analysis_manual)
        self.btn_force_analyze.clicked.connect(self._run_analysis_manual)
        self.btn_stop_eng.clicked.connect(self._stop_engine)
        self.spn_depth.valueChanged.connect(self._save_engine_settings)
        self.spn_time.valueChanged.connect(self._save_engine_settings)
        self.spn_threads.valueChanged.connect(self._save_engine_settings)
        self.spn_hash.valueChanged.connect(self._save_engine_settings)
        self._recognition_timer.timeout.connect(self._tick_recognition)
        self._analysis_timer.timeout.connect(self._tick_auto_analysis)

    # ── Drag support ─────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self.config.overlay.pos_x = self.x()
        self.config.overlay.pos_y = self.y()
        save_config(self.config)

    # ── Mode handling ────────────────────────────────────────────────────────
    def _on_mode_changed(self, mode: str):
        self.config.mode = mode
        save_config(self.config)
        self._update_mode_visibility()
        self._update_mode_label(mode)
        if mode == "LIVE ENGINE":
            self._engine_paused = False
            self.lbl_status.setText("LIVE ENGINE – BEST only on your turn (I play …)")
            self._ensure_engine_started()
            self._analysis_timer.start()
            self._request_analysis(force=True)
        elif mode == "LIVE":
            self.lbl_status.setText("LIVE – engine disabled (fair-play)")
            self._analysis_timer.stop()
            self.arrow_overlay.clear()
            self._clear_engine_display()
        elif mode == "TRAINING":
            self.lbl_status.setText("TRAINING – engine available")
            self._analysis_timer.stop()
            self._ensure_engine_started()
        else:
            self.lbl_status.setText("ANALYSIS – full engine & review")
            self._analysis_timer.stop()
            self._ensure_engine_started()

    def _update_mode_label(self, mode: str):
        colors = {
            "LIVE": GREEN,
            "LIVE ENGINE": YELLOW,
            "TRAINING": PURPLE,
            "ANALYSIS": PURPLE,
        }
        self.lbl_mode.setText(f"MODE: {mode}")
        self.lbl_mode.setStyleSheet(f"color: {colors.get(mode, TEXT)}; font-weight: bold;")

    def _update_mode_visibility(self):
        mode = self.config.mode
        is_live = mode == "LIVE"
        is_live_engine = mode == "LIVE ENGINE"
        is_classic_engine = mode in ("TRAINING", "ANALYSIS")

        self.checklist_group.setVisible(is_live and self.config.live.show_personal_checklist)
        self.engine_live_group.setVisible(is_live_engine)
        self.engine_group.setVisible(is_classic_engine)

        if not is_live_engine:
            self.arrow_overlay.clear()

    def _clear_engine_display(self):
        self.lbl_eval.setText("Eval: —")
        self.lbl_best.setText("Best: —")
        self.lst_candidates.clear()
        self.lbl_threats.setText("Threats: —")
        self.lbl_eval2.setText("Eval: —")
        self.lst_lines.clear()

    # ── Recognition loop ─────────────────────────────────────────────────────
    def _start_recognition_loop(self):
        # Capture ~every 1s for responsive move detection
        self.config.overlay.capture_fps = 1.0
        self._recognition_timer.start(1000)
        self._analysis_timer.setInterval(1500)

    def _tick_recognition(self):
        if not self.config.board_region.calibrated:
            return
        if self._worker_thread is not None and self._worker_thread.isRunning():
            return
        self._worker_thread = QThread()
        self._worker = RecognitionWorker(
            self.detector, self.capture, self.config.board_region
        )
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.process)
        self._worker.signals.detection_done.connect(self._on_detection)
        self._worker.signals.status.connect(self._on_worker_status)
        self._worker.signals.detection_done.connect(self._worker_thread.quit)
        self._worker_thread.finished.connect(self._cleanup_worker)
        self._worker_thread.start()

    def _cleanup_worker(self):
        if self._worker:
            self._worker.stop()
        self._worker = None
        self._worker_thread = None

    @Slot(object)
    def _on_detection(self, result: DetectionResult):
        if not self.config.board_region.calibrated:
            self.lbl_conn.setText("● No board")
            self.lbl_conn.setStyleSheet(f"color: {RED};")
            return

        img = result.board_image
        self._last_board_img = img
        self.lbl_conn.setText("● Region")
        self.lbl_conn.setStyleSheet(f"color: {GREEN};")

        # 1) Prefer moves-panel OCR when configured
        if self.moves_region is not None:
            try:
                self._ocr_and_sync_moves()
            except Exception:
                pass

        # 2) Always track board changes for BOTH sides (strict). Needed so your turn returns.
        move = None
        if img is not None:
            try:
                move = self.move_diff.detect_move(img, self.tracker.state.board)
                # Second pass: more sensitive while waiting for opponent
                if move is None and not self._is_my_turn():
                    move = self.move_diff.detect_move(
                        img, self.tracker.state.board, mean_thr=7.0, edge_thr=0.02
                    )
            except Exception:
                move = None

        if move is not None:
            try:
                san = self.tracker.state.board.san(move)
            except Exception:
                san = move.uci()
            accepted, msg = self.tracker._apply_move(move)
            if accepted:
                self.config.last_fen = self.tracker.state.board.fen()
                if img is not None:
                    self.move_diff.force_snapshot(img)
                self._refresh_ui()
                self.lbl_conn.setText("● Board")
                if self.config.mode == "LIVE ENGINE" and not self._engine_paused:
                    if self._is_my_turn():
                        self.lbl_status.setText(f"Move {san} · YOUR turn – analyzing")
                        self._request_analysis(force=True)
                    else:
                        self.arrow_overlay.clear()
                        self.lbl_best.setText(f"Waiting… {self.tracker.side_to_move()}")
                        self.lbl_status.setText(f"Move {san} · opponent to move")
                else:
                    self.lbl_status.setText(f"Move detected: {san}")
                return

        # Recovery: if Stockfish best move already looks played on the board, apply it
        if (
            self._current_analysis
            and self._current_analysis.best_move_uci
            and img is not None
        ):
            recovered = self._try_recover_played_best(img)
            if recovered:
                return

        side = self.tracker.side_to_move()
        self.lbl_status.setText(f"Watching… {side} to move · if wrong: copy Chess.com moves → Sync Moves")

    @Slot(str)
    def _on_worker_status(self, text: str):
        self.lbl_status.setText(text)

    # ── Engine control ───────────────────────────────────────────────────────
    def _ensure_engine_started(self) -> bool:
        if self.engine.is_ready:
            return True
        ok = self.engine.start(
            threads=self.spn_threads.value(),
            hash_mb=self.spn_hash.value(),
        )
        if not ok:
            self.lbl_status.setText(
                "Stockfish not found. Put stockfish*.exe in the stockfish folder "
                "inside ChessAI_Overlay_LIVE, then click Analyze Now again."
            )
        else:
            self.lbl_status.setText(f"Engine ready: {self.engine.engine_path}")
            self.config.engine.path = self.engine.engine_path
            from src.utils.config import save_config
            save_config(self.config)
        return ok

    def _save_engine_settings(self):
        self.config.engine.depth = self.spn_depth.value()
        self.config.engine.movetime_ms = self.spn_time.value()
        self.config.engine.threads = self.spn_threads.value()
        self.config.engine.hash_mb = self.spn_hash.value()
        save_config(self.config)

    def _tick_auto_analysis(self):
        """Every 2s: sync moves (OCR/clipboard), track both sides, BEST only on my turn."""
        if self.config.mode != "LIVE ENGINE":
            return
        # Moves panel OCR
        if self.moves_region is not None:
            try:
                self._ocr_and_sync_moves(force=False)
            except Exception as e:
                print(f"[tick] ocr sync error: {e}")
        # Clipboard auto-sync if it looks like a move list (both sides)
        try:
            self._try_clipboard_sync()
        except Exception:
            pass
        if self._engine_paused:
            return
        if self._analyzing:
            return
        if not self._is_my_turn():
            side = self.tracker.side_to_move()
            self.lbl_status.setText(f"Opponent to move ({side}) – waiting for your turn")
            self.arrow_overlay.clear()
            self.lbl_best.setText(f"Waiting… {side}")
            return
        self._request_analysis(force=True)

    def _is_my_turn(self) -> bool:
        turn_white = self.tracker.state.board.turn  # True = White
        if self.my_color == "white":
            return bool(turn_white)
        return not bool(turn_white)

    def _on_my_color_changed(self, label: str):
        self.my_color = "white" if label.lower().startswith("w") else "black"
        # Match board orientation: my pieces at bottom
        want = "white" if self.my_color == "white" else "black"
        if self.config.board_orientation != want:
            self.config.board_orientation = want
            self.detector.set_orientation(want)
            self.move_diff.set_orientation(want)
            self.tracker.state.orientation = want
            self.arrow_overlay.set_orientation(want)
        self.lbl_status.setText(f"You play {label} – BEST only on your turn")
        if self.config.mode == "LIVE ENGINE" and not self._engine_paused and self._is_my_turn():
            self._request_analysis(force=True)

    def _request_analysis(self, force: bool = False):
        """Schedule async analysis of current position (never blocks UI)."""
        if self.config.mode not in ("LIVE ENGINE", "TRAINING", "ANALYSIS"):
            return
        if self._engine_paused and not force:
            return
        # LIVE ENGINE auto-path skips opponent turn; manual Analyze Now (_run_analysis_manual) sets force after unpause
        # Distinguish: force from timer still checks my turn; button sets a flag
        if self.config.mode == "LIVE ENGINE" and not self._is_my_turn() and not getattr(self, "_manual_analyze", False):
            self.lbl_status.setText(f"Waiting for opponent… ({self.tracker.side_to_move()} to move)")
            self.arrow_overlay.clear()
            return
        self._manual_analyze = False
        fen = self.tracker.state.board.fen()
        if not force and fen == self._last_analyzed_fen:
            return
        if self._analyzing or (self._analysis_thread is not None and self._analysis_thread.isRunning()):
            return
        # Manual Analyze Now should unpause
        if force:
            self._engine_paused = False
            if self.config.mode == "LIVE ENGINE" and not self._analysis_timer.isActive():
                self._analysis_timer.start()
        if not self._ensure_engine_started():
            return

        self._last_analyzed_fen = fen
        self._analyzing = True
        # LIVE: short time limit so UI stays responsive
        depth = min(self.spn_depth.value(), 18)
        movetime = min(max(200, self.spn_time.value()), 1500)
        self.lbl_status.setText(f"Analyzing… {movetime}ms")

        self._analysis_thread = QThread()
        worker = AnalysisWorker(
            self.engine,
            fen,
            depth=depth,
            movetime_ms=movetime,
            multipv=3,
        )
        self._analysis_worker = worker
        worker.moveToThread(self._analysis_thread)
        self._analysis_thread.started.connect(worker.process)
        worker.signals.analysis_done.connect(self._on_analysis_done)
        worker.signals.analysis_done.connect(self._analysis_thread.quit)
        self._analysis_thread.finished.connect(self._on_analysis_thread_finished)
        self._analysis_thread.start()

    def _on_analysis_thread_finished(self):
        self._analysis_thread = None
        self._analysis_worker = None
        self._analyzing = False

    def _run_analysis_manual(self):
        self._manual_analyze = True
        self._engine_paused = False
        if self.config.mode == "LIVE ENGINE" and not self._analysis_timer.isActive():
            self._analysis_timer.start()
        self._request_analysis(force=True)

    @Slot(object)
    def _on_analysis_done(self, result: AnalysisResult):
        self._current_analysis = result
        if result.error:
            self.lbl_eval.setText("Error")
            self.lbl_eval2.setText("Error")
            self.lbl_status.setText(result.error)
            return

        side = self.tracker.side_to_move()  # White / Black
        # Eval is relative to side to move: higher number = better for the player to move
        self.lbl_eval.setText(result.evaluation or "—")
        self.lbl_eval2.setText(f"Eval ({side}): {result.evaluation or '—'}")
        best = result.best_move_san or "—"
        mine = "YOU" if ((side=="White" and self.my_color=="white") or (side=="Black" and self.my_color=="black")) else "opponent"
        self.lbl_best.setText(f"BEST for {side} ({mine}): {best}")

        self.lst_candidates.clear()
        self.lst_lines.clear()
        for line in result.lines[:3]:
            score = f"M{line.score_mate}" if line.score_mate is not None else (
                f"{line.score_cp / 100:+.2f}" if line.score_cp is not None else "?"
            )
            pv = " ".join(line.pv_san[:8])
            prefix = "★ " if line.rank == 1 else f"{line.rank}. "
            entry = f"{prefix}{score}   {pv}"
            self.lst_candidates.addItem(entry)
            self.lst_lines.addItem(entry)

        self.lbl_status.setText(f"{side} to move · best = {best} · {result.evaluation}")

        # Tactical summary
        tactics = analyze_tactics(self.tracker.state.board)
        parts = []
        if tactics.in_check:
            parts.append("IN CHECK")
        if tactics.hanging:
            hangs = ", ".join(f"{h.piece}@{h.square}" for h in tactics.hanging[:5])
            parts.append(f"Hanging: {hangs}")
        if tactics.checks:
            parts.append(f"Checks: {', '.join(tactics.checks[:4])}")
        self.lbl_threats.setText(" | ".join(parts) if parts else "No immediate tactics")

        # Draw arrows for top move(s)
        if self.config.mode == "LIVE ENGINE" and self.chk_arrows.isChecked() and self._is_my_turn():
            self._update_arrows(result)
        else:
            self.arrow_overlay.clear()

    def _try_recover_played_best(self, img) -> bool:
        """If engine best move was already played on board, apply it and re-analyze."""
        import chess as _chess
        res = self._current_analysis
        if not res or not res.best_move_uci or len(res.best_move_uci) < 4:
            return False
        uci = res.best_move_uci
        try:
            if len(uci) >= 5 and uci[4] in "qrbn":
                move = _chess.Move.from_uci(uci[:5])
            else:
                move = _chess.Move.from_uci(uci[:4])
        except Exception:
            return False
        board = self.tracker.state.board
        if move not in board.legal_moves:
            return False
        try:
            gray = self.move_diff._prepare(img)
            occ = self.move_diff._occupancy_grid(gray)
            fr, fc = self.move_diff._square_to_rc(move.from_square)
            tr, tc = self.move_diff._square_to_rc(move.to_square)
            from_occ = float(occ[fr, fc])
            to_occ = float(occ[tr, tc])
        except Exception:
            return False
        if from_occ > 0.22 or to_occ < 0.12:
            return False
        try:
            san = board.san(move)
        except Exception:
            san = move.uci()
        accepted, _ = self.tracker._apply_move(move)
        if not accepted:
            return False
        self.move_diff.force_snapshot(img)
        self.config.last_fen = self.tracker.state.board.fen()
        self._refresh_ui()
        self.lbl_status.setText(f"Synced move: {san}")
        self.lbl_conn.setText("● Board")
        if self.config.mode == "LIVE ENGINE":
            self._request_analysis(force=True)
        return True

    def _update_arrows(self, result: AnalysisResult):

        """Draw ONLY the engine BEST move (not the last played move)."""
        if not self.config.board_region.calibrated:
            return
        r = self.config.board_region
        self.arrow_overlay.set_board_geometry(int(r.x), int(r.y), int(r.width), int(r.height))
        self.arrow_overlay.set_orientation(self.config.board_orientation)
        self.arrow_overlay.show()
        self.arrow_overlay.raise_()

        arrows = []
        highlights = []
        # Only rank-1 best move from Stockfish
        if not result.lines:
            self.arrow_overlay.clear()
            return
        line = result.lines[0]
        if not line.pv_uci:
            self.arrow_overlay.clear()
            return
        uci = line.pv_uci[0]
        if len(uci) < 4:
            self.arrow_overlay.clear()
            return
        frm, to = uci[:2], uci[2:4]
        best_color = QColor(155, 89, 182, 240)
        from_highlight = QColor(155, 89, 182, 140)
        to_highlight = QColor(46, 204, 113, 180)  # green destination = play here
        arrows.append((frm, to, best_color))
        highlights.append((frm, from_highlight))
        highlights.append((to, to_highlight))
        self.arrow_overlay.set_arrows(arrows, highlights)

    def _stop_engine(self):
        self._engine_paused = True
        self._analysis_timer.stop()
        self._analyzing = False
        try:
            self.engine.stop()
        except Exception:
            pass
        self.arrow_overlay.clear()
        self.lbl_status.setText("Engine STOPPED (timer off) – Analyze Now to resume")

    # ── Manual controls ──────────────────────────────────────────────────────
    def _start_region_select(self):
        self.hide()
        self.arrow_overlay.hide()
        QApplication.processEvents()
        time.sleep(0.15)
        selector = RegionSelector()
        if selector.exec_select():
            x, y, w, h = selector.region
            self.config.board_region.x = x
            self.config.board_region.y = y
            self.config.board_region.width = w
            self.config.board_region.height = h
            self.config.board_region.calibrated = True
            save_config(self.config)
            self.move_diff.reset()
            self.move_diff.set_orientation(self.config.board_orientation)
            # Assume start position when selecting a new region (Neo / computer game)
            import chess as _chess
            self.tracker.reset(_chess.STARTING_FEN, self.config.board_orientation)
            self._refresh_ui()
            self.lbl_status.setText(
                f"Region set {w}×{h}. Neo tracking ON – play moves, analysis every 2s"
            )
            self.arrow_overlay.set_board_geometry(x, y, w, h)
            self.lbl_conn.setText("● Region")
            self.lbl_conn.setStyleSheet(f"color: {GREEN};")
            if self.config.mode == "LIVE ENGINE":
                self._request_analysis(force=True)
        self.show()
        self.raise_()

    def _reset_board_tracking(self):
        """Full resync: starting position + fresh board snapshot."""
        self.tracker.reset(chess.STARTING_FEN, self.config.board_orientation)
        self.move_diff.reset()
        self._last_analyzed_fen = ""
        self._analyzing = False
        self._current_analysis = None
        self._last_synced_count = 0
        self._engine_paused = False
        self.my_color = 'white'  # side we play & show BEST for
        if self._last_board_img is not None:
            self.move_diff.force_snapshot(self._last_board_img)
        self.arrow_overlay.clear()
        self._clear_engine_display()
        self._refresh_ui()
        self.lbl_status.setText(
            "Reset OK – play from start, or paste moves + Sync Moves, or Set FEN"
        )
        self.lbl_conn.setText("● Region")
        self.lbl_conn.setStyleSheet(f"color: {GREEN};")
        if self.config.mode == "LIVE ENGINE":
            if not self._analysis_timer.isActive():
                self._analysis_timer.start()
            self._request_analysis(force=True)

    def _flip_orientation(self):
        new_or = "black" if self.config.board_orientation == "white" else "white"
        self.config.board_orientation = new_or
        self.detector.set_orientation(new_or)
        self.tracker.state.orientation = new_or
        self.move_diff.set_orientation(new_or)
        self.move_diff.reset()
        self.arrow_overlay.set_orientation(new_or)
        save_config(self.config)
        self.lbl_status.setText(f"Orientation: {new_or} at bottom")
        if self._current_analysis and self.config.mode == "LIVE ENGINE":
            self._update_arrows(self._current_analysis)

    def _apply_manual_fen(self):
        fen = self.txt_fen.text().strip()
        if not fen:
            return
        if self.tracker.force_position(fen):
            self.detector.force_fen(fen)
            self.config.last_fen = fen
            save_config(self.config)
            self.move_diff.reset()
            if self._last_board_img is not None:
                self.move_diff.force_snapshot(self._last_board_img)
            self.lbl_status.setText("FEN applied – Neo tracking continues from here")
            self._refresh_ui()
            if self.config.mode == "LIVE ENGINE":
                self._request_analysis(force=True)
        else:
            self.lbl_status.setText("Invalid FEN")

    def _on_auto_board_toggled(self, checked: bool):
        self._auto_board_moves = bool(checked)
        self.lbl_status.setText(
            "Board auto-moves ON (may err on Neo)" if checked else "Board auto-moves OFF – use Moves Panel / Sync"
        )

    def _select_moves_region(self):
        self.hide()
        self.arrow_overlay.hide()
        QApplication.processEvents()
        import time as _t
        _t.sleep(0.15)
        selector = RegionSelector()
        if selector.exec_select():
            self.moves_region = selector.region
            self.lbl_status.setText(
                f"Moves panel set {selector.region[2]}x{selector.region[3]} – OCR every 2s"
            )
            self._ocr_and_sync_moves(force=True)
        self.show()
        self.raise_()

    def _try_clipboard_sync(self):
        """If clipboard holds a longer move list than we have, sync both sides."""
        clip = QApplication.clipboard().text().strip()
        if not clip or len(clip) < 5:
            return
        # Must look like moves
        if not any(x in clip for x in ("e4", "e5", "d4", "d5", "Nf3", "1.", "O-O")):
            # still try parse
            pass
        board, applied, msg = sync_from_text(clip)
        if not applied:
            return
        if len(applied) < self._last_synced_count:
            return
        if len(applied) == self._last_synced_count:
            if board is not None and board.board_fen() == self.tracker.state.board.board_fen():
                return
        self._apply_synced_moves(applied, msg)

    def _ocr_and_sync_moves(self, force: bool = False):

        if self.moves_region is None:
            return
        x, y, w, h = self.moves_region
        img = self.capture.capture_region(x, y, w, h)
        if img is None:
            return
        if not tesseract_available():
            if force:
                self.lbl_status.setText(
                    "Tesseract OCR not installed – paste moves + Sync Moves "
                    "(install: https://github.com/UB-Mannheim/tesseract/wiki)"
                )
            return
        raw = ocr_moves_image(img)
        if not raw or len(raw.strip()) < 3:
            return
        board, applied, msg = sync_from_text(raw)
        if not applied:
            return
        # Update if more moves OR same count but different position (re-sync)
        if not force:
            if len(applied) < self._last_synced_count:
                return
            if len(applied) == self._last_synced_count:
                # Same number of moves – only skip if FEN matches
                if board is not None and board.board_fen() == self.tracker.state.board.board_fen():
                    return
        self._apply_synced_moves(applied, msg)

    def _apply_synced_moves(self, applied, msg: str):
        """Apply full move list from start – updates Game tab for BOTH sides."""
        self.tracker.reset(chess.STARTING_FEN, self.config.board_orientation)
        applied_ok = []
        for san in applied:
            try:
                move = self.tracker.state.board.parse_san(san)
                ok, _ = self.tracker._apply_move(move)
                if ok:
                    applied_ok.append(san)
                else:
                    break
            except Exception as e:
                print(f"[sync] stop at {san}: {e}")
                break
        self._last_synced_count = len(applied_ok)
        self.move_diff.reset()
        if self._last_board_img is not None:
            try:
                self.move_diff.force_snapshot(self._last_board_img)
            except Exception:
                pass
        self.config.last_fen = self.tracker.state.board.fen()
        try:
            from src.utils.config import save_config
            save_config(self.config)
        except Exception:
            pass
        # ALWAYS refresh Game list
        self._refresh_ui()
        side = self.tracker.side_to_move()
        hist = " ".join(applied_ok)
        print(f"[sync] applied {len(applied_ok)} moves: {hist} | {side} to move")
        self.lbl_conn.setText(f"● {len(applied_ok)} moves")
        self.lbl_conn.setStyleSheet(f"color: {GREEN};")
        if self.config.mode == "LIVE ENGINE" and not self._engine_paused and self._is_my_turn():
            self.lbl_status.setText(f"{msg} · YOUR turn")
            self._request_analysis(force=True)
        else:
            self.arrow_overlay.clear()
            self.lbl_best.setText(f"Waiting… {side}")
            self.lbl_status.setText(f"{msg} · tracked {len(applied_ok)} moves · {side}")

    def _sync_from_move_list(self):
        """Paste / clipboard Chess.com moves → full game state for BOTH sides."""
        raw = self.txt_moves.text().strip()
        if not raw:
            clip = QApplication.clipboard().text().strip()
            if clip and any(c.isalpha() for c in clip):
                raw = clip
                self.txt_moves.setText(clip[:240])
        if not raw:
            self.lbl_status.setText("Copy Chess.com move list, then Sync Moves")
            return
        board, applied, msg = sync_from_text(raw)
        if not applied:
            self.lbl_status.setText(msg or "Could not parse moves")
            return
        self._apply_synced_moves(applied, msg)

    def _toggle_pin(self):

        self.config.overlay.always_on_top = not self.config.overlay.always_on_top
        flags = self.windowFlags()
        if self.config.overlay.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        save_config(self.config)

    def _on_opacity(self, val: int):
        op = val / 100.0
        self.setWindowOpacity(op)
        self.config.overlay.opacity = op

    # ── UI refresh ───────────────────────────────────────────────────────────
    def _refresh_ui(self):
        try:
            board = self.tracker.state.board
            side = self.tracker.side_to_move()
            moves = self.tracker.get_move_history_san()
            n = len(moves)
            last = moves[-1] if n else "—"
            self.lbl_turn.setText(f"Turn: {side}  |  Last: {last}  |  Moves: {n}")
            if self.tracker.is_game_over():
                self.lbl_result.setText(f"Result: {self.tracker.result()}")
            else:
                self.lbl_result.setText("")
            self.lst_moves.clear()
            for i in range(0, n, 2):
                num = i // 2 + 1
                white = moves[i]
                black = moves[i + 1] if i + 1 < n else ""
                self.lst_moves.addItem(f"{num}. {white}  {black}")
            self.lst_moves.scrollToBottom()
            self.txt_fen.setText(board.fen())
        except Exception as e:
            print(f"[refresh_ui] {e}")

    def closeEvent(self, event):
        self._recognition_timer.stop()
        self._analysis_timer.stop()
        if self._worker:
            self._worker.stop()
        self.engine.stop()
        self.capture.close()
        self.arrow_overlay.close()
        self.config.overlay.pos_x = self.x()
        self.config.overlay.pos_y = self.y()
        self.config.overlay.width = self.width()
        self.config.overlay.height = self.height()
        save_config(self.config)
        event.accept()


class RegionSelector(QWidget):
    """
    Full-desktop translucent widget for selecting a rectangular region.
    Covers the entire virtual desktop (all monitors) using explicit geometry
    so Windows DPI scaling does not leave half the screen uncovered.
    """

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Cover full virtual desktop (works with multi-monitor + DPI)
        screen = QGuiApplication.primaryScreen()
        vg = screen.virtualGeometry() if screen else QGuiApplication.screens()[0].geometry()
        self.setGeometry(vg)
        self.setStyleSheet("background-color: transparent;")
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._origin: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self.region = (0, 0, 0, 0)
        self._accepted = False
        self._vg_topleft = vg.topLeft()

        label = QLabel(
            "Drag a tight rectangle around the CHESSBOARD only (not the whole window).\n"
            "Press Esc to cancel.",
            self,
        )
        label.setStyleSheet(
            "color: white; font-size: 18px; background: rgba(0,0,0,160); padding: 12px; border-radius: 6px;"
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.adjustSize()
        label.move(max(20, (vg.width() - label.width()) // 2), 40)

    def exec_select(self) -> bool:
        self.show()
        self.raise_()
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        self._loop = loop
        loop.exec()
        return self._accepted

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            # Use widget-local coords then map to global – more reliable under DPI
            self._origin = event.globalPosition().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event):
        if self._origin is not None:
            self._current = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._origin is not None and self._current is not None:
            x1 = min(self._origin.x(), self._current.x())
            y1 = min(self._origin.y(), self._current.y())
            x2 = max(self._origin.x(), self._current.x())
            y2 = max(self._origin.y(), self._current.y())
            w, h = x2 - x1, y2 - y1
            if w > 60 and h > 60:
                self.region = (x1, y1, w, h)
                self._accepted = True
            self._loop.quit()
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._accepted = False
            self._loop.quit()
            self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Light dim over whole screen so the board stays visible
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))

        if self._origin and self._current:
            x1 = min(self._origin.x(), self._current.x())
            y1 = min(self._origin.y(), self._current.y())
            x2 = max(self._origin.x(), self._current.x())
            y2 = max(self._origin.y(), self._current.y())
            tl = self.mapFromGlobal(QPoint(x1, y1))
            rw, rh = x2 - x1, y2 - y1
            # Clear the selected area so you see the board clearly
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(tl.x(), tl.y(), rw, rh, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            # Purple border around selection
            pen = QPen(QColor(155, 89, 182, 255))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(155, 89, 182, 40)))
            painter.drawRect(tl.x(), tl.y(), rw, rh)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(tl.x() + 6, max(16, tl.y() - 8), f"{rw} x {rh}  – release to confirm")
