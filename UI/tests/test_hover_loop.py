from types import SimpleNamespace

from src.models.hover_loop import (CHECK_EVERY_S, EAGER_S, LOOK_EVERY_S, LOOK_FOR_S, MOVE_PX, SETTLE_S,
                                   HoverLoop)

SCREEN = (3840, 2160)
TIP = SimpleNamespace(item_id="OccultistRobe_3001", rolls=(), unread=())
BOX = SimpleNamespace(left=2030, right=2700, rule_y=700)
CARD = SimpleNamespace(name="Occultist Robe", value=245)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Panel:
    def __init__(self):
        self.shown = []
        self.hidden = 0

    def show(self, card, tooltip, screen):
        self.shown.append((card, tooltip, screen))

    def hide(self):
        self.hidden += 1


class Reader:
    """Finds TIP once `appears_after` looks have come up empty; the tooltip stays up while `up`."""

    def __init__(self, appears_after=0, fail=False):
        self.appears_after, self.fail = appears_after, fail
        self.looks, self.checks, self.up = [], 0, True

    def read_screen(self, grab, cursor, scale, screen):
        self.looks.append((cursor, scale, screen))
        if self.fail:
            raise RuntimeError("OCR worker died")
        return (TIP, BOX) if len(self.looks) > self.appears_after else None

    def still_showing(self, grab, cursor, scale, screen, box):
        self.checks += 1
        return self.up


def _loop(reader=None, enabled=True, active=True, cursor=(2000, 1000)):
    clock, panel = Clock(), Panel()
    state = SimpleNamespace(cursor=cursor, enabled=enabled, active=active)
    loop = HoverLoop(cursor=lambda: state.cursor, game_active=lambda: state.active, grab=lambda region: None,
                     screen_size=lambda: SCREEN, reader=reader or Reader(), value_of=lambda tip: CARD,
                     panel=panel, enabled=lambda: state.enabled, clock=clock)
    return loop, clock, panel, state


def _run(loop, clock, seconds, poll=0.02):
    end = clock.t + seconds
    while clock.t < end:
        clock.t = round(clock.t + poll, 6)
        loop.step()


def test_looks_as_soon_as_the_cursor_settles_and_shows_the_card_beside_the_tooltip():
    reader = Reader()
    loop, clock, panel, state = _loop(reader)
    loop.step()
    assert reader.looks == []            # just arrived: could be passing over the item
    _run(loop, clock, SETTLE_S + 0.02)
    assert len(reader.looks) == 1
    cursor, scale, screen = reader.looks[0]
    assert cursor == (2000, 1000) and scale == 1.0 and screen == SCREEN
    card, tooltip, screen = panel.shown[0]
    assert card is CARD and tooltip == (2030, 700 - 110, 2700, 700)  # title bar above the rule, screen pixels
    _run(loop, clock, 0.2)
    assert len(reader.looks) == 1        # found: no more looks while resting on it


def test_a_tooltip_the_game_draws_late_is_caught_on_the_next_poll():
    reader = Reader(appears_after=10)    # ~0.2 s of empty looks, like the game's hover delay
    loop, clock, panel, state = _loop(reader)
    loop.step()
    _run(loop, clock, SETTLE_S + 0.3)
    assert len(reader.looks) == 11 and len(panel.shown) == 1


def test_an_empty_spot_is_looked_at_less_after_a_while_then_not_at_all():
    reader = Reader(appears_after=10_000)
    loop, clock, panel, state = _loop(reader)
    loop.step()
    _run(loop, clock, EAGER_S)
    eager = len(reader.looks)
    _run(loop, clock, LOOK_FOR_S - EAGER_S)
    patient = len(reader.looks) - eager
    assert eager >= (EAGER_S - SETTLE_S) / 0.02 - 2
    assert patient <= (LOOK_FOR_S - EAGER_S) / LOOK_EVERY_S + 1
    total = len(reader.looks)
    _run(loop, clock, 2.0)
    assert len(reader.looks) == total and panel.shown == []


def test_moving_hides_the_card_and_looks_again_once_settled():
    reader = Reader()
    loop, clock, panel, state = _loop(reader)
    loop.step()
    _run(loop, clock, SETTLE_S + 0.02)
    state.cursor = (2000 + MOVE_PX + 5, 1000)
    _run(loop, clock, 0.02)
    assert panel.hidden == 1
    _run(loop, clock, SETTLE_S + 0.02)
    assert len(reader.looks) == 2 and len(panel.shown) == 2


def test_the_card_goes_when_the_games_tooltip_does():
    reader = Reader()
    loop, clock, panel, state = _loop(reader)
    loop.step()
    _run(loop, clock, SETTLE_S + 0.02)
    _run(loop, clock, CHECK_EVERY_S * 2)
    assert panel.hidden == 0 and 1 <= reader.checks <= 3   # checked now and then, not every poll
    reader.up = False                                      # e.g. a key closed the tooltip
    _run(loop, clock, CHECK_EVERY_S + 0.02)
    assert panel.hidden == 1
    looks = len(reader.looks)
    _run(loop, clock, 1.0)
    assert len(reader.looks) == looks                      # not re-read until the cursor moves


def test_off_or_game_in_background_means_no_looks_and_hides_the_card():
    for enabled, active in ((False, True), (True, False)):
        reader = Reader()
        loop, clock, panel, state = _loop(reader, enabled=enabled, active=active)
        loop.step()
        _run(loop, clock, 0.5)
        assert reader.looks == [] and panel.shown == []
    loop, clock, panel, state = _loop()
    loop.step()
    _run(loop, clock, SETTLE_S + 0.02)
    state.enabled = False
    _run(loop, clock, 0.1)
    assert panel.hidden == 1


def test_a_failing_read_stops_looking_until_the_cursor_moves():
    reader = Reader(fail=True)
    loop, clock, panel, state = _loop(reader)
    loop.step()
    _run(loop, clock, 1.0)                                 # must not raise, nor retry every poll
    assert len(reader.looks) == 1 and panel.shown == []
