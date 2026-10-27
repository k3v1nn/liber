# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import io
import struct
import threading
import time
import unittest
import warnings
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from conversor.web_images import (
    ALL_FAILED_MESSAGE,
    IMAGE_PROGRESS_MESSAGE,
    NOT_HTML_MESSAGE,
    PAGE_PROGRESS_MESSAGE,
    ImportCancelled,
    import_images_from_urls,
)


def _png(color: str, size: tuple[int, int] = (400, 600), **save_kwargs) -> bytes:
    stream = io.BytesIO()
    with Image.new("RGB", size, color) as image:
        image.save(stream, format="PNG", **save_kwargs)
    return stream.getvalue()


def _jpeg(size: tuple[int, int] = (400, 600), color: str = "white", orientation: int | None = None) -> bytes:
    stream = io.BytesIO()
    with Image.new("RGB", size, color) as image:
        if orientation is None:
            image.save(stream, format="JPEG")
        else:
            exif = Image.Exif()
            exif[274] = orientation
            image.save(stream, format="JPEG", exif=exif)
    return stream.getvalue()


def _cmyk_jpeg() -> bytes:
    stream = io.BytesIO()
    with Image.new("CMYK", (400, 600), (0, 120, 120, 0)) as image:
        image.save(stream, format="JPEG")
    return stream.getvalue()


