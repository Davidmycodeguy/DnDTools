"""The hover value card: what goes on it (build_card) and how it looks (render_card, a PIL image).

Designed to sit beside the game's own item tooltip and read like part of the game: a rarity-tinted
title band with the item's icon and a serif title, the value with the game's coin icon, a price
ladder showing where the item lands among live asks, market facts, and every random roll with a
quality meter and the gold it adds. Drawn as RGBA (rounded corners, soft shadow) for a
per-pixel-alpha window. Sizes are designed at 1080p and scaled with the screen.
"""
import math
import os
import re
import statistics
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from src.models.market_rules import listing_fee

RARITY_COLORS = {"Poor": (157, 157, 157), "Common": (230, 230, 230), "Uncommon": (124, 210, 60),
                 "Rare": (63, 140, 255), "Epic": (179, 92, 242), "Legendary": (255, 154, 31),
                 "Unique": (232, 198, 90), "Artifact": (226, 70, 60)}
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
    "MagicalInteractionSpeed": "Magic Interaction", "RegularInteractionSpeed": "Interaction Speed",
    "PhysicalDamageBonus": "Physical Damage Bonus", "MagicalDamageBonus": "Magical Damage Bonus",
}
MAX_QUALITY = 0.98   # a roll this close to the top of its range reads MAX
TREND_MIN_DAYS = 4   # fewer days of prices make a trend line noise
PACE_MIN_LISTED = 3  # too few listings to call the market fast or slow
SYNERGY_MIN_PCT = 3  # smaller pair effects are noise
PACES = ((0.25, "sells fast"), (0.08, "steady"), (0.0, "slow market"))  # weekly sales per listing


@dataclass(frozen=True)
class RollLine:
    label: str
    value: str              # as the game shows it, e.g. "+5.1%"
    quality: float | None   # 0..1 within the stat's range on this item
    gold: int | None        # what the roll adds to the price vs an average roll
    is_max: bool


@dataclass(frozen=True)
class MarketFacts:
    asks: tuple = ()        # unit prices of other open listings
    sold_week: int = 0      # listings that vanished before expiring in the last 7 days
    trend: tuple = ()       # daily median unit prices, oldest first
    seen_ago_s: float | None = None  # how old the asks are when none are live
    sales_tracked: bool = False      # the market was read twice lately, so sales could be seen


@dataclass(frozen=True)
class ItemFacts:
    kind: str = ""          # e.g. "Shield" or "Chest · Plate"
    icon: str | None = None  # path to the item's icon image
    merchant: int = 0       # what a merchant pays for the whole stack
    slots: int = 1          # inventory cells it takes


@dataclass(frozen=True)
class HoverCard:
    name: str
    rarity: str
    kind: str
    icon: str | None
    value: int | None       # typical ask for these exact rolls
    low: int | None
    high: int | None
    fast_sale: int | None   # lowest reasonable price: sells quickly
    net: int | None         # fast sale after the listing fee
    confidence: str | None
    verdict: str            # "list" | "merchant" | "unknown"
    asks: tuple             # cheapest first
    seen_ago_s: float | None
    sold_week: int
    pace: str | None        # "sells fast" | "steady" | "slow market"
    trend: tuple
    trend_pct: float | None
    merchant: int
    slots: int
    per_slot: int
    rolls: tuple
    quality: int | None     # 0..100 across the rolls
    pairs: tuple            # (label, pct) synergy notes
    unread: int
    listings: int           # listings the model learned this item from


def item_kind(meta):
    """The type line under the title, e.g. "Shield · One Handed", "Chest · Plate", "Necklace"."""
    meta = meta or {}
    kind = str(meta.get("type") or "")
    if kind == "Weapon":
        parts = (meta.get("weapon_type"), meta.get("hand_type"))
    elif kind == "Armor":
        parts = (meta.get("slot_type"), meta.get("armor_type"))
    elif kind == "Accessory":
        parts = (meta.get("slot_type"),)
    elif kind == "Utility":
        parts = (meta.get("utility_type") or "Utility",)
    else:
        parts = ()
    return " · ".join(str(p) for p in parts if p)


