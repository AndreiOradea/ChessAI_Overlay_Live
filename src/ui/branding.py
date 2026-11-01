from pathlib import Path

from PySide6.QtGui import QIcon


def brand_image_path() -> Path:
    return Path(__file__).with_name("assets") / "chessai-knight.png"


def app_icon() -> QIcon:
    return QIcon(str(brand_image_path()))
