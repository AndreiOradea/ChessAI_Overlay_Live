#!/usr/bin/env python3
"""
ChessAI Overlay LIVE
Universal chess companion overlay for Windows 10/11.

Launch:
    python main.py
"""

import sys
import os

# Pixel-accurate coordinates for screen capture (must be set BEFORE Qt loads)
# Prevents half-screen region selector on 125%/150% Windows display scaling.
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

# Ensure project root is on path
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.utils.config import load_config, APP_NAME
from src.ui.overlay import OverlayPanel


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ChessAI")
    app.setStyle("Fusion")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    config = load_config()
    panel = OverlayPanel(config)
    panel.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
