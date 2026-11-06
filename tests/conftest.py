"""A local test website, so tests never touch real sites."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


def _card(number: int) -> str:
    return (
        f'<article class="card"><h3><a href="/item/{number}" title="Item {number}">Item {number}</a></h3>'
        f'<p class="price">£{number}.50</p><img src="/img/{number}.png"></article>'
    )


def _listing(page: int) -> str:
    start = (page - 1) * 5 + 1
    cards = "".join(_card(n) for n in range(start, start + 5))
    nav = '<nav><ul><li><a href="/about">About</a></li><li><a href="/x">X</a></li><li><a href="/y">Y</a></li></ul></nav>'
    pager = f'<a class="pager" rel="next" href="/list/{page + 1}">Next</a>' if page < 3 else ""
    return f"<html><body>{nav}<main><div class='grid'>{cards}</div>{pager}</main></body></html>"


PAGES = {
    "/robots.txt": "User-agent: *\nDisallow: /private\n",
    "/table": (
        "<html><body><table><tr><th>Name</th><th>Age</th></tr>"
        "<tr><td>Ann</td><td>30</td></tr><tr><td>Ben</td><td>41</td></tr></table></body></html>"
    ),
    "/private": "<html><body><h1>Secret</h1></body></html>",
    "/blank": "<html><head><title>T</title></head><body><h1>Hello</h1><p>Only text.</p></body></html>",
    "/evil": (
        "<html><body><table><tr><th>A</th><th>B</th></tr>"
        '<tr><td>=HYPERLINK("http://bad")</td><td>-5</td></tr></table></body></html>'
    ),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/list/"):
            body, status = _listing(int(path.rsplit("/", 1)[1])), 200
        elif path == "/forbidden":
            body, status = "no", 403
        elif path in PAGES:
            body, status = PAGES[path], 200
        else:
            body, status = "missing", 404
        data = body.encode()
        self.send_response(status)
        kind = "text/plain" if path == "/robots.txt" else "text/html; charset=utf-8"
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