def _png_with_dimensions(width: int, height: int) -> bytes:
    """A PNG whose header claims huge dimensions without carrying real pixel data."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


def _html(markup: str, status: int = 200) -> tuple[int, dict[str, str], bytes]:
    return status, {"Content-Type": "text/html; charset=utf-8"}, markup.encode("utf-8")


def _image(data: bytes, content_type: str = "image/png") -> tuple[int, dict[str, str], bytes]:
    return 200, {"Content-Type": content_type}, data


def _gallery(*sources: str, title: str = "Galeria &amp; Cia", head: str = "") -> str:
    images = "".join(f'<img src="{source}">' for source in sources)
    return f"<html><head><title>{title}</title>{head}</head><body>{images}</body></html>"


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        """Clients abandon stalled downloads on purpose in the deadline test."""


class _Server:
    """Minimal threaded HTTP server; routes map a path to a response or a handler callable."""

    def __init__(self, routes):
        self.routes = routes
        self.requests: list[tuple[str, dict[str, str]]] = []
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with server._lock:
                    server.requests.append((self.path, {name.lower(): value for name, value in self.headers.items()}))
                route = server.routes.get(self.path)
                if route is None:
                    self.send(404, {}, b"")
                elif callable(route):
                    route(self)
                else:
                    self.send(*route)

            def send(self, status, headers, body):
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        self.httpd = _QuietServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}{path}"

    def count(self, path: str) -> int:
        with self._lock:
            return sum(1 for requested, _ in self.requests if requested == path)

    def headers_for(self, path: str) -> list[dict[str, str]]:
        with self._lock:
            return [headers for requested, headers in self.requests if requested == path]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _delayed(data: bytes, content_type: str = "image/png", delay: float = 0.5):
    def handler(request):
        time.sleep(delay)
        request.send(200, {"Content-Type": content_type}, data)

    return handler


def _pixel(path: Path, point: tuple[int, int] = (0, 0)) -> tuple[int, int, int]:
    with Image.open(path) as image:
        return image.convert("RGB").getpixel(point)


class ImportImagesTests(unittest.TestCase):
    def test_concurrent_downloads_keep_page_order_and_compact_failures(self):
        page = _gallery("/1.png", "/missing.png", "/1.png", "/3.png", "/4.png")
        routes = {
            "/page": _html(page),
            "/1.png": _delayed(_png("red")),
            "/missing.png": (404, {"Content-Type": "text/html"}, b""),
            "/3.png": _delayed(_png("blue")),
            "/4.png": _delayed(_png("green")),
        }
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            updates: list[tuple[int, int, str]] = []
            started = time.monotonic()
            reports = import_images_from_urls(
                [server.url("/page")], Path(tmp), progress=lambda done, total, message: updates.append((done, total, message))
            )
            elapsed = time.monotonic() - started
            report = reports[0]
            self.assertEqual([path.name for path in report.paths], ["page-0001.png", "page-0002.png", "page-0003.png"])
            self.assertTrue(all(path.parent == Path(tmp) / "source-01" for path in report.paths))
            self.assertEqual([_pixel(path) for path in report.paths], [(255, 0, 0), (0, 0, 255), (0, 128, 0)])
            self.assertEqual(server.count("/missing.png"), 1)
            self.assertEqual(server.count("/1.png"), 1)
        self.assertEqual(len(reports), 1)
        self.assertEqual(report.title, "Galeria & Cia")
        self.assertEqual(report.skipped, 1)
        self.assertFalse(report.truncated)
        self.assertIsNone(report.error)
        self.assertEqual(updates[0], (0, 4, PAGE_PROGRESS_MESSAGE))
        self.assertTrue(all(total == 4 for _, total, _ in updates))
        self.assertEqual(max(done for done, _, _ in updates), 4)
        self.assertTrue(all(message == f"Imagem {done} de 4" for done, _, message in updates[1:]))
        # Three images sleep for half a second each; the pool runs them together.
        self.assertLess(elapsed, 1.2)

    def test_failing_url_is_reported_without_aborting_the_others(self):
        routes = {
            "/ok": _html(_gallery("/1.png")),
            "/1.png": _image(_png("red")),
            "/untitled": _html('<img src="/2.png">'),
            "/2.png": _image(_png("blue")),
            "/text": (200, {"Content-Type": "text/plain"}, b"plain text"),
            "/missing": (404, {"Content-Type": "text/html"}, b""),
        }
        urls = ["/ok", "/text", "/missing", "/untitled"]
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            reports = import_images_from_urls([server.url(path) for path in urls], Path(tmp))
            self.assertEqual(reports[3].paths[0].parent.name, "source-04")
        self.assertEqual([report.url for report in reports], [server.url(path) for path in urls])
        self.assertEqual(len(reports[0].paths), 1)
        self.assertEqual(reports[0].paths[0].parent.name, "source-01")
        self.assertIsNone(reports[0].error)
        self.assertEqual((reports[1].paths, reports[1].skipped, reports[1].error), ([], 0, NOT_HTML_MESSAGE))
        self.assertEqual((reports[2].paths, reports[2].skipped), ([], 0))
        self.assertIn("HTTP 404", reports[2].error)
        self.assertEqual(reports[3].title, "127.0.0.1")
        self.assertEqual(len(reports[3].paths), 1)
        self.assertTrue(all(report.title for report in reports))

    def test_all_urls_failing_raises(self):
        routes = {"/text": (200, {"Content-Type": "text/plain"}, b"plain text")}
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as single:
                import_images_from_urls([server.url("/text")], Path(tmp))
            self.assertEqual(str(single.exception), NOT_HTML_MESSAGE)
            with self.assertRaises(ValueError) as several:
                import_images_from_urls([server.url("/text"), server.url("/missing")], Path(tmp))
            self.assertEqual(str(several.exception), ALL_FAILED_MESSAGE)
            with self.assertRaises(ValueError):
                import_images_from_urls([], Path(tmp))

    def test_cancel_raises_promptly_and_cleans_partial_downloads(self):
        sources = [f"/{number}.png" for number in range(1, 9)]
        routes = {"/page": _html(_gallery(*sources))}
        routes.update({source: _delayed(_png("red")) for source in sources})
        cancel = threading.Event()
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            timer = threading.Timer(0.15, cancel.set)
            timer.start()
            started = time.monotonic()
            try:
                with self.assertRaises(ImportCancelled):
                    import_images_from_urls([server.url("/page")], Path(tmp), is_cancelled=cancel.is_set)
            finally:
                timer.cancel()
            elapsed = time.monotonic() - started
            leftovers = list(Path(tmp).rglob("download-*"))
        self.assertLess(elapsed, 1.5)
        self.assertEqual(leftovers, [])

    def test_cancel_before_start_does_not_reach_the_network(self):
        with _Server({"/page": _html(_gallery("/1.png"))}) as server, TemporaryDirectory() as tmp:
            with self.assertRaises(ImportCancelled):
                import_images_from_urls([server.url("/page")], Path(tmp), is_cancelled=lambda: True)
            self.assertEqual(server.requests, [])

    def test_base_href_is_resolved_against_the_final_url_and_images_send_referer(self):
        page = _html(_gallery("pic.png", title="Base", head='<base href="img/">'))
        routes = {
            "/start": (302, {"Location": "/gallery/"}, b""),
            "/gallery/": page,
            "/gallery/img/pic.png": _image(_png("red")),
        }
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            reports = import_images_from_urls([server.url("/start")], Path(tmp))
            image_headers = server.headers_for("/gallery/img/pic.png")
        self.assertEqual(len(reports[0].paths), 1)
        self.assertEqual(reports[0].title, "Base")
        self.assertEqual(len(image_headers), 1)
        self.assertEqual(image_headers[0]["referer"], server.url("/gallery/"))

    def test_empty_html_becomes_a_friendly_error(self):
        routes = {
            "/empty": _html(""),
            "/blank": _html("   \r\n\t "),
            "/garbage": (200, {"Content-Type": "text/html"}, b"\x00\x01\x02 not html"),
        }
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            for path in ("/empty", "/blank", "/garbage"):
                with self.subTest(path=path), self.assertRaises(ValueError) as caught:
                    import_images_from_urls([server.url(path)], Path(tmp) / path.strip("/"))
                self.assertIn("imagem", str(caught.exception))
            with self.assertRaises(ValueError) as empty:
                import_images_from_urls([server.url("/empty")], Path(tmp) / "again")
            self.assertEqual(str(empty.exception), NOT_HTML_MESSAGE)

    def test_decompression_bombs_are_skipped_not_fatal(self):
        routes = {
            "/page": _html(_gallery("/huge.png", "/bomb.png", "/ok.png")),
            "/huge.png": _image(_png_with_dimensions(10000, 10000)),
            "/bomb.png": _image(_png_with_dimensions(30000, 30000)),
            "/ok.png": _image(_png("blue")),
        }
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                reports = import_images_from_urls([server.url("/page")], Path(tmp))
            self.assertEqual(len(reports[0].paths), 1)
            self.assertEqual(_pixel(reports[0].paths[0]), (0, 0, 255))
        self.assertEqual(reports[0].skipped, 2)

    def test_direct_image_url_is_fetched_once_and_keeps_original_bytes(self):
        data = _jpeg()
        updates: list[tuple[int, int, str]] = []
        with _Server({"/photo.jpg": _image(data, "image/jpeg")}) as server, TemporaryDirectory() as tmp:
            reports = import_images_from_urls(
                [server.url("/photo.jpg")],
                Path(tmp),
                progress=lambda done, total, message: updates.append((done, total, message)),
            )
            self.assertEqual(server.count("/photo.jpg"), 1)
            report = reports[0]
            self.assertEqual([path.name for path in report.paths], ["page-0001.jpg"])
            self.assertEqual(report.paths[0].parent.name, "source-01")
            self.assertEqual(report.paths[0].read_bytes(), data)
        self.assertEqual(updates, [(0, 1, IMAGE_PROGRESS_MESSAGE), (1, 1, IMAGE_PROGRESS_MESSAGE)])
        self.assertEqual(report.title, "127.0.0.1/photo.jpg")
        self.assertEqual((report.skipped, report.truncated, report.error), (0, False, None))

    def test_octet_stream_images_are_accepted_by_magic_bytes(self):
        png = _png("green")
        routes = {
            "/page": _html(_gallery("/raw", "/junk", "/probe.png")),
            "/raw": (200, {"Content-Type": "application/octet-stream"}, png),
            "/junk": (200, {"Content-Type": "application/octet-stream"}, b"<html>not an image</html>"),
            "/probe.png": (200, {"Content-Type": "application/octet-stream"}, png),
        }
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            reports = import_images_from_urls([server.url("/page")], Path(tmp))
            self.assertEqual(reports[0].skipped, 1)
            self.assertEqual([path.name for path in reports[0].paths], ["page-0001.png", "page-0002.png"])
            self.assertEqual(server.count("/probe.png"), 1)
        with _Server({"/probe.png": (200, {"Content-Type": "application/octet-stream"}, png)}) as server, TemporaryDirectory() as tmp:
            direct = import_images_from_urls([server.url("/probe.png")], Path(tmp))
            self.assertEqual(server.count("/probe.png"), 1)
        self.assertEqual([path.name for path in direct[0].paths], ["page-0001.png"])

    def test_transient_server_errors_are_retried(self):
        attempts = {"count": 0}

        def flaky(request):
            attempts["count"] += 1
            if attempts["count"] < 3:
                request.send(503, {"Content-Type": "text/html"}, b"")
            else:
                request.send(200, {"Content-Type": "image/png"}, _png("red"))

        routes = {"/page": _html(_gallery("/flaky.png")), "/flaky.png": flaky}
        with patch("conversor.web_images.RETRY_BACKOFF", 0.01):
            with _Server(routes) as server, TemporaryDirectory() as tmp:
                reports = import_images_from_urls([server.url("/page")], Path(tmp))
        self.assertEqual(attempts["count"], 3)
        self.assertEqual(len(reports[0].paths), 1)
        self.assertEqual(reports[0].skipped, 0)

    def test_per_url_deadline_skips_stalled_images_instead_of_hanging(self):
        routes = {
            "/page": _html(_gallery("/fast.png", "/slow.png")),
            "/fast.png": _image(_png("red")),
            "/slow.png": _delayed(_png("blue"), delay=1.0),
        }
        with patch("conversor.web_images.URL_DEADLINE", 0.5):
            with _Server(routes) as server, TemporaryDirectory() as tmp:
                started = time.monotonic()
                report = import_images_from_urls([server.url("/page")], Path(tmp))[0]
                elapsed = time.monotonic() - started
                self.assertEqual(len(report.paths), 1)
        self.assertEqual(report.skipped, 1)
        self.assertLess(elapsed, 2.0)

    def test_unconditional_downloads_are_byte_identical_but_oriented_jpegs_and_cmyk_are_fixed(self):
        plain_jpeg = _jpeg()
        oriented_jpeg = _jpeg(orientation=6)
        mirrored_png = _png("green", exif=_exif_blob(2))
        cmyk = _cmyk_jpeg()
        routes = {
            "/page": _html(_gallery("/plain.jpg", "/oriented.jpg", "/mirrored.png", "/cmyk.jpg")),
            "/plain.jpg": _image(plain_jpeg, "image/jpeg"),
            "/oriented.jpg": _image(oriented_jpeg, "image/jpeg"),
            "/mirrored.png": _image(mirrored_png, "image/png"),
            "/cmyk.jpg": _image(cmyk, "image/jpeg"),
        }
        with _Server(routes) as server, TemporaryDirectory() as tmp:
            report = import_images_from_urls([server.url("/page")], Path(tmp))[0]
            self.assertEqual(report.skipped, 0)
            self.assertEqual(
                [path.name for path in report.paths],
                ["page-0001.jpg", "page-0002.jpg", "page-0003.png", "page-0004.jpg"],
            )
            self.assertEqual(report.paths[0].read_bytes(), plain_jpeg)
            self.assertEqual(report.paths[2].read_bytes(), mirrored_png)
            with Image.open(report.paths[1]) as fixed:
                self.assertEqual(fixed.size, (600, 400))
                self.assertIsNone(fixed.getexif().get(274))
                self.assertEqual(fixed.format, "JPEG")
            with Image.open(report.paths[3]) as fixed:
                self.assertEqual(fixed.mode, "RGB")
                self.assertEqual(fixed.size, (400, 600))

    def test_gallery_stops_at_the_candidate_limit(self):
        routes = {"/page": _html(_gallery("/1.png", "/2.png", "/3.png"))}
        routes.update({f"/{number}.png": _image(_png("red")) for number in (1, 2, 3)})
        with patch("conversor.web_images.MAX_GALLERY_IMAGES", 2):
            with _Server(routes) as server, TemporaryDirectory() as tmp:
                report = import_images_from_urls([server.url("/page")], Path(tmp))[0]
        self.assertTrue(report.truncated)
        self.assertEqual(len(report.paths), 2)


def _exif_blob(orientation: int) -> bytes:
    exif = Image.Exif()
    exif[274] = orientation
    return exif.tobytes()


if __name__ == "__main__":
    unittest.main()
