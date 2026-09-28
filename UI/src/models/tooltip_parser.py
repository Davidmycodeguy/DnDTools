"""Turns the OCR'd lines of a game item tooltip into an item id and its stats.

Tooltips list the title, then base stats as "Name value" and random rolls as "+value Name", then
Required Class / Slot Type / ... / "Rarity: X" and the flavour text. Values shown with % are stored
x10 in the game data (Armor Penetration 30% = 300), plain ones as shown.
"""
import difflib
import re
from dataclasses import dataclass

DASHES = str.maketrans({"−": "-", "‒": "-", "–": "-", "—": "-"})
DIGIT_SLIPS = str.maketrans({"I": "1", "l": "1", "|": "1", "O": "0", "o": "0"})
RARITY_KEYS = {"poor": "Poor", "comm": "Common", "unco": "Uncommon", "rare": "Rare", "epic": "Epic",
               "lege": "Legendary", "uniq": "Unique", "arti": "Artifact"}
NAME_CUTOFF = 0.85   # fuzzy item-name match (OCR slips like "Occu1tist Rohe")
STAT_CUTOFF = 0.8    # fuzzy stat-name match (names cut short at the crop edge)
PERCENT_SCALE = 10

# Base stats ("Name value").
BASE_NAMES = {
    "weapondamage": "PhysicalWeaponDamage", "magicweapondamage": "MagicalWeaponDamage",
    "magicalweapondamage": "MagicalWeaponDamage", "armorrating": "ArmorRating",
    "magicresistance": "MagicRegistance", "movespeed": "MoveSpeed", "armorpenetration": "ArmorPenetration",
    "magicpenetration": "MagicPenetration", "projectiledamagereduction": "ProjectileReductionMod",
    "headshotdamagereduction": "HeadshotReductionMod", "actionspeed": "ActionSpeed", "luck": "Luck",
    "magicaldamage": "MagicalDamage", "strength": "Strength", "vigor": "Vigor", "agility": "Agility",
    "dexterity": "Dexterity", "will": "Will", "knowledge": "Knowledge", "resourcefulness": "Resourcefulness",
}
# Random rolls ("+value Name"). A few names mean a flat or a % stat depending on the "%".
ROLL_NAMES = {
    "armorrating": "ArmorRatingAdd", "weapondamage": "PhysicalWeaponDamageAdd",
    "additionalweapondamage": "PhysicalWeaponDamageAdd", "physicaldamage": "PhysicalDamageAdd",
    "additionalphysicaldamage": "PhysicalDamageAdd", "physicaldamagebonus": "PhysicalDamageBonus",
    "truephysicaldamage": "PhysicalDamageTrue", "physicaldamagereduction": "PhysicalDamageReduction",
    "physicalpower": "PhysicalPower", "physicalhealing": "PhysicalHealing", "magicaldamage": "MagicalDamageAdd",
    "additionalmagicaldamage": "MagicalDamageAdd", "magicaldamagebonus": "MagicalDamageBonus",
    "truemagicaldamage": "MagicalDamageTrue", "magicaldamagereduction": "MagicalDamageReduction",
    "magicalpower": "MagicalPower", "magicalhealing": "MagicalHealing",
    "magicalinteractionspeed": "MagicalInteractionSpeed", "regularinteractionspeed": "RegularInteractionSpeed",
    "spellcastingspeed": "SpellCastingSpeed", "actionspeed": "ActionSpeed", "armorpenetration": "ArmorPenetration",
    "magicpenetration": "MagicPenetration", "magicresistance": "MagicRegistance",
    "headshotdamage": "HeadshotDamageMod", "headshotdamagebonus": "HeadshotDamageMod",
    "headshotdamagereduction": "HeadshotReductionMod", "projectiledamagereduction": "ProjectileReductionMod",
    "buffdurationbonus": "BuffDurationBonus", "debuffdurationbonus": "DebuffDurationBonus",
    "cooldownreduction": "CooldownReductionBonus", "cooldownreductionbonus": "CooldownReductionBonus",
    "undeaddamagebonus": "UndeadDamageMod", "undeaddamagereduction": "UndeadReductionMod",
    "demondamagebonus": "DemonDamageMod", "demondamagereduction": "DemonReductionMod", "luck": "Luck",
    "allattributes": "AllAttributes", "strength": "Strength", "vigor": "Vigor", "agility": "Agility",
    "dexterity": "Dexterity", "will": "Will", "knowledge": "Knowledge", "resourcefulness": "Resourcefulness",
}
FLAT_OR_PERCENT = {"maxhealth": ("MaxHealthAdd", "MaxHealthBonus"), "movespeed": ("MoveSpeedAdd", "MoveSpeedBonus"),
                   "memorycapacity": ("MemoryCapacityAdd", "MemoryCapacityBonus")}

_NUMBER = r"[\dIl|Oo]+(?:[.,]\d+)?"
ROLL_LINE = re.compile(rf"^\+\s*(?P<num>{_NUMBER})\s*(?P<pct>%)?\s*(?P<name>[A-Za-z].*)$")
BASE_LINE = re.compile(rf"^(?P<name>[A-Za-z][A-Za-z' ]*?)\s+(?P<num>-?\s*{_NUMBER})\s*(?P<pct>%|f)?$")
RARITY_LINE = re.compile(r"^rar[a-z]*\W*(?P<word>[a-z]*)", re.IGNORECASE)  # "Rarity: Epic" or "Rarity:Epic"
EDGE_DASHES = re.compile(r"^-\s+|\s+-$")


