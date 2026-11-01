from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QScrollArea

from src.ui.main_window import MainWindow
from src.utils.config import AppConfig


class StubEngine:
    ready = False

    def stop(self):
        pass


class StubCapture:
    def close(self):
        pass


class StubTemplates:
    ready = False


def make_window(monkeypatch, qtbot):
    monkeypatch.setattr("src.ui.main_window.save_config", lambda _config: None)
    monkeypatch.setattr(
        "src.ui.main_window.StockfishEngine", lambda _path: StubEngine()
    )
    monkeypatch.setattr("src.ui.main_window.ScreenCapture", StubCapture)
    monkeypatch.setattr("src.ui.main_window.PieceTemplateMatcher", StubTemplates)
    window = MainWindow(AppConfig(mode="LIVE"))
    qtbot.addWidget(window)
    return window


def test_compact_navigation_and_welcome_animation(qtbot, monkeypatch):
    window = make_window(monkeypatch, qtbot)

    assert window.size().width() == 860
    assert window.windowType() == Qt.WindowType.Window
    assert window.nav_home.isChecked()
    assert [button.text() for button in (
        window.nav_home,
        window.nav_board,
        window.nav_analysis,
        window.nav_settings,
    )] == ["⌂", "♟", "↗", "⚙"]
    assert [button.accessibleName() for button in (
        window.nav_home,
        window.nav_board,
        window.nav_analysis,
        window.nav_settings,
    )] == ["Home", "Board", "Analysis", "Settings"]
    assert window.nav_home.toolTip() == "Home"
    assert window.pages.currentWidget() is window.page_home

    window._type_welcome()
    assert window.lbl_welcome.text().startswith("W")
    window.nav_settings.click()
    assert window.pages.currentWidget() is window.page_settings

    window.close()


def test_sidebar_selection_indicator_slides_to_active_page(qtbot, monkeypatch):
    window = make_window(monkeypatch, qtbot)
    window.show()
    qtbot.wait(30)

    window.nav_board.click()
    assert window.pages.currentWidget() is window.page_board
    assert window._sidebar_animation.endValue() == window.nav_board.geometry().adjusted(
        1, 0, -1, 0
    )
    qtbot.wait(260)
    assert window.sidebar_indicator.geometry() == window.nav_board.geometry().adjusted(
        1, 0, -1, 0
    )

    window.close()


def test_settings_update_persisted_config_and_board(qtbot, monkeypatch):
    window = make_window(monkeypatch, qtbot)
    window.nav_settings.click()

    window.cmb_theme.setCurrentText("Light")
    window.cmb_accent.setCurrentText("Blue")
    window.chk_coordinates.setChecked(False)
    window.cmb_orientation.setCurrentText("Black at bottom")
    window.spn_depth.setValue(22)
    window.spn_ms.setValue(1200)
    window.spn_multipv.setValue(4)
    window.sld_opacity.setValue(85)

    assert window.config.theme == "Light"
    assert window.config.accent == "Blue"
    assert not window.board_view._show_coordinates
    assert window.config.board_orientation == "black"
    assert window.board_view._orientation == "black"
    assert window.config.engine.depth == 22
    assert window.config.engine.movetime_ms == 1200
    assert window.config.multipv == 4
    assert window.config.opacity == 0.85

    window.chk_always_on_top.setChecked(False)
    assert not window.config.always_on_top
    assert not (
        window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    )
    window.close()


def test_settings_controls_are_available_in_scrollable_cards(qtbot, monkeypatch):
    window = make_window(monkeypatch, qtbot)
    window.show()
    window.nav_settings.click()
    qtbot.wait(250)

    scroll = window.page_settings.findChild(QScrollArea, "settingsScroll")
    assert scroll is not None
    for control in (window.cmb_theme, window.cmb_orientation, window.spn_depth):
        assert scroll.widget().isAncestorOf(control)
        assert control.isVisible()

    window.close()


def test_custom_accent_color_is_applied_and_saved(qtbot, monkeypatch):
    window = make_window(monkeypatch, qtbot)
    monkeypatch.setattr(
        "src.ui.main_window.QColorDialog.getColor",
        lambda *_args, **_kwargs: QColor("#23a8d1"),
    )

    window.btn_accent_color.click()

    assert window.config.accent == "Custom"
    assert window.config.custom_accent == "#23a8d1"
    assert window._accent_color().name() == "#23a8d1"
    assert window.cmb_accent.currentText() == "Custom"
    window.close()


def test_background_controls_load_image_and_allow_window_resize(
    qtbot, monkeypatch, tmp_path
):
    image_path = tmp_path / "wallpaper.png"
    image = QPixmap(80, 60)
    image.fill(QColor("#56789a"))
    assert image.save(str(image_path))
    window = make_window(monkeypatch, qtbot)
    window.config.background_image = str(image_path)
    window.config.background_opacity = 100
    window._load_background_image()
    window.show()
    window.nav_settings.click()
    qtbot.wait(100)

    assert not window._wallpaper.pixmap().isNull()
    assert not window._wallpaper_tint.isHidden()
    assert window.lbl_background_image.text() == image_path.name
    window.sld_background_opacity.setValue(70)
    window.sld_background_tint.setValue(40)
    window.sld_background_blur.setValue(8)
    window.cmb_background_fit.setCurrentText("Fit")
    assert window.config.background_opacity == 70
    assert window.config.background_tint == 40
    assert window.config.background_blur == 8
    assert window.config.background_fit == "Fit"
    assert window._wallpaper_blur.blurRadius() == 8

    window.resize(920, 600)
    assert window.size().width() == 920
    assert window.size().height() == 600
    assert window.size_grip.isVisible()
    window._remove_background_image()
    assert window._wallpaper_tint.isHidden()
    window.close()


def test_background_selection_copies_image_into_app_settings(
    qtbot, monkeypatch, tmp_path
):
    source = tmp_path / "chosen.png"
    image = QPixmap(32, 24)
    image.fill(QColor("#aabbcc"))
    assert image.save(str(source))
    config_dir = tmp_path / "app-data"
    monkeypatch.setattr("src.ui.main_window.CONFIG_DIR", config_dir)
    monkeypatch.setattr(
        "src.ui.main_window.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), "Images"),
    )
    window = make_window(monkeypatch, qtbot)

    window.btn_background_choose.click()

    stored_image = config_dir / "backgrounds" / "wallpaper.png"
    assert Path(window.config.background_image) == stored_image
    assert stored_image.is_file()
    assert window.lbl_background_image.text() == stored_image.name
    window.close()
