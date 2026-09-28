from src.request_guard import is_cross_site_write

HOST = "127.0.0.1:48307"


def test_the_apps_own_window_can_write():
    assert not is_cross_site_write("POST", "http://127.0.0.1:48307", "same-origin", HOST)


def test_local_tools_without_an_origin_can_write():
    assert not is_cross_site_write("POST", None, None, HOST)


def test_a_web_page_elsewhere_cannot_write():
    assert is_cross_site_write("POST", "https://evil.example", "cross-site", HOST)
    assert is_cross_site_write("DELETE", "https://evil.example", None, HOST)
    assert is_cross_site_write("POST", "null", None, HOST)                # sandboxed frames, file:// pages
    assert is_cross_site_write("POST", None, "cross-site", HOST)


def test_reads_are_never_blocked():
    assert not is_cross_site_write("GET", "https://evil.example", "cross-site", HOST)


def test_localhost_and_127_0_0_1_count_as_the_same_app():
    assert not is_cross_site_write("POST", "http://localhost:48307", "same-site", "localhost:48307")
