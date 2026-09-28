from src.models.game_window import game_has_focus

GAME = "Dark and Darker  "


def test_the_games_own_window_in_front():
    assert game_has_focus(GAME, GAME, game_window_shown=True) is True


def test_an_in_game_overlay_holding_focus_over_the_game_still_counts():
    assert game_has_focus("Discord Overlay", GAME, game_window_shown=True) is True


def test_an_overlay_over_a_minimised_game_does_not():
    assert game_has_focus("Discord Overlay", GAME, game_window_shown=False) is False


def test_another_app_in_front_does_not():
    assert game_has_focus("Discord", GAME, game_window_shown=True) is False
    assert game_has_focus("", GAME, game_window_shown=True) is False
