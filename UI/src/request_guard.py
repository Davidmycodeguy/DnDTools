"""Cross-site request forgery guard for the local web server.

The app serves its UI on 127.0.0.1, and some routes act in the game (sorting, listing, selling). Any
web page the user visits could otherwise POST to that port. Browsers label such requests with an
Origin and Sec-Fetch-Site header; a write from another site is refused. Requests without either
header (curl, scripts, the app's own tools) are allowed.
"""
from urllib.parse import urlsplit

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_cross_site_write(method, origin, fetch_site, host):
    """Whether a request is a write coming from a page on another site (to refuse it)."""
    if str(method).upper() not in WRITE_METHODS:
        return False
    if fetch_site == "cross-site":
        return True
    if origin is None:
        return False
    if origin == "null":
        return True
    return urlsplit(origin).netloc.lower() != str(host).lower()
