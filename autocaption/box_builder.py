"""Moving rounded word backgrounds, positioned using libass's own glyph layout.

Measure short batches of colored caption masks with the same FFmpeg/libass
renderer used for export. This avoids font-metric guesses and extra Python
dependencies, including for installed Windows fonts and accented words.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from . import media
from .ass_builder import REF_H, _display, _inline_color, ass_time
from .grouping import CaptionLine
from .styles import StylePreset

# Distinct opaque colors identify each word without changing text geometry.
PALETTE = ("#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF")
BATCH_SIZE = 6
_MASK_THRESHOLD = bytes(255 if value >= 8 else 0 for value in range(256))


def _pixel_bounds(frame: bytes, width: int, color: str):
    """Bounds of the solid glyph pixels (antialiasing is covered by padding)."""
    pixel = bytes.fromhex(color.lstrip("#"))
    left, top, right, bottom = width, len(frame), -1, -1
    offset = frame.find(pixel)
    while offset != -1:
        if offset % 3 == 0:
            y, x = divmod(offset // 3, width)
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
        offset = frame.find(pixel, offset + 1)
    return (left, top, right + 1, bottom + 1) if right >= 0 else None


def _threshold_mask(frame: bytes) -> bytes:
    """Include partially covered glyph pixels, even when none are fully opaque.

    Small letters, punctuation and light fonts can consist entirely of
    antialiased pixels. Requiring an exact 255-valued palette color loses them.
    The layout masks have a black RGB background, so thresholding each channel
    retains the palette identity without requiring a solid interior pixel.
    """
    return frame.translate(_MASK_THRESHOLD)


def _measure(lines, style, width, height, header):
    font_size = max(1, round(style.font_size * height / REF_H))
    mask_height = max(64, font_size * 3)
    mask_height += mask_height % 2
    longest = max((len(" ".join(_display(w.text, style.caps) for w in line.words))
                   for line in lines), default=0)
    # Measure on a wider canvas: otherwise an oversized caption can place a
    # whole word offscreen, which used to trigger a fatal measurement error.
    mask_width = max(width, font_size * (longest + 4) * 2)
    mask_width += mask_width % 2
    mask_header = header.replace(f"PlayResY: {height}\n", f"PlayResY: {mask_height}\n")
    mask_header = mask_header.replace(f"PlayResX: {width}\n", f"PlayResX: {mask_width}\n")
    fonts = Path(__file__).resolve().parent / "fonts"
    results = []
    with tempfile.TemporaryDirectory(prefix="autocaption_box_") as directory:
        for start in range(0, len(lines), BATCH_SIZE):
            batch = lines[start:start + BATCH_SIZE]
            # A caption normally has <= 6 words. Longer CLI lines are measured
            # in passes so every word still gets an unambiguous palette color.
            measured = [[None] * len(line.words) for line in batch]
            count = max((len(line.words) for line in batch), default=0)
            for first_word in range(0, count, len(PALETTE)):
                events = []
                for index, line in enumerate(batch):
                    parts = []
                    for word_index, word in enumerate(line.words):
                        palette_index = word_index - first_word
                        color = PALETTE[palette_index] if 0 <= palette_index < len(PALETTE) else "#000000"
                        parts.append(f"{{\\c{_inline_color(color)}}}{_display(word.text, style.caps)}")
                    events.append(
                        f"Dialogue: 0,{ass_time(index)},{ass_time(index + 1)},Caption,,0,0,0,,"
                        f"{{\\pos({mask_width / 2:.0f},{mask_height / 2:.0f})\\bord0\\shad0}}{' '.join(parts)}"
                    )
                Path(directory, "mask.ass").write_text(mask_header + "\n".join(events) + "\n", encoding="utf-8")
                vf = "format=rgb24,ass=filename=mask.ass"
                if fonts.is_dir():
                    vf += f":fontsdir='{media._filter_path(fonts)}'"
                run = subprocess.run(
                    [media.find_tool("ffmpeg"), "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", f"color=c=black:s={mask_width}x{mask_height}:r=1",
                     "-vf", vf, "-frames:v", str(len(batch)),
                     "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                    cwd=directory, capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if run.returncode:
                    raise RuntimeError("Could not measure the box style with FFmpeg: " + run.stderr.decode("utf-8", errors="replace"))
                frame_size = mask_width * mask_height * 3
                if len(run.stdout) != frame_size * len(batch):
                    raise RuntimeError("FFmpeg returned incomplete caption layout frames.")
                for index, line in enumerate(batch):
                    frame = run.stdout[index * frame_size:(index + 1) * frame_size]
                    frame = _threshold_mask(frame)
                    for word_index in range(first_word, min(first_word + len(PALETTE), len(line.words))):
                        bounds = _pixel_bounds(frame, mask_width, PALETTE[word_index - first_word])
                        # No visible pixels (e.g. zero-width Unicode marks):
                        # keep the caption text and don't abort the whole video.
                        measured[index][word_index] = bounds
            results.extend(measured)
    return results, mask_width, mask_height


def _rounded_rect(width: float, height: float, radius: float) -> str:
    """ASS vector path with cubic Bezier corners."""
    r = min(radius, width / 2, height / 2)
    k = r * 0.55228475
    def p(x, y):
        return f"{x:.2f} {y:.2f}"
    return (
        f"m {p(r, 0)} l {p(width-r, 0)} "
        f"b {p(width-r+k, 0)} {p(width, r-k)} {p(width, r)} "
        f"l {p(width, height-r)} b {p(width, height-r+k)} {p(width-r+k, height)} {p(width-r, height)} "
        f"l {p(r, height)} b {p(r-k, height)} {p(0, height-r+k)} {p(0, height-r)} "
        f"l {p(0, r)} b {p(0, r-k)} {p(r-k, 0)} {p(r, 0)}"
    )


def box_events(lines: list[CaptionLine], style: StylePreset, width: int, height: int, header: str) -> list[str]:
    if not lines:
        return []
    layouts, mask_width, mask_height = _measure(lines, style, width, height, header)
    font_size = max(1, round(style.font_size * height / REF_H))
    pad_x, pad_y = max(2, font_size * 0.13), max(2, font_size * 0.10)
    target_y = round(height * style.pos_y)
    events = []
    for line, bounds in zip(lines, layouts):
        visible = [b for b in bounds if b is not None]
        center_x, center_y = mask_width / 2, mask_height / 2
        margin = min(40 * height / REF_H, width * 0.08)
        half_width = max((max(center_x - b[0], b[2] - center_x) + pad_x for b in visible), default=1)
        fit = min(1.0, (width / 2 - margin) / half_width)
        # Shared height prevents the box from bouncing on accents/descenders.
        top = target_y + (min((b[1] for b in visible), default=center_y) - center_y - pad_y) * fit
        bottom = target_y + (max((b[3] for b in visible), default=center_y) - center_y + pad_y) * fit
        for word, box in zip(line.words, bounds):
            if box is None or ass_time(word.start) == ass_time(word.end):
                continue
            left = width / 2 + (box[0] - center_x - pad_x) * fit
            right = width / 2 + (box[2] - center_x + pad_x) * fit
            drawing = _rounded_rect(right - left, bottom - top, font_size * 0.08 * fit)
            events.append(
                f"Dialogue: 0,{ass_time(word.start)},{ass_time(word.end)},Caption,,0,0,0,,"
                f"{{\\an7\\pos({left:.2f},{top:.2f})\\bord0\\shad0"
                f"\\c{_inline_color(style.box_color)}\\p1}}{drawing}{{\\p0}}"
            )
        text = " ".join(_display(word.text, style.caps) for word in line.words)
        events.append(
            f"Dialogue: 1,{ass_time(line.start)},{ass_time(line.end)},Caption,,0,0,0,,"
            f"{{\\pos({width / 2:.0f},{target_y})\\fscx{fit * 100:.4f}\\fscy{fit * 100:.4f}}}{text}"
        )
    return events