def market_pace(listed, sold_week):
    """How quickly this item sells, from last week's sales against what is listed now."""
    if listed < PACE_MIN_LISTED:
        return None
    ratio = sold_week / listed
    return next(label for edge, label in PACES if ratio >= edge)


def round_gold(value):
    """Model effects are estimates: round them so they don't look more exact than they are."""
    step = 10 if abs(value) >= 100 else 5 if abs(value) >= 20 else 1
    return int(step * round(value / step))


def age_text(seconds):
    """How long ago, briefly: "35 min", "7 h", "3 d"."""
    if seconds < 3600:
        return f"{max(1, round(seconds / 60))} min"
    if seconds < 2 * 86400:
        return f"{round(seconds / 3600)} h"
    return f"{round(seconds / 86400)} d"


def stat_label(stat):
    return STAT_LABELS.get(stat) or re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stat)


def roll_text(stat, value):
    return f"+{value / 10:g}%" if stat in PERCENT_STATS else f"+{value:g}"


def _trend_pct(trend):
    if len(trend) < TREND_MIN_DAYS:
        return None
    start, end = statistics.mean(trend[:2]), statistics.mean(trend[-2:])
    return (end / start - 1) * 100 if start else None


def build_card(tip, estimate, market=MarketFacts(), item=ItemFacts()):
    """Everything the card shows, from a parsed tooltip, its Item Worth estimate (or None) and facts."""
    worth = {r.stat: r for r in (estimate.rolls if estimate else ())}
    typical = estimate.typical if estimate else 0
    rolls = []
    for stat, value in tip.rolls:
        found = worth.get(stat)
        quality = found.quality if found else None
        gold = round_gold(typical * found.effect_pct / 100) if found and typical else None
        rolls.append(RollLine(stat_label(stat), roll_text(stat, value), quality, gold,
                              quality is not None and quality >= MAX_QUALITY))
    known = [r.quality for r in rolls if r.quality is not None]
    value = round(estimate.value) if estimate else None
    fast_sale = round(min(estimate.floor, estimate.value)) if estimate else None
    net = fast_sale - listing_fee(fast_sale) if fast_sale is not None else None
    merchant = int(item.merchant or 0)
    if estimate is None:
        verdict = "unknown"
    else:  # listing only pays when a fast sale nets more than the merchant (and more than nothing)
        verdict = "merchant" if net <= 0 or (merchant and merchant >= net) else "list"
    slots = max(int(item.slots or 1), 1)
    pairs = tuple((" + ".join(stat_label(s) for s in p.stats), p.effect_pct)
                  for p in (estimate.pairs if estimate else ()) if abs(p.effect_pct) >= SYNERGY_MIN_PCT)
    return HoverCard(
        name=tip.title, rarity=tip.rarity, kind=item.kind, icon=item.icon, value=value,
        low=round(estimate.low) if estimate else None, high=round(estimate.high) if estimate else None,
        fast_sale=fast_sale, net=net, confidence=estimate.confidence if estimate else None, verdict=verdict,
        asks=tuple(sorted(round(a) for a in market.asks)), seen_ago_s=market.seen_ago_s,
        sold_week=int(market.sold_week),
        pace=market_pace(len(market.asks), int(market.sold_week))
        if market.sales_tracked or market.sold_week else None,
        trend=tuple(market.trend), trend_pct=_trend_pct(tuple(market.trend)), merchant=merchant, slots=slots,
        per_slot=round((value if value is not None else merchant) / slots), rolls=tuple(rolls),
        quality=round(100 * sum(known) / len(known)) if known else None, pairs=pairs, unread=len(tip.unread),
        listings=estimate.listings if estimate else 0)


