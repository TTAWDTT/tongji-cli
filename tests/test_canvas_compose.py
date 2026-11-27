import json
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.canvas import api as canvas_api
from tongji_cli.canvas.compose import send_message
from tongji_cli.common import QueryUnavailable


class CanvasMail(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, content="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content)
        self.end_headers()
        self.wfile.write((json.dumps(data) if content == "application/json" else data).encode())

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/v1/courses":
            return self.reply(200, [{"id": 4, "course_code": "SE", "name": "课设"}])
        if url.path == "/api/v1/search/recipients" and parse_qs(url.query).get("user_id") == ["8"]:
            return self.reply(200, [{"id": 8, "name": "示例", "common_courses": {"4": []}}])
        if url.path == "/api/v1/users/self/profile":
            return self.reply(200, {"id": 5})
        if url.path == "/conversations":
            html = """<meta charset="utf-8"><div role="dialog"><form class="compose_form">
            <input type="hidden" name="recipients[]" value="RECIPIENT"><input type="hidden" name="context_code" value="course_4">
            <input name="subject"><textarea name="body"></textarea></form><button>发送</button></div>
            <script>document.querySelector('button').onclick=()=>fetch('/api/v1/conversations',{
            method:'POST',body:new URLSearchParams(new FormData(document.querySelector('form')))})</script>"""
            return self.reply(200, html.replace("RECIPIENT", str(self.server.recipient)), "text/html; charset=utf-8")
        if url.path == "/api/v1/conversations/21" and parse_qs(url.query).get("auto_mark_as_read") == ["false"]:
            return self.reply(200, {"id": 21, "subject": "已有会话", "audience": ["8"],
                                    "participants": [{"id": 5}, {"id": 8}, {"id": 10}],
                                    "messages": [{"id": self.server.received_id, "body": self.server.body, "author_id": 5}]})
        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/v1/conversations":
            return self.send_error(404)
        data = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        self.server.sent += 1
        self.server.subject, self.server.body = data["subject"][0], data["body"][0]
        self.reply(201, [{"id": 21, "messages": [{"id": 60}]}])


class ComposeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), CanvasMail)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.host = patch.object(canvas_api, "CANVAS", f"http://127.0.0.1:{cls.server.server_port}")
        cls.host.start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.host.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.server.sent, self.server.received_id, self.server.recipient = 0, 60, 8
        self.ctx = self.browser.new_context()
        self.page = self.ctx.new_page()
        self.addCleanup(self.ctx.close)

    def send(self, preview):
        return send_message(self.ctx, self.page, "SE", 8, "课设", "逐字核对\r\n第二段", preview)[0]

    def test_preview_then_exact_receipt(self):
        self.assertEqual(self.send(True)["action"], "preview")
        self.assertEqual(self.server.sent, 0)
        row = self.send(False)
        self.assertEqual((row["action"], row["id"], row["message_id"], self.server.sent), ("sent", 21, 60, 1))
        self.assertEqual((row["title"], self.server.body), ("已有会话", "逐字核对\n第二段"))

    def test_wrong_address_and_unconfirmed_receipt(self):
        with self.assertRaisesRegex(QueryUnavailable, "只能有一行"):
            send_message(self.ctx, self.page, "SE", 8, "两\n行", "正文", False)
        self.server.recipient = 1
        with self.assertRaisesRegex(QueryUnavailable, "收件人或课程"):
            self.send(False)
        self.assertEqual(self.server.sent, 0)
        self.server.recipient, self.server.received_id = 8, 59
        with self.assertRaisesRegex(QueryUnavailable, "回执未核实"):
            self.send(False)
        self.assertEqual(self.server.sent, 1)
