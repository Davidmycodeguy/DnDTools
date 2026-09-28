"""Finds the game's item tooltip near the cursor in a screen capture.

Every item tooltip underlines its title with thin rules in the item's rarity color, running most of
the tooltip's width. Nothing else near an item is that long, thin and saturated, so the longest such
run nearest the cursor marks the tooltip's width and where its title ends. Pixel sizes are measured
at 3840x2160 and scaled by `scale` (screen height / 2160).
"""
import hashlib
from dataclasses import dataclass

import numpy as np

MIN_RULE_PX = 250        # shortest rule counted as a tooltip (Gem Ring rule: ~620 px at 4K)
MAX_RULE_PX = 1300       # wider runs are screen borders or UI frames, not tooltips
RULE_MIN_SATURATION = 50  # max - min channel: rarity colors are vivid, text and frames are not
RULE_MIN_BRIGHTNESS = 100
# Common tooltips underline the title in grey-white instead: accept bright, colourless runs too
# (the fill check keeps white text out).
NEUTRAL_MIN_BRIGHTNESS = 120
NEUTRAL_MAX_SATURATION = 40
# Poor tooltips underline it in dim grey (~80), as dim as plenty of UI lines, so a dim rule must also
# have the title rule's shape: two thin lines, the second starting ~5 px below the first (at 4K).
DIM_MIN_BRIGHTNESS = 60
DIM_MAX_SATURATION = 20
DOUBLE_GAP_PX = (4, 6)
DOUBLE_MIN_FILL = 0.6    # the second line lit along this much of the first
RULE_GROUP_PX = 14       # the two rules under a title are ~6 px apart
RULE_MAX_GAP_PX = 12     # a rule fades toward its ends and breaks into pieces up to ~10 px apart
RULE_MIN_FILL = 0.8      # a rule row is ~96% lit; a row through bridged text is under 50%
TITLE_HEIGHT_PX = 110    # title bar above the first rule
SIDE_PADDING_PX = 45     # text starts ~30 px inside the rule; more would catch neighbouring UI text
SEARCH_X_PX = 1500       # tooltips open beside the hovered item: search this far around the cursor
SEARCH_Y_PX = 1300
COLUMN_STEP = 2          # rules are long and horizontal: every other column is plenty
MAX_BODY_PX = 1500       # tallest tooltip body below the rules
TYPICAL_BODY_PX = 800    # for ranking: the hovered item sits beside the tooltip's body, not its rule
# Probing: the game opens a tooltip right beside the cursor (~20-30 px away), 600+ px wide, going
# up or down to fit. A narrow strip each side of the cursor therefore crosses the rule of any
# tooltip there, and grabbing two strips is a tiny fraction of grabbing the whole search area.
PROBE_OFFSET_PX = 200    # past the cursor sprite and the rule's faded end, well inside its run
PROBE_WIDTH_PX = 64
PROBE_UP_PX = 1800       # a tooltip opening upward ends by the cursor: its rule can be this far up
PROBE_DOWN_PX = 300      # one opening downward starts by the cursor: its rule is a title bar below
PROBE_MIN_LIT = 0.9      # a rule lights (nearly) the whole strip; text doesn't
PROBE_COLUMN_STEP = 4    # strip columns sampled
RULE_MAX_SPAN_PX = 16    # a rule's two thin lines span ~8 rows; item art lit this wide is a blob
MAX_PROBE_ROWS = 8       # candidate rules measured per look, nearest the cursor first
BAND_PX = 10             # rows either side of a candidate grabbed to measure its whole rule
RULE_MIN_VISIBLE = 0.25  # a tooltip is still up while this much of its rule shows ...
RULE_COLOR_TOLERANCE = 48  # ... in its own colour (its ends fade)


@dataclass(frozen=True)
class TooltipBox:
    """A tooltip in frame pixels: the extent of its title rule and the rule's row."""
    left: int
    right: int
    rule_y: int
    color: tuple

    def ocr_region(self, frame_width, frame_height, scale):
        """(left, top, right, bottom) to read: the title and everything below, within the frame."""
        pad = round(SIDE_PADDING_PX * scale)
        return (max(0, self.left - pad), max(0, self.rule_y - round(TITLE_HEIGHT_PX * scale)),
                min(frame_width, self.right + pad), min(frame_height, self.rule_y + round(MAX_BODY_PX * scale)))