# --- look -------------------------------------------------------------------------------------
WIDTH, PAD, RADIUS, SHADOW = 304, 14, 10, 12
ZOOM = 1.1  # the game's own tooltip text is large; keep the card easy to read beside it
BG_TOP, BG_BOTTOM = (27, 22, 18), (12, 10, 8)
TEXT, MUTED, FAINT, LINE = (236, 228, 212), (156, 144, 126), (98, 90, 80), (60, 51, 43)
GOLD, GOLD_DIM = (236, 196, 104), (122, 100, 56)
GREEN, RED, AMBER, BLUE, VIOLET = (126, 211, 107), (224, 100, 90), (230, 162, 60), (95, 168, 255), (186, 150, 255)
BADGES = {"list": ((34, 84, 36), (150, 226, 130), "LIST IT"), "merchant": ((92, 60, 16), (246, 196, 112), "MERCHANT"),
          "unknown": ((48, 43, 38), (170, 160, 146), "NO DATA")}
CONFIDENCE_BARS = {"high": 3, "medium": 2, "low": 1}
SLOT_GLOW = 0.42  # peak opacity of the rarity glow behind the item icon
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONTS = {"title": ("palab.ttf", None), "num": ("bahnschrift.ttf", "SemiBold"), "num_bold": ("bahnschrift.ttf", "Bold"),
         "num_cond": ("bahnschrift.ttf", "SemiBold SemiCondensed"), "text": ("segoeui.ttf", None),
         "semi": ("seguisb.ttf", None), "bold": ("segoeuib.ttf", None), "symbol": ("seguisym.ttf", None)}
COIN_ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                         "assets", "icons", "Misc", "GoldCoins.webp")


@lru_cache(maxsize=128)
def _font(kind, px):
    name, variation = FONTS[kind]
    try:
        font = ImageFont.truetype(os.path.join(FONT_DIR, name), max(px, 6))
        if variation:
            font.set_variation_by_name(variation)
        return font
    except (OSError, ValueError):
        try:
            return ImageFont.truetype(os.path.join(FONT_DIR, "segoeui.ttf"), max(px, 6))
        except OSError:
            return ImageFont.load_default()


@lru_cache(maxsize=64)
def _icon(path, box):
    """The icon fitted inside a (w, h) box (long items tilted 45° to fill it), or None."""
    try:
        image = Image.open(path).convert("RGBA")
    except (OSError, ValueError, TypeError):
        return None
    if max(image.size) >= 2 * min(image.size):
        image = image.rotate(45, resample=Image.BICUBIC, expand=True)
        image = image.crop(image.getbbox() or (0, 0, image.width, image.height))
    image.thumbnail(box, Image.LANCZOS)
    return image


@lru_cache(maxsize=8)
def _slot_glow(size):
    """Alpha mask for the icon tile's glow: strongest in the middle, gone at the edges."""
    radial = ImageOps.invert(Image.radial_gradient("L"))  # 255 at the centre, 127 at the edge midpoints
    return radial.point(lambda v: round(max(0, v - 128) * 2 * SLOT_GLOW)).resize((size, size), Image.BICUBIC)


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _quality_color(q):
    """Red (weak roll) through amber to green (top of the range)."""
    q = min(max(q, 0.0), 1.0)
    return _mix((214, 86, 70), (232, 178, 64), q / 0.5) if q < 0.5 else _mix((232, 178, 64), (112, 206, 96),
                                                                              (q - 0.5) / 0.5)


def _money(v):
    return f"{v:,.0f}"


