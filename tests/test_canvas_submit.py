import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from tongji_cli.canvas.submit import submit
from tongji_cli.canvas import api as canvas_api
from tongji_cli.common import QueryUnavailable


class AssignmentSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/courses/1/assignments/2":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if getattr(self.server, "classic", False):
                self.wfile.write("""<button onclick="document.querySelector('#submit_assignment').hidden=false">Start Assignment</button>
                    <div id="submit_assignment" hidden><div id="submit_online_upload_form">
                    <input type="file" multiple><button onclick="fetch('/send',{method:'POST',
                    body:JSON.stringify(Array.from(this.previousElementSibling.files,f=>({
                    display_name:f.name,size:f.size})))})">Submit Assignment</button></div></div>""".encode())
                return
            self.wfile.write("""<button onclick="this.hidden=true;document.querySelector('template').replaceWith(
                document.querySelector('template').content.cloneNode(true))">Start Assignment</button>
                <template><input type="file" multiple><button onclick="fetch('/send',{method:'POST',
                body: JSON.stringify(Array.from(document.querySelector('input').files,f=>({
                display_name:f.name,size:f.size})))})">Submit Assignment</button></template>""".encode())
            return
        resources = {
            "/api/v1/courses": [{"id": 1, "name": "样例课程"}],
            "/api/v1/courses/1/assignments/2": {
                "id": 2, "name": "样例作业", "submission_types": ["online_upload"], "allowed_extensions": ["pdf"],
                "html_url": canvas_api.CANVAS + "/courses/1/assignments/2"
            },
            "/api/v1/courses/1/assignments/2/submissions/self": self.server.receipt,
        }
        if path not in resources:
            self.send_error(404)
            return
        data = resources[path]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_POST(self):
        if self.path != "/send":
            self.send_error(404)
            return
        files = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.receipt = {"attempt": self.server.receipt["attempt"] + 1,
                               "submitted_at": "2026-11-27T00:00:00Z", "submission_type": "online_upload",
                               "attachments": files}
        self.send_response(204)
        self.end_headers()


class SubmissionTest(unittest.TestCase):
    def test_preview_and_submit(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), AssignmentSite) as server, TemporaryDirectory() as tmp:
            server.receipt = {"attempt": 1}
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(canvas_api, "CANVAS", f"http://127.0.0.1:{server.server_port}"), sync_playwright() as pw:
                    browser = pw.chromium.launch(channel="chrome")
                    ctx = browser.new_context()
                    page = ctx.new_page()
                    files = [Path(tmp) / "a.pdf", Path(tmp) / "b.pdf"]
                    for f in files:
                        f.write_bytes(b"example")
                    preview, = submit(ctx, page, "1", 2, files, True)
                    self.assertEqual(preview["action"], "preview")
                    self.assertEqual(server.receipt, {"attempt": 1})
                    sent, = submit(ctx, page, "1", 2, files, False)
                    self.assertEqual(sent["attempt"], 2)
                    self.assertEqual(len(server.receipt["attachments"]), 2)
                    server.classic = True
                    sent, = submit(ctx, page, "1", 2, files, False)
                    self.assertEqual(sent["attempt"], 3)
                    bad = Path(tmp) / "a.txt"
                    bad.write_text("example")
                    with self.assertRaisesRegex(QueryUnavailable, "扩展名"):
                        submit(ctx, page, "1", 2, [bad], True)
                    self.assertEqual(server.receipt["attempt"], 3)
                    browser.close()
            finally:
                server.shutdown()
