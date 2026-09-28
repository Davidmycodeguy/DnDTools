"""The hover value card: what goes on it (build_card) and how it looks (render_card, a PIL image).

Drawn as an RGBA image so the panel can have rounded corners, a soft shadow, bars and badges, then
shown in a per-pixel-alpha window. Sizes are designed at 1080p and scaled with the screen.
"""
import os
import re
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.models.market_rules import listing_fee

RARITY_COLORS = {"Poor": (150, 150, 150), "Common": (225, 225, 225), "Uncommon": (98, 196, 60),
                 "Rare": (64, 140, 235), "Epic": (178, 92, 240), "Legendary": (255, 140, 30),
                 "Unique": (240, 205, 80), "Artifact": (235, 70, 60)}
# Stats stored x10 and shown with % in game.
PERCENT_STATS = frozenset({
    "ActionSpeed", "ArmorPenetration", "MagicPenetration", "BuffDurationBonus", "DebuffDurationBonus",
    "CooldownReductionBonus", "DemonDamageMod", "DemonReductionMod", "UndeadDamageMod", "UndeadReductionMod",
    "HeadshotDamageMod", "HeadshotReductionMod", "ProjectileReductionMod", "MagicalDamageBonus",
    "PhysicalDamageBonus", "MagicalDamageReduction", "PhysicalDamageReduction", "MagicalInteractionSpeed",
    "RegularInteractionSpeed", "SpellCastingSpeed", "MaxHealthBonus", "MoveSpeedBonus", "MemoryCapacityBonus"})
STAT_LABELS = {
    "PhysicalWeaponDamageAdd": "Weapon Damage", "PhysicalDamageAdd": "Physical Damage",
    "PhysicalDamageTrue": "True Physical Damage", "MagicalDamageAdd": "Magical Damage",
    "MagicalDamageTrue": "True Magical Damage", "MagicRegistance": "Magic Resistance",
    "ArmorRatingAdd": "Armor Rating", "MaxHealthAdd": "Max Health", "MaxHealthBonus": "Max Health",
    "MoveSpeedAdd": "Move Speed", "MoveSpeedBonus": "Move Speed", "MemoryCapacityAdd": "Memory Capacity",
    "MemoryCapacityBonus": "Memory Capacity", "UndeadDamageMod": "Undead Damage", "UndeadReductionMod":
    "Undead Reduction", "DemonDamageMod": "Demon Damage", "DemonReductionMod": "Demon Reduction",
    "HeadshotDamageMod": "Headshot Damage", "HeadshotReductionMod": "Headshot Reduction",
    "ProjectileReductionMod": "Projectile Reduction", "CooldownReductionBonus": "Cooldown Reduction",
}


@dataclass(frozen=True)
class RollLine:
    label: str
    value: str             # as the game shows it, e.g. "+5.1%"
    quality: float | None  # 0..1 within the stat's range on this item
    effect_pct: float | None


@dataclass(frozen=True)
class HoverCard:
    name: str
    rarity: str
    value: int | None
    low: int | None
    high: int | None
    confidence: str | None
    verdict: str           # "list" | "merchant" | "unknown"
    verdict_text: str
    lowest_ask: int | None
    listed: int
    sold: int
    merchant: int
    slots: int
    rolls: tuple
    quality: int | None    # 0..100 across the rolls
    pairs: tuple           # "Strength + Vigor"-style synergy notes
    unread: int
    listings: int          # listings the value model learned this item from


def stat_label(stat):
    return STAT_LABELS.get(stat) or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stat)


def roll_text(stat, value):
    if stat in PERCENT_STATS:
        return f"+{value / 10:g}%"
    return f"+{value:g}"