class _Nothing:
    """Stands in for the image and its ImageDraw while a layout pass only measures."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _Pen:
    """Top-to-bottom drawing on the card; sizes are 1080p units times the screen scale. Without an
    image it only measures (text widths, heights): the layout runs once to size the card, once to draw."""

    def __init__(self, image, scale, width):
        self.drawing = image is not None
        # An opaque RGB canvas drawn in "RGBA" mode blends translucent fills instead of punching
        # holes in the card's alpha.
        self.image = image if self.drawing else _Nothing()
        self.d = ImageDraw.Draw(image, "RGBA") if self.drawing else _Nothing()
        self.s, self.w, self.y = scale, width, 0.0

    def px(self, v):
        return round(v * self.s)

    def font(self, kind, size):
        return _font(kind, self.px(size))

    def text(self, xy, text, kind, size, fill, anchor="ls"):
        self.d.text(xy, text, font=self.font(kind, size), fill=fill, anchor=anchor)

    def length(self, text, kind, size):
        return self.font(kind, size).getlength(text)

    def spans(self, x, baseline, parts):
        """Draw (text, kind, size, colour) pieces one after another on a baseline; returns the end x."""
        for text, kind, size, colour in parts:
            self.text((x, baseline), text, kind, size, colour)
            x += self.length(text, kind, size)
        return x

    def spans_length(self, parts):
        return sum(self.length(text, kind, size) for text, kind, size, _ in parts)

    def fit(self, text, kind, size, room, smallest):
        """(text, size) within `room` px: the font shrinks down to `smallest`, then the text is cut with "…"."""
        while size > smallest and self.length(text, kind, size) > room:
            size -= 0.5
        if self.length(text, kind, size) > room:
            while len(text) > 1 and self.length(text.rstrip() + "…", kind, size) > room:
                text = text[:-1]
            text = text.rstrip() + "…"
        return text, size


# --- sections ---------------------------------------------------------------------------------
def _header(pen, card, color):
    """Rarity-tinted title band: icon tile, serif title, rarity/kind line, verdict badge."""
    pad, band = pen.px(PAD), pen.px(62)
    for y in range(band):  # the game's title bars: rarity colour fading into the card
        pen.d.line((0, y, pen.w, y), fill=color + (round(78 * (1 - y / band) ** 1.4),))
    tile = pen.px(44)
    tx, ty = pad, pen.px(9)
    pen.d.rounded_rectangle((tx, ty, tx + tile, ty + tile), radius=pen.px(6), fill=(14, 11, 9))
    if pen.drawing:
        # A rarity glow behind the icon, like the game's inventory slots; dark icons stay readable.
        pen.image.paste(Image.new("RGB", (tile, tile), color), (tx, ty), _slot_glow(tile))
        icon = _icon(card.icon, (tile - pen.px(6), tile - pen.px(6))) if card.icon else None
        if icon is not None:
            pen.image.paste(icon, (tx + (tile - icon.width) // 2, ty + (tile - icon.height) // 2), icon)
    pen.d.rounded_rectangle((tx, ty, tx + tile, ty + tile), radius=pen.px(6), outline=color + (150,),
                            width=max(1, pen.px(1.2)))
    badge_bg, badge_fg, badge_text = BADGES[card.verdict]
    badge_w = pen.length(badge_text, "bold", 9.5) + pen.px(16)
    bx1, by = pen.w - pad, pen.px(11)
    pen.d.rounded_rectangle((bx1 - badge_w, by, bx1, by + pen.px(19)), radius=pen.px(9.5), fill=badge_bg,
                            outline=badge_fg + (90,), width=max(1, pen.px(1)))
    pen.text((bx1 - badge_w / 2, by + pen.px(9.5)), badge_text, "bold", 9.5, badge_fg, anchor="mm")
    text_x = tx + tile + pen.px(10)
    title_room = bx1 - badge_w - pen.px(8) - text_x
    title, size = pen.fit(card.name, "title", 17.0, title_room, 12)
    pen.text((text_x, pen.px(29)), title, "title", size, _mix(color, (255, 255, 255), 0.12))
    sub, sub_size = pen.fit(card.rarity.upper() + (f"  ·  {card.kind.upper()}" if card.kind else ""), "semi", 9,
                            pen.w - pad - text_x, 8)
    pen.text((text_x, pen.px(47)), sub, "semi", sub_size, _mix(color, MUTED, 0.45))
    y = band
    pen.d.line((0, y, pen.w, y), fill=color + (190,), width=max(1, pen.px(1.4)))
    pen.d.line((pen.px(24), y + pen.px(3), pen.w - pen.px(24), y + pen.px(3)), fill=color + (70,),
               width=max(1, pen.px(1)))
    pen.y = y + pen.px(10)


def _confidence(pen, right, baseline, level):
    bars = CONFIDENCE_BARS.get(level, 0)
    w, gap = pen.px(3), pen.px(2)
    for i in range(3):
        h = pen.px(5 + 3 * i)
        x = right - (3 - i) * (w + gap)
        pen.d.rectangle((x, baseline - h, x + w, baseline), fill=GOLD if i < bars else LINE)
    pen.text((right - 3 * (w + gap) - pen.px(6), baseline), f"{level} confidence", "text", 9.5, MUTED, anchor="rs")


def _hero(pen, card):
    """The value with the game's coin, how sure we are, and the fast-sale suggestion."""
    pad = pen.px(PAD)
    baseline = pen.y + pen.px(31)
    coin = _icon(COIN_ICON, (pen.px(22), pen.px(22)))
    x = pad
    if coin is not None:
        pen.image.paste(coin, (x, round(baseline - pen.px(23))), coin)
        x += coin.width + pen.px(5)
    if card.value is not None:
        pen.text((x, baseline), _money(card.value), "num_bold", 31, GOLD)
        _confidence(pen, pen.w - pad, baseline - pen.px(4), card.confidence)
    else:
        pen.text((x, baseline), _money(card.merchant), "num_bold", 31, MUTED)
        pen.text((pen.w - pad, baseline - pen.px(4)), "merchant price", "text", 9.5, MUTED, anchor="rs")
    line = baseline + pen.px(20)
    if card.value is None:
        pen.text((pad, line), "No market data for this item yet", "text", 11, MUTED)
        line += pen.px(15)
        pen.text((pad, line), "Crawl the Marketplace in DnDTools to price it", "text", 9.5, FAINT)
    elif card.verdict == "merchant":
        pen.spans(pad, line, [("Merchant pays ", "text", 11, MUTED), (_money(card.merchant), "num", 12, AMBER),
                              ("  ·  a fast sale nets only ", "text", 11, MUTED), (_money(card.net), "num", 12, TEXT)])
    else:
        pen.spans(pad, line, [("Fast sale ", "text", 11, MUTED), (_money(card.fast_sale), "num", 12, GREEN),
                              ("  ·  nets ", "text", 11, MUTED), (_money(card.net), "num", 12, TEXT),
                              (" after fee", "text", 11, MUTED)])
    pen.y = line + pen.px(12)


