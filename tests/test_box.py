"""Render-level coverage for word boxes and their alignment with real fonts."""

import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from autocaption.ass_builder import build_ass
from autocaption.grouping import CaptionLine
from autocaption.media import _filter_path
from autocaption.styles import PRESETS
from autocaption.transcribe import Word

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required for box layout")


def _render(ass_path, width, height, time):
    fonts = Path(__file__).resolve().parents[1] / "autocaption" / "fonts"
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
         f"color=c=0x887e72:s={width}x{height}:r=10", "-vf",
         f"format=rgb24,ass=filename={ass_path.name}:fontsdir='{_filter_path(fonts)}'",
         "-ss", str(time), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
        cwd=ass_path.parent, check=True, capture_output=True,
    ).stdout


@pytest.mark.parametrize("width,height,font_size", [(540, 960, 130), (1080, 1920, 130), (1280, 720, 130), (360, 640, 300)])
def test_box_follows_each_word_and_contains_its_glyphs(tmp_path, width, height, font_size):
    from autocaption.box_builder import _pixel_bounds

    words = [Word("Existe", 0, .7), Word("uma", .7, 1.4), Word("dúvida", 1.4, 2.1)]
    line = CaptionLine(words)
    style = replace(PRESETS["box"], box_color="#004080", font_size=font_size)
    doc = build_ass([line], style, width, height)
    path = tmp_path / "captions.ass"
    path.write_text(doc, encoding="utf-8")
    boxes = [l for l in doc.splitlines() if l.startswith("Dialogue: 0,")]
    assert len(boxes) == 3
    assert sum(l.startswith("Dialogue: 1,") for l in doc.splitlines()) == 1
    positions = [tuple(map(float, re.search(r"\\pos\(([^,]+),([^)]*)\)", b).groups())) for b in boxes]
    assert positions[0][0] < positions[1][0] < positions[2][0]
    assert len({y for _, y in positions}) == 1
    previous_left = -1
    for i, sample in enumerate((.3, 1., 1.7)):
        frame = _render(path, width, height, sample)
        rect = _pixel_bounds(frame, width, "#004080")
        assert rect is not None
        assert rect[0] > previous_left
        previous_left = rect[0]
        # Measure text alone with just the active word visible, keeping the
        # full phrase's advances, and verify the rendered box encloses it.
        only = " ".join((f"{{\\alpha&H00&}}{w.text.upper()}" if j == i
                         else f"{{\\alpha&HFF&}}{w.text.upper()}") for j, w in enumerate(words))
        active_path = tmp_path / "active.ass"
        header = doc.split("Dialogue:")[0]
        text_event = next(l for l in doc.splitlines() if l.startswith("Dialogue: 1,"))
        text_tags = text_event.split(",", 9)[9].split("}", 1)[0] + "}"
        active_path.write_text(header + f"Dialogue: 1,0:00:00.00,0:00:02.10,Caption,,0,0,0,,"
                               f"{text_tags}{only}\n", encoding="utf-8")
        glyph = _pixel_bounds(_render(active_path, width, height, sample), width, "#FFFFFF")
        assert glyph is not None
        assert rect[0] < glyph[0] < glyph[2] < rect[2]
        assert rect[1] < glyph[1] < glyph[3] < rect[3]
    assert _pixel_bounds(_render(path, width, height, 2.3), width, "#004080") is None


def test_box_preserves_accents_lowercase_and_longer_lines():
    words = [Word(t, i * .2, (i + 1) * .2) for i, t in enumerate("Existe uma dúvida e você já pode perguntar".split())]
    style = replace(PRESETS["box"], font_size=65, caps=False)
    doc = build_ass([CaptionLine(words)], style, 1080, 1920)
    assert "Existe uma dúvida e você já pode perguntar" in doc
    assert sum(l.startswith("Dialogue: 0,") for l in doc.splitlines()) == 8


def test_box_empty_transcript():
    assert "Dialogue:" not in build_ass([], PRESETS["box"], 1080, 1920)


def test_box_layout_across_batches_and_font_families():
    lines = [CaptionLine([Word("ação", i, i + .5), Word("óculos", i + .5, i + 1)]) for i in range(13)]
    doc = build_ass(lines, replace(PRESETS["box"], font="DejaVu Sans", caps=False), 540, 960)
    assert sum(l.startswith("Dialogue: 0,") for l in doc.splitlines()) == 26
    assert sum(l.startswith("Dialogue: 1,") for l in doc.splitlines()) == 13


def test_box_settings_match_export_flags():
    pytest.importorskip("customtkinter")
    from autocaption.gui import DEFAULT_SETTINGS, settings_to_flags, settings_to_style

    settings = dict(DEFAULT_SETTINGS, style="box", box_color="#004080")
    flags = settings_to_flags(settings)
    assert flags[flags.index("--box-color") + 1] == "#004080"
    assert settings_to_style(settings).box_color == "#004080"
    assert settings_to_style(settings).text_color == "#FFFFFF"


def test_measurement_accepts_glyphs_without_solid_pixels():
    from autocaption.box_builder import _pixel_bounds, _threshold_mask

    # Two faint antialiased red pixels: neither ever reaches #FF0000.
    frame = bytes([0, 0, 0, 90, 0, 0, 170, 0, 0, 0, 0, 0])
    assert _pixel_bounds(frame, 4, "#FF0000") is None
    assert _pixel_bounds(_threshold_mask(frame), 4, "#FF0000") == (1, 0, 3, 1)


def test_box_tiny_light_font_and_invisible_marks_do_not_abort():
    words = [Word(w, i * .3, (i + 1) * .3) for i, w in enumerate(["É", "uma", "dúvida", ".", "\u200b"])]
    doc = build_ass([CaptionLine(words)], replace(PRESETS["box"], font="DejaVu Sans", font_size=8), 1080, 1920)
    assert "É UMA DÚVIDA ." in doc
    assert sum(l.startswith("Dialogue: 1,") for l in doc.splitlines()) == 1
    # Visible words all get boxes, including the dot with only antialias pixels.
    assert sum(l.startswith("Dialogue: 0,") for l in doc.splitlines()) == 4
