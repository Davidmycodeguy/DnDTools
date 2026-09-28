"""Is the game what the player is looking at and using?"""

# In-game overlays that can hold the keyboard focus while the game keeps drawing beneath them.
OVERLAY_TITLES = frozenset({"Discord Overlay", "NVIDIA GeForce Overlay", "NVIDIA Overlay"})


def game_has_focus(foreground_title, game_title, game_window_shown):
    """True when the game's window is in front, or an in-game overlay (Discord, NVIDIA) holds focus
    while the game's window shows beneath it (not minimised)."""
    return foreground_title == game_title or (foreground_title in OVERLAY_TITLES and bool(game_window_shown))
