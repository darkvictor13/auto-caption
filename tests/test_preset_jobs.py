"""The Generate action takes a stable snapshot of the applied preset."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from autocaption.presets import DEFAULT_SETTINGS


def make_app(settings, files):
    return SimpleNamespace(
        _worker_thread=None, files=files, _gather_settings=lambda: settings,
        _save_settings=Mock(), _worker=Mock(), generate_button=Mock(), cancel_button=Mock(),
        open_button=Mock(), progress=Mock(), _cancelled=True, _last_output="old",
    )


def test_generation_captures_queue_and_all_settings_before_controls_change(monkeypatch):
    pytest.importorskip("customtkinter")
    from autocaption import gui

    settings = {**DEFAULT_SETTINGS, "style": "box", "font": "Anton", "language": "pt",
                "burn": False, "srt": False, "nvenc": True}
    files = [Path("one.mp4"), Path("two.mp4")]
    app = make_app(settings, files)
    thread = Mock()
    factory = Mock(return_value=thread)
    monkeypatch.setattr(gui.threading, "Thread", factory)
    gui.App._generate(app)
    captured_files, flags = factory.call_args.kwargs["args"]
    assert flags == gui.settings_to_flags(settings)
    settings["style"] = "pop"
    files.clear()
    assert captured_files == [Path("one.mp4"), Path("two.mp4")]
    assert flags[flags.index("--style") + 1] == "box"
    thread.start.assert_called_once()
    assert not app._cancelled and app._last_output is None
    app.generate_button.configure.assert_called_once_with(state="disabled")
    app._save_settings.assert_called_once()
    app._proc = Mock()
    app._proc.poll.return_value = None
    gui.App._cancel(app)
    assert app._cancelled
    app._proc.terminate.assert_called_once()


@pytest.mark.parametrize("case", ["empty", "invalid", "busy"])
def test_generation_does_not_start_when_not_ready(monkeypatch, case):
    pytest.importorskip("customtkinter")
    from autocaption import gui

    settings = {**DEFAULT_SETTINGS, "font_size": "invalid" if case == "invalid" else "130"}
    app = make_app(settings, [] if case == "empty" else [Path("test.mp4")])
    if case == "busy":
        app._worker_thread = Mock()
        app._worker_thread.is_alive.return_value = True
    factory = Mock()
    monkeypatch.setattr(gui.threading, "Thread", factory)
    monkeypatch.setattr(gui.messagebox, "showinfo", Mock())
    monkeypatch.setattr(gui.messagebox, "showerror", Mock())
    gui.App._generate(app)
    factory.assert_not_called()
    app._save_settings.assert_not_called()
