from src.ui.startup_splash import StartupSplash


def test_splash_finishes_and_closes(qtbot):
    splash = StartupSplash()
    splash._intro_animation.setDuration(1)
    splash._fade_animation.setDuration(1)
    qtbot.addWidget(splash)

    with qtbot.waitSignal(splash.finished, timeout=1000):
        splash.show()
        splash.start()

    assert not splash.isVisible()


def test_splash_has_compact_window_and_welcome_text():
    splash = StartupSplash()

    assert splash.size().width() == 460
    assert splash.size().height() == 270
    assert splash.WELCOME_TEXT.startswith("Welcome")
    assert not splash._logo.isNull()
