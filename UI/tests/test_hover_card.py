from types import SimpleNamespace as N

import pytest

from src.models.hover_card import (ItemFacts, MarketFacts, age_text, build_card, item_kind, market_pace,
                                   render_card, roll_text, round_gold, stat_label)

TIP = N(title="Dark Cuirass", rarity="Epic", rolls=(("Strength", 3), ("ArmorPenetration", 42)), unread=())
SHOP = ItemFacts(kind="Chest · Plate", icon=None, merchant=60, slots=6)


def _estimate(value=364.4, floor=310, pairs=()):
    return N(value=value, low=290.1, high=455.0, floor=floor, confidence="high", listings=812, typical=350,
             rolls=(N(stat="Strength", quality=0.98, effect_pct=18.0),
                    N(stat="ArmorPenetration", quality=0.5, effect_pct=-9.5)),
             pairs=pairs)


def test_list_it_when_a_fast_sale_nets_more_than_a_merchant_pays():
    card = build_card(TIP, _estimate(), MarketFacts(), SHOP)
    assert (card.value, card.low, card.high, card.confidence) == (364, 290, 455, "high")
    assert (card.fast_sale, card.net) == (310, 294)  # fee: 5% of 310 rounded up = 16g
    assert card.verdict == "list"


def test_fast_sale_is_never_above_the_value():
    card = build_card(TIP, _estimate(value=200, floor=260), MarketFacts(), SHOP)
    assert card.fast_sale == 200


def test_merchant_when_the_fee_eats_the_margin():
    card = build_card(TIP, _estimate(value=60, floor=55), MarketFacts(), ItemFacts(merchant=50))
    assert (card.fast_sale, card.net) == (55, 40)  # the 15g minimum fee
    assert card.verdict == "merchant"


def test_no_estimate_means_no_data_and_the_merchant_price_carries_the_card():
    card = build_card(TIP, None, MarketFacts(), ItemFacts(merchant=15, slots=3))
    assert (card.verdict, card.value, card.fast_sale, card.net, card.quality) == ("unknown", None, None, None, None)
    assert card.per_slot == 5
    assert [(r.quality, r.gold, r.is_max) for r in card.rolls] == [(None, None, False), (None, None, False)]


def test_rolls_read_like_the_game_with_quality_and_the_gold_they_add():
    card = build_card(TIP, _estimate(), MarketFacts(), SHOP)
    assert [(r.label, r.value, r.quality, r.gold, r.is_max) for r in card.rolls] == [
        ("Strength", "+3", 0.98, 65, True),                   # 18% of a 350g typical = 63, shown as 65
        ("Armor Penetration", "+4.2%", 0.5, -35, False)]
    assert card.quality == 74


def test_only_meaningful_synergies_are_listed():
    pairs = (N(stats=("Strength", "ArmorPenetration"), effect_pct=12.0), N(stats=("Strength", "Vigor"), effect_pct=2.4))
    card = build_card(TIP, _estimate(pairs=pairs), MarketFacts(), SHOP)
    assert card.pairs == (("Strength + Armor Penetration", 12.0),)


def test_market_facts_come_through_sorted_with_pace_and_trend():
    market = MarketFacts(asks=(330.4, 280.0, 512.6), sold_week=1, trend=(100, 100, 110, 120))
    card = build_card(TIP, _estimate(), market, SHOP)
    assert (card.asks, card.sold_week, card.pace) == ((280, 330, 513), 1, "sells fast")
    assert card.trend_pct == pytest.approx(15.0)


def test_a_short_price_history_has_no_trend():
    card = build_card(TIP, _estimate(), MarketFacts(trend=(100, 120, 140)), SHOP)
    assert card.trend_pct is None


def test_value_per_inventory_slot():
    card = build_card(TIP, _estimate(), MarketFacts(), SHOP)
    assert card.per_slot == 61  # 364 over 6 slots


def test_market_pace_needs_a_few_listings_to_judge():
    assert market_pace(2, 5) is None
    assert [market_pace(4, 1), market_pace(10, 1), market_pace(10, 0)] == ["sells fast", "steady", "slow market"]