def _density(values, xs):
    """Smoothed share of `values` (log prices) at each of `xs`: a kernel density estimate."""
    values, xs = np.asarray(values, dtype=float), np.asarray(xs, dtype=float)
    n = len(values)
    spread = float(values.std()) if n > 1 else 0.1
    width = min(max(0.9 * spread * n ** -0.2, 0.035), 0.25)
    return np.exp(-0.5 * ((xs[:, None] - values[None, :]) / width) ** 2).sum(axis=1).tolist()


def _ladder(pen, card):
    """Where this item lands among live asks, on a log price scale: the curve is where listings
    cluster, the lit part the model's typical range for these rolls."""
    if card.value is None:
        return
    pad = pen.px(PAD)
    asks = card.asks
    points = [card.low, card.high, card.value, card.fast_sale]
    if asks:
        points += [asks[0], asks[min(len(asks) - 1, int(len(asks) * 0.9))]]
    lo, hi = math.log(max(min(points), 1)), math.log(max(max(points), 2))
    margin = (hi - lo) * 0.06 or 0.1
    lo, hi = lo - margin, hi + margin
    left, right = pad, pen.w - pad - pen.px(10)
    top, base = pen.y + pen.px(2), pen.y + pen.px(28)

    def x_of(v):
        return left + (right - left) * (min(max(math.log(max(v, 1)), lo), hi) - lo) / (hi - lo)
    logs = [math.log(max(a, 1)) for a in asks if math.log(max(a, 1)) <= hi] if pen.drawing else []
    if len(logs) >= 2:
        steps = 120
        xs = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
        dens = _density(logs, xs)
        peak = max(dens) or 1
        curve = [(left + (right - left) * i / steps, base - (base - top) * d / peak) for i, d in enumerate(dens)]
        pen.d.polygon([(left, base)] + curve + [(right, base)], fill=GOLD + (46,))
        x_low, x_high = x_of(card.low), x_of(card.high)
        lit = [(x, y) for x, y in curve if x_low <= x <= x_high]
        if len(lit) >= 2:
            pen.d.polygon([(lit[0][0], base)] + lit + [(lit[-1][0], base)], fill=GOLD + (70,))
        pen.d.line(curve, fill=GOLD + (190,), width=max(1, pen.px(1.3)), joint="curve")
    else:
        pen.d.rounded_rectangle((x_of(card.low), base - pen.px(5), x_of(card.high), base), radius=pen.px(2),
                                fill=GOLD + (70,))
    pen.d.line((left, base, right, base), fill=LINE, width=max(1, pen.px(1)))
    if any(math.log(max(a, 1)) > hi for a in asks):
        pen.text((right + pen.px(4), base - pen.px(3)), "›", "bold", 12, MUTED, anchor="lm")
    if asks:
        x = x_of(asks[0])
        pen.d.line((x, base - pen.px(9), x, base + pen.px(3)), fill=(250, 246, 236), width=max(1, pen.px(1.6)))
    fx, tri = x_of(card.fast_sale), pen.px(4.5)
    pen.d.line((fx, top + pen.px(4), fx, base), fill=GREEN + (150,), width=max(1, pen.px(1)))
    pen.d.polygon([(fx, base + pen.px(2)), (fx - tri, base + tri * 1.8), (fx + tri, base + tri * 1.8)], fill=GREEN)
    vx, r = x_of(card.value), pen.px(6)
    pen.d.line((vx, top, vx, base), fill=GOLD + (170,), width=max(1, pen.px(1)))
    pen.d.polygon([(vx, base - r), (vx + r, base), (vx, base + r), (vx - r, base)], fill=GOLD, outline=(44, 32, 16))
    caption = base + pen.px(22)
    if asks:
        pen.spans(left, caption, [("lowest ", "text", 9.5, FAINT), (_money(asks[0]), "num", 10.5, TEXT)])
        if card.verdict == "list":
            share = round(100 * sum(1 for a in asks if a > card.fast_sale) / len(asks))
            parts = [("fast sale beats ", "text", 9.5, FAINT), (f"{share}%", "num", 10.5, GREEN),
                     (" of asks", "text", 9.5, FAINT)]
            pen.spans(pen.w - pad - sum(pen.length(t, k, z) for t, k, z, _ in parts), caption, parts)
    else:
        pen.spans(left, caption, [("typical ", "text", 9.5, FAINT),
                                  (f"{_money(card.low)} – {_money(card.high)}", "num", 10.5, TEXT)])
    pen.y = caption + pen.px(8)


