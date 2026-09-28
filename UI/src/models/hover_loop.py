"""Watches the cursor while the game is in front; when it rests on an item, shows that item's value.

The game draws an item's tooltip while the cursor rests on it, so the loop waits for the cursor to
settle, reads the tooltip once, and hides the panel as soon as the cursor moves on.
"""
import logging
import math
import time

from src.models.tooltip_finder import SEARCH_X_PX, SEARCH_Y_PX, TITLE_HEIGHT_PX

logger = logging.getLogger(__name__)

POLL_S = 0.05
STILL_S = 0.25   # the tooltip is up by the time the cursor has rested this long
MOVE_PX = 6      # cursor movement that counts as moving on
READS_PER_REST = 2  # the game can be slow to draw a tooltip (e.g. right after a click): try again once
BASE_HEIGHT = 2160
ERROR_BACKOFF_S = 5.0


class HoverLoop:
    def __init__(self, *, cursor, game_active, grab, screen_size, reader, value_of, panel, enabled,
                 clock=time.monotonic):
        self._cursor = cursor
        self._game_active = game_active
        self._grab = grab            # (left, top, right, bottom) screen pixels -> PIL image
        self._screen_size = screen_size
        self._reader = reader        # TooltipReader-like: read(image, cursor, scale)
        self._value_of = value_of    # ParsedTooltip -> [PanelLine]
        self._panel = panel
        self._enabled = enabled
        self._clock = clock
        self._last = None            # last cursor position
        self._since = 0.0            # when the cursor settled there
        self._read_here = False      # this rest has been read already
        self._tries = 0              # reads during this rest
        self._showing = False
        self._active = None          # last on/off state, logged when it changes

    def _hide(self):
        if self._showing:
            self._panel.hide()
            self._showing = False

    def step(self):
        active = bool(self._enabled() and self._game_active())
        if active != self._active:
            logger.info("Hover values %s", "watching the cursor" if active else "paused")
            self._active = active
        if not active:
            self._hide()
            self._last, self._read_here = None, False
            return
        position, now = self._cursor(), self._clock()
        if self._last is None or math.dist(position, self._last) > MOVE_PX:
            self._last, self._since, self._read_here, self._tries = position, now, False, 0
            self._hide()
            return
        if self._read_here or now - self._since < STILL_S:
            return
        self._read_here = True
        self._tries += 1
        if not self._read(position) and self._tries < READS_PER_REST:
            self._read_here, self._since = False, now  # look again after another short rest

    def _read(self, position):
        width, height = self._screen_size()
        scale = height / BASE_HEIGHT
        x, y = position
        region = (max(0, x - round(SEARCH_X_PX * scale)), max(0, y - round(SEARCH_Y_PX * scale)),
                  min(width, x + round(SEARCH_X_PX * scale)), min(height, y + round(SEARCH_Y_PX * scale)))
        try:
            found = self._reader.read(self._grab(region), (x - region[0], y - region[1]), scale)
            lines = self._value_of(found[0]) if found else None
        except Exception:  # a bad read must never stop the loop
            logger.exception("Hover value read failed")
            found, lines = None, None
        logger.debug("Hover read at %s: %s", position, found[0].item_id if found else "no tooltip")
        if not found or not lines:
            self._hide()
            return False
        box = found[1]
        ox, oy = region[0], region[1]
        tooltip = (box.left + ox, box.rule_y + oy - round(TITLE_HEIGHT_PX * scale), box.right + ox, box.rule_y + oy)
        self._panel.show(lines, tooltip, (width, height))
        self._showing = True
        return True

    def run(self, stop_event, sleep=time.sleep):
        while not stop_event.is_set():
            try:
                self.step()
                sleep(POLL_S)
            except Exception:
                logger.exception("Hover value loop step failed")
                sleep(ERROR_BACKOFF_S)  # don't flood the log with a lasting fault
        self._hide()