def build_card(tip, estimate, lowest_ask, listed, sold, vendor_price, slots):
    """Everything the card shows, from a parsed tooltip and its Item Worth estimate (or None)."""
    qualities = {r.stat: r for r in (estimate.rolls if estimate else ())}
    rolls = tuple(RollLine(stat_label(stat), roll_text(stat, value),
                           qualities[stat].quality if stat in qualities else None,
                           qualities[stat].effect_pct if stat in qualities else None)
                  for stat, value in tip.rolls)
    known = [r.quality for r in rolls if r.quality is not None]
    quality = round(100 * sum(known) / len(known)) if known else None
    if estimate is None:
        verdict, text = "unknown", "No market data yet"
    else:
        value = round(estimate.value)
        net = value - listing_fee(value)
        if vendor_price and vendor_price >= net:
            verdict, text = "merchant", f"Sell to merchant · {vendor_price}g"
        else:
            verdict, text = "list", f"List it · nets ~{net}g after fee"
    pairs = tuple(f"{' + '.join(stat_label(s) for s in p.stats)} {p.effect_pct:+.0f}%"
                  for p in (estimate.pairs if estimate else ()) if abs(p.effect_pct) >= 1)
    return HoverCard(
        name=tip.title, rarity=tip.rarity,
        value=round(estimate.value) if estimate else None, low=round(estimate.low) if estimate else None,
        high=round(estimate.high) if estimate else None, confidence=estimate.confidence if estimate else None,
        verdict=verdict, verdict_text=text, lowest_ask=round(lowest_ask) if lowest_ask else None,
        listed=listed, sold=sold, merchant=int(vendor_price or 0), slots=max(int(slots or 1), 1),
        rolls=rolls, quality=quality, pairs=pairs, unread=len(tip.unread),
        listings=estimate.listings if estimate else 0)


# --- drawing -----------------------------------------------------------------------------------
WIDTH = 330
PAD = 14
RADIUS = 12
SHADOW = 10
BG_TOP, BG_BOTTOM = (30, 25, 22), (16, 13, 12)
TEXT, MUTED, FAINT = (240, 232, 214), (150, 140, 124), (95, 88, 78)
GOLD = (236, 200, 110)
ROLL_BLUE = (104, 170, 255)
VERDICT_COLORS = {"list": ((46, 125, 50), (205, 240, 200)), "merchant": ((150, 96, 20), (255, 226, 170)),
                  "unknown": ((60, 55, 50), (200, 192, 176))}
CONFIDENCE_DOTS = {"high": 3, "medium": 2, "low": 1}
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONT_FILES = {"regular": "segoeui.ttf", "semibold": "seguisb.ttf", "bold": "segoeuib.ttf"}


def _font(weight, px):
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, FONT_FILES[weight]), px)
    except OSError:
        return ImageFont.load_default()


def _quality_color(q):
    """Red (weak roll) through amber to green (top of the range)."""
    q = min(max(q, 0.0), 1.0)
    if q < 0.5:
        a, b, t = (220, 80, 60), (235, 185, 60), q / 0.5
    else:
        a, b, t = (235, 185, 60), (90, 200, 90), (q - 0.5) / 0.5
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


class _Pen:
    """Draws top-to-bottom on the card, tracking the y cursor; sizes in 1080p units x scale."""

    def __init__(self, draw, scale, width):
        self.d, self.s, self.w, self.y = draw, scale, width, 0.0

    def px(self, v):
        return round(v * self.s)

    def font(self, weight, size):
        return _font(weight, self.px(size))

    def text(self, x, text, weight, size, fill, anchor="la", y=None):
        self.d.text((x, self.y if y is None else y), text, font=self.font(weight, size), fill=fill, anchor=anchor)

    def advance(self, v):
        self.y += self.px(v)


def _header(pen, card, color):
    pad = pen.px(PAD)
    pen.advance(12)
    pen.text(pad, card.rarity.upper(), "bold", 10.5, color)
    pen.text(pen.w - pad, "DnDTools", "semibold", 10.5, FAINT, anchor="ra")
    pen.advance(16)
    pen.text(pad, card.name, "bold", 17, TEXT)
    pen.advance(28)


