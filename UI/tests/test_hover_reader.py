import numpy as np
from PIL import Image

from src.models.hover_reader import TooltipReader
from src.models.tooltip_finder import TooltipBox
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



class FakeScreen:
    def __init__(self, frame):
        self.frame, self.grabs = frame, []

    def __call__(self, region):
        left, top, right, bottom = region
        self.grabs.append(region)
        return self.frame[top:bottom, left:right]


def _screen_with_rule(left=1030, rule_y=700, width=3000, height=2000, color=(76, 150, 3)):
    frame = np.full((height, width, 3), 8, dtype=np.uint8)
    frame[rule_y:rule_y + 2, left:left + 600] = color
    return frame


def test_reads_the_tooltip_beside_the_cursor_grabbing_only_what_it_needs():
    screen = FakeScreen(_screen_with_rule())
    ocr = FakeOcr([ROBE])
    found = TooltipReader(ocr, INDEX).read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    assert found is not None
    tip, box = found
    assert tip.item_id == "OccultistRobe_3001" and (box.left, box.right, box.rule_y) == (1030, 1630, 700)
    grabbed = sum((r[2] - r[0]) * (r[3] - r[1]) for r in screen.grabs)
    assert grabbed < 0.3 * 3000 * 2000


def test_nothing_beside_the_cursor_means_no_ocr():
    screen = FakeScreen(_screen_with_rule(left=100))  # a rule far from the cursor
    ocr = FakeOcr([ROBE])
    assert TooltipReader(ocr, INDEX).read_screen(screen, cursor=(2400, 900), scale=1.0, screen=(3000, 2000)) is None
    assert ocr.reads == 0


def test_a_tooltip_read_before_is_not_read_again_from_the_screen():
    screen = FakeScreen(_screen_with_rule())
    ocr = FakeOcr([ROBE])
    reader = TooltipReader(ocr, INDEX)
    first = reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    again = reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    assert first == again and ocr.reads == 1


def test_still_showing_while_the_tooltips_rule_is_there():
    reader = TooltipReader(FakeOcr([ROBE]), INDEX)
    screen = FakeScreen(_screen_with_rule())
    _, box = reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    assert reader.still_showing(screen, (1000, 900), 1.0, (3000, 2000), box) is True
    gone = FakeScreen(np.full((2000, 3000, 3), 8, dtype=np.uint8))
    assert reader.still_showing(gone, (1000, 900), 1.0, (3000, 2000), box) is False


GREY = (174, 173, 173)  # a fixed UI line: bright and colourless, like a Common tooltip's rule


def test_a_fixed_ui_line_by_the_cursor_is_checked_once_per_rest():
    screen = FakeScreen(_screen_with_rule(color=GREY))
    ocr = FakeOcr([MERCHANT] * 5)
    reader = TooltipReader(ocr, INDEX)
    for _ in range(5):
        assert reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000)) is None
    assert ocr.reads == 1
    first_look = len(screen.grabs) - 4
    assert first_look >= 3 and all(r[3] - r[1] > 100 for r in screen.grabs[-4:])  # later looks: one strip grab each


def test_a_tooltip_appearing_where_a_ui_line_was_is_still_read():
    frame = _screen_with_rule(color=GREY)
    screen = FakeScreen(frame)
    ocr = FakeOcr([MERCHANT, ROBE])
    reader = TooltipReader(ocr, INDEX)
    assert reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000)) is None
    frame[700:702, 1030:1630] = (76, 150, 3)            # the game draws its tooltip there
    found = reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    assert found is not None and found[0].item_id == "OccultistRobe_3001"


def test_a_new_rest_looks_at_everything_again():
    screen = FakeScreen(_screen_with_rule(color=GREY))
    reader = TooltipReader(FakeOcr([MERCHANT, MERCHANT]), INDEX)
    reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    before = len(screen.grabs)
    reader.read_screen(screen, cursor=(1010, 900), scale=1.0, screen=(3000, 2000))
    assert any(r[3] - r[1] <= 21 and r[2] - r[0] > 64 for r in screen.grabs[before:])  # the line measured again


def test_a_ui_line_found_to_be_no_tooltip_is_skipped_at_later_rests_too():
    screen = FakeScreen(_screen_with_rule(color=GREY))
    ocr = FakeOcr([MERCHANT] * 3)
    reader = TooltipReader(ocr, INDEX)
    reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    before = len(screen.grabs)
    reader.read_screen(screen, cursor=(1010, 905), scale=1.0, screen=(3000, 2000))   # another rest
    assert ocr.reads == 1
    crop = TooltipBox(1030, 1630, 700, GREY).ocr_region(3000, 2000, 1.0)
    assert crop not in screen.grabs[before:]                                          # nor grabbed again


def test_a_tooltip_that_merely_failed_to_parse_is_read_again_later():
    unknown = [OcrLine("Mystery Blade", 98, 19, 162, 18), OcrLine("Rarity: Epic", 101, 387, 150, 15)]
    frame = _screen_with_rule()
    screen = FakeScreen(frame)
    ocr = FakeOcr([unknown, ROBE])
    reader = TooltipReader(ocr, INDEX)
    assert reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000)) is None
    frame[1400:1480, 1100:1200] = (60, 60, 60)  # the next capture differs (no cached crop)
    assert reader.read_screen(screen, cursor=(1010, 905), scale=1.0, screen=(3000, 2000)) is not None
    assert ocr.reads == 2


def test_still_showing_when_another_overlay_covers_part_of_the_rule():
    frame = _screen_with_rule()
    screen = FakeScreen(frame)
    reader = TooltipReader(FakeOcr([ROBE]), INDEX)
    _, box = reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    frame[600:900, 1000:1330] = (30, 20, 20)      # e.g. another tool's panel over the left half
    assert reader.still_showing(screen, (1000, 900), 1.0, (3000, 2000), box) is True


def test_a_different_line_where_the_rule_was_is_not_the_tooltip():
    frame = _screen_with_rule()
    screen = FakeScreen(frame)
    reader = TooltipReader(FakeOcr([ROBE]), INDEX)
    _, box = reader.read_screen(screen, cursor=(1000, 900), scale=1.0, screen=(3000, 2000))
    frame[690:712, :] = 8
    frame[700:702, 900:1800] = GREY               # tooltip gone; a grey UI line happens to be on that row
    assert reader.still_showing(screen, (1000, 900), 1.0, (3000, 2000), box) is False