def test_item_kind_is_the_line_under_the_title():
    assert item_kind({"type": "Weapon", "weapon_type": "Shield", "hand_type": "One Handed"}) == "Shield · One Handed"
    assert item_kind({"type": "Armor", "slot_type": "Chest", "armor_type": "Plate"}) == "Chest · Plate"
    assert item_kind({"type": "Accessory", "slot_type": "Necklace"}) == "Necklace"
    assert item_kind({"type": "Utility"}) == "Utility"
    assert item_kind(None) == ""


def test_gold_effects_are_rounded_to_what_an_estimate_can_claim():
    assert [round_gold(7.4), round_gold(63), round_gold(-33.25), round_gold(187)] == [7, 65, -35, 190]


def test_stat_labels_and_values():
    assert stat_label("UndeadDamageMod") == "Undead Damage"
    assert stat_label("SpellCastingSpeed") == "Spell Casting Speed"
    assert roll_text("UndeadDamageMod", 51) == "+5.1%"
    assert roll_text("MaxHealthAdd", 6) == "+6"


def test_render_scales_with_the_screen_and_has_transparent_corners():
    pairs = (N(stats=("Strength", "ArmorPenetration"), effect_pct=12.0),)
    market = MarketFacts(asks=tuple(range(250, 700, 15)), sold_week=6, trend=(300, 320, 310, 340, 360))
    card = build_card(TIP, _estimate(pairs=pairs), market, SHOP)
    small, big = render_card(card, 1080), render_card(card, 2160)
    assert small.mode == "RGBA" and abs(big.width - 2 * small.width) <= 1
    assert small.getpixel((0, 0))[3] == 0                                  # shadow margin corner
    assert small.getpixel((small.width // 2, small.height // 2))[3] == 255  # card body


def test_render_without_market_data_or_an_icon_file():
    tip = N(title="Quarterstaff", rarity="Uncommon", rolls=(("UndeadDamageMod", 51),), unread=("+1 ???",))
    card = build_card(tip, None, MarketFacts(), ItemFacts(icon="missing/icon.webp", merchant=15, slots=5))
    assert render_card(card, 1080).height > 100


def test_render_with_one_ask_and_a_long_title():
    tip = N(title="Blue Sapphire (Perfect) of the Very Long Name", rarity="Legendary", rolls=(), unread=())
    card = build_card(tip, _estimate(), MarketFacts(asks=(400,)), ItemFacts(merchant=50))
    assert render_card(card, 1440).height > 100


def test_older_asks_carry_how_long_ago_they_were_seen():
    card = build_card(TIP, _estimate(), MarketFacts(asks=(300,), seen_ago_s=7 * 3600), SHOP)
    assert card.seen_ago_s == 7 * 3600


def test_age_text_is_short():
    assert [age_text(35 * 60), age_text(7 * 3600 + 900), age_text(3 * 86400)] == ["35 min", "7 h", "3 d"]


def test_no_pace_until_sales_could_have_been_seen():
    asks = (300, 320, 340, 360)
    assert build_card(TIP, _estimate(), MarketFacts(asks=asks), SHOP).pace is None
    assert build_card(TIP, _estimate(), MarketFacts(asks=asks, sales_tracked=True), SHOP).pace == "slow market"


def test_a_fast_sale_that_rounds_to_nothing_still_makes_a_card():
    card = build_card(TIP, _estimate(value=0.4, floor=0.3), MarketFacts(), ItemFacts(merchant=5))
    assert (card.fast_sale, card.net, card.verdict) == (0, -15, "merchant")
    assert render_card(card, 1080).height > 100
    card = build_card(TIP, _estimate(value=0.4, floor=0.3), MarketFacts(), ItemFacts(merchant=0))
    assert render_card(card, 1080).height > 100


def test_the_fast_sale_is_what_the_lister_would_list_at_when_known():
    card = build_card(TIP, _estimate(), MarketFacts(asks=(280, 330), listing_price=275), SHOP)
    assert (card.fast_sale, card.net) == (275, 260)  # fee: 5% of 275 rounded up = 14g
    card = build_card(TIP, _estimate(), MarketFacts(asks=(280, 330)), SHOP)
    assert card.fast_sale == 310                     # no listing price: the model's lowest reasonable price