def _sparkline(pen, box, values, colour):
    x0, y0, x1, y1 = box
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    points = [(x0 + (x1 - x0) * i / (len(values) - 1), y1 - (y1 - y0) * (v - lo) / span) for i, v in enumerate(values)]
    pen.d.line(points, fill=colour, width=max(1, pen.px(1.4)), joint="curve")
    lx, ly = points[-1]
    r = pen.px(2)
    pen.d.ellipse((lx - r, ly - r, lx + r, ly + r), fill=colour)


def _market(pen, card):
    """Supply, recent sales and pace, trend, merchant price and gold per inventory slot."""
    pad = pen.px(PAD)
    baseline = pen.y + pen.px(14)
    if card.asks or card.sold_week:
        groups = [[(str(len(card.asks)), "num", 11.5, TEXT), (" listed", "text", 10.5, MUTED)]]
        if card.asks and card.seen_ago_s is not None:
            groups[0].append((f" ({age_text(card.seen_ago_s)} ago)", "text", 10.5, FAINT))
        if card.sold_week:
            groups.append([("  ·  ", "text", 10.5, FAINT), (str(card.sold_week), "num", 11.5, TEXT),
                           (" sold this week", "text", 10.5, MUTED)])
        if card.pace:
            colour = {"sells fast": GREEN, "steady": GOLD}.get(card.pace, MUTED)
            groups.append([("  ·  ", "text", 10.5, FAINT), (card.pace, "semi", 10.5, colour)])
    else:
        note = "No listings seen this week" if card.listings else "Not seen on the market yet"
        groups = [[(note, "text", 10.5, MUTED)]]
    room = pen.w - 2 * pad
    while len(groups) > 1 and pen.spans_length([p for g in groups for p in g]) > room:
        groups.pop()  # the least important facts give way first
    parts = [p for g in groups for p in g]
    end = pen.spans(pad, baseline, parts)
    if card.trend_pct is not None and len(card.trend) >= 2:
        colour = GREEN if card.trend_pct >= 0 else RED
        label = f"{card.trend_pct:+.0f}%"
        lw = pen.length(label, "num", 10.5)
        spark_left = pen.w - pad - lw - pen.px(46)
        if spark_left - pen.px(8) >= end:  # only where it doesn't run into the facts
            pen.text((pen.w - pad, baseline), label, "num", 10.5, colour, anchor="rs")
            _sparkline(pen, (spark_left, baseline - pen.px(11), pen.w - pad - lw - pen.px(6), baseline - pen.px(1)),
                       card.trend, colour)
    baseline += pen.px(18)
    slot_colour = GREEN if card.per_slot >= 100 else GOLD if card.per_slot >= 30 else MUTED
    parts = [("Merchant ", "text", 10.5, MUTED), (_money(card.merchant), "num", 11.5, AMBER),
             ("   ·   ", "text", 10.5, FAINT), (_money(card.per_slot), "num", 11.5, slot_colour),
             (" per slot" + (f" · {card.slots} slots" if card.slots > 1 else ""), "text", 10.5, MUTED)]
    pen.spans(pad, baseline, parts)
    pen.y = baseline + pen.px(11)