@dataclass(frozen=True)
class Row:
    text: str
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class ParsedTooltip:
    title: str
    rarity: str
    item_id: str
    rolls: tuple   # ((stat_id, value), ...) random rolls, in game-data units
    base: tuple    # ((stat_id, value), ...) base stats
    unread: tuple  # stat-like lines whose stat isn't known


def _norm(text):
    return re.sub(r"[^a-z]", "", str(text).lower())


def merge_rows(lines):
    """OCR pieces on the same line ("Rarity:" + "Epic") joined left to right, top to bottom."""
    rows = []
    for line in sorted(lines, key=lambda l: l.y + l.h / 2):
        centre = line.y + line.h / 2
        row = rows[-1] if rows else None
        if row and abs((row[0].y + row[0].h / 2) - centre) <= max(row[0].h, line.h) / 2:
            row.append(line)
        else:
            rows.append([line])
    merged = []
    for pieces in rows:
        pieces = sorted(pieces, key=lambda l: l.x)
        left, top = min(p.x for p in pieces), min(p.y for p in pieces)
        right, bottom = max(p.x + p.w for p in pieces), max(p.y + p.h for p in pieces)
        merged.append(Row(" ".join(p.text for p in pieces), left, top, right - left, bottom - top))
    return merged


def _closest(table, key, cutoff):
    if key in table:
        return table[key]
    match = difflib.get_close_matches(key, list(table), n=1, cutoff=cutoff)
    return table[match[0]] if match else None


def _value(num, percent):
    number = float(num.replace(" ", "").translate(DIGIT_SLIPS).replace(",", "."))
    return round(number * (PERCENT_SCALE if percent else 1))


def parse_stat(text):
    """("roll" | "base", stat_id, value) for a stat line, or None when it isn't one we know."""
    line = EDGE_DASHES.sub("", str(text).translate(DASHES).strip()).strip()
    roll = ROLL_LINE.match(line)
    if roll:
        key, percent = _norm(roll["name"]), roll["pct"] is not None
        pair = FLAT_OR_PERCENT.get(key) or FLAT_OR_PERCENT.get(_closest({k: k for k in FLAT_OR_PERCENT}, key, 0.9) or "")
        stat = pair[percent] if pair else _closest(ROLL_NAMES, key, STAT_CUTOFF)
        return ("roll", stat, _value(roll["num"], percent)) if stat else None
    base = BASE_LINE.match(line)
    if base:
        stat = _closest(BASE_NAMES, _norm(base["name"]), STAT_CUTOFF)
        return ("base", stat, _value(base["num"], base["pct"] is not None)) if stat else None
    return None


def _looks_like_stat(text):
    line = EDGE_DASHES.sub("", str(text).translate(DASHES).strip()).strip()
    return bool(ROLL_LINE.match(line) or BASE_LINE.match(line))


class ItemIndex:
    """Item ids by rarity and name, from DnDTools' items.json records."""

    def __init__(self, items: dict):
        self._by_rarity = {}
        for item_id, record in items.items():
            rarity = RARITY_KEYS.get(_norm(record.get("rarity"))[:4])
            if rarity and record.get("name"):
                self._by_rarity.setdefault(rarity, {})[_norm(record["name"])] = item_id

    def resolve(self, title, rarity):
        return _closest(self._by_rarity.get(rarity, {}), _norm(title), NAME_CUTOFF)


def _rarity(row):
    match = RARITY_LINE.match(row.text.strip())
    return RARITY_KEYS.get(_norm(match["word"])[:4]) if match and match["word"] else None


def looks_like_tooltip(lines):
    """Whether OCR'd text could be an item tooltip at all: every tooltip has a "Rarity: X" line."""
    return any(_rarity(row) for row in merge_rows(lines))


def parse_tooltip(lines, index, title_bottom):
    """ParsedTooltip, or None unless a known item's title sits in the title bar (above
    `title_bottom`, crop pixels) and a "Rarity: X" line follows."""
    rows = merge_rows(lines)
    rarity_at = next((i for i, row in enumerate(rows) if _rarity(row)), None)
    if rarity_at is None:
        return None
    rarity = _rarity(rows[rarity_at])
    titles = [i for i, row in enumerate(rows[:rarity_at]) if row.y < title_bottom]
    for title_at in reversed(titles):  # the row nearest the rule is the title
        item_id = index.resolve(rows[title_at].text, rarity)
        if item_id:
            break
    else:
        return None
    rolls, base, unread = [], [], []
    for row in rows[title_at + 1:rarity_at]:
        stat = parse_stat(row.text)
        if stat:
            (rolls if stat[0] == "roll" else base).append((stat[1], stat[2]))
        elif _looks_like_stat(row.text):
            unread.append(row.text)
    return ParsedTooltip(rows[title_at].text, rarity, item_id, tuple(rolls), tuple(base), tuple(unread))
