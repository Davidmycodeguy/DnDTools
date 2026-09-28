from src.models.tooltip_parser import ItemIndex, ParsedTooltip, merge_rows, parse_tooltip, parse_stat
from src.models.win_ocr import OcrLine

ITEMS = {
    "OccultistRobe_3001": {"name": "Occultist Robe", "rarity": "Uncommon"},
    "OccultistRobe_4001": {"name": "Occultist Robe", "rarity": "Rare"},
    "WoolenCap_2001": {"name": "Woolen Cap", "rarity": "Common"},
    "ArmingSword_2001": {"name": "Arming Sword", "rarity": "Common"},
    "GemRing_5001": {"name": "Gem Ring (Perfect)", "rarity": "Epic"},
    "Quarterstaff_3001": {"name": "Quarterstaff", "rarity": "Uncommon"},
}
INDEX = ItemIndex(ITEMS)
TITLE_BOTTOM = 55  # half-scale crop: the title bar is the top 110 px of a 4K tooltip read


def _lines(rows):
    return [OcrLine(text, x, y, w, h) for text, x, y, w, h in rows]


# Real Windows OCR output for tooltips captured in game (half-scale 4K crops, 2026-09-28).
OCCULTIST_ROBE = _lines([
    ["Occultist Robe", 98, 19, 162, 18], ["Armor Rating 49", 110, 78, 134, 17],
    ["Magic Resistance 50", 95, 105, 165, 17], ["Move Speed —4", 116, 132, 123, 17],
    ["Vigor 2", 149, 159, 57, 17], ["Will 1", 157, 186, 41, 14], ["- +2% Undead Damage Bonus", 45, 214, 246, 16],
    ["Required Class.", 116, 261, 126, 17], ["Warlock", 146, 287, 65, 12], ["Slot Type: Chest", 111, 312, 137, 15],
    ["Armor Type:", 102, 337, 100, 15], ["Cloth", 213, 337, 43, 12], ["Loot State:", 96, 362, 88, 12],
    ["Handled", 196, 362, 67, 12], ["Rarity:", 101, 387, 55, 15], ["Uncommon", 167, 387, 90, 12],
    ["A bewitching garment that weaves", 39, 436, 280, 16], ["together style and sorcery.", 69, 463, 219, 16]])
WOOLEN_CAP = _lines([
    ["Woolen Cap", 146, 19, 131, 22], ["Armor Rating 21", 145, 78, 131, 17],
    ["Headshot Damage Reduction 7 f", 78, 105, 254, 17], ["Move Speed —2", 149, 132, 122, 17],
    ["Vigor I", 183, 159, 54, 17], ["Dexterity I", 166, 186, 88, 17], ["Agility I", 178, 213, 65, 17],
    ["Slot Type: Head(Hat)", 122, 267, 179, 16], ["Armor Type: Cloth", 135, 293, 154, 15],
    ["Supplied", 228, 317, 68, 17], ["Loot State:", 128, 318, 88, 12], ["Rarity:", 144, 343, 55, 15],
    ["Common", 210, 343, 70, 13], ["A practical cap easily found by an)", 53, 392, 279, 17],
    ["13 :", 90, 748, 75, 11], ["29.3", 303, 748, 29, 12]])
GEM_RING = _lines([
    ["Gem Ring (Perfect)", 89, 19, 300, 22], ["Slot Type: Invalid", 126, 80, 180, 16],
    ["Looted", 222, 105, 60, 14], ["Loot State:", 122, 106, 90, 13], ["Rarity: Epic", 150, 130, 100, 16],
    ["This gold ring, adorned with a gleaming", 39, 245, 320, 16], ["Deal", 11, 416, 40, 14]])
MERCHANT_HEADER = _lines([  # a fixed UI line under a merchant's name, read as if it were a tooltip
    ["The Collector", 60, 20, 180, 22], ["I'm surprised you survived", 40, 90, 240, 16],
    ["Gem Ring", 150, 700, 120, 20], ["Rarity", 160, 800, 60, 16]])


def test_rows_merge_pieces_on_the_same_line_left_to_right():
    rows = merge_rows(_lines([["Epic", 167, 387, 50, 12], ["Rarity:", 101, 386, 55, 15], ["Next", 90, 420, 40, 12]]))
    assert [r.text for r in rows] == ["Rarity: Epic", "Next"]


def test_parses_an_uncommon_robe_with_its_random_roll():
    tip = parse_tooltip(OCCULTIST_ROBE, INDEX, TITLE_BOTTOM)
    assert tip == ParsedTooltip(
        title="Occultist Robe", rarity="Uncommon", item_id="OccultistRobe_3001",
        rolls=(("UndeadDamageMod", 20),),
        base=(("ArmorRating", 49), ("MagicRegistance", 50), ("MoveSpeed", -4), ("Vigor", 2), ("Will", 1)),
        unread=())


