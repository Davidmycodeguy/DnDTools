from types import SimpleNamespace

from src.models.hover_loop import MOVE_PX, READS_PER_REST, STILL_S, HoverLoop
from src.models.hover_reader import PanelLine

SCREEN = (3840, 2160)
TIP = SimpleNamespace(item_id="OccultistRobe_3001", rolls=(), unread=())
BOX = SimpleNamespace(left=300, right=900, rule_y=500)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class Panel:
    def __init__(self):
        self.shown = []
        self.hidden = 0

    def show(self, lines, tooltip, screen):
        self.shown.append((lines, tooltip, screen))

    def hide(self):
        self.hidden += 1


class Reader:
    def __init__(self, result=(TIP, BOX)):
        self.result = result
        self.calls = []

    def read(self, image, cursor, scale):
        self.calls.append((image, cursor, scale))
        return self.result


def _loop(reader=None, enabled=True, active=True, cursor=(2000, 1000)):
    clock, panel = Clock(), Panel()
    state = SimpleNamespace(cursor=cursor, enabled=enabled, active=active, grabs=[])

    def grab(region):
        state.grabs.append(region)
        return f"image{region}"
    loop = HoverLoop(cursor=lambda: state.cursor, game_active=lambda: state.active, grab=grab,
                     screen_size=lambda: SCREEN, reader=reader or Reader(),
                     value_of=lambda tip: [PanelLine("Worth ~245g", "value")], panel=panel,
                     enabled=lambda: state.enabled, clock=clock)
    return loop, clock, panel, state


def test_reads_once_the_cursor_rests_then_shows_the_value_beside_the_tooltip():
    reader = Reader()
    loop, clock, panel, state = _loop(reader)
    loop.step()
    assert reader.calls == []  # just arrived: the game hasn't drawn its tooltip yet
    clock.t = STILL_S + 0.01
    loop.step()
    assert len(reader.calls) == 1
    (left, top, right, bottom) = state.grabs[0]
    image, cursor, scale = reader.calls[0]
    assert cursor == (2000 - left, 1000 - top) and scale == 1.0
    lines, tooltip, screen = panel.shown[0]
    assert lines == [PanelLine("Worth ~245g", "value")] and screen == SCREEN
    assert tooltip[0] == BOX.left + left and tooltip[2] == BOX.right + left  # back in screen pixels
    loop.step()
    assert len(reader.calls) == 1  # still resting on the same item: nothing re-read


def test_moving_the_cursor_hides_the_panel_and_reads_again_after_the_next_rest():
    reader = Reader()
    loop, clock, panel, state = _loop(reader)
    loop.step()
    clock.t = STILL_S + 0.01
    loop.step()
    state.cursor = (2000 + MOVE_PX + 5, 1000)
    clock.t += 0.05
    loop.step()
    assert panel.hidden >= 1
    clock.t += STILL_S + 0.01
    loop.step()
    assert len(reader.calls) == 2


def test_nothing_found_hides_the_panel():
    loop, clock, panel, state = _loop(Reader(result=None))
    loop.step()
    clock.t = STILL_S + 0.01
    loop.step()
    assert panel.shown == []


def test_off_or_game_in_background_means_no_reads():
    for enabled, active in ((False, True), (True, False)):
        reader = Reader()
        loop, clock, panel, state = _loop(reader, enabled=enabled, active=active)
        loop.step()
        clock.t = STILL_S + 0.01
        loop.step()
        assert reader.calls == [] and panel.shown == []


def test_the_search_area_stays_on_screen():
    reader = Reader()
    loop, clock, panel, state = _loop(reader, cursor=(10, 2150))
    loop.step()
    clock.t = STILL_S + 0.01
    loop.step()
    left, top, right, bottom = state.grabs[0]
    assert left == 0 and bottom == SCREEN[1] and right <= SCREEN[0] and top >= 0


def test_a_failing_read_does_not_stop_the_loop():
    class Broken:
        def read(self, image, cursor, scale):
            raise RuntimeError("OCR worker died")
    loop, clock, panel, state = _loop(Broken())
    loop.step()
    clock.t = STILL_S + 0.01
    loop.step()  # must not raise
    assert panel.shown == []


def test_turning_it_off_hides_a_shown_panel():
    loop, clock, panel, state = _loop()
    loop.step()
    clock.t = STILL_S + 0.01
    loop.step()
    state.enabled = False
    loop.step()
    loop.step()
    assert panel.hidden == 1


class SlowTooltip:
    """No tooltip on the first look (the game hasn't drawn it yet), then the item."""

    def __init__(self, misses):
        self.misses, self.calls = misses, 0

    def read(self, image, cursor, scale):
        self.calls += 1
        return None if self.calls <= self.misses else (TIP, BOX)


def _rest(loop, clock, times):
    for _ in range(times):
        clock.t += STILL_S + 0.01
        loop.step()


def test_a_tooltip_drawn_late_is_read_on_the_second_look():
    reader = SlowTooltip(misses=1)
    loop, clock, panel, state = _loop(reader)
    loop.step()
    _rest(loop, clock, 3)
    assert reader.calls == 2 and len(panel.shown) == 1


def test_an_empty_spot_is_looked_at_only_a_few_times():
    reader = SlowTooltip(misses=99)
    loop, clock, panel, state = _loop(reader)
    loop.step()
    _rest(loop, clock, 6)
    assert reader.calls == READS_PER_REST and panel.shown == []