def _value_block(pen, card):
    pad = pen.px(PAD)
    if card.value is None:
        pen.text(pad, f"{card.merchant:,}g", "bold", 30, MUTED)
        pen.text(pen.w - pad, "merchant price", "regular", 10.5, MUTED, anchor="ra", y=pen.y + pen.px(17))
        pen.advance(44)
        return
    pen.text(pad, f"{card.value:,}g", "bold", 30, GOLD)
    dots = CONFIDENCE_DOTS.get(card.confidence, 0)
    r = pen.px(3.2)
    for i in range(3):  # filled left to right
        cx = pen.w - pad - pen.px(25) + i * pen.px(10)
        cy = pen.y + pen.px(24)
        fill = GOLD if i < dots else (70, 62, 54)
        pen.d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
    pen.text(pen.w - pad - pen.px(34), f"{card.confidence} confidence", "regular", 10.5, MUTED, anchor="ra",
             y=pen.y + pen.px(17))
    pen.advance(44)
    if card.low is not None and card.high is not None and card.high > card.low:
        _range_bar(pen, card)


def _range_bar(pen, card):
    pad = pen.px(PAD)
    left, right = pad, pen.w - pad
    y = pen.y
    h = pen.px(6)
    pen.d.rounded_rectangle((left, y, right, y + h), radius=h // 2, fill=(58, 50, 44))
    span = card.high - card.low
    t = min(max((card.value - card.low) / span, 0), 1)
    mx = left + (right - left) * t
    pen.d.rounded_rectangle((left, y, mx, y + h), radius=h // 2, fill=(150, 120, 60))
    r = pen.px(6)
    pen.d.ellipse((mx - r, y + h / 2 - r, mx + r, y + h / 2 + r), fill=GOLD, outline=(40, 32, 20), width=pen.px(1.5))
    pen.advance(10)
    pen.text(left, f"{card.low:,}g", "regular", 10.5, MUTED)
    pen.text(right, f"{card.high:,}g", "regular", 10.5, MUTED, anchor="ra")
    pen.text((left + right) / 2, "typical range", "regular", 10, FAINT, anchor="ma")
    pen.advance(22)


def _verdict(pen, card):
    pad = pen.px(PAD)
    bg, fg = VERDICT_COLORS[card.verdict]
    top, height = pen.y, pen.px(28)
    pen.d.rounded_rectangle((pad, top, pen.w - pad, top + height), radius=pen.px(7), fill=bg)
    pen.text(pen.w / 2, card.verdict_text.upper() if card.verdict != "unknown" else card.verdict_text,
             "bold", 12, fg, anchor="mm", y=top + height / 2)
    pen.advance(28 + 12)


def _stats(pen, card):
    pad = pen.px(PAD)
    per_slot = (card.value if card.value is not None else card.merchant) / card.slots
    cells = [("Lowest ask", f"{card.lowest_ask:,}g" if card.lowest_ask else "—"),
             ("On market", f"{card.listed} listed" + (f" · {card.sold} sold" if card.sold else "")),
             ("Merchant", f"{card.merchant:,}g"),
             ("Per slot", f"{per_slot:,.0f}g" + (f" ({card.slots} slots)" if card.slots > 1 else ""))]
    col_w = (pen.w - 2 * pad - pen.px(8)) / 2
    for i, (label, value) in enumerate(cells):
        col, row = i % 2, i // 2
        x = pad + col * (col_w + pen.px(8))
        y = pen.y + row * pen.px(44)
        pen.d.rounded_rectangle((x, y, x + col_w, y + pen.px(38)), radius=pen.px(6), fill=(38, 32, 28))
        pen.text(x + pen.px(8), label.upper(), "semibold", 9, MUTED, y=y + pen.px(5))
        pen.text(x + pen.px(8), value, "bold", 13.5, TEXT, y=y + pen.px(18))
    pen.advance(2 * 44 + 4)


def _rolls(pen, card):
    if not card.rolls:
        return
    pad = pen.px(PAD)
    pen.d.line((pad, pen.y, pen.w - pad, pen.y), fill=(58, 50, 44), width=max(1, pen.px(1)))
    pen.advance(8)
    pen.text(pad, "ROLLS", "bold", 10.5, MUTED)
    if card.quality is not None:
        pen.text(pen.w - pad, f"Quality {card.quality}/100", "bold", 11, _quality_color(card.quality / 100),
                 anchor="ra")
    pen.advance(20)
    for roll in card.rolls:
        pen.text(pad, roll.label, "regular", 12.5, TEXT)
        pen.text(pen.w - pad, roll.value, "bold", 12.5, ROLL_BLUE, anchor="ra")
        pen.advance(19)
        if roll.quality is not None:
            bar_right = pen.w - pad - pen.px(56)
            h = pen.px(5)
            pen.d.rounded_rectangle((pad, pen.y, bar_right, pen.y + h), radius=h // 2, fill=(58, 50, 44))
            fill_to = pad + (bar_right - pad) * min(max(roll.quality, 0), 1)
            if fill_to > pad + h:
                pen.d.rounded_rectangle((pad, pen.y, fill_to, pen.y + h), radius=h // 2,
                                        fill=_quality_color(roll.quality))
            if roll.effect_pct is not None:
                pen.text(pen.w - pad, f"{roll.effect_pct:+.0f}% value", "regular", 9.5, MUTED, anchor="ra",
                         y=pen.y - pen.px(4))
            pen.advance(13)
    for note in card.pairs[:2]:
        pen.text(pad, f"Synergy: {note}", "regular", 10.5, (180, 160, 230))
        pen.advance(16)


def _footer(pen, card):
    pad = pen.px(PAD)
    if card.unread:
        pen.text(pad, f"{card.unread} stat{'s' if card.unread > 1 else ''} not read — value may be off",
                 "semibold", 10.5, (255, 183, 77))
        pen.advance(17)
    source = f"local market model · {card.listings:,} listings" if card.listings else "local market data"
    pen.text(pad, source, "regular", 9.5, FAINT)
    pen.advance(20)


def _draw(card, scale, draw, width):
    pen = _Pen(draw, scale, width)
    color = RARITY_COLORS.get(card.rarity, TEXT)
    _header(pen, card, color)
    _value_block(pen, card)
    _verdict(pen, card)
    _stats(pen, card)
    _rolls(pen, card)
    _footer(pen, card)
    return pen.y


def render_card(card, screen_height):
    """The card as an RGBA image (with a soft shadow margin) for a screen of `screen_height` pixels."""
    scale = screen_height / 1080
    width = round(WIDTH * scale)
    measure = ImageDraw.Draw(Image.new("RGBA", (width, 10)))
    height = round(_draw(card, scale, measure, width))
    margin = round(SHADOW * scale)
    canvas = Image.new("RGBA", (width + 2 * margin, height + 2 * margin), (0, 0, 0, 0))
    radius = round(RADIUS * scale)
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((margin, margin + round(3 * scale), margin + width, margin + height),
                                             radius=radius, fill=(0, 0, 0, 170))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(margin / 2)))
    body = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gradient = Image.linear_gradient("L").resize((width, height))
    top, bottom = Image.new("RGBA", (width, height), BG_TOP + (246,)), Image.new("RGBA", (width, height),
                                                                                 BG_BOTTOM + (246,))
    body.paste(Image.composite(bottom, top, gradient), (0, 0))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    card_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    card_img.paste(body, (0, 0), mask)
    draw = ImageDraw.Draw(card_img)
    color = RARITY_COLORS.get(card.rarity, TEXT)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, outline=color + (170,),
                           width=max(1, round(1.5 * scale)))
    draw.rounded_rectangle((round(radius * 0.8), 0, width - round(radius * 0.8), round(3 * scale)),
                           radius=round(2 * scale), fill=color + (230,))
    _draw(card, scale, draw, width)
    canvas.alpha_composite(card_img, (margin, margin))
    return canvas
