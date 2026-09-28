import os
import queue
import shutil
import sys

import pytest
from PIL import Image, ImageDraw, ImageFont

from src.models.win_ocr import OcrError, OcrLine, WindowsOcr, parse_answer

READY = '{"ok": true, "ready": true, "language": "en-US"}'


class FakeProcess:
    """Stands in for the PowerShell worker: answers each image path with a scripted JSON line."""

    def __init__(self, answers, ready=READY):
        self.written = []
        self.lines = queue.Queue()
        self.answers = list(answers)
        self.killed = False
        if ready:
            self.lines.put(ready + "\n")
        self.stdin = self
        self.stdout = iter(self.lines.get, None)

    def write(self, text):
        self.written.append(text)
        if text.strip() and text.strip() != "exit" and self.answers:
            self.lines.put(self.answers.pop(0) + "\n")

    def flush(self):
        pass

    def poll(self):
        return 0 if self.killed else None

    def kill(self):
        self.killed = True
        self.lines.put(None)


def test_parse_answer_reads_lines_with_boxes():
    lines = parse_answer('{"ok":true,"lines":[{"text":"Rarity: Epic","x":265,"y":254,"w":199,"h":32}]}')
    assert lines == [OcrLine("Rarity: Epic", 265, 254, 199, 32)]


def test_parse_answer_single_line_object_and_empty():
    # PowerShell's ConvertTo-Json turns a one-item array into an object and an empty one into nothing.
    assert parse_answer('{"ok":true,"lines":{"text":"50","x":1,"y":2,"w":3,"h":4}}') == [OcrLine("50", 1, 2, 3, 4)]
    assert parse_answer('{"ok":true,"lines":null}') == []
    assert parse_answer('{"ok":true}') == []


def test_parse_answer_errors():
    with pytest.raises(OcrError, match="boom"):
        parse_answer('{"ok":false,"error":"boom"}')
    with pytest.raises(OcrError):
        parse_answer("not json")


def test_read_sends_a_temp_image_path_and_returns_lines(tmp_path):
    process = FakeProcess(['{"ok":true,"lines":[{"text":"Gem Ring","x":1,"y":2,"w":3,"h":4}]}'])
    ocr = WindowsOcr(launch=lambda: process, temp_dir=str(tmp_path))
    lines = ocr.read(Image.new("RGB", (40, 20)))
    assert lines == [OcrLine("Gem Ring", 1, 2, 3, 4)]
    path = process.written[0].strip()
    assert path.startswith(str(tmp_path)) and path.endswith(".bmp")  # uncompressed: saves in <1 ms


def test_start_boots_the_worker_and_warms_up_recognition(tmp_path):
    launched = []
    answers = ['{"ok":true,"lines":[]}', '{"ok":true,"lines":[{"text":"Gem Ring","x":1,"y":2,"w":3,"h":4}]}']
    ocr = WindowsOcr(launch=lambda: launched.append(FakeProcess(answers)) or launched[-1], temp_dir=str(tmp_path))
    ocr.start()
    ocr.start()  # already running: nothing more to do
    assert len(launched) == 1 and len(launched[0].written) == 1  # one throwaway read: the first is slow
    assert ocr.read(Image.new("RGB", (4, 4))) == [OcrLine("Gem Ring", 1, 2, 3, 4)] and len(launched) == 1


def test_worker_that_never_answers_times_out_and_is_restarted(tmp_path):
    silent = FakeProcess([])
    answering = FakeProcess(['{"ok":true,"lines":[]}'])
    launched = [silent, answering]
    ocr = WindowsOcr(launch=lambda: launched.pop(0), timeout=0.05, temp_dir=str(tmp_path))
    with pytest.raises(OcrError, match="did not answer"):
        ocr.read(Image.new("RGB", (4, 4)))
    assert silent.killed
    assert ocr.read(Image.new("RGB", (4, 4))) == []


def test_worker_without_ocr_language_fails_clearly(tmp_path):
    process = FakeProcess([], ready='{"ok":false,"error":"Windows has no OCR language installed"}')
    ocr = WindowsOcr(launch=lambda: process, temp_dir=str(tmp_path))
    with pytest.raises(OcrError, match="no OCR language"):
        ocr.read(Image.new("RGB", (4, 4)))


@pytest.mark.skipif(sys.platform != "win32" or not shutil.which("powershell"), reason="needs Windows OCR")
def test_real_windows_ocr_reads_rendered_text(tmp_path):
    image = Image.new("RGB", (900, 120), "black")
    font_path = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "arial.ttf")
    font = ImageFont.truetype(font_path, 56) if os.path.exists(font_path) else ImageFont.load_default()
    ImageDraw.Draw(image).text((20, 25), "Rarity: Epic", fill="white", font=font)
    ocr = WindowsOcr(temp_dir=str(tmp_path))
    try:
        texts = [line.text for line in ocr.read(image)]
    finally:
        ocr.close()
    assert any("Rarity" in t and "Epic" in t for t in texts)


def test_a_worker_that_died_is_restarted_on_the_next_read(tmp_path):
    first = FakeProcess([])
    second = FakeProcess(['{"ok":true,"lines":[]}'])
    launched = [first, second]
    ocr = WindowsOcr(launch=lambda: launched.pop(0), temp_dir=str(tmp_path))
    ocr.start = lambda: None  # boot lazily in this test
    first.killed = True        # e.g. antivirus killed the hidden PowerShell
    first.lines.put(None)
    with pytest.raises(OcrError):
        ocr.read(Image.new("RGB", (4, 4)))
    assert ocr.read(Image.new("RGB", (4, 4))) == [] and not launched


def test_writing_to_a_dead_worker_is_an_ocr_error_not_a_crash(tmp_path):
    class Broken(FakeProcess):
        def write(self, text):
            raise OSError(22, "Invalid argument")
    broken, fresh = Broken([]), FakeProcess(['{"ok":true,"lines":[]}'])
    launched = [broken, fresh]
    ocr = WindowsOcr(launch=lambda: launched.pop(0), temp_dir=str(tmp_path))
    with pytest.raises(OcrError):
        ocr.read(Image.new("RGB", (4, 4)))
    assert ocr.read(Image.new("RGB", (4, 4))) == []
