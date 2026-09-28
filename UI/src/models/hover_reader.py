"""Reads the item tooltip under the cursor (find it, OCR it, parse it) and words its value."""
import hashlib
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from src.models.market_rules import listing_fee
from src.models.tooltip_finder import TITLE_HEIGHT_PX, find_tooltips
from src.models.tooltip_parser import parse_tooltip

MAX_CANDIDATES = 3   # fixed UI lines can look like title rules; each costs one ~25 ms read
CACHE_SIZE = 64      # screens already read (a tooltip stays up while the cursor rests)
OCR_BASE_SCALE = 0.5  # 4K text is read best at half size; smaller screens at full size
SIGNATURE_SIZE = (48, 48)


@dataclass(frozen=True)
class PanelLine:
    text: str
    style: str  # "value" | "detail" | "verdict" | "muted" | "warning"


class TooltipReader:
    def __init__(self, ocr, index, candidates=MAX_CANDIDATES):
        self._ocr = ocr
        self._index = index
        self._candidates = candidates
        self._cache = OrderedDict()  # crop signature -> ParsedTooltip | None

    def read(self, image, cursor, scale):
        """(ParsedTooltip, TooltipBox) for the tooltip nearest `cursor` in `image`, or None."""
        frame = np.asarray(image.convert("RGB"))
        for box in find_tooltips(frame, cursor, scale, limit=self._candidates):
            parsed = self._read_box(image, box, scale)
            if parsed is not None:
                return parsed, box
        return None

    def _read_box(self, image, box, scale):
        crop = image.crop(box.ocr_region(image.width, image.height, scale))
        key = hashlib.sha1(crop.convert("L").resize(SIGNATURE_SIZE).tobytes()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        factor = min(1.0, OCR_BASE_SCALE / scale) if scale > 0 else 1.0
        if factor < 1.0:
            crop = crop.resize((max(1, round(crop.width * factor)), max(1, round(crop.height * factor))))
        parsed = parse_tooltip(self._ocr.read(crop), self._index, TITLE_HEIGHT_PX * scale * factor)
        self._cache[key] = parsed
        if len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return parsed


def describe_value(tip, estimate, lowest_ask, vendor_price):
    """The panel's lines for a parsed tooltip: worth, range, lowest ask and what a merchant pays."""
    lines = []
    if estimate is not None:
        value = round(estimate.value)
        lines.append(PanelLine(f"Worth ~{value}g", "value"))
        lines.append(PanelLine(f"Range {round(estimate.low)}–{round(estimate.high)}g · "
                               f"{estimate.confidence} confidence", "detail"))
    else:
        lines.append(PanelLine("No market data yet", "muted"))
    if lowest_ask:
        price, count = lowest_ask
        lines.append(PanelLine(f"Lowest ask {round(price)}g ({count} listed)", "detail"))
    if tip.unread:
        count = len(tip.unread)
        lines.append(PanelLine(f"{count} stat{'s' if count > 1 else ''} not read — value may be off", "warning"))
    if vendor_price:
        if estimate is None:
            lines.append(PanelLine(f"Merchant pays {vendor_price}g", "verdict"))
        else:
            value = round(estimate.value)
            better = "list it" if value - listing_fee(value) > vendor_price else "sell it there"
            lines.append(PanelLine(f"Merchant pays {vendor_price}g — {better}", "verdict"))
    return lines