def _quality_ring(pen, cx, cy, quality):
    r, width = pen.px(10), max(2, pen.px(2.6))
    box = (cx - r, cy - r, cx + r, cy + r)
    pen.d.arc(box, 0, 360, fill=LINE, width=width)
    pen.d.arc(box, -90, -90 + 360 * quality / 100, fill=_quality_color(quality / 100), width=width)
    pen.text((cx, cy), str(quality), "num_bold", 9, TEXT, anchor="mm")


def _rolls(pen, card):
    if not card.rolls:
        return
    pad = pen.px(PAD)
    pen.d.line((pad, pen.y, pen.w - pad, pen.y), fill=LINE, width=max(1, pen.px(1)))
    head = pen.y + pen.px(20)
    pen.text((pad, head), "RANDOM ROLLS", "bold", 9, MUTED)
    if card.quality is not None:
        _quality_ring(pen, pen.w - pad - pen.px(10), head - pen.px(4), card.quality)
        pen.text((pen.w - pad - pen.px(25), head), "roll quality", "text", 9, FAINT, anchor="rs")
    y = head + pen.px(8)
    pip_w, pip_gap, pips = pen.px(5), pen.px(2), 10
    pips_w = pips * pip_w + (pips - 1) * pip_gap
    badge_right = pen.w - pad
    pips_right = badge_right - pen.px(40)
    rated = card.quality is not None  # without an estimate there is no quality to meter
    value_right = pips_right - pips_w - pen.px(8) if rated else badge_right
    for roll in card.rolls:
        baseline = y + pen.px(17)
        room = value_right - pen.length(roll.value, "num", 12.5) - pen.px(8) - pad
        label, size = pen.fit(roll.label, "text", 12.0, room, 9.5)
        pen.text((pad, baseline), label, "text", size, TEXT)
        pen.text((value_right, baseline), roll.value, "num", 12.5, BLUE, anchor="rs")
        if not rated:
            y += pen.px(22)
            continue
        top = baseline - pen.px(8)
        filled = 0 if roll.quality is None else max(1, round(roll.quality * pips))
        colour = _quality_color(roll.quality) if roll.quality is not None else LINE
        for i in range(pips):
            x = pips_right - pips_w + i * (pip_w + pip_gap)
            pen.d.rounded_rectangle((x, top, x + pip_w, top + pen.px(7)), radius=pen.px(1.5),
                                    fill=colour if i < filled else (46, 39, 33))
        if roll.is_max:
            w = pen.px(32)
            pen.d.rounded_rectangle((badge_right - w, top - pen.px(2), badge_right, top + pen.px(10)),
                                    radius=pen.px(5), fill=(92, 72, 24), outline=GOLD + (160,), width=max(1, pen.px(1)))
            pen.text((badge_right - w / 2, top + pen.px(4)), "MAX", "bold", 8, GOLD, anchor="mm")
        elif roll.gold is not None:
            colour = GREEN if roll.gold > 0 else RED if roll.gold < 0 else MUTED
            pen.text((badge_right, baseline), f"{roll.gold:+,}", "num", 11, colour, anchor="rs")
        y += pen.px(22)
    for label, pct in card.pairs[:2]:
        baseline = y + pen.px(15)
        star, effect = ("✦ ", "symbol", 9.5, VIOLET), (f"  {pct:+.0f}%", "num", 10.5, VIOLET)
        label, size = pen.fit(label, "text", 10, pen.w - 2 * pad - pen.spans_length([star, effect]), 8.5)
        pen.spans(pad, baseline, [star, (label, "text", size, VIOLET), effect])
        y += pen.px(17)
    pen.y = y + pen.px(6)


