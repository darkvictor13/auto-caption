"""The GUI must agree with the child process about stdout encoding on Windows."""

import queue
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_gui_worker_reads_portuguese_output_without_replacement_characters(monkeypatch):
    pytest.importorskip("customtkinter")
    from autocaption import gui

    popen = subprocess.Popen
    sentence = "Existe uma dúvida. Você é técnico óptico."
    monkeypatch.setenv("AUTOCAPTION_TEST_MARKER", "inherited")

    def launch(_command, **kwargs):
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        assert kwargs["env"]["PYTHONUTF8"] == "1"
        assert kwargs["env"]["AUTOCAPTION_TEST_MARKER"] == "inherited"
        # Run a real child process; avoid invoking transcription in this test.
        return popen([sys.executable, "-c", f"print({sentence!r})"], **kwargs)

    monkeypatch.setattr(gui.subprocess, "Popen", launch)
    worker = SimpleNamespace(_cancelled=False, _last_output=None, _log_q=queue.Queue())
    gui.App._worker(worker, [Path("teste.mp4")], [])
    messages = []
    while not worker._log_q.empty():
        item = worker._log_q.get_nowait()
        if isinstance(item, str):
            messages.append(item)
    output = "".join(messages)
    assert sentence in output
    assert "\ufffd" not in output
    assert "[error]" not in output
