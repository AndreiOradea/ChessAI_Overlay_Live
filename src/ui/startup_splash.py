from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from src.ui.branding import app_icon, brand_image_path


class StartupSplash(QWidget):
    finished = Signal()

    INTRO_DURATION_MS = 1900
    FADE_DURATION_MS = 1000
    WELCOME_TEXT = "Welcome to ChessAI Helper"

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(460, 270)
        self._logo = QPixmap(str(brand_image_path()))
        self._progress = 0.0
        self._intro_animation = QVariantAnimation(self)
        self._intro_animation.setDuration(self.INTRO_DURATION_MS)
        self._intro_animation.setStartValue(0.0)
        self._intro_animation.setEndValue(1.0)
        self._intro_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._intro_animation.valueChanged.connect(self._set_progress)
        self._intro_animation.finished.connect(self._fade_out)

        self._fade_animation = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_animation.setDuration(self.FADE_DURATION_MS)
        self._fade_animation.setStartValue(1.0)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_animation.finished.connect(self._finish)

    @property
    def progress(self) -> float:
        return self._progress

    @progress.setter
    def progress(self, value: float):
        self._progress = value
        self.update()

    def start(self):
        self._intro_animation.start()

    def _set_progress(self, value):
        self.progress = float(value)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        bounds = self.rect().adjusted(1, 1, -1, -1)
        panel = QPainterPath()
        panel.addRoundedRect(bounds, 22, 22)
        painter.fillPath(panel, QColor("#0e1119"))
        painter.setPen(QPen(QColor("#303544"), 1))
        painter.drawPath(panel)

        center_x = self.width() / 2
        reveal = min(1.0, self._progress / 0.34)
        logo_center_y = 83
        if not self._logo.isNull():
            logo_size = round(100 + 12 * reveal)
            logo = self._logo.scaled(
                logo_size,
                logo_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.setOpacity(reveal)
            painter.drawPixmap(
                round(center_x - logo.width() / 2),
                round(logo_center_y - logo.height() / 2),
                logo,
            )
            painter.setOpacity(1.0)

        text_progress = max(0.0, min(1.0, (self._progress - 0.28) / 0.55))
        typed_count = round(len(self.WELCOME_TEXT) * text_progress)
        welcome = self.WELCOME_TEXT[:typed_count]
        painter.setPen(QColor("#f3f1fa"))
        welcome_font = painter.font()
        welcome_font.setFamily("Segoe UI")
        welcome_font.setPixelSize(22)
        welcome_font.setBold(True)
        painter.setFont(welcome_font)
        welcome_rect = painter.fontMetrics().boundingRect(welcome)
        text_x = center_x - welcome_rect.width() / 2
        text_y = 163
        painter.drawText(int(text_x), text_y, welcome)

        if typed_count == len(self.WELCOME_TEXT) and int(self._progress * 5) % 2 == 0:
            cursor_x = text_x + welcome_rect.width() + 4
            painter.setPen(QPen(QColor("#b28aff"), 2))
            painter.drawLine(int(cursor_x), text_y - 19, int(cursor_x), text_y + 3)

        subtitle_font = painter.font()
        subtitle_font.setPixelSize(10)
        subtitle_font.setBold(False)
        painter.setFont(subtitle_font)
        painter.setPen(QColor("#9299aa"))
        painter.drawText(
            0,
            193,
            self.width(),
            20,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "LIVE CHESS ANALYSIS",
        )

        bar_left, bar_y, bar_width = 64, 226, self.width() - 128
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#242938"))
        painter.drawRoundedRect(bar_left, bar_y, bar_width, 3, 1.5, 1.5)
        painter.setBrush(QColor("#9a70ee"))
        painter.drawRoundedRect(
            bar_left, bar_y, int(bar_width * self._progress), 3, 1.5, 1.5
        )

    def _fade_out(self):
        self._fade_animation.start()

    def _finish(self):
        self.close()
        self.finished.emit()
