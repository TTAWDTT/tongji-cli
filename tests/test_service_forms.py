import sys
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import notices
from queries import QueryUnavailable


class FormsTest(unittest.TestCase):
    def test_selected_attachment_downloads_in_popup(self):
        source = "http://school.test/material"
        attachment = {"title": "form.doc", "url": "http://school.test/download"}
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                context = browser.new_context()
                context.route(source, lambda r: r.fulfill(content_type="text/html", body=
                    '<a href="/download" target="_blank">form.doc</a><a href="/other">other.doc</a>'))
                context.route("**/download", lambda r: r.fulfill(content_type="text/html", body=
                    '<script>setTimeout(()=>location.replace("/file"),150)</script>'))
                context.route("**/file", lambda r: r.fulfill(body=b"app form data", headers={
                    "Content-Type": "application/msword", "Content-Disposition": 'attachment; filename="form.doc"'}))
                target = Path(tmp) / "application.doc"
                item = notices.download_form(context, source, attachment, target)
                self.assertEqual((item["bytes"], target.read_bytes()), (13, b"app form data"))
                with self.assertRaisesRegex(QueryUnavailable, "已变动"):
                    notices.download_form(context, source, {**attachment, "title": "missing.doc"}, target)
            finally:
                browser.close()
