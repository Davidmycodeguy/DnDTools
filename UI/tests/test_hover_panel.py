from src.models.hover_panel import GAP_PX, font_px, place_panel

SCREEN = (3840, 2160)


def test_panel_goes_left_of_the_tooltip_top_aligned():
    x, y = place_panel((400, 200), tooltip=(2000, 900, 2700, 1010), screen=SCREEN)
    assert (x, y) == (2000 - GAP_PX - 400, 900)


def test_panel_goes_right_when_there_is_no_room_on_the_left():
    x, y = place_panel((400, 200), tooltip=(150, 900, 850, 1010), screen=SCREEN)
    assert x == 850 + GAP_PX


def test_panel_stays_on_screen():
    x, y = place_panel((400, 200), tooltip=(100, 2100, 3800, 2150), screen=SCREEN)
    assert 0 <= x <= SCREEN[0] - 400 and 0 <= y <= SCREEN[1] - 200


def test_fonts_scale_with_the_screen():
    assert font_px(22, 1080) == 22
    assert font_px(22, 2160) == 44
