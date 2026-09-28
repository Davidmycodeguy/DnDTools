"""Windows' built-in OCR, driven through a long-lived PowerShell worker (win_ocr.ps1).

Starting PowerShell costs about a second, so one worker stays up and reads one image per request
(about 70 ms each). Nothing to install: Windows.Media.Ocr ships with Windows 10 and 11.
"""
import json
import os
import queue
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

OCR_SCRIPT = Path(__file__).with_name("win_ocr.ps1")
READ_TIMEOUT_S = 5.0
START_TIMEOUT_S = 15.0
CREATE_NO_WINDOW = 0x08000000


class OcrError(RuntimeError):
    pass


@dataclass(frozen=True)
class OcrLine:
    text: str
    x: int
    y: int
    w: int
    h: int


def _as_list(value):
    """PowerShell's ConvertTo-Json writes one-item arrays as an object and empty ones as null."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_answer(raw: str):
    try:
        answer = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise OcrError(f"unreadable OCR answer: {raw[:80]!r}") from exc
    if not isinstance(answer, dict) or not answer.get("ok"):
        raise OcrError(str(answer.get("error") if isinstance(answer, dict) else answer))
    return [OcrLine(str(line.get("text", "")), int(line.get("x", 0)), int(line.get("y", 0)),
                    int(line.get("w", 0)), int(line.get("h", 0)))
            for line in _as_list(answer.get("lines")) if isinstance(line, dict)]


def _launch_powershell():
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(OCR_SCRIPT)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        bufsize=1, creationflags=CREATE_NO_WINDOW)


class WindowsOcr:
    def __init__(self, launch=_launch_powershell, timeout=READ_TIMEOUT_S, temp_dir=None):
        self._launch = launch
        self._timeout = timeout
        self._temp_dir = temp_dir or tempfile.gettempdir()
        self._lock = threading.Lock()
        self._process = None
        self._answers = None

    def _start(self):
        process = self._launch()
        answers = queue.Queue()

        def pump():
            for line in process.stdout:
                answers.put(line)
            answers.put(None)
        threading.Thread(target=pump, daemon=True, name="WindowsOcrReader").start()
        self._process, self._answers = process, answers
        ready = self._next_answer(max(self._timeout, START_TIMEOUT_S))
        parse_answer(ready)  # raises when the worker couldn't start OCR

    def _next_answer(self, timeout):
        try:
            line = self._answers.get(timeout=timeout)
        except queue.Empty:
            line = None
        if line is None:
            self._stop()
            raise OcrError("the OCR worker did not answer")
        return line

    def _stop(self):
        process, self._process, self._answers = self._process, None, None
        if process is not None and process.poll() is None:
            process.kill()

    def start(self):
        """Boot the worker now (it takes ~0.5-0.8 s) and warm up recognition (the first read is
        ~5x slower than the rest), so the first real read doesn't wait for either."""
        with self._lock:
            if self._process is not None:
                return
            self._ensure_running()
        self.read(Image.new("RGB", (64, 32)))

    def _ensure_running(self):
        if self._process is None:
            try:
                self._start()
            except OcrError:
                self._stop()
                raise

    def read(self, image):
        """OCR a PIL image; lines with their boxes in the image's pixels."""
        # BMP: uncompressed, so saving takes <1 ms where PNG took ~20 ms.
        path = os.path.join(self._temp_dir, f"dndtools-ocr-{uuid.uuid4().hex}.bmp")
        image.save(path)
        try:
            with self._lock:
                self._ensure_running()
                self._process.stdin.write(path + "\n")
                self._process.stdin.flush()
                return parse_answer(self._next_answer(self._timeout))
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def close(self):
        with self._lock:
            if self._process is not None:
                try:
                    self._process.stdin.write("exit\n")
                    self._process.stdin.flush()
                except (OSError, ValueError):
                    pass
            self._stop()