def test_ocr_slips_in_numbers_are_corrected():
    tip = parse_tooltip(WOOLEN_CAP, INDEX, TITLE_BOTTOM)
    assert tip.item_id == "WoolenCap_2001"
    assert tip.base == (("ArmorRating", 21), ("HeadshotReductionMod", 70), ("MoveSpeed", -2),
                        ("Vigor", 1), ("Dexterity", 1), ("Agility", 1))
    assert tip.rolls == ()


def test_items_without_stats_still_resolve():
    tip = parse_tooltip(GEM_RING, INDEX, TITLE_BOTTOM)
    assert (tip.item_id, tip.rarity, tip.base, tip.rolls) == ("GemRing_5001", "Epic", (), ())


def test_the_title_must_sit_in_the_title_bar():
    assert parse_tooltip(MERCHANT_HEADER, INDEX, TITLE_BOTTOM) is None


def test_nothing_without_a_rarity_line():
    assert parse_tooltip(OCCULTIST_ROBE[:6], INDEX, TITLE_BOTTOM) is None


def test_rarity_picks_the_right_item_among_same_names():
    lines = [line if line.text != "Uncommon" else OcrLine("Rare", 167, 387, 40, 12) for line in OCCULTIST_ROBE]
    assert parse_tooltip(lines, INDEX, TITLE_BOTTOM).item_id == "OccultistRobe_4001"


def test_a_slightly_misread_title_still_resolves():
    lines = [OcrLine("Occu1tist Rohe", 98, 19, 162, 18)] + OCCULTIST_ROBE[1:]
    assert parse_tooltip(lines, INDEX, TITLE_BOTTOM).item_id == "OccultistRobe_3001"


def test_unknown_items_are_not_guessed():
    lines = [OcrLine("Totally New Helm", 98, 19, 162, 18)] + OCCULTIST_ROBE[1:]
    assert parse_tooltip(lines, INDEX, TITLE_BOTTOM) is None


def test_stat_lines():
    assert parse_stat("Weapon Damage 28") == ("base", "PhysicalWeaponDamage", 28)
    assert parse_stat("Armor Penetration 30%") == ("base", "ArmorPenetration", 300)
    assert parse_stat("Projectile Damage Reduction 3.5%") == ("base", "ProjectileReductionMod", 35)
    assert parse_stat("Move Speed −50") == ("base", "MoveSpeed", -50)
    assert parse_stat("+5.1% Undead Damage Bonu") == ("roll", "UndeadDamageMod", 51)
    assert parse_stat("- +3 Strength -") == ("roll", "Strength", 3)
    assert parse_stat("+12 Armor Rating") == ("roll", "ArmorRatingAdd", 12)
    assert parse_stat("+2.4% Max Health") == ("roll", "MaxHealthBonus", 24)
    assert parse_stat("+6 Max Health") == ("roll", "MaxHealthAdd", 6)
    assert parse_stat("Slot Type: Chest") is None
    assert parse_stat("Fighter. Ranger. Bard") is None


def test_unmapped_stat_lines_are_reported_not_guessed():
    lines = OCCULTIST_ROBE[:6] + [OcrLine("+4% Brand New Stat", 45, 214, 246, 16)] + OCCULTIST_ROBE[7:]
    tip = parse_tooltip(lines, INDEX, TITLE_BOTTOM)
    assert tip.rolls == () and tip.unread == ("+4% Brand New Stat",)


def test_a_rarity_line_read_without_its_space_still_counts():
    from src.models.tooltip_parser import looks_like_tooltip
    from src.models.win_ocr import OcrLine
    assert looks_like_tooltip([OcrLine("Rarity:Uncommon", 101, 387, 150, 15)])
    assert looks_like_tooltip([OcrLine("Rarity: Epic", 101, 387, 150, 15)])
    assert not looks_like_tooltip([OcrLine("My Listings", 10, 10, 100, 15)])


def test_memory_capacity_and_other_bonus_rolls_are_read():
    from src.models.tooltip_parser import parse_stat
    assert parse_stat("+7.1% Memory Capacity Bonus") == ("roll", "MemoryCapacityBonus", 71)
    assert parse_stat("+3 Memory Capacity") == ("roll", "MemoryCapacityAdd", 3)
    assert parse_stat("+2.5% Max Health Bonus") == ("roll", "MaxHealthBonus", 25)


def test_base_stats_beyond_the_basics_are_read():
    from src.models.tooltip_parser import parse_stat
    assert parse_stat("Regular Interaction Speed 15.7%") == ("base", "RegularInteractionSpeed", 157)
    assert parse_stat("Spell Casting Speed 5%") == ("base", "SpellCastingSpeed", 50)
    assert parse_stat("Magical Power 3") == ("base", "MagicalPower", 3)
    assert parse_stat("Undead Damage Bonus 4%") == ("base", "UndeadDamageMod", 40)
