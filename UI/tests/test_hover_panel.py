from PIL import Image

from src.models.hover_panel import GAP_PX, place_panel, premultiplied_bgra

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



def test_pixels_go_to_the_window_premultiplied_in_bgra_order():
    image = Image.new("RGBA", (2, 1))
    image.putdata([(200, 100, 50, 255), (200, 100, 50, 128)])
    assert premultiplied_bgra(image) == bytes([50, 100, 200, 255, 25, 50, 100, 128])
