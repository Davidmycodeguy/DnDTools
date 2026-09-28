import numpy as np

from src.models.tooltip_finder import TooltipBox, find_tooltip, find_tooltips

EPIC = (150, 60, 195)
LEGENDARY = (230, 120, 20)


def _frame(width=1600, height=1400):
    return np.full((height, width, 3), 8, dtype=np.uint8)


def _tooltip(frame, left, rule_y, width, color=EPIC):
    """A dark panel whose title is underlined by two thin rarity-colored rules (as in game at 4K)."""
    frame[rule_y - 105:rule_y + 600, left:left + width] = (20, 14, 22)
    for y in (rule_y, rule_y + 6):
        frame[y:y + 2, left + 70:left + width - 70] = color
    frame[rule_y - 70:rule_y - 30, left + 150:left + width - 150:6] = (170, 90, 210)  # title text strokes
    return frame


def test_finds_the_tooltip_nearest_the_cursor():
    frame = _tooltip(_frame(), left=400, rule_y=500, width=730)
    box = find_tooltip(frame, cursor=(380, 420), scale=1.0)
    assert box == TooltipBox(left=470, right=1060, rule_y=500, color=box.color)
    assert box.color == EPIC


def test_ocr_region_covers_title_and_body_within_the_frame():
    frame = _tooltip(_frame(), left=400, rule_y=500, width=730)
    box = find_tooltip(frame, cursor=(380, 420), scale=1.0)
    left, top, right, bottom = box.ocr_region(frame_width=1600, frame_height=1400, scale=1.0)
    assert left < 400 + 70 and right > 400 + 730 - 70
    assert top <= 500 - 100 and bottom == 1400  # the body runs to the frame's edge at most


def test_nothing_without_a_long_rule():
    frame = _frame()
    frame[500:502, 400:560] = EPIC  # a colored word, not a tooltip rule
    assert find_tooltip(frame, cursor=(400, 400), scale=1.0) is None


def test_white_rules_of_common_tooltips_count_but_white_text_does_not():
    frame = _frame()
    frame[500:501, 300:1000] = (174, 173, 173)         # Common tooltip rule: grey-white...
    frame[500:501, 480:490] = (60, 60, 60)             # ...with a few short dips (seen in game)
    box = find_tooltip(frame, cursor=(290, 450), scale=1.0)
    assert (box.left, box.right, box.color) == (300, 1000, (174, 173, 173))
    text = _frame()
    for start in range(300, 800, 12):                  # white text: strokes with small gaps
        text[500:501, start:start + 8] = (230, 230, 230)
    assert find_tooltip(text, cursor=(290, 450), scale=1.0) is None


def test_two_tooltips_pick_the_one_by_the_cursor():
    frame = _tooltip(_frame(2400), left=100, rule_y=400, width=700, color=EPIC)
    frame = _tooltip(frame, left=1400, rule_y=400, width=700, color=LEGENDARY)
    box = find_tooltip(frame, cursor=(1380, 350), scale=1.0)
    assert box.color == LEGENDARY


def test_scale_shrinks_the_minimum_rule_length():
    frame = _frame(800, 700)
    frame[250:251, 100:300] = EPIC  # 200 px: long enough at half of 4K, too short at 4K
    assert find_tooltip(frame, cursor=(90, 200), scale=0.5) is not None
    assert find_tooltip(frame, cursor=(90, 200), scale=1.0) is None


def test_a_rule_broken_into_pieces_still_counts_whole():
    frame = _frame()
    for start in range(300, 1000, 110):  # 100 px pieces with 10 px gaps, like the fading rule in game
        frame[500:502, start:start + 100] = EPIC
    box = find_tooltip(frame, cursor=(290, 450), scale=1.0)
    assert (box.left, box.right) == (300, 1060)  # last piece: 960-1060


def test_only_the_area_around_the_cursor_is_searched():
    frame = _tooltip(_frame(4000, 1400), left=3000, rule_y=500, width=730)
    assert find_tooltip(frame, cursor=(100, 400), scale=1.0) is None
    assert find_tooltip(frame, cursor=(2900, 400), scale=1.0) is not None


def test_screen_borders_wider_than_any_tooltip_are_ignored():
    frame = _frame(3000, 1400)
    frame[1:3, :] = (230, 190, 40)  # gold window border across the whole screen
    assert find_tooltip(frame, cursor=(1500, 200), scale=1.0) is None


def test_rule_pieces_on_neighbouring_rows_merge_into_one_rule():
    frame = _frame()
    frame[500:501, 600:1000] = EPIC   # the right end of the rule is drawn one row higher...
    frame[501:502, 300:620] = EPIC    # ...than its left part
    box = find_tooltip(frame, cursor=(290, 450), scale=1.0)
    assert (box.left, box.right, box.rule_y) == (300, 1000, 500)


def test_coloured_text_bridged_across_letters_is_not_a_rule():
    frame = _frame()
    for start in range(300, 900, 10):   # brown description text: half lit once gaps are bridged
        frame[500:501, start:start + 5] = (155, 99, 69)
    assert find_tooltip(frame, cursor=(290, 450), scale=1.0) is None


def test_several_candidates_come_nearest_first():
    frame = _tooltip(_frame(2400), left=100, rule_y=400, width=700, color=EPIC)
    frame = _tooltip(frame, left=1400, rule_y=400, width=700, color=LEGENDARY)
    boxes = find_tooltips(frame, cursor=(1380, 350), scale=1.0)
    assert [b.color for b in boxes] == [LEGENDARY, EPIC]


def test_a_tooltip_opening_upward_beats_a_nearer_ui_line():
    # Items low on screen open their tooltip upward: the rule is far above the cursor, but the
    # tooltip's body reaches down beside the item.
    frame = _tooltip(_frame(3000, 1600), left=1600, rule_y=300, width=700)
    frame[1100:1101, 700:1000] = (174, 173, 173)  # a fixed grey UI line, closer to the cursor's row
    boxes = find_tooltips(frame, cursor=(1560, 1150), scale=1.0)
    assert boxes[0].rule_y == 300
