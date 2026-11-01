#!/usr/bin/env python3
import os, sys
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")
os.environ.setdefault("QT_SCALE_FACTOR", "1")

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from src.utils.config import load_config, APP_NAME
from src.ui.branding import app_icon
from src.ui.main_window import MainWindow
from src.ui.startup_splash import StartupSplash


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setFont(QFont("Segoe UI", 10))
    splash = StartupSplash()
    splash.show()
    app.processEvents()

    win = MainWindow(load_config())
    splash.finished.connect(win.show)
    splash.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
