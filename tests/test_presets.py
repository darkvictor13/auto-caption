"""User presets survive restarts and restore every setting used by the GUI."""

import json

import pytest

from autocaption.presets import DEFAULT_SETTINGS, PresetStore


def optical_settings():
    return {
        "style": "box", "position": "high", "highlight_color": "#00FF88",
        "box_color": "#004080", "font": "Montserrat ExtraBold", "font_size": "95",
        "words_per_line": "3", "language": "pt", "model_label": "large-v3 - best (multilingual)",
        "caps": False, "burn": False, "srt": False, "nvenc": True,
    }


def test_full_crud_survives_restart_without_changing_other_presets(tmp_path):
    path = tmp_path / "config" / "presets.json"
    store = PresetStore(path)
    store.load()
    settings = optical_settings()
    assert set(settings) == set(DEFAULT_SETTINGS)
    assert store.create(" Ótica ", settings) == "Ótica"
    settings["font"] = "changed outside store"
    assert store.get("Ótica") == optical_settings()
    store.create("Podcast", DEFAULT_SETTINGS)
    store.duplicate("Ótica", "Ótica filial")
    store.rename("Ótica", "ÓTICA")
    store.update("ÓTICA", {**optical_settings(), "font_size": "110"})
    copy = store.get("Ótica filial")
    copy["box_color"] = "external mutation"
    restarted = PresetStore(path)
    restarted.load()
    assert restarted.get("Ótica filial") == optical_settings()
    assert restarted.get("ÓTICA")["font_size"] == "110"
    restarted.delete("ÓTICA")
    store.load()
    assert store.names() == ["Podcast", "Ótica filial"]
    assert store.get("Podcast") == DEFAULT_SETTINGS
    assert "Ótica" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["", "   ", "x" * 81, "bad\nname", "óTiCa"])
def test_reject_invalid_or_duplicate_names_without_changing_disk(tmp_path, name):
    store = PresetStore(tmp_path / "presets.json")
    store.create("Ótica", DEFAULT_SETTINGS)
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.create(name, DEFAULT_SETTINGS)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("override", [
    {"font_size": "zero"}, {"font_size": "0"}, {"words_per_line": "7"},
    {"box_color": "bad"}, {"style": "unknown"}, {"caps": "false"},
    {"model_label": "unknown"}, {"language": " "},
])
def test_reject_invalid_settings(tmp_path, override):
    store = PresetStore(tmp_path / "presets.json")
    with pytest.raises(ValueError):
        store.create("Invalid", {**DEFAULT_SETTINGS, **override})
    assert store.names() == []
    assert not store.path.exists()


@pytest.mark.parametrize("content", ["broken json", "[]", '{"version": 2, "presets": {}}',
                                         '{"version": 1, "presets": {"Broken": null}}'])
def test_bad_file_is_preserved_and_cannot_be_overwritten(tmp_path, content):
    path = tmp_path / "presets.json"
    path.write_text(content, encoding="utf-8")
    store = PresetStore(path)
    with pytest.raises(ValueError):
        store.load()
    with pytest.raises(ValueError):
        store.create("New", DEFAULT_SETTINGS)
    assert path.read_text(encoding="utf-8") == content


def test_failed_atomic_save_keeps_disk_and_memory(tmp_path, monkeypatch):
    from autocaption import presets

    store = PresetStore(tmp_path / "presets.json")
    store.create("Ótica", optical_settings())
    before = store.path.read_bytes()

    def fail(*args):
        raise OSError("Disk unavailable")

    monkeypatch.setattr(presets.os, "replace", fail)
    with pytest.raises(OSError):
        store.update("Ótica", DEFAULT_SETTINGS)
    assert store.get("Ótica") == optical_settings()
    assert store.path.read_bytes() == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_older_preset_receives_defaults_for_new_settings(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps({"version": 1, "presets": {"Old": {"style": "box"}}}))
    store = PresetStore(path)
    store.load()
    assert store.get("Old") == {**DEFAULT_SETTINGS, "style": "box"}


def test_gui_crud_and_generation_flags(tmp_path, monkeypatch):
    pytest.importorskip("customtkinter")
    from autocaption import gui

    monkeypatch.setattr(gui, "CONFIG_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(gui.App, "_check_ffmpeg", lambda self: None)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *args: True)
    app = gui.App()
    app.withdraw()
    try:
        def name(value):
            monkeypatch.setattr(gui.ctk, "CTkInputDialog", lambda **kwargs: type(
                "Dialog", (), {"get_input": lambda self: value})())

        app._apply_settings(optical_settings())
        name("Ótica")
        app._edit_preset("create")
        assert app.preset_var.get() == "Ótica"
        app._apply_settings(DEFAULT_SETTINGS)
        app._apply_preset("Ótica")
        assert app._gather_settings() == optical_settings()
        flags = gui.settings_to_flags(app._gather_settings())
        for flag, value in (("--style", "box"), ("--font", "Montserrat ExtraBold"),
                            ("--model", "large-v3"), ("--language", "pt"),
                            ("--box-color", "#004080"), ("--words-per-line", "3")):
            assert flags[flags.index(flag) + 1] == value
        assert {"--no-caps", "--no-burn", "--no-srt", "--nvenc"} <= set(flags)
        preview = gui.settings_to_style(app._gather_settings())
        assert (preview.mode, preview.font, preview.box_color) == ("box", "Montserrat ExtraBold", "#004080")
        app.font_size_var.set("110")
        app._edit_preset("update")
        name("Ótica filial")
        app._edit_preset("duplicate")
        name("Filial")
        app._edit_preset("rename")
        assert app.preset_store.get("Filial")["font_size"] == "110"
        app._edit_preset("delete")
        assert app.preset_var.get() == ""
        assert app.font_size_var.get() == "110"
        assert app.preset_store.names() == ["Ótica"]
        app._save_settings()
        assert json.loads((tmp_path / "settings.json").read_text())["font_size"] == "110"
        # Dialog cancellation and denied confirmations must not mutate a preset.
        before = app.preset_store.path.read_bytes()
        name(None)
        app._edit_preset("create")
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *args: False)
        app._apply_preset("Ótica")
        app.font_size_var.set("200")
        app._edit_preset("update")
        app._edit_preset("delete")
        assert app.preset_store.path.read_bytes() == before
        assert app.preset_var.get() == "Ótica"
    finally:
        app._on_close()


def test_gui_disables_preset_controls_when_file_is_damaged(tmp_path):
    pytest.importorskip("customtkinter")
    from autocaption import gui
    from types import SimpleNamespace
    from unittest.mock import Mock

    path = tmp_path / "presets.json"
    path.write_text("damaged", encoding="utf-8")
    app = SimpleNamespace(preset_store=PresetStore(path), preset_menu=Mock(),
                          preset_buttons={key: Mock() for key in ("create", "update", "delete")},
                          preset_status=Mock(), _log=Mock())
    gui.App._load_presets(app)
    app.preset_menu.configure.assert_called_once_with(state="disabled")
    for button in app.preset_buttons.values():
        button.configure.assert_called_once_with(state="disabled")
    assert "Existing file preserved" in app._log.call_args.args[0]
    assert path.read_text(encoding="utf-8") == "damaged"
