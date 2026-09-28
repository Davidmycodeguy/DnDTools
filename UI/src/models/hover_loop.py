"""Watches the cursor while the game is in front; when it rests on an item, shows that item's value.

The game draws an item's tooltip ~0.2-0.3 s after the cursor comes to rest. Rather than wait a
fixed time, the loop looks for it on every poll from the moment the cursor settles (a look grabs
only two thin strips beside the cursor, so an empty look is cheap), reads it the moment it appears,
hides the card as soon as the cursor moves on or the game's tooltip goes away.
"""
import logging
import math
import time

from src.models.tooltip_finder import TITLE_HEIGHT_PX

logger = logging.getLogger(__name__)

POLL_S = 0.02         # cursor checks; a resting cursor's tooltip is looked for this often
SETTLE_S = 0.05       # the cursor has stopped, not just passed over an item
EAGER_S = 0.6         # look on every poll this long (tooltips appear ~0.2-0.3 s in) ...
LOOK_EVERY_S = 0.1    # ... then less often ...
LOOK_FOR_S = 1.5      # ... and stop: nothing is coming at this spot
CHECK_EVERY_S = 0.25  # while the card shows: is the game's tooltip still up?
MOVE_PX = 6           # cursor movement that counts as moving on
BASE_HEIGHT = 2160
ERROR_BACKOFF_S = 5.0


class HoverLoop:
    def __init__(self, *, cursor, game_active, grab, screen_size, reader, value_of, panel, enabled,
                 clock=time.monotonic):
        self._cursor = cursor
        self._game_active = game_active
        self._grab = grab            # (left, top, right, bottom) screen pixels -> RGB array
        self._screen_size = screen_size
        self._reader = reader        # read_screen(...) -> (ParsedTooltip, box) | None; still_showing(...)
        self._value_of = value_of    # ParsedTooltip -> card for the panel
        self._panel = panel
        self._enabled = enabled
        self._clock = clock
        self._last = None            # last cursor position
        self._since = 0.0            # when the cursor settled there
        self._looked = -math.inf     # last look (or check) at this rest
        self._done = False           # nothing more to look for until the cursor moves
        self._shown = None           # the tooltip box the card is showing for
        self._active = None          # last on/off state, logged when it changes

    def _hide(self):
        if self._shown is not None:
            self._panel.hide()
            self._shown = None

    def _geometry(self):
        width, height = self._screen_size()
        return (width, height), height / BASE_HEIGHT

    def step(self):
        active = bool(self._enabled() and self._game_active())
        if active != self._active:
            logger.info("Hover values %s", "watching the cursor" if active else "paused")
            self._active = active
        if not active:
            self._hide()
            self._last = None
            return
        position, now = self._cursor(), self._clock()
        if self._last is None or math.dist(position, self._last) > MOVE_PX:
            self._last, self._since, self._looked, self._done = position, now, -math.inf, False
            self._hide()
            return
        if self._shown is not None:
            if now - self._looked >= CHECK_EVERY_S:
                self._looked = now
                self._check(position)
            return
        rest = now - self._since
        if self._done or rest < SETTLE_S:
            return
        if rest > LOOK_FOR_S:
            self._done = True
            return
        if rest > EAGER_S and now - self._looked < LOOK_EVERY_S:
            return
        self._looked = now
        self._look(position, rest)

    def _look(self, position, rest):
        screen, scale = self._geometry()
        try:
            found = self._reader.read_screen(self._grab, position, scale, screen)
            card = self._value_of(found[0]) if found else None
        except Exception:  # a bad read must never stop the loop, nor repeat on every poll
            logger.exception("Hover value read failed")
            self._done = True
            return
        if not found or card is None:
            return
        box = found[1]
        tooltip = (box.left, box.rule_y - round(TITLE_HEIGHT_PX * scale), box.right, box.rule_y)
        self._panel.show(card, tooltip, screen)
        self._shown, self._done = box, True
        logger.debug("Hover card for %s shown %.0f ms after the cursor rested (found at %.0f ms)",
                    found[0].item_id, 1000 * (self._clock() - self._since), 1000 * rest)

    def _check(self, position):
        screen, scale = self._geometry()
        try:
            showing = self._reader.still_showing(self._grab, position, scale, screen, self._shown)
        except Exception:
            logger.debug("Hover tooltip check failed", exc_info=True)
            showing = True  # keep the card rather than flicker it on a bad capture
        if not showing:
            self._hide()

    def run(self, stop_event, sleep=time.sleep):
        while not stop_event.is_set():
            try:
                self.step()
                sleep(POLL_S)
            except Exception:
                logger.exception("Hover value loop step failed")
                sleep(ERROR_BACKOFF_S)  # don't flood the log with a lasting fault
        self._hide()
