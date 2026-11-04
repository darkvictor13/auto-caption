"""Named, local snapshots of all GUI settings, independent of caption styles."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

MODEL_CHOICES = {
    "auto (recommended)": None,
    "tiny.en - fastest": "tiny.en",
    "base.en - fast": "base.en",
    "small.en - balanced": "small.en",
    "medium.en - accurate": "medium.en",
    "large-v3 - best (multilingual)": "large-v3",
}

DEFAULT_SETTINGS = {
    "style": "pop",
    "position": "low",
    "highlight_color": "#FFD700",
    "box_color": "#242424",
    "font": "Anton",
    "font_size": "130",
    "words_per_line": "4",
    "language": "en",
    "model_label": "auto (recommended)",
    "caps": True,
    "burn": True,
    "srt": True,
    "nvenc": False,
}


def validate_settings(settings: dict) -> dict:
    """Return a complete, normalized snapshot or reject invalid values."""
    if not isinstance(settings, dict):
        raise ValueError("Preset settings must be an object.")
    result = dict(DEFAULT_SETTINGS)
    result.update({key: value for key, value in settings.items() if key in result})
    for key, default in DEFAULT_SETTINGS.items():
        if type(result[key]) is not type(default):
            raise ValueError(f"Invalid value for {key}.")
    for key, choices in (
        ("style", ("pop", "karaoke", "box")),
        ("position", ("high", "mid", "low")),
        ("model_label", MODEL_CHOICES),
    ):
        if result[key] not in choices:
            raise ValueError(f"Invalid value for {key}.")
    for key in ("highlight_color", "box_color"):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", result[key]):
            raise ValueError(f"Invalid color for {key}.")
        result[key] = result[key].upper()
    for key in ("font_size", "words_per_line"):
        try:
            number = int(result[key])
        except ValueError:
            raise ValueError(f"{key} must be a positive integer.") from None
        if number < 1 or (key == "words_per_line" and number > 6):
            raise ValueError(f"Invalid value for {key}.")
        result[key] = str(number)
    for key in ("font", "language"):
        result[key] = result[key].strip()
        if not result[key]:
            raise ValueError(f"{key} cannot be empty.")
    return result


class PresetConflictError(ValueError):
    """Another app instance changed the preset file since it was loaded."""


class PresetStore:
    def __init__(self, path: Path):
        self.path = path
        self._presets: dict[str, dict] = {}
        self._writable = True
        self._source: bytes | None = None

    def load(self) -> None:
        """Missing files are normal; damaged files must never be overwritten."""
        self._writable = False
        try:
            source = self.path.read_bytes()
            raw = json.loads(source.decode("utf-8"))
        except FileNotFoundError:
            self._presets = {}
            self._writable = True
            self._source = None
            return
        if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("presets"), dict):
            raise ValueError("Unsupported or invalid preset file.")
        loaded = {}
        for name, settings in raw["presets"].items():
            clean = self._validate_name(name, loaded)
            loaded[clean] = validate_settings(settings)
        self._presets = loaded
        self._source = source
        self._writable = True

    @staticmethod
    def _validate_name(name: str, existing: dict, excluding: str | None = None) -> str:
        name = name.strip()
        if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError("Use a preset name with 1 to 80 characters.")
        if any(key != excluding and key.casefold() == name.casefold() for key in existing):
            raise ValueError("A preset with this name already exists.")
        return name

    def names(self) -> list[str]:
        return sorted(self._presets, key=str.casefold)

    def get(self, name: str) -> dict:
        return dict(self._presets[name])

    def _write(self, presets: dict) -> None:
        if not self._writable:
            raise ValueError("Cannot save presets until the existing preset file can be loaded.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "presets": presets}, ensure_ascii=False, indent=2)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=self.path.parent,
                                             suffix=".tmp", delete=False) as file:
                temporary = Path(file.name)
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            try:
                current = self.path.read_bytes()
            except FileNotFoundError:
                current = None
            if current != self._source:
                raise PresetConflictError(
                    "Presets changed in another window. The list will be reloaded; "
                    "select a preset and try again. Current settings are kept."
                )
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self._presets = presets
        self._source = payload.encode("utf-8")

    def create(self, name: str, settings: dict) -> str:
        name = self._validate_name(name, self._presets)
        self._write({**self._presets, name: validate_settings(settings)})
        return name

    def update(self, name: str, settings: dict) -> None:
        self.get(name)
        self._write({**self._presets, name: validate_settings(settings)})

    def rename(self, name: str, new_name: str) -> str:
        settings = self.get(name)
        new_name = self._validate_name(new_name, self._presets, excluding=name)
        updated = dict(self._presets)
        del updated[name]
        updated[new_name] = settings
        self._write(updated)
        return new_name

    def duplicate(self, name: str, new_name: str) -> str:
        return self.create(new_name, self.get(name))

    def delete(self, name: str) -> None:
        updated = dict(self._presets)
        del updated[name]
        self._write(updated)
