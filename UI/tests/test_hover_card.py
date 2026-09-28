from types import SimpleNamespace as N

from src.models.hover_card import build_card, render_card, roll_text, stat_label

TIP = N(title="Dark Cuirass", rarity="Epic", rolls=(("Strength", 3), ("ArmorPenetration", 42)), unread=())


def _estimate(value=364.4, pairs=()):
    return N(value=value, low=290.1, high=455.0, floor=310, confidence="high", listings=812,
             rolls=(N(stat="Strength", quality=0.9, effect_pct=18.0),
                    N(stat="ArmorPenetration", quality=0.5, effect_pct=9.5)),
             pairs=pairs)


def test_list_it_when_the_market_nets_more_than_a_merchant_pays():
    card = build_card(TIP, _estimate(), lowest_ask=330, listed=14, sold=3, vendor_price=60, slots=6)
    assert (card.verdict, card.verdict_text) == ("list", "List it · nets ~345g after fee")  # fee: 5% of 364 rounded up = 19g
    assert (card.value, card.low, card.high, card.confidence) == (364, 290, 455, "high")
    assert (card.lowest_ask, card.listed, card.sold, card.merchant, card.slots) == (330, 14, 3, 60, 6)


def test_sell_to_merchant_when_the_fee_eats_the_margin():
    card = build_card(TIP, _estimate(value=60), lowest_ask=None, listed=0, sold=0, vendor_price=50, slots=1)
    assert (card.verdict, card.verdict_text) == ("merchant", "Sell to merchant · 50g")


def test_no_estimate_means_no_market_data():
    card = build_card(TIP, None, lowest_ask=None, listed=0, sold=0, vendor_price=15, slots=3)
    assert card.verdict == "unknown" and card.value is None and card.quality is None
    assert [r.quality for r in card.rolls] == [None, None]


def test_rolls_read_like_the_game_with_their_quality():
    card = build_card(TIP, _estimate(), lowest_ask=None, listed=0, sold=0, vendor_price=0, slots=1)
    assert [(r.label, r.value, r.quality, r.effect_pct) for r in card.rolls] == [
        ("Strength", "+3", 0.9, 18.0), ("Armor Penetration", "+4.2%", 0.5, 9.5)]
    assert card.quality == 70


def test_only_meaningful_synergies_are_listed():
    pairs = (N(stats=("Strength", "ArmorPenetration"), effect_pct=12.0), N(stats=("Strength", "Vigor"), effect_pct=0.4))
    card = build_card(TIP, _estimate(pairs=pairs), lowest_ask=None, listed=0, sold=0, vendor_price=0, slots=1)
    assert card.pairs == ("Strength + Armor Penetration +12%",)


def test_stat_labels_and_values():
    assert stat_label("UndeadDamageMod") == "Undead Damage"
    assert stat_label("SpellCastingSpeed") == "Spell Casting Speed"
    assert roll_text("UndeadDamageMod", 51) == "+5.1%"
    assert roll_text("MaxHealthAdd", 6) == "+6"


def test_render_scales_with_the_screen_and_has_transparent_corners():
    card = build_card(TIP, _estimate(), lowest_ask=330, listed=14, sold=3, vendor_price=60, slots=6)
    small, big = render_card(card, 1080), render_card(card, 2160)
    assert small.mode == "RGBA" and big.width == 2 * small.width
    assert small.getpixel((0, 0))[3] == 0                      # shadow margin corner
    assert small.getpixel((small.width // 2, small.height // 2))[3] > 200  # card body


def test_render_without_market_data():
    card = build_card(N(title="Quarterstaff", rarity="Uncommon", rolls=(), unread=("+1 ???",)), None,
                      lowest_ask=None, listed=0, sold=0, vendor_price=15, slots=3)
    assert render_card(card, 1080).height > 100