def _footer(pen, card):
    pad = pen.px(PAD)
    baseline = pen.y + pen.px(14)
    if card.unread:
        sign = ("⚠ ", "symbol", 9.5, AMBER)  # Segoe UI has no ⚠; Segoe UI Symbol does
        note, size = pen.fit(f"{card.unread} stat{'s' if card.unread > 1 else ''} not read — value may be off", "semi",
                             9.5, pen.w - 2 * pad - pen.spans_length([sign]), 8)
        pen.spans(pad, baseline, [sign, (note, "semi", size, AMBER)])
        baseline += pen.px(16)
    pen.text((pad, baseline), "DnDTools", "semi", 8.5, FAINT)
    if card.listings:
        pen.text((pen.w - pad, baseline), f"local model · {card.listings:,} listings", "text", 8.5, FAINT, anchor="rs")
    pen.y = baseline + pen.px(9)


def _layout(card, scale, image, width):
    """Lay out every section, drawing on the opaque RGB `image` (None: only measure); returns the height."""
    pen = _Pen(image, scale, width)
    color = RARITY_COLORS.get(card.rarity, TEXT)
    _header(pen, card, color)
    _hero(pen, card)
    _ladder(pen, card)
    _market(pen, card)
    _rolls(pen, card)
    _footer(pen, card)
    return round(pen.y)


@lru_cache(maxsize=32)
def _background(width, height):
    """The card's dark vertical gradient (shared: callers copy it before drawing)."""
    return Image.composite(Image.new("RGB", (width, height), BG_BOTTOM), Image.new("RGB", (width, height), BG_TOP),
                           Image.linear_gradient("L").resize((width, height)))


@lru_cache(maxsize=32)
def _corners(width, height, radius):
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    return mask


@lru_cache(maxsize=32)
def _backdrop(width, height, color, scale):
    """The soft shadow and rarity glow around a card this size: two full-canvas blurs (~25 ms at 4K)
    done once per size and colour."""
    radius, margin = round(RADIUS * scale), round(SHADOW * scale)
    canvas = Image.new("RGBA", (width + 2 * margin, height + 2 * margin), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((margin, margin + round(4 * scale), margin + width, margin + height),
                                             radius=radius, fill=(0, 0, 0, 190))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(margin / 2)))
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle((margin, margin, margin + width, margin + height), radius=radius,
                                           outline=color + (80,), width=max(1, round(3 * scale)))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(1, scale * 2))))
    return canvas


def render_card(card, screen_height):
    """The card as an RGBA image (with a soft shadow margin) for a screen `screen_height` pixels tall."""
    scale = screen_height / 1080 * ZOOM
    width = round(WIDTH * scale)
    height = _layout(card, scale, None, width)
    radius, margin = round(RADIUS * scale), round(SHADOW * scale)
    color = RARITY_COLORS.get(card.rarity, TEXT)
    body = _background(width, height).copy()
    _layout(card, scale, body, width)
    ImageDraw.Draw(body).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius,
                                           outline=_mix(color, BG_TOP, 0.5), width=max(1, round(1.2 * scale)))
    card_img = body.convert("RGBA")
    card_img.putalpha(_corners(width, height, radius))
    canvas = _backdrop(width, height, color, scale).copy()
    canvas.alpha_composite(card_img, (margin, margin))
    return canvas
