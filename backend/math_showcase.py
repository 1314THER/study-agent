"""Isolated, read-only static server for math.150.chat."""
from __future__ import annotations

import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
MATH = FRONTEND / "math-showcase"

PAGES = {
    "/": MATH / "index.html",
    "/index.html": MATH / "index.html",
    "/home.html": MATH / "index.html",
    "/topics.html": MATH / "topics.html",
}
ASSETS = {
    "/math.css": MATH / "math.css",
    "/math.js": MATH / "math.js",
    "/math-render.js": MATH / "math-render.js",
    "/topics.js": MATH / "topics.js",
    "/math-mark.svg": MATH / "math-mark.svg",
    "/assets/fudan-favicon.png": MATH / "assets" / "fudan-favicon.png",
    "/assets/fudan-favicon-180.png": MATH / "assets" / "fudan-favicon-180.png",
    "/math-case.json": MATH / "math-case.json",
    "/math-topics.json": MATH / "math-topics.json",
    "/vendor/katex/katex.min.css": FRONTEND / "vendor/katex/katex.min.css",
    "/vendor/katex/katex.min.js": FRONTEND / "vendor/katex/katex.min.js",
}
for _name in (
    "AMS-Regular", "Caligraphic-Bold", "Caligraphic-Regular", "Fraktur-Bold",
    "Fraktur-Regular", "Main-Bold", "Main-BoldItalic", "Main-Italic", "Main-Regular",
    "Math-BoldItalic", "Math-Italic", "SansSerif-Bold", "SansSerif-Italic",
    "SansSerif-Regular", "Script-Regular", "Size1-Regular", "Size2-Regular",
    "Size3-Regular", "Size4-Regular", "Typewriter-Regular",
):
    ASSETS[f"/vendor/katex/fonts/KaTeX_{_name}.woff2"] = FRONTEND / "vendor/katex/fonts" / f"KaTeX_{_name}.woff2"


def safe_target(path: str) -> Path | None:
    target = PAGES.get(path) or ASSETS.get(path)
    if target is None:
        return None
    try:
        resolved = target.resolve(strict=True)
        resolved.relative_to(FRONTEND.resolve(strict=True))
        if target.is_symlink() or not resolved.is_file():
            return None
        # Resolved targets remain inside the explicit static roots.
        if path in PAGES or path in {"/math.css", "/math.js", "/math-render.js", "/topics.js", "/math-mark.svg", "/math-case.json", "/math-topics.json", "/assets/fudan-favicon.png", "/assets/fudan-favicon-180.png"}:
            resolved.relative_to(MATH.resolve(strict=True))
        elif path.startswith("/vendor/katex/"):
            resolved.relative_to((FRONTEND / "vendor/katex").resolve(strict=True))
        return resolved
    except (OSError, ValueError):
        return None


class MathShowcaseHandler(BaseHTTPRequestHandler):
    server_version = "math.150.chat"
    sys_version = ""

    def _respond(self, *, head: bool = False) -> None:
        if self.command not in ("GET", "HEAD"):
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
            return
        path = urlsplit(self.path).path
        if path == "/health":
            body = b'{"ok":true,"mode":"math-showcase","ai_enabled":false}\n'
            content_type = "application/json; charset=utf-8"
        else:
            target = safe_target(path)
            if target is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                body = target.read_bytes()
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in ("application/javascript", "application/json", "image/svg+xml"):
                content_type += "; charset=utf-8"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._respond()

    def do_HEAD(self) -> None:
        self._respond(head=True)

    def do_POST(self) -> None:
        self._respond()

    def do_PUT(self) -> None:
        self._respond()

    def do_PATCH(self) -> None:
        self._respond()

    def do_DELETE(self) -> None:
        self._respond()

    def log_message(self, fmt: str, *args) -> None:
        # Keep routine public reads out of logs; server errors remain managed by systemd.
        return


class MathShowcaseServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True
    allow_reuse_address = True


def main() -> None:
    parser = argparse.ArgumentParser(description="math.150.chat 静态展示站")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    if args.host not in ("127.0.0.1", "::1") or not (1 <= args.port <= 65535):
        parser.error("服务只允许绑定本机回环地址，端口范围为 1 至 65535。")
    with MathShowcaseServer((args.host, args.port), MathShowcaseHandler) as server:
        server.serve_forever(poll_interval=0.4)


if __name__ == "__main__":
    main()
