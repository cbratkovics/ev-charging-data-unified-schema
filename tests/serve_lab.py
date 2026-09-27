"""Loopback-only static test server with the real GitHub Pages repository prefix."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"
PREFIX = "/ev-charging-data-unified-schema"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def translate_path(self, path: str) -> str:
        if path == PREFIX:
            path = "/"
        elif path.startswith(PREFIX + "/"):
            path = path[len(PREFIX) :]
        return super().translate_path(path)


ThreadingHTTPServer(("127.0.0.1", 4173), Handler).serve_forever()
