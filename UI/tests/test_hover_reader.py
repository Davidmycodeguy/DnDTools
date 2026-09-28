import numpy as np
from PIL import Image

from src.models.hover_reader import TooltipReader
from src.models.tooltip_parser import ItemIndex
from src.models.win_ocr import OcrLine

INDEX = ItemIndex({"OccultistRobe_3001": {"name": "Occultist Robe", "rarity": "Uncommon"}})
ROBE = [OcrLine("Occultist Robe", 98, 19, 162, 18), OcrLine("- +2% Undead Damage Bonus", 45, 214, 246, 16),
        OcrLine("Rarity: Uncommon", 101, 387, 150, 15)]
MERCHANT = [OcrLine("The Collector", 60, 20, 180, 22), OcrLine("Rarity", 160, 800, 60, 16)]


def _frame_with_rules(*rules, width=2000, height=1600):
    frame = np.full((height, width, 3), 8, dtype=np.uint8)
    for left, rule_y, color in rules:
        frame[rule_y:rule_y + 2, left:left + 600] = color
    return Image.fromarray(frame)


class FakeOcr:
    def __init__(self, answers):
        self.answers = list(answers)
        self.reads = 0

    def read(self, image):
        self.reads += 1
        return self.answers.pop(0) if self.answers else []


def test_reads_the_first_candidate_that_is_a_real_tooltip():
    image = _frame_with_rules((300, 400, (140, 140, 140)), (900, 700, (76, 150, 3)))
    ocr = FakeOcr([MERCHANT, ROBE])
    found = TooltipReader(ocr, INDEX).read(image, cursor=(880, 650), scale=1.0)
    assert found is not None
    tip, box = found
    assert tip.item_id == "OccultistRobe_3001" and tip.rolls == (("UndeadDamageMod", 20),)
    assert box.left >= 900


def test_a_screen_already_read_is_not_read_again():
    image = _frame_with_rules((900, 700, (76, 150, 3)))
    ocr = FakeOcr([ROBE])
    reader = TooltipReader(ocr, INDEX)
    first = reader.read(image, cursor=(880, 650), scale=1.0)
    again = reader.read(image, cursor=(880, 650), scale=1.0)
    assert first == again and ocr.reads == 1


def test_lines_that_are_not_tooltips_are_remembered_too():
    image = _frame_with_rules((300, 400, (140, 140, 140)))
    ocr = FakeOcr([MERCHANT])
    reader = TooltipReader(ocr, INDEX)
    assert reader.read(image, cursor=(280, 350), scale=1.0) is None
    assert reader.read(image, cursor=(280, 350), scale=1.0) is None
    assert ocr.reads == 1


def test_no_rule_means_no_read():
    ocr = FakeOcr([ROBE])
    assert TooltipReader(ocr, INDEX).read(_frame_with_rules(), cursor=(500, 500), scale=1.0) is None
    assert ocr.reads == 0

