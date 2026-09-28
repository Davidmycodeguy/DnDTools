"""Reads the item tooltip under the cursor: find it, OCR it, parse it, remembering screens read."""
import hashlib
import time
from collections import OrderedDict

import numpy as np
from PIL import Image

from src.models.tooltip_finder import (MAX_PROBE_ROWS, RULE_GROUP_PX, TITLE_HEIGHT_PX, find_tooltips, measure,
                                      nearness, probe,
                                      rule_still_there)
from src.models.tooltip_parser import looks_like_tooltip, parse_tooltip

MAX_CANDIDATES = 3   # fixed UI lines can look like title rules; each costs one ~25 ms read
CACHE_SIZE = 64      # screens already read (a tooltip stays up while the cursor rests)
NOT_TOOLTIPS_SIZE = 256  # fixed UI lines found to be no tooltip, remembered by where they are ...
UI_LINE_MISSES = 2       # ... once this many rests found no tooltip text there (one bad read proves nothing)
UI_LINE_MEMORY_S = 600.0  # ... and forgotten after this long (screens change)
OCR_BASE_SCALE = 0.5  # 4K text is read best at half size; smaller screens at full size
SIGNATURE_SIZE = (48, 48)


class TooltipReader:
    def __init__(self, ocr, index, candidates=MAX_CANDIDATES, clock=time.monotonic):
        self._ocr = ocr
        self._index = index
        self._candidates = candidates
        self._cache = OrderedDict()  # crop signature -> ParsedTooltip | None
        self._clock = clock
        self._rest = None            # (cursor, scale, screen) of the rest being looked at
        self._rests = 0              # rests seen, so misses at a spot count once per rest
        self._rejected = set()       # probe rows found to be no tooltip during this rest
        self._not_tooltips = OrderedDict()  # rule geometry -> (misses, last rest, when) with no "Rarity:" line

    def read(self, image, cursor, scale):
        """(ParsedTooltip, TooltipBox) for the tooltip nearest `cursor` in `image`, or None."""
        frame = np.asarray(image.convert("RGB"))
        for box in find_tooltips(frame, cursor, scale, limit=self._candidates):
            parsed = self._read_box(image, box, scale)
            if parsed is not None:
                return parsed, box
        return None

    def read_screen(self, grab, cursor, scale, screen):
        """(ParsedTooltip, TooltipBox) for the tooltip beside `cursor`, grabbing only the screen
        regions needed, or None. `grab(region)` returns a region's RGB pixels; the box is in screen
        pixels. Called over and over while the cursor rests: rows that turned out to be fixed UI
        lines are skipped until their pixels change, so a look usually costs two strip grabs."""
        rest = (tuple(cursor), scale, tuple(screen))
        if rest != self._rest:
            self._rest, self._rejected, self._rests = rest, set(), self._rests + 1
        candidates = []  # (box, row signature)
        rows = [(row, signature) for row, signature in probe(grab, cursor, scale, screen)
                if signature not in self._rejected][:MAX_PROBE_ROWS]
        for row, signature in rows:
            boxes = measure(grab, row, cursor, scale, screen, self._candidates)
            if not boxes:
                self._rejected.add(signature)
            candidates += [(box, signature) for box in boxes]
        near = nearness(cursor, scale)
        candidates.sort(key=lambda c: near(c[0]))
        failed = set()
        for box, signature in candidates[:self._candidates]:
            place = _place(box)
            if self._known_ui_line(place):  # a fixed UI line seen before: no grab, no OCR
                failed.add(signature)
                continue
            crop = Image.fromarray(np.ascontiguousarray(grab(box.ocr_region(screen[0], screen[1], scale))))
            parsed, tooltip_like = self._read_crop(crop, scale)
            if parsed is not None:
                return parsed, box
            if not tooltip_like:
                self._note_miss(place)
            failed.add(signature)
        self._rejected |= failed - {signature for _, signature in candidates[self._candidates:]}
        return None

    def _known_ui_line(self, place):
        entry = self._not_tooltips.get(place)
        return bool(entry) and entry[0] >= UI_LINE_MISSES and self._clock() - entry[2] < UI_LINE_MEMORY_S

    def _note_miss(self, place):
        """No tooltip text under this rule; after misses at separate rests it counts as a fixed UI line."""
        misses, last_rest, when = self._not_tooltips.get(place, (0, None, 0.0))
        if self._clock() - when >= UI_LINE_MEMORY_S:
            misses = 0
        if last_rest != self._rests:
            misses += 1
        self._not_tooltips[place] = (misses, self._rests, self._clock())
        self._not_tooltips.move_to_end(place)
        if len(self._not_tooltips) > NOT_TOOLTIPS_SIZE:
            self._not_tooltips.popitem(last=False)

    def still_showing(self, grab, cursor, scale, screen, box):
        """Whether the tooltip `box` (screen pixels) is still up: one thin grab over its rule."""
        band = max(2, round(RULE_GROUP_PX * scale))
        return rule_still_there(grab((box.left, max(0, box.rule_y - band), box.right,
                                      min(screen[1], box.rule_y + band + 1))), box.color)

    def _read_box(self, image, box, scale):
        return self._read_crop(image.crop(box.ocr_region(image.width, image.height, scale)), scale)[0]

    def _read_crop(self, crop, scale):
        """(ParsedTooltip | None, whether the text could be a tooltip at all) for a tooltip-sized crop."""
        key = hashlib.sha1(crop.convert("L").resize(SIGNATURE_SIZE).tobytes()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        factor = min(1.0, OCR_BASE_SCALE / scale) if scale > 0 else 1.0
        if factor == 0.5:
            crop = crop.reduce(2)  # 4K: a box average, ~10x faster than resize and as readable
        elif factor < 1.0:
            crop = crop.resize((max(1, round(crop.width * factor)), max(1, round(crop.height * factor))),
                               Image.BILINEAR)
        lines = self._ocr.read(crop)
        result = (parse_tooltip(lines, self._index, TITLE_HEIGHT_PX * scale * factor), looks_like_tooltip(lines))
        self._cache[key] = result
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return result


def _place(box):
    """Where a rule is and its colour, loosely (measurements wobble by a pixel or two)."""
    return box.rule_y // 4, box.left // 8, box.right // 8, tuple(c // 16 for c in box.color)
