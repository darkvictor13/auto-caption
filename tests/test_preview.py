"""Exercise the actual FFmpeg render used by the Preview style button."""

import shutil
import struct
from dataclasses import replace

import pytest

from autocaption.styles import PRESETS

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required for previews")


@pytest.mark.parametrize("preset,size", [("box", 8), ("box", 130), ("box", 300), ("pop", 130), ("karaoke", 130)])
def test_preview_style_produces_png_with_current_settings(tmp_path, preset, size):
    pytest.importorskip("customtkinter")
    from autocaption.gui import render_preview

    path = tmp_path / "prévia com espaço.png"
    style = replace(PRESETS[preset], font="DejaVu Sans", font_size=size, box_color="#004080")
    render_preview(style, path)
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (540, 960)
    ass = path.with_suffix(".ass").read_text(encoding="utf-8")
    if preset == "box":
        assert "EXISTE UMA DÚVIDA" in ass
        assert r"\c&H804000&\p1" in ass
