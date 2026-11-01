"""Main always-on-top window: internal board mirrors screen game + analysis."""
from __future__ import annotations
import shutil
import time
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    QThread,
    QObject,
    Signal,
    Slot,
    QPoint,
)
from PySide6.QtGui import (
    QGuiApplication,
    QColor,
    QPainter,
    QPen,
    QBrush,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QFileDialog,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import chess

from src.utils.config import AppConfig, CONFIG_DIR, save_config
from src.utils.screen_capture import ScreenCapture
from src.chess.game_tracker import GameTracker
from src.chess.move_list_sync import sync_from_text
from src.recognition.move_diff import MoveDiffTracker, highlighted_last_move
from src.recognition.board_sync import resync_board, mismatch, visual_occupancy
from src.recognition.piece_templates import PieceTemplateMatcher
from src.engine.stockfish_wrapper import StockfishEngine, AnalysisResult
from src.ui.branding import app_icon, brand_image_path
from src.ui.chess_board_widget import ChessBoardWidget

PURPLE = "#9B59B6"
BG = "#1a1b20"
CARD = "#25262e"
TEXT = "#ECECF1"
GREEN = "#2ECC71"
YELLOW = "#F1C40F"
RED = "#E24949"


class AnalysisWorker(QObject):
    done = Signal(object)

    def __init__(
        self, engine: StockfishEngine, fen: str, depth: int, ms: int, multipv: int = 3
    ):
        super().__init__()
        self.engine, self.fen, self.depth, self.ms = engine, fen, depth, ms
        self.multipv = multipv

    @Slot()
    def run(self):
        try:
            result = self.engine.analyze(
                self.fen,
                depth=self.depth,
                movetime_ms=self.ms,
                multipv=self.multipv,
            )
        except Exception as error:
            result = AnalysisResult(
                fen=self.fen,
                error=f"Analysis failed: {error}",
            )
        self.done.emit(result)


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
        self._analysis_pending = False
        self._stop_engine_after_analysis = False
        self._restart_engine_when_idle = False
        self._analysis_retry_fen: Optional[str] = None
        self._close_when_idle = False
        self._last_fen_analyzed = ""
        self._thread: Optional[QThread] = None
        self._worker = None
        self._analysis_fen = ""
        self._drag = None
        self._last_img = None
        self._manual_piece_overrides: Dict[
            chess.Square, Optional[chess.Piece]
        ] = {}

        self._wallpaper = QLabel(self)
        self._wallpaper.setObjectName("wallpaper")
        self._wallpaper.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._wallpaper.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._wallpaper_blur = QGraphicsBlurEffect(self._wallpaper)
        self._wallpaper_blur.setBlurRadius(config.background_blur)
        self._wallpaper.setGraphicsEffect(self._wallpaper_blur)
        self._wallpaper.lower()
        self._wallpaper_tint = QWidget(self)
        self._wallpaper_tint.setObjectName("wallpaperTint")
        self._wallpaper_tint.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._wallpaper_source = QPixmap()

        self._build_ui(config)

        # timers
        self.timer_cap = QTimer(self)
        self.timer_cap.timeout.connect(self._tick_capture)
        self.timer_cap.start(250)
        self.timer_eng = QTimer(self)
        self.timer_eng.timeout.connect(self._tick_engine)
        self.timer_eng.setInterval(1200)
        self.welcome_timer = QTimer(self)
        self.welcome_timer.setInterval(55)
        self.welcome_timer.timeout.connect(self._type_welcome)
        self._welcome_text = "Welcome to ChessAI"
        self._welcome_index = 0

        # signals
        self.btn_region.clicked.connect(self._select_region)
        self.btn_flip.clicked.connect(self._flip)
        self.btn_reset.clicked.connect(self._reset)
        self.btn_sync.clicked.connect(self._sync_moves)
        self.btn_analyze.clicked.connect(self._analyze_now)
        self.btn_resync.clicked.connect(self._on_resync_clicked)
        self.btn_stop.clicked.connect(self._stop_engine)
        self.btn_edit_position.clicked.connect(self._toggle_position_edit)
        self.btn_analysis_resync.clicked.connect(self._on_resync_clicked)
        self.btn_analysis_run.clicked.connect(self._analyze_now)
        self.btn_home_board.clicked.connect(lambda: self._navigate(self.nav_board))
        self.btn_home_region.clicked.connect(self._select_region)
        self.btn_home_analyze.clicked.connect(self._home_analyze)
        self.cmb_mode.currentTextChanged.connect(self._on_mode)
        self.cmb_color.currentTextChanged.connect(self._on_color)
        self.cmb_theme.currentTextChanged.connect(self._on_theme_changed)
        self.cmb_accent.currentTextChanged.connect(self._on_accent_changed)
        self.btn_accent_color.clicked.connect(self._choose_custom_accent)
        self.btn_background_choose.clicked.connect(self._choose_background_image)
        self.btn_background_remove.clicked.connect(self._remove_background_image)
        self.cmb_orientation.currentTextChanged.connect(
            self._on_orientation_changed
        )
        self.chk_coordinates.toggled.connect(self._on_coordinates_changed)
        self.chk_always_on_top.toggled.connect(self._on_always_on_top_changed)
        self.sld_opacity.valueChanged.connect(self._on_opacity_changed)
        self.sld_opacity.sliderReleased.connect(lambda: save_config(self.config))
        self.sld_background_opacity.valueChanged.connect(
            self._on_background_opacity_changed
        )
        self.sld_background_tint.valueChanged.connect(
            self._on_background_tint_changed
        )
        self.sld_background_blur.valueChanged.connect(
            self._on_background_blur_changed
        )
        for slider in (
            self.sld_background_opacity,
            self.sld_background_tint,
            self.sld_background_blur,
        ):
            slider.sliderReleased.connect(lambda: save_config(self.config))
        self.cmb_background_fit.currentTextChanged.connect(
            self._on_background_fit_changed
        )
        self.spn_depth.valueChanged.connect(self._on_engine_settings_changed)
        self.spn_ms.valueChanged.connect(self._on_engine_settings_changed)
        self.spn_multipv.valueChanged.connect(self._on_engine_settings_changed)
        for button in self._page_by_button:
            button.clicked.connect(
                lambda checked=False, target=button: self._navigate(target)
            )

        self._apply_theme()
        self._navigate(self.nav_home, animate=False)
        self._refresh()
        self._on_mode(self.cmb_mode.currentText())
        self.welcome_timer.start()

    def _build_ui(self, config: AppConfig):
        self.setWindowTitle("ChessAI Board LIVE")
        self.setObjectName("mainWindow")
        self.setWindowIcon(app_icon())
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | (
                Qt.WindowType.WindowStaysOnTopHint
                if config.always_on_top
                else Qt.WindowType.Widget
            )
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(860, 510)
        self.setMinimumSize(800, 480)
        self.move(config.pos_x, config.pos_y)
        self.setWindowOpacity(config.opacity)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(8)

        self.header_widget = QWidget()
        self.header_widget.setObjectName("titlebar")
        self.header_widget.installEventFilter(self)
        head = QHBoxLayout(self.header_widget)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        logo = QLabel()
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(28, 28)
        logo_pixmap = QPixmap(str(brand_image_path()))
        if not logo_pixmap.isNull():
            logo.setPixmap(
                logo_pixmap.scaled(
                    28,
                    28,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        logo.installEventFilter(self)
        head.addWidget(logo)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("CHESSAI")
        title.setObjectName("brand")
        title.installEventFilter(self)
        subtitle = QLabel("LIVE OVERLAY")
        subtitle.setObjectName("brandSub")
        subtitle.installEventFilter(self)
        brand.addWidget(title)
        brand.addWidget(subtitle)
        head.addLayout(brand)
        head.addSpacing(8)
        head.addWidget(self._separator())
        self.lbl_header_welcome = QLabel("Welcome")
        self.lbl_header_welcome.setObjectName("headerWelcome")
        self.lbl_header_welcome.installEventFilter(self)
        head.addWidget(self.lbl_header_welcome)
        head.addStretch()
        self.lbl_dot = QLabel("●")
        head.addWidget(self.lbl_dot)
        for label, slot in (("–", self.showMinimized), ("×", self.close)):
            button = QPushButton(label)
            button.setObjectName("windowControl")
            button.setFixedSize(28, 28)
            button.clicked.connect(slot)
            head.addWidget(button)
        root.addWidget(self.header_widget)

        body = QHBoxLayout()
        body.setSpacing(10)
        sidebar = QWidget()
        self.sidebar_widget = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(70)
        nav_layout = QVBoxLayout(sidebar)
        nav_layout.setContentsMargins(2, 8, 2, 8)
        nav_layout.setSpacing(5)
        self.sidebar_indicator = QFrame(sidebar)
        self.sidebar_indicator.setObjectName("navIndicator")
        self.sidebar_indicator.hide()
        self.nav_home = self._nav_button("Home", "⌂")
        self.nav_board = self._nav_button("Board", "♟")
        self.nav_analysis = self._nav_button("Analysis", "↗")
        self.nav_settings = self._nav_button("Settings", "⚙")
        for button in (
            self.nav_home,
            self.nav_board,
            self.nav_analysis,
            self.nav_settings,
        ):
            nav_layout.addWidget(button)
        nav_layout.addStretch()
        self.lbl_status = QLabel("Ready")
        self.lbl_status.setObjectName("status")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setMaximumHeight(40)
        nav_layout.addWidget(self.lbl_status)
        body.addWidget(sidebar)

        self.pages = QStackedWidget()
        self._page_opacity = QGraphicsOpacityEffect(self.pages)
        self._page_opacity.setOpacity(1.0)
        self.pages.setGraphicsEffect(self._page_opacity)
        self._page_animation = QPropertyAnimation(self._page_opacity, b"opacity", self)
        self._page_animation.setDuration(180)
        self._page_animation.setStartValue(0.7)
        self._page_animation.setEndValue(1.0)
        self._page_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._sidebar_animation = QPropertyAnimation(
            self.sidebar_indicator, b"geometry", self
        )
        self._sidebar_animation.setDuration(220)
        self._sidebar_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        body.addWidget(self.pages, stretch=1)
        root.addLayout(body, stretch=1)
        footer = QHBoxLayout()
        footer.addStretch()
        self.size_grip = QSizeGrip(self)
        self.size_grip.setToolTip("Drag to resize the window")
        footer.addWidget(self.size_grip)
        root.addLayout(footer)

        self._build_home_page()
        self._build_board_page(config)
        self._build_analysis_page()
        self._build_settings_page(config)
        self._page_by_button = {
            self.nav_home: self.page_home,
            self.nav_board: self.page_board,
            self.nav_analysis: self.page_analysis,
            self.nav_settings: self.page_settings,
        }

    @staticmethod
    def _separator() -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setObjectName("separator")
        return separator

    @staticmethod
    def _card() -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        return card

    @staticmethod
    def _nav_button(label: str, icon: str) -> QPushButton:
        button = QPushButton(icon)
        button.setObjectName("navButton")
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.setCheckable(True)
        button.setMinimumSize(48, 42)
        return button

    @staticmethod
    def _action_card(title: str, description: str, icon: str) -> QPushButton:
        button = QPushButton(f"{icon}   {title}\n{description}")
        button.setObjectName("actionCard")
        button.setMinimumHeight(92)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _build_home_page(self):
        self.page_home = QWidget()
        layout = QVBoxLayout(self.page_home)
        layout.setContentsMargins(12, 8, 8, 6)
        layout.setSpacing(9)
        heading = QLabel("YOUR CHESS WORKSPACE")
        heading.setObjectName("eyebrow")
        layout.addWidget(heading)
        self.lbl_welcome = QLabel("")
        self.lbl_welcome.setObjectName("welcome")
        layout.addWidget(self.lbl_welcome)
        description = QLabel("Your board, your engine, your next move.")
        description.setObjectName("muted")
        layout.addWidget(description)
        layout.addSpacing(8)
        actions_heading = QLabel("QUICK ACTIONS")
        actions_heading.setObjectName("eyebrow")
        layout.addWidget(actions_heading)
        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.btn_home_board = self._action_card(
            "Open board", "View and edit your position", "♟"
        )
        self.btn_home_region = self._action_card(
            "Select screen", "Choose a board to follow", "⌖"
        )
        self.btn_home_analyze = self._action_card(
            "Analyze now", "Find the strongest continuation", "↗"
        )
        for button in (
            self.btn_home_board,
            self.btn_home_region,
            self.btn_home_analyze,
        ):
            actions.addWidget(button)
        layout.addLayout(actions)
        layout.addStretch()
        footer = QHBoxLayout()
        self.lbl_home_turn = QLabel("White to move")
        self.lbl_home_turn.setObjectName("homeMetric")
        footer.addWidget(self.lbl_home_turn)
        footer.addStretch()
        self.lbl_home_engine = QLabel("ENGINE READY")
        self.lbl_home_engine.setObjectName("engineBadge")
        footer.addWidget(self.lbl_home_engine)
        layout.addLayout(footer)
        self.pages.addWidget(self.page_home)

    def _build_board_page(self, config: AppConfig):
        self.page_board = QWidget()
        layout = QHBoxLayout(self.page_board)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(9)

        board_card = self._card()
        board_card.setMinimumWidth(290)
        board_layout = QVBoxLayout(board_card)
        board_layout.setContentsMargins(8, 7, 8, 8)
        board_heading = QHBoxLayout()
        label = QLabel("LIVE BOARD")
        label.setObjectName("eyebrow")
        board_heading.addWidget(label)
        board_heading.addStretch()
        self.lbl_board_side = QLabel("WHITE TO MOVE")
        self.lbl_board_side.setObjectName("sideBadge")
        board_heading.addWidget(self.lbl_board_side)
        board_layout.addLayout(board_heading)
        self.board_view = ChessBoardWidget()
        self.board_view.set_orientation(config.board_orientation)
        self.board_view.set_show_coordinates(config.show_coordinates)
        self.board_view.move_requested.connect(self._on_internal_move)
        self.board_view.position_edited.connect(self._on_position_edited)
        board_layout.addWidget(self.board_view, stretch=1)
        layout.addWidget(board_card, stretch=5)

        controls_card = self._card()
        controls_card.setMinimumWidth(275)
        controls = QVBoxLayout(controls_card)
        controls.setContentsMargins(10, 9, 10, 9)
        controls.setSpacing(6)
        self.lbl_turn = QLabel("White to move | Last: — | Moves: 0")
        self.lbl_turn.setObjectName("muted")
        self.lbl_turn.setWordWrap(True)
        controls.addWidget(self.lbl_turn)
        selections = QHBoxLayout()
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["LIVE", "LIVE ENGINE"])
        self.cmb_mode.setCurrentText(
            config.mode
            if config.mode in ("LIVE", "LIVE ENGINE")
            else "LIVE ENGINE"
        )
        self.cmb_color = QComboBox()
        self.cmb_color.addItems(["White", "Black"])
        self.cmb_color.setCurrentText(
            "White" if config.my_color == "white" else "Black"
        )
        selections.addWidget(self.cmb_mode)
        selections.addWidget(self.cmb_color)
        controls.addLayout(selections)

        row = QHBoxLayout()
        self.btn_region = QPushButton("Select screen")
        self.btn_region.setObjectName("accent")
        row.addWidget(self.btn_region)
        self.btn_resync = QPushButton("Resync")
        row.addWidget(self.btn_resync)
        controls.addLayout(row)
        row = QHBoxLayout()
        self.btn_flip = QPushButton("Flip board")
        row.addWidget(self.btn_flip)
        self.btn_reset = QPushButton("Reset")
        row.addWidget(self.btn_reset)
        controls.addLayout(row)
        self.btn_edit_position = QPushButton("Edit position")
        self.btn_edit_position.setToolTip(
            "Drag any piece to move it. Right-click a square to add/remove a piece or set the turn."
        )
        controls.addWidget(self.btn_edit_position)

        eval_heading = QLabel("ENGINE EVALUATION")
        eval_heading.setObjectName("eyebrow")
        controls.addWidget(eval_heading)
        self.lbl_eval = QLabel("—")
        self.lbl_eval.setObjectName("eval")
        controls.addWidget(self.lbl_eval)
        self.lbl_best = QLabel("BEST: —")
        self.lbl_best.setObjectName("best")
        self.lbl_best.setWordWrap(True)
        controls.addWidget(self.lbl_best)
        self.lst_lines = QListWidget()
        self.lst_lines.setMaximumHeight(82)
        controls.addWidget(self.lst_lines, stretch=1)
        actions = QHBoxLayout()
        self.btn_analyze = QPushButton("Analyze")
        self.btn_analyze.setObjectName("accent")
        actions.addWidget(self.btn_analyze)
        self.btn_stop = QPushButton("Stop")
        actions.addWidget(self.btn_stop)
        controls.addLayout(actions)
        layout.addWidget(controls_card, stretch=4)
        self.pages.addWidget(self.page_board)

    def _build_analysis_page(self):
        self.page_analysis = QWidget()
        layout = QVBoxLayout(self.page_analysis)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(7)
        header = QHBoxLayout()
        title = QLabel("ENGINE ANALYSIS")
        title.setObjectName("eyebrow")
        header.addWidget(title)
        header.addStretch()
        self.lbl_analysis_depth = QLabel("")
        self.lbl_analysis_depth.setObjectName("sideBadge")
        self.lbl_analysis_depth.setText(
            f"DEPTH {self.config.engine.depth}  ·  MULTIPV {self.config.multipv}"
        )
        header.addWidget(self.lbl_analysis_depth)
        layout.addLayout(header)

        summary = self._card()
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(12, 7, 12, 7)
        eval_column = QVBoxLayout()
        label = QLabel("POSITION EVALUATION")
        label.setObjectName("eyebrow")
        eval_column.addWidget(label)
        self.lbl_analysis_eval = QLabel("—")
        self.lbl_analysis_eval.setObjectName("eval")
        eval_column.addWidget(self.lbl_analysis_eval)
        summary_layout.addLayout(eval_column)
        summary_layout.addStretch()
        self.lbl_analysis_best = QLabel("BEST MOVE  —")
        self.lbl_analysis_best.setObjectName("best")
        summary_layout.addWidget(self.lbl_analysis_best)
        layout.addWidget(summary)

        lines_card = self._card()
        lines_layout = QVBoxLayout(lines_card)
        lines_layout.setContentsMargins(9, 7, 9, 7)
        label = QLabel("TOP LINES")
        label.setObjectName("eyebrow")
        lines_layout.addWidget(label)
        self.lst_analysis_lines = QListWidget()
        lines_layout.addWidget(self.lst_analysis_lines)
        layout.addWidget(lines_card, stretch=2)

        moves_card = self._card()
        moves_layout = QVBoxLayout(moves_card)
        moves_layout.setContentsMargins(9, 7, 9, 7)
        label = QLabel("GAME MOVES")
        label.setObjectName("eyebrow")
        moves_layout.addWidget(label)
        self.lst_moves = QListWidget()
        moves_layout.addWidget(self.lst_moves)
        layout.addWidget(moves_card, stretch=1)

        row = QHBoxLayout()
        self.txt_moves = QLineEdit()
        self.txt_moves.setPlaceholderText(
            "Paste a move list, e.g. 1. e4 e5 2. Nf3 Nc6"
        )
        row.addWidget(self.txt_moves)
        self.btn_sync = QPushButton("Sync")
        self.btn_sync.setObjectName("accent")
        row.addWidget(self.btn_sync)
        layout.addLayout(row)
        actions = QHBoxLayout()
        self.btn_analysis_resync = QPushButton("Resync board")
        actions.addWidget(self.btn_analysis_resync)
        self.btn_analysis_run = QPushButton("Analyze position")
        self.btn_analysis_run.setObjectName("accent")
        actions.addWidget(self.btn_analysis_run)
        layout.addLayout(actions)
        self.pages.addWidget(self.page_analysis)

    def _build_settings_page(self, config: AppConfig):
        self.page_settings = QWidget()
        layout = QVBoxLayout(self.page_settings)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        heading = QLabel("SETTINGS")
        heading.setObjectName("eyebrow")
        layout.addWidget(heading)
        title = QLabel("Tune your workspace")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("settingsContent")
        grid = QGridLayout(content)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addWidget(scroll, stretch=1)
        scroll.setWidget(content)

        appearance = self._settings_card("APPEARANCE", grid, 0, 0)
        background = self._settings_card("BACKGROUND", grid, 0, 1)
        board = self._settings_card("BOARD & GAME", grid, 1, 0)
        engine = self._settings_card("ENGINE", grid, 1, 1)
        overlay = self._settings_card("OVERLAY", grid, 2, 0)

        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(["Midnight", "Light"])
        self.cmb_theme.setCurrentText(
            config.theme if config.theme in ("Midnight", "Light") else "Midnight"
        )
        self.cmb_accent = QComboBox()
        accents = ["Violet", "Blue", "Rose", "Mint"]
        if config.accent == "Custom":
            accents.append("Custom")
        self.cmb_accent.addItems(accents)
        self.cmb_accent.setCurrentText(
            config.accent
            if config.accent in accents
            else "Violet"
        )
        self._setting_row(appearance, "Theme", self.cmb_theme)
        self._setting_row(appearance, "Accent", self.cmb_accent)
        self.btn_accent_color = QPushButton("Choose custom color")
        self.btn_accent_color.setToolTip("Pick any accent color")
        appearance.addWidget(self.btn_accent_color)
        appearance.addStretch()

        background_buttons = QHBoxLayout()
        self.btn_background_choose = QPushButton("Choose image")
        self.btn_background_remove = QPushButton("Remove")
        background_buttons.addWidget(self.btn_background_choose, stretch=1)
        background_buttons.addWidget(self.btn_background_remove)
        background.addLayout(background_buttons)
        self.lbl_background_image = QLabel("No background image selected")
        self.lbl_background_image.setObjectName("muted")
        self.lbl_background_image.setWordWrap(True)
        self.lbl_background_image.setMaximumHeight(30)
        background.addWidget(self.lbl_background_image)
        self.sld_background_opacity = self._background_slider(
            background, "Image opacity", 0, 100, config.background_opacity
        )
        self.sld_background_tint = self._background_slider(
            background, "Dark tint", 0, 100, config.background_tint
        )
        self.sld_background_blur = self._background_slider(
            background, "Blur", 0, 30, config.background_blur
        )
        self.cmb_background_fit = QComboBox()
        self.cmb_background_fit.addItems(["Fill", "Fit", "Stretch", "Center"])
        if config.background_fit in ("Fill", "Fit", "Stretch", "Center"):
            self.cmb_background_fit.setCurrentText(config.background_fit)
        self._setting_row(background, "Image fit", self.cmb_background_fit)

        self.cmb_orientation = QComboBox()
        self.cmb_orientation.addItems(["White at bottom", "Black at bottom"])
        self.cmb_orientation.setCurrentText(
            "White at bottom"
            if config.board_orientation == "white"
            else "Black at bottom"
        )
        self.chk_coordinates = QCheckBox("Show board coordinates")
        self.chk_coordinates.setChecked(config.show_coordinates)
        self._setting_row(board, "Orientation", self.cmb_orientation)
        board.addWidget(self.chk_coordinates)
        self._setting_row(board, "Mode", self.cmb_mode)
        self._setting_row(board, "I play", self.cmb_color)
        board.addStretch()

        self.spn_depth = QSpinBox()
        self.spn_depth.setRange(6, 30)
        self.spn_depth.setValue(config.engine.depth)
        self.spn_ms = QSpinBox()
        self.spn_ms.setRange(100, 5000)
        self.spn_ms.setValue(config.engine.movetime_ms)
        self.spn_multipv = QSpinBox()
        self.spn_multipv.setRange(1, 5)
        self.spn_multipv.setValue(max(1, min(5, config.multipv)))
        self._setting_row(engine, "Depth", self.spn_depth)
        self._setting_row(engine, "Move time (ms)", self.spn_ms)
        self._setting_row(engine, "Lines", self.spn_multipv)
        engine.addStretch()

        opacity_row = QHBoxLayout()
        self.sld_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sld_opacity.setRange(65, 100)
        self.sld_opacity.setValue(
            max(65, min(100, round(config.opacity * 100)))
        )
        self.lbl_opacity = QLabel(f"{self.sld_opacity.value()}%")
        opacity_row.addWidget(self.sld_opacity, stretch=1)
        opacity_row.addWidget(self.lbl_opacity)
        overlay.addWidget(QLabel("Window opacity"))
        overlay.addLayout(opacity_row)
        self.chk_always_on_top = QCheckBox("Keep window on top")
        self.chk_always_on_top.setChecked(config.always_on_top)
        overlay.addWidget(self.chk_always_on_top)
        overlay.addStretch()

        note = QLabel("Changes save automatically")
        note.setObjectName("muted")
        layout.addWidget(note)
        self._load_background_image()
        self.pages.addWidget(self.page_settings)

    def _settings_card(
        self, title: str, parent: QGridLayout, row: int, column: int
    ) -> QVBoxLayout:
        card = self._card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(7)
        heading = QLabel(title)
        heading.setObjectName("eyebrow")
        card_layout.addWidget(heading)
        parent.addWidget(card, row, column)
        return card_layout

    @staticmethod
    def _background_slider(
        parent: QVBoxLayout, title: str, minimum: int, maximum: int, value: int
    ) -> QSlider:
        row = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("settingLabel")
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(max(minimum, min(maximum, value)))
        value_label = QLabel(f"{slider.value()}%")
        value_label.setMinimumWidth(28)
        row.addWidget(label)
        row.addWidget(slider, stretch=1)
        row.addWidget(value_label)
        slider.valueChanged.connect(
            lambda value, display=value_label, suffix="%" if maximum == 100 else "": display.setText(
                f"{value}{suffix}"
            )
        )
        parent.addLayout(row)
        return slider

    @staticmethod
    def _setting_row(parent: QVBoxLayout, label: str, control: QWidget):
        row = QHBoxLayout()
        title = QLabel(label)
        title.setObjectName("settingLabel")
        row.addWidget(title)
        row.addStretch()
        row.addWidget(control)
        parent.addLayout(row)

    def _navigate(self, button: QPushButton, animate: bool = True):
        self.pages.setCurrentWidget(self._page_by_button[button])
        for nav_button in self._page_by_button:
            nav_button.setChecked(nav_button is button)
        self.sidebar_widget.layout().activate()
        target = button.geometry().adjusted(1, 0, -1, 0)
        self._sidebar_animation.stop()
        if animate and not self.sidebar_indicator.isHidden():
            self._sidebar_animation.setStartValue(
                self.sidebar_indicator.geometry()
            )
            self._sidebar_animation.setEndValue(target)
            self._sidebar_animation.start()
        else:
            self.sidebar_indicator.setGeometry(target)
            self.sidebar_indicator.show()
            self.sidebar_indicator.lower()
        if animate:
            self._page_animation.stop()
            self._page_opacity.setOpacity(0.7)
            self._page_animation.start()

    def _home_analyze(self):
        self._navigate(self.nav_analysis)
        self._analyze_now()

    def _type_welcome(self):
        self._welcome_index += 1
        welcome = self._welcome_text[: self._welcome_index]
        self.lbl_welcome.setText(welcome + ("▏" if self._welcome_index < len(self._welcome_text) else ""))
        self.lbl_header_welcome.setText(welcome)
        if self._welcome_index >= len(self._welcome_text):
            self.welcome_timer.stop()

    def _accent_color(self) -> QColor:
        if self.config.accent == "Custom":
            custom = QColor(self.config.custom_accent)
            if custom.isValid():
                return custom
        return QColor(
            {
                "Violet": "#9b70ee",
                "Blue": "#4f9cf5",
                "Rose": "#e66d9c",
                "Mint": "#48c79a",
            }.get(self.config.accent, "#9b70ee")
        )

    def _apply_theme(self):
        dark = self.config.theme != "Light"
        palette = (
            {
                "bg": "#0d1119",
                "panel": "#121722",
                "card": "#171c28",
                "input": "#202634",
                "border": "#2a3040",
                "text": "#ebecf2",
                "muted": "#9299aa",
                "hover": "#22283a",
            }
            if dark
            else {
                "bg": "#edf0f6",
                "panel": "#f7f8fb",
                "card": "#ffffff",
                "input": "#f2f4f8",
                "border": "#d8ddea",
                "text": "#202432",
                "muted": "#697286",
                "hover": "#e5e9f2",
            }
        )
        accent = self._accent_color().name()
        self.setStyleSheet(
            f"""
            QWidget {{ background: transparent; color: {palette['text']};
                font-family: Segoe UI; font-size: 10px; }}
            QWidget#mainWindow {{ background: {palette['bg']}; }}
            QWidget#sidebar {{ background: {palette['panel']};
                border: 1px solid {palette['border']}; border-radius: 12px; }}
            QFrame#navIndicator {{ background: {palette['hover']};
                border: 1px solid {palette['border']}; border-left: 3px solid {accent};
                border-radius: 9px; }}
            QWidget#titlebar {{ background: transparent; }}
            QWidget#wallpaper, QWidget#wallpaperTint,
            QScrollArea#settingsScroll, QWidget#settingsContent {{
                background: transparent; }}
            QFrame#card {{ background: {palette['card']};
                border: 1px solid {palette['border']}; border-radius: 12px; }}
            QFrame#separator {{ color: {palette['border']}; max-width: 1px; }}
            QLabel#logo {{ background: {accent}; color: white; border-radius: 8px;
                font-size: 19px; font-weight: 700; }}
            QLabel#brand {{ background: transparent; font-size: 11px;
                font-weight: 700; letter-spacing: 1px; }}
            QLabel#brandSub, QLabel#eyebrow {{ background: transparent;
                color: {palette['muted']}; font-size: 8px; font-weight: 700;
                letter-spacing: 1px; }}
            QLabel#headerWelcome {{ background: transparent;
                color: {palette['muted']}; font-size: 9px; }}
            QLabel#status {{ background: transparent; color: {palette['muted']};
                font-size: 8px; }}
            QLabel#muted, QLabel#settingLabel {{ background: transparent;
                color: {palette['muted']}; font-size: 9px; }}
            QLabel#welcome {{ background: transparent; font-size: 24px;
                font-weight: 700; }}
            QLabel#pageTitle {{ background: transparent; font-size: 17px;
                font-weight: 700; }}
            QLabel#homeMetric {{ background: transparent; font-size: 12px;
                font-weight: 600; }}
            QLabel#engineBadge, QLabel#sideBadge {{ background: {palette['panel']};
                color: {accent}; border: 1px solid {palette['border']};
                border-radius: 8px; padding: 4px 7px; font-size: 8px;
                font-weight: 700; }}
            QLabel#eval {{ background: transparent; color: #58c994;
                font-size: 21px; font-weight: 700; }}
            QLabel#best {{ background: transparent; color: {accent};
                font-size: 11px; font-weight: 700; }}
            QPushButton {{ background: {palette['input']};
                border: 1px solid {palette['border']}; border-radius: 7px;
                padding: 6px 8px; font-size: 9px; }}
            QPushButton:hover {{ border-color: {accent}; }}
            QPushButton#accent {{ background: {accent}; color: white;
                border: 1px solid {accent}; font-weight: 700; }}
            QPushButton#navButton {{ background: transparent; border: 1px solid transparent;
                color: {palette['muted']}; font-family: "Segoe UI Symbol";
                font-size: 21px; font-weight: 400; padding: 0; }}
            QPushButton#navButton:hover {{ background: {palette['hover']}; }}
            QPushButton#navButton:checked {{ background: transparent;
                color: {accent}; border-color: transparent; }}
            QPushButton#actionCard {{ text-align: left; white-space: pre-line;
                background: {palette['card']}; border: 1px solid {palette['border']};
                padding: 12px; font-weight: 600; }}
            QPushButton#actionCard:hover {{ border-color: {accent};
                background: {palette['hover']}; }}
            QPushButton#windowControl {{ padding: 0; font-size: 15px; }}
            QComboBox, QSpinBox, QLineEdit, QListWidget {{ background: {palette['input']};
                border: 1px solid {palette['border']}; border-radius: 6px;
                padding: 4px 6px; selection-background-color: {accent}; }}
            QComboBox QAbstractItemView {{ background: {palette['card']};
                selection-background-color: {accent}; }}
            QListWidget {{ padding: 3px; }}
            QCheckBox {{ background: transparent; spacing: 6px; font-size: 9px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; }}
            QCheckBox::indicator:unchecked {{ background: {palette['input']};
                border: 1px solid {palette['border']}; border-radius: 4px; }}
            QCheckBox::indicator:checked {{ background: {accent};
                border: 1px solid {accent}; border-radius: 4px; }}
            QSlider::groove:horizontal {{ height: 4px; background: {palette['border']};
                border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ width: 12px; margin: -5px 0;
                border-radius: 6px; background: {accent}; }}
            QSizeGrip {{ background: transparent; }}
            """
        )
        self._wallpaper_tint.setStyleSheet(
            "background-color: rgba(0, 0, 0, "
            f"{round(self.config.background_tint * 2.2)});"
        )
        if hasattr(self, "btn_accent_color"):
            foreground = "#111111" if self._accent_color().lightness() > 150 else "#ffffff"
            self.btn_accent_color.setText(
                f"Choose custom color  {self._accent_color().name().upper()}"
            )
            self.btn_accent_color.setStyleSheet(
                f"background-color: {accent}; color: {foreground};"
            )
        self.board_view.set_colors(
            QColor(palette["panel"]),
            QColor("#eee7da" if dark else "#f2e7d2"),
            QColor("#8a7868" if dark else "#9b775e"),
            self._accent_color(),
        )

    def _on_theme_changed(self, theme: str):
        self.config.theme = theme
        self._apply_theme()
        save_config(self.config)

    def _on_accent_changed(self, accent: str):
        self.config.accent = accent
        if accent != "Custom":
            self.config.custom_accent = ""
        self._apply_theme()
        save_config(self.config)

    def _choose_custom_accent(self):
        color = QColorDialog.getColor(
            self._accent_color(), self, "Choose accent color"
        )
        if not color.isValid():
            return
        self.config.custom_accent = color.name()
        if self.cmb_accent.findText("Custom") < 0:
            self.cmb_accent.addItem("Custom")
        self.cmb_accent.setCurrentText("Custom")
        self._apply_theme()
        save_config(self.config)

    def _choose_background_image(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Choose a background image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not selected:
            return
        source = Path(selected)
        if QPixmap(str(source)).isNull():
            self.lbl_status.setText("That file could not be loaded as an image.")
            return
        try:
            background_dir = CONFIG_DIR / "backgrounds"
            background_dir.mkdir(parents=True, exist_ok=True)
            destination = background_dir / f"wallpaper{source.suffix.lower()}"
            if source.resolve() != destination.resolve():
                shutil.copy2(source, destination)
        except OSError as error:
            self.lbl_status.setText(f"Could not save background image: {error}")
            return
        self.config.background_image = str(destination)
        self._load_background_image()
        save_config(self.config)
        self.lbl_status.setText("Background image updated.")

    def _remove_background_image(self):
        self.config.background_image = ""
        self._wallpaper_source = QPixmap()
        self.lbl_background_image.setText("No background image selected")
        self._update_background_pixmap()
        save_config(self.config)
        self.lbl_status.setText("Background image removed.")

    def _load_background_image(self):
        image_path = self.config.background_image
        self._wallpaper_source = QPixmap(image_path) if image_path else QPixmap()
        if image_path and self._wallpaper_source.isNull():
            self.lbl_background_image.setText(
                f"Image unavailable: {Path(image_path).name}"
            )
            self.lbl_status.setText("Saved background image could not be loaded.")
        elif image_path:
            self.lbl_background_image.setText(Path(image_path).name)
        else:
            self.lbl_background_image.setText("No background image selected")
        self._update_background_pixmap()

    def _update_background_pixmap(self):
        if self._wallpaper_source.isNull():
            self._wallpaper.clear()
            self._wallpaper_tint.hide()
            return
        self._wallpaper_tint.show()
        target = self.size()
        if target.width() < 1 or target.height() < 1:
            return
        fit = self.config.background_fit
        if fit == "Stretch":
            pixmap = self._wallpaper_source.scaled(
                target,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        elif fit == "Center":
            pixmap = self._wallpaper_source
        elif fit == "Fit":
            pixmap = self._wallpaper_source.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            pixmap = self._wallpaper_source.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = max(0, (pixmap.width() - target.width()) // 2)
            y = max(0, (pixmap.height() - target.height()) // 2)
            pixmap = pixmap.copy(x, y, target.width(), target.height())

        opacity = max(0, min(100, self.config.background_opacity))
        if opacity < 100:
            faded = QPixmap(pixmap.size())
            faded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(faded)
            painter.setOpacity(opacity / 100)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            pixmap = faded
        self._wallpaper.setPixmap(pixmap)
        self._wallpaper_blur.setBlurRadius(self.config.background_blur)

    def _on_background_opacity_changed(self, value: int):
        self.config.background_opacity = value
        self._update_background_pixmap()

    def _on_background_tint_changed(self, value: int):
        self.config.background_tint = value
        self._wallpaper_tint.setStyleSheet(
            f"background-color: rgba(0, 0, 0, {round(value * 2.2)});"
        )

    def _on_background_blur_changed(self, value: int):
        self.config.background_blur = value
        self._wallpaper_blur.setBlurRadius(value)

    def _on_background_fit_changed(self, fit: str):
        self.config.background_fit = fit
        self._update_background_pixmap()
        save_config(self.config)

    def _on_orientation_changed(self, label: str):
        orientation = "white" if label.startswith("White") else "black"
        if orientation == self.config.board_orientation:
            return
        self.config.board_orientation = orientation
        self.tracker.state.orientation = orientation
        self.move_diff.set_orientation(orientation)
        self.move_diff.reset()
        self.board_view.set_orientation(orientation)
        save_config(self.config)

    def _on_coordinates_changed(self, enabled: bool):
        self.config.show_coordinates = enabled
        self.board_view.set_show_coordinates(enabled)
        save_config(self.config)

    def _on_always_on_top_changed(self, enabled: bool):
        self.config.always_on_top = enabled
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.raise_()
        save_config(self.config)

    def _on_opacity_changed(self, value: int):
        self.config.opacity = value / 100
        self.lbl_opacity.setText(f"{value}%")
        self.setWindowOpacity(self.config.opacity)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.rect()
        self._wallpaper.setGeometry(rect)
        self._wallpaper_tint.setGeometry(rect)
        self._update_background_pixmap()

    def _on_engine_settings_changed(self, _value: int):
        self.config.engine.depth = self.spn_depth.value()
        self.config.engine.movetime_ms = self.spn_ms.value()
        self.config.multipv = self.spn_multipv.value()
        self.lbl_analysis_depth.setText(
            f"DEPTH {self.config.engine.depth}  ·  MULTIPV {self.config.multipv}"
        )
        save_config(self.config)

    def _clear_analysis_display(self, best_text: str = "BEST: —"):
        self.lbl_eval.setText("—")
        self.lbl_best.setText(best_text)
        self.lst_lines.clear()
        self.lbl_analysis_eval.setText("—")
        self.lbl_analysis_best.setText("BEST MOVE  —")
        self.lst_analysis_lines.clear()

    def eventFilter(self, watched, event):
        draggable_names = {
            "titlebar",
            "logo",
            "brand",
            "brandSub",
            "headerWelcome",
        }
        if watched.objectName() in draggable_names:
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._drag = (
                    event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
                return True
            if (
                event.type() == QEvent.Type.MouseMove
                and self._drag
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self.move(event.globalPosition().toPoint() - self._drag)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag = None
                return True
        return super().eventFilter(watched, event)

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
                        self._manual_piece_overrides.clear()
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
        self.cmb_orientation.setCurrentText(
            "White at bottom" if o == "white" else "Black at bottom"
        )
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
        self._manual_piece_overrides.clear()
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
            self.cmb_orientation.setCurrentText(
                "White at bottom" if want == "white" else "Black at bottom"
            )
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
            self.lbl_home_engine.setText("LIVE ENGINE")
            self.lbl_status.setText(f"LIVE ENGINE – {self._turn_label()}")
            self._request_analysis()
        else:
            self.timer_eng.stop()
            self._stop_engine_safely()
            self.board_view.clear_analysis()
            self._clear_analysis_display("BEST: — (engine off)")
            self.lbl_home_engine.setText("TRACKING ONLY")
            self.lbl_status.setText("LIVE – tracking only, no engine")

    def _stop_engine_safely(self):
        if self._analyzing:
            self._analysis_pending = False
            self._restart_engine_when_idle = False
            self._stop_engine_after_analysis = True
        else:
            self.engine.stop()

    def _stop_engine(self):
        self._paused = True
        self.timer_eng.stop()
        self._analysis_pending = False
        self._stop_engine_safely()
        self.board_view.clear_analysis()
        self._clear_analysis_display()
        self.lbl_home_engine.setText("ENGINE STOPPED")
        self.lbl_status.setText("Engine stopped")

    def _on_resync_clicked(self):
        """Read the screen position without leaving stale engine lines visible."""
        if self.board_view.edit_mode:
            self._set_position_edit_mode(False, resume_engine=False)
        ok = self._resync_from_screen()
        if ok:
            self._paused = False
            self.board_view.clear_analysis()
            self._clear_analysis_display()
            if self.cmb_mode.currentText() == "LIVE ENGINE":
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
            self._stop_engine_safely()
            self.board_view.clear_analysis()
            self._clear_analysis_display()
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
        previous_board = self.tracker.state.board
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece != previous_board.piece_at(square):
                self._manual_piece_overrides[square] = piece
        self.tracker.state.board = board.copy()
        self.tracker.state.moves = []
        self._last_fen_analyzed = ""
        self.board_view.set_last_move(None)
        self.board_view.clear_analysis()
        self._clear_analysis_display()
        self._refresh()
        if board.is_valid():
            self.lbl_status.setText(
                f"Position updated · {self._turn_label()} · move history cleared"
            )
        else:
            self.lbl_status.setText(
                f"Position updated · {self._turn_label()} · incomplete/invalid position; finish editing before analysis"
            )

    def _apply_manual_piece_overrides(
        self, board: chess.Board
    ) -> tuple[chess.Board, int]:
        if not self._manual_piece_overrides:
            return board, 0
        corrected = board.copy()
        for square, piece in self._manual_piece_overrides.items():
            corrected.set_piece_at(square, piece)
        corrected.castling_rights = 0
        corrected.ep_square = None
        corrected.clear_stack()
        return corrected, len(self._manual_piece_overrides)

    def _advance_manual_piece_override(self, move: chess.Move):
        source = move.from_square
        target = move.to_square
        has_override = source in self._manual_piece_overrides
        source_override = self._manual_piece_overrides.pop(source, None)
        self._manual_piece_overrides.pop(target, None)
        if has_override:
            piece = self.tracker.state.board.piece_at(target)
            self._manual_piece_overrides[target] = piece or source_override

    def _on_internal_move(self, move: chess.Move):
        ok, san = self.tracker.apply_move(move)
        if not ok:
            self.lbl_status.setText(f"Illegal move: {san}")
            self.board_view.update()
            return
        self._advance_manual_piece_override(move)
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
        self._analysis_retry_fen = None
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

        highlighted = highlighted_last_move(img, self.config.board_orientation)
        highlighted_move = highlighted[0] if highlighted is not None else None
        highlighted_turn = highlighted[1] if highlighted is not None else None
        template_warning = ""
        # 1) Prefer template matching (per-piece photos from start position)
        if self.templates.ready:
            try:
                new_board, status, turn_known = self.templates.to_board(
                    img, self.config.board_orientation, turn=highlighted_turn
                )
                if new_board is not None:
                    new_board, correction_count = (
                        self._apply_manual_piece_overrides(new_board)
                    )
                    if not new_board.is_valid():
                        self.lbl_status.setText(
                            "Manual piece corrections conflict with the recognized position; "
                            "edit the board to resolve them before resyncing."
                        )
                        return False
                    if correction_count:
                        status += (
                            f" · kept {correction_count} manual piece correction(s)"
                        )
                n_pieces = len(new_board.piece_map()) if new_board else 0
                if new_board is not None and 8 <= n_pieces <= 32:
                    if new_board.board_fen() == self.tracker.state.board.board_fen():
                        turn_changed = (
                            turn_known
                            and new_board.turn != self.tracker.state.board.turn
                        )
                        if turn_changed:
                            current_board = self.tracker.state.board
                            current_board.turn = new_board.turn
                            current_board.ep_square = new_board.ep_square
                            current_board.halfmove_clock = new_board.halfmove_clock
                            current_board.fullmove_number = new_board.fullmove_number
                            current_board.clear_stack()
                            self.tracker.state.moves = []
                            self.board_view.clear_analysis()
                            self._last_fen_analyzed = ""
                        self.move_diff.force_snapshot(img)
                        self._refresh(highlighted_move)
                        message = (
                            "Screen position and turn synced"
                            if turn_changed
                            else "Screen matches current position"
                        )
                        if correction_count:
                            message += (
                                f" · kept {correction_count} manual piece correction(s)"
                            )
                        self.lbl_status.setText(f"{message} · {self._turn_label()}")
                        return True
                    if turn_known:
                        new_board.castling_rights = 0
                        self.tracker.state.board = new_board
                        self.tracker.state.moves = []
                        self.move_diff.force_snapshot(img)
                        self.board_view.clear_analysis()
                        self._last_fen_analyzed = ""
                        self._refresh(highlighted_move)
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
            self._stop_engine_safely()
            self.board_view.clear_analysis()
            self._clear_analysis_display()
            self.lbl_status.setText(
                f"{template_warning or status} Paste the full move list below and press Sync."
            )
            return False

        n_new = len(new_board.piece_map()) if new_board else 0
        if n_new < 8:
            self.lbl_status.setText(status + " · board unchanged (too few pieces)")
            return False
        new_board, correction_count = self._apply_manual_piece_overrides(new_board)
        if not new_board.is_valid():
            self.lbl_status.setText(
                "Manual piece corrections conflict with the recognized position; "
                "edit the board to resolve them before resyncing."
            )
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
        self.board_view.clear_analysis()
        self._last_fen_analyzed = ""
        self._refresh(highlighted_move)
        if correction_count:
            status += f" · kept {correction_count} manual piece correction(s)"
        self.lbl_status.setText(status)
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
        self._manual_piece_overrides.clear()
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
        self._advance_manual_piece_override(move)
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
        if self.cmb_mode.currentText() != "LIVE ENGINE" and not force:
            return
        if self._paused and not force:
            return
        board = self.tracker.state.board
        if not board.is_valid():
            self.board_view.clear_analysis()
            self._clear_analysis_display("BEST: — (invalid position)")
            self.lbl_status.setText(
                "Position is incomplete or invalid; edit it before engine analysis"
            )
            return
        fen = board.fen()
        if fen != self._analysis_retry_fen:
            self._analysis_retry_fen = None
        if not force and fen == self._last_fen_analyzed:
            return
        if self._analyzing:
            if force:
                self._analysis_pending = True
                self.lbl_status.setText(
                    "Position updated · waiting for current analysis to finish…"
                )
            return
        if not self.engine.ready:
            if not self.engine.start(self.config.engine.threads, self.config.engine.hash_mb):
                self.lbl_status.setText("Stockfish not found – put stockfish*.exe in stockfish\\ folder (or Desktop\\stockfish)")
                self.lbl_home_engine.setText("ENGINE NOT FOUND")
                return
        self.lbl_home_engine.setText("ANALYZING")
        self._analyzing = True
        self._last_fen_analyzed = fen
        self._analysis_fen = fen
        self.lbl_status.setText("Analyzing…")
        self._thread = QThread()
        self._worker = AnalysisWorker(
            self.engine,
            fen,
            self.spn_depth.value(),
            self.spn_ms.value(),
            self.spn_multipv.value(),
        )
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
        closing = self._close_when_idle
        if self._stop_engine_after_analysis:
            self._stop_engine_after_analysis = False
            self._restart_engine_when_idle = False
            self._analysis_pending = False
            if not closing:
                self.engine.stop()
        elif self._restart_engine_when_idle:
            self._restart_engine_when_idle = False
            self.engine.stop()
            if self.engine.start(
                self.config.engine.threads, self.config.engine.hash_mb
            ):
                self.lbl_home_engine.setText("ENGINE RESTARTED")
                self.lbl_status.setText(
                    "Stockfish restarted · retrying the current position…"
                )
            else:
                self._analysis_pending = False
                self.lbl_home_engine.setText("ENGINE ERROR")
                self.lbl_status.setText(
                    "Stockfish stopped unexpectedly and could not restart. "
                    "Check the engine file and try Analyze again."
                )
        should_analyze = self._analysis_pending
        self._analysis_pending = False
        should_analyze = should_analyze or (
            not self._paused
            and self.cmb_mode.currentText() == "LIVE ENGINE"
            and self.tracker.state.board.fen() != self._analysis_fen
        )
        if closing:
            self._close_when_idle = False
            self.close()
            return
        if should_analyze:
            self._request_analysis(force=True)

    @Slot(object)
    def _on_analysis(self, result: AnalysisResult):
        if (
            self._paused
            or result.fen != self.tracker.state.board.fen()
        ):
            return
        if result.error:
            err = str(result.error)
            lowered_error = err.lower()
            if (
                "process died" in lowered_error
                or "engine terminated" in lowered_error
                or "exit code" in lowered_error
            ):
                if self._analysis_retry_fen != result.fen:
                    self._analysis_retry_fen = result.fen
                    self._last_fen_analyzed = ""
                    self._restart_engine_when_idle = True
                    self._analysis_pending = True
                    self.lbl_status.setText(
                        "Stockfish stopped unexpectedly · restarting safely…"
                    )
                else:
                    self._last_fen_analyzed = result.fen
                    self.lbl_home_engine.setText("ENGINE ERROR")
                    self.lbl_status.setText(
                        f"{err}. Automatic retry failed; press Analyze to try again."
                    )
            else:
                self.lbl_status.setText(err)
            return
        self._analysis_retry_fen = None
        self.lbl_eval.setText(result.evaluation or "—")
        self.lbl_best.setText(f"BEST: {result.best_san or '—'}")
        self.lbl_analysis_eval.setText(result.evaluation or "—")
        self.lbl_analysis_best.setText(
            f"BEST MOVE  {result.best_san or '—'}"
        )
        self.lst_lines.clear()
        self.lst_analysis_lines.clear()
        alts = []
        for line in result.lines[: self.spn_multipv.value()]:
            sc = f"M{line.score_mate}" if line.score_mate is not None else (
                f"{line.score_cp/100:+.2f}" if line.score_cp is not None else "?"
            )
            pv = " ".join(line.pv_san[:6])
            display_line = f"{'★' if line.rank==1 else line.rank} {sc}  {pv}"
            self.lst_lines.addItem(display_line)
            self.lst_analysis_lines.addItem(display_line)
            if line.rank > 1 and line.pv_uci:
                alts.append(line.pv_uci[0])
        # Draw on INTERNAL board
        self.board_view.set_analysis_arrows(result.best_uci, alts)
        self.lbl_home_engine.setText("ENGINE READY")
        self.lbl_status.setText("Analysis ready")

    def _refresh(self, last_move_override: Optional[chess.Move] = None):
        b = self.tracker.state.board
        self.board_view.set_board(b)
        moves = self.tracker.state.moves
        last_move = moves[-1] if moves else None
        side = self.tracker.side_to_move()
        n = len(moves)
        if last_move_override is not None and (
            last_move is None or last_move.uci != last_move_override.uci()
        ):
            self.board_view.set_last_move(last_move_override.uci())
            last_mover = not b.turn
            is_my_move = (last_mover == chess.WHITE) == (
                self._my_color() == "white"
            )
            owner = "you" if is_my_move else "opponent"
            last = (
                f"{chess.square_name(last_move_override.from_square)}-"
                f"{chess.square_name(last_move_override.to_square)} ({owner})"
            )
        elif last_move is None:
            self.board_view.set_last_move(None)
            last = "—"
        else:
            self.board_view.set_last_move(last_move.uci)
            last_mover = not b.turn
            is_my_move = (last_mover == chess.WHITE) == (
                self._my_color() == "white"
            )
            owner = "you" if is_my_move else "opponent"
            last = f"{last_move.san} ({owner})"
        turn_text = f"{self._turn_label()} | Last: {last} | Moves: {n}"
        self.lbl_turn.setText(turn_text)
        self.lbl_board_side.setText(
            "WHITE TO MOVE" if b.turn == chess.WHITE else "BLACK TO MOVE"
        )
        self.lbl_home_turn.setText(
            f"{self._turn_label()}  ·  {n} moves"
        )
        self.lst_moves.clear()
        for line in self.tracker.history_pairs():
            self.lst_moves.addItem(line)
        self.lst_moves.scrollToBottom()

    def closeEvent(self, e):
        if self._analyzing:
            e.ignore()
            self._close_when_idle = True
            self._paused = True
            self.timer_cap.stop()
            self.timer_eng.stop()
            self._analysis_pending = False
            self._restart_engine_when_idle = False
            self._stop_engine_after_analysis = True
            return
        self.timer_cap.stop()
        self.timer_eng.stop()
        self.engine.stop()
        self.capture.close()
        self.config.pos_x, self.config.pos_y = self.x(), self.y()
        save_config(self.config)
        e.accept()
