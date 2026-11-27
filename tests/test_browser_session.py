import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_session import open_session


class BrowserSessionTest(unittest.TestCase):
    def test_reopening_restores_school_tab_and_session_cookie_once(self):
        with TemporaryDirectory() as tmp, sync_playwright() as pw:
            profile = Path(tmp) / "profile"
            class Site(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<title>School</title>")

                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            url = f"http://127.0.0.1:{server.server_port}/"
            for number in range(3):
                context = open_session(pw, profile)
                try:
                    page, = context.pages
                    if number == 0:
                        page.goto(url)
                        page.evaluate("sessionStorage.setItem('term', 'spring')")
                        context.add_cookies([{"name": "login", "value": "fixture", "url": url, "httpOnly": True}])
                    else:
                        expect(page).to_have_url(url)
                        self.assertEqual(page.evaluate("sessionStorage.getItem('term')"), "spring")
                        self.assertTrue(any(c["name"] == "login" and c["httpOnly"] for c in context.cookies(url)))
                finally:
                    context.close()