def _extremes(frame):
    """(brightest, dimmest) channel per pixel, from channel slices (several times faster than max(axis=2))."""
    red, green, blue = frame[..., 0], frame[..., 1], frame[..., 2]
    return np.maximum(np.maximum(red, green), blue), np.minimum(np.minimum(red, green), blue)


def _rule_masks(frame):
    """(vivid, neutral) masks: rarity-coloured pixels, and bright colourless ones."""
    high, low = _extremes(frame)  # uint8: high >= low, so no overflow
    saturation = high - low
    vivid = (saturation >= RULE_MIN_SATURATION) & (high >= RULE_MIN_BRIGHTNESS)
    neutral = (saturation < NEUTRAL_MAX_SATURATION) & (high >= NEUTRAL_MIN_BRIGHTNESS)
    return vivid, neutral


def _dim_mask(frame):
    """Dim, colourless pixels: a Poor rule's grey, below the Common rule's brightness."""
    high, low = _extremes(frame)
    return (high - low < DIM_MAX_SATURATION) & (high >= DIM_MIN_BRIGHTNESS) & (high < NEUTRAL_MIN_BRIGHTNESS)


def _gaps(scale):
    """Rows below a rule's first line where its second line starts."""
    low, high = (max(2, round(g * scale)) for g in DOUBLE_GAP_PX)
    return range(low, max(low, high) + 1)


