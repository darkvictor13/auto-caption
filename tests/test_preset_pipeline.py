"""Exercise restored presets through the CLI and real FFmpeg exports.

Only speech recognition is replaced with deterministic Portuguese words: no
model download or GPU is required to verify styles and output switches.
"""

import shutil
import subprocess

import pytest

from autocaption import cli, media
from autocaption.presets import DEFAULT_SETTINGS, PresetStore
from autocaption.transcribe import Word

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required for exports")


@pytest.mark.parametrize("style", ["pop", "karaoke", "box"])
@pytest.mark.parametrize("burn,srt", [(True, True), (True, False), (False, True), (False, False)])
def test_restored_preset_exports_video_and_subtitles(tmp_path, monkeypatch, style, burn, srt):
    pytest.importorskip("customtkinter")
    from autocaption.gui import render_preview, settings_to_flags, settings_to_style

    source = tmp_path / "vídeo de teste.mp4"
    subprocess.run([
        media.find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "color=c=0x1a2436:s=320x568:r=10:d=2", "-c:v", "libx264", str(source),
    ], check=True, capture_output=True)
    settings = {**DEFAULT_SETTINGS, "style": style, "font_size": "95", "position": "high",
                "highlight_color": "#00FF88", "box_color": "#004080", "words_per_line": "2",
                "language": "pt", "model_label": "tiny.en - fastest", "caps": False,
                "burn": burn, "srt": srt}
    store = PresetStore(tmp_path / "presets.json")
    store.create("Ótica", settings)
    restored = PresetStore(store.path)
    restored.load()
    settings = restored.get("Ótica")
    calls = []

    def transcribe(path, **kwargs):
        calls.append((path, kwargs))
        return [Word("Existe", 0, .5), Word("uma", .5, 1), Word("dúvida", 1, 1.8)]

    monkeypatch.setattr(cli, "transcribe", transcribe)
    assert cli.main([str(source), *settings_to_flags(settings)]) == 0
    assert calls == [(source.resolve(), {"model_name": "tiny.en", "device": "auto", "language": "pt"})]
    ass = source.with_suffix(".ass").read_text(encoding="utf-8")
    assert "Anton" in ass and "Existe" in ass and "dúvida" in ass
    assert "EXISTE" not in ass
    assert r"\pos(160,182)" in ass
    assert source.with_suffix(".davinci.srt").exists() == srt
    output = source.with_name(source.stem + ".captioned.mp4")
    assert output.exists() == burn
    if burn:
        assert media.probe_video_size(output) == (320, 568)
    preview = tmp_path / "prévia.png"
    render_preview(settings_to_style(settings), preview, width=320, height=568)
    assert preview.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("style", ["pop", "karaoke", "box"])
def test_restored_preset_handles_audio_only_input(tmp_path, monkeypatch, style):
    pytest.importorskip("customtkinter")
    from autocaption.gui import settings_to_flags

    source = tmp_path / "áudio.wav"
    subprocess.run([
        media.find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=1", str(source),
    ], check=True, capture_output=True)
    store = PresetStore(tmp_path / "presets.json")
    store.create("Audio", {**DEFAULT_SETTINGS, "style": style, "language": "auto"})
    store.load()
    monkeypatch.setattr(cli, "transcribe", lambda *args, **kwargs: [Word("Olá", 0, .8)])
    assert cli.main([str(source), *settings_to_flags(store.get("Audio"))]) == 0
    assert source.with_suffix(".ass").is_file()
    assert source.with_suffix(".davinci.srt").is_file()
    assert not source.with_name(source.stem + ".captioned.mp4").exists()
