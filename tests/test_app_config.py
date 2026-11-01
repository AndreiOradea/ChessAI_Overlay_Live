import json

from src.utils import config as app_config
from src.utils.config import AppConfig


def test_ui_settings_are_saved_and_loaded(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(app_config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(app_config, "CONFIG_PATH", config_path)
    config = AppConfig(
        theme="Light",
        accent="Mint",
        custom_accent="#12abef",
        background_image=r"C:\wallpapers\chess.png",
        background_opacity=72,
        background_tint=35,
        background_blur=8,
        background_fit="Fit",
        show_coordinates=False,
        always_on_top=False,
        multipv=4,
    )

    app_config.save_config(config)
    loaded = app_config.load_config()

    assert loaded.theme == "Light"
    assert loaded.accent == "Mint"
    assert loaded.custom_accent == "#12abef"
    assert loaded.background_image == r"C:\wallpapers\chess.png"
    assert loaded.background_opacity == 72
    assert loaded.background_tint == 35
    assert loaded.background_blur == 8
    assert loaded.background_fit == "Fit"
    assert not loaded.show_coordinates
    assert not loaded.always_on_top
    assert loaded.multipv == 4


def test_legacy_config_receives_defaults_for_new_ui_settings(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"mode": "LIVE", "opacity": 0.9}),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_config, "CONFIG_PATH", config_path)

    loaded = app_config.load_config()

    assert loaded.theme == "Midnight"
    assert loaded.accent == "Violet"
    assert loaded.custom_accent == ""
    assert loaded.background_image == ""
    assert loaded.background_opacity == 100
    assert loaded.background_tint == 60
    assert loaded.background_blur == 0
    assert loaded.background_fit == "Fill"
    assert loaded.show_coordinates
    assert loaded.always_on_top
    assert loaded.multipv == 3
