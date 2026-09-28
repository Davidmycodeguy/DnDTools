from types import SimpleNamespace

import numpy as np
from PIL import Image

from src.models.hover_reader import PanelLine, TooltipReader, describe_value
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


def _tip(rolls=(), unread=()):
    return SimpleNamespace(title="Occultist Robe", rarity="Uncommon", item_id="OccultistRobe_3001",
                           rolls=rolls, base=(), unread=unread)


def test_describe_value_with_a_model_estimate():
    estimate = SimpleNamespace(value=245.4, low=190.2, high=301.0, floor=210.0, confidence="high")
    lines = describe_value(_tip(), estimate, lowest_ask=(180, 12), vendor_price=36)
    assert lines[0] == PanelLine("Worth ~245g", "value")
    assert PanelLine("Range 190–301g · high confidence", "detail") in lines
    assert PanelLine("Lowest ask 180g (12 listed)", "detail") in lines
    assert lines[-1] == PanelLine("Merchant pays 36g — list it", "verdict")


def test_describe_value_says_merchant_when_the_market_pays_less():
    estimate = SimpleNamespace(value=40, low=30, high=55, floor=33, confidence="medium")
    lines = describe_value(_tip(), estimate, lowest_ask=None, vendor_price=50)
    assert lines[-1] == PanelLine("Merchant pays 50g — sell it there", "verdict")


def test_describe_value_without_market_data():
    lines = describe_value(_tip(), None, lowest_ask=None, vendor_price=12)
    assert lines[0] == PanelLine("No market data yet", "muted")
    assert lines[-1] == PanelLine("Merchant pays 12g", "verdict")


def test_describe_value_flags_unread_stats():
    estimate = SimpleNamespace(value=100, low=80, high=120, floor=90, confidence="low")
    lines = describe_value(_tip(unread=("+4% Brand New Stat",)), estimate, lowest_ask=None, vendor_price=0)
    assert PanelLine("1 stat not read — value may be off", "warning") in lines