def _runs(row, min_length, max_gap, min_fill=RULE_MIN_FILL):
    """[(start, end)] of runs of True at least `min_length` long, bridging gaps up to `max_gap`,
    that stay at least `min_fill` lit (text bridged across letter gaps is mostly gaps)."""
    padded = np.concatenate(([False], row, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    merged = []
    for start, end in zip(edges[::2].tolist(), edges[1::2].tolist()):
        if merged and start - merged[-1][1] <= max_gap:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return [(a, b) for a, b in merged if b - a >= min_length and row[a:b].mean() >= min_fill]


def _rules(mask, min_length, max_gap, max_length):
    """[(top, left, right)] of every title rule: long vivid runs, merged across nearby rows.

    A rule is drawn as two thin lines whose faded ends break into pieces on neighbouring rows, so
    runs a few rows apart that overlap sideways are one rule. Tooltips can sit side by side
    (comparisons), so one row may hold several rules.
    """
    rules = []  # [top, left, right, last_row]
    for y in np.flatnonzero(mask.sum(axis=1) >= min_length):
        for left, right in _runs(mask[y], min_length, max_gap):
            if right - left > max_length:
                continue
            rule = next((r for r in rules if 0 <= y - r[3] <= RULE_GROUP_PX and left < r[2] and right > r[1]), None)
            if rule is None:
                rules.append([int(y), left, right, int(y)])
            else:
                rule[1], rule[2], rule[3] = min(rule[1], left), max(rule[2], right), int(y)
    return [(top, left, right) for top, left, right, _ in rules]


def _double(dim, rule, scale):
    """Whether a dim rule (top, left, right) has a second line just below it, as title rules do."""
    top, left, right = rule
    return any(top + gap < dim.shape[0] and dim[top + gap, left:right].mean() >= DOUBLE_MIN_FILL
               for gap in _gaps(scale))


def _distance(point, left, top, right, bottom):
    x, y = point
    dx = max(left - x, 0, x - right)
    dy = max(top - y, 0, y - bottom)
    return dx * dx + dy * dy


def probe_strips(cursor, scale, screen):
    """Screen regions (left, top, right, bottom) to watch for a title rule: a narrow strip each
    side of the cursor, clipped to the screen (a strip mostly off screen is dropped)."""
    cx, cy = cursor
    width, height = screen
    offset, strip = round(PROBE_OFFSET_PX * scale), max(8, round(PROBE_WIDTH_PX * scale))
    top, bottom = max(0, cy - round(PROBE_UP_PX * scale)), min(height, cy + round(PROBE_DOWN_PX * scale))
    regions = []
    for start in (cx + offset, cx - offset - strip):
        left, right = max(0, start), min(width, start + strip)
        if right - left >= strip // 2 and bottom > top:
            regions.append((left, top, right, bottom))
    return regions


def rule_rows(strip, scale=1.0):
    """Rows of `strip` crossed end to end by a title rule: the top row of each thin lit cluster."""
    if strip.size == 0:
        return []
    strip = strip[:, ::PROBE_COLUMN_STEP]  # a rule crossing the strip lights every column: a sample is plenty
    vivid, neutral = _rule_masks(strip)
    lit = np.flatnonzero((vivid | neutral).mean(axis=1) >= PROBE_MIN_LIT).tolist()
    group, span = max(2, round(RULE_GROUP_PX * scale)), max(4, round(RULE_MAX_SPAN_PX * scale))
    clusters = []
    for y in lit:
        if clusters and y - clusters[-1][1] <= group:
            clusters[-1][1] = y
        else:
            clusters.append([y, y])
    rows = [top for top, bottom in clusters if bottom - top < span]
    return sorted(rows + [y for y in _double_dim_rows(strip, scale) if all(abs(y - r) > group for r in rows)])


def _double_dim_rows(strip, scale):
    """Rows where a Poor rule starts across the whole strip: a dim line, dark rows, a second dim line."""
    lit = _dim_mask(strip).mean(axis=1) >= PROBE_MIN_LIT
    gaps, after = _gaps(scale), max(2, round(3 * scale))
    rows = []
    for y in np.flatnonzero(lit).tolist():
        if y == 0 or lit[y - 1] or y + gaps[-1] + after >= len(lit):
            continue
        for gap in gaps:
            if lit[y + gap] and not lit[y + 1:y + gap].all() and not lit[y + gap + after]:
                rows.append(y)
                break
    return rows


def probe(grab, cursor, scale, screen):
    """[(screen row, signature)] of rule candidates crossing the probe strips, likeliest first. The
    signature fingerprints what that strip shows around the row, so a caller can skip a row it
    already found to be no tooltip (a fixed UI line) until those pixels change. Each strip keeps its
    own rows: a line on one side must not hide a tooltip opening on the other."""
    below = max(8, round(2 * RULE_MAX_SPAN_PX * scale))
    strips = probe_strips(cursor, scale, screen)
    if not strips:
        return []
    # One grab for both strips: a screen copy waits for the next composited frame (~15 ms at 60 Hz)
    # whatever its size, so the number of grabs is what costs, not their width.
    box = (min(s[0] for s in strips), strips[0][1], max(s[2] for s in strips), strips[0][3])
    both = grab(box)
    rows = []
    for index, region in enumerate(strips):
        pixels = both[:, region[0] - box[0]:region[2] - box[0]]
        for row in rule_rows(pixels, scale):
            patch = np.ascontiguousarray(pixels[max(0, row - 2):row + below])
            rows.append((region[1] + row, (index, region[1] + row, hashlib.sha1(patch.tobytes()).digest())))
    near = row_nearness(cursor, scale)
    return sorted(rows, key=lambda r: near(r[0]))


def row_nearness(cursor, scale):
    """Sort key for a rule row: how far the cursor is from where that tooltip's body would be (a
    tooltip opening upward has its rule far above the item it describes)."""
    cy = cursor[1]
    title, body = round(TITLE_HEIGHT_PX * scale), round(TYPICAL_BODY_PX * scale)
    return lambda row: max(row - title - cy, 0, cy - (row + body))


def measure(grab, row, cursor, scale, screen, limit=3):
    """TooltipBoxes (screen pixels) of the rules on `row`, from a thin band grabbed across the
    search width: their full extent and colour."""
    cx, cy = cursor
    width, height = screen
    reach, band = round(SEARCH_X_PX * scale), max(4, round(BAND_PX * scale))
    region = (max(0, cx - reach), max(0, row - band), min(width, cx + reach), min(height, row + band + 1))
    pixels = grab(region)
    if pixels.size == 0:
        return []
    local = (cx - region[0], min(max(cy - region[1], 0), pixels.shape[0] - 1))  # rules far above still count
    return [TooltipBox(b.left + region[0], b.right + region[0], b.rule_y + region[1], b.color)
            for b in find_tooltips(pixels, local, scale, limit=limit)]


def nearness(cursor, scale):
    """Sort key: how far a box's tooltip is from the cursor (its body beside the item, not just its rule)."""
    title, body = round(TITLE_HEIGHT_PX * scale), round(TYPICAL_BODY_PX * scale)
    return lambda b: _distance(cursor, b.left, b.rule_y - title, b.right, b.rule_y + body)


def rank(boxes, cursor, scale):
    """Boxes nearest the cursor first."""
    return sorted(boxes, key=nearness(cursor, scale))


def find_near_cursor(grab, cursor, scale, screen, limit=3):
    """Up to `limit` TooltipBoxes (screen pixels) by the cursor, nearest first. Grabs only the
    probe strips and, for each rule they cross, a thin band to measure it: a few % of the screen.
    `grab(region)` returns that region's pixels as an RGB array."""
    group = max(2, round(RULE_GROUP_PX * scale))
    boxes = []
    for row, _ in probe(grab, cursor, scale, screen)[:MAX_PROBE_ROWS]:
        for box in measure(grab, row, cursor, scale, screen, limit):
            if not any(abs(box.rule_y - b.rule_y) <= group and box.left < b.right and box.right > b.left for b in boxes):
                boxes.append(box)
    return rank(boxes, cursor, scale)[:limit]


def rule_still_there(pixels, color):
    """Whether a band grabbed over a tooltip's rule (exactly its extent) still shows it: enough of
    its columns lit in the rule's colour. Another overlay may cover part of it, so not all of it."""
    if pixels.size == 0:
        return False
    vivid, neutral = _rule_masks(pixels)
    same = np.abs(pixels.astype(np.int16) - np.asarray(color, dtype=np.int16)).max(axis=2) <= RULE_COLOR_TOLERANCE
    # Along one row: another overlay may hide part of the rule, but scattered specks aren't a rule.
    return bool(((vivid | neutral | _dim_mask(pixels)) & same).mean(axis=1).max() >= RULE_MIN_VISIBLE)


def find_tooltip(frame, cursor, scale=1.0):
    """The TooltipBox nearest `cursor` (frame pixels), or None when no tooltip is showing."""
    boxes = find_tooltips(frame, cursor, scale, limit=1)
    return boxes[0] if boxes else None


def find_tooltips(frame, cursor, scale=1.0, limit=3):
    """Up to `limit` TooltipBoxes, nearest `cursor` first. Fixed UI lines can look like title rules,
    so callers confirm each by reading it."""
    cx, cy = cursor
    x0, y0 = max(0, cx - round(SEARCH_X_PX * scale)), max(0, cy - round(SEARCH_Y_PX * scale))
    window = frame[y0:cy + round(SEARCH_Y_PX * scale), x0:cx + round(SEARCH_X_PX * scale):COLUMN_STEP]
    vivid, neutral = _rule_masks(window)
    step = COLUMN_STEP
    widest = round(MAX_RULE_PX * scale / step)
    shortest, gap = max(10, round(MIN_RULE_PX * scale / step)), max(1, round(RULE_MAX_GAP_PX * scale / step))
    dim = _dim_mask(window)
    candidates = (_rules(vivid, shortest, gap, widest) + _rules(neutral, shortest, gap, widest)
                  + [rule for rule in _rules(dim, shortest, gap, widest) if _double(dim, rule, scale)])
    title = round(TITLE_HEIGHT_PX * scale)
    local = ((cx - x0) / step, cy - y0)
    body = round(TYPICAL_BODY_PX * scale)
    nearest = sorted(candidates, key=lambda c: _distance(local, c[1], c[0] - title, c[2], c[0] + body))[:limit]
    boxes = []
    for y, left, right in nearest:
        lit = vivid[y, left:right] | neutral[y, left:right]
        if not lit.any():
            lit = dim[y, left:right]
        color = tuple(int(v) for v in np.median(window[y, left:right][lit], axis=0)) if lit.any() else (0, 0, 0)
        boxes.append(TooltipBox(left=left * step + x0, right=right * step + x0, rule_y=y + y0, color=color))
    return boxes
