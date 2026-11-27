import json
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from tongji_cli.canvas import api as canvas_api
from tongji_cli.common import QueryUnavailable
from tongji_cli.canvas.notifications import notification_settings


class SettingsSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/profile/communication":
            body = """<table><thead><tr><th>类别</th><th>Email<br>a@example.test</th>
                <th>Email<br>b@example.test</th></tr></thead><tbody><tr data-testid="due_date">
                <th>截止时间</th><td><button disabled>每周摘要</button></td>
                <td><button onclick="document.querySelector('[role=menuitem]').hidden=false">每周摘要</button></td>
                </tr></tbody></table><button role="menuitem" hidden onclick="fetch('/change',{method:'POST'})">每日摘要</button>"""
            mime = "text/html; charset=utf-8"
        elif path == "/api/v1/users/self/communication_channels":
            body = json.dumps([{"id": 1, "type": "email", "workflow_state": "active", "address": "b@example.test"}])
            mime = "application/json"
        elif path == "/api/v1/users/self/communication_channels/1/notification_preferences":
            body = json.dumps({"notification_preferences": [
                {"notification": event, "frequency": self.server.frequency, "category": "Due Date"}
                for event in ("new_event", "updated_event")]})
            mime = "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_POST(self):
        if self.path != "/change":
            self.send_error(404)
            return
        self.server.writes += 1
        self.server.frequency = "daily"
        self.send_response(204)
        self.end_headers()


class NotificationTest(unittest.TestCase):
    def test_preview_update_readback_and_repeat(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), SettingsSite)
        server.frequency = "weekly"
        server.writes = 0
        Thread(target=server.serve_forever, daemon=True).start()
        try:
            with patch.object(canvas_api, "CANVAS", f"http://127.0.0.1:{server.server_port}"), sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome")
                page = browser.new_page()
                args = SimpleNamespace(operation="notification", category="due_date", channel=1,
                                       frequency="daily", preview=True)
                result, = notification_settings(page.context, page, args)
                self.assertEqual((result["action"], result["notifications"], server.writes), ("preview", 2, 0))
                args.preview = False
                args.category = ""
                with self.assertRaisesRegex(QueryUnavailable, "没有此通知类别"):
                    notification_settings(page.context, page, args)
                self.assertEqual(server.writes, 0)
                args.category = "due_date"
                result, = notification_settings(page.context, page, args)
                self.assertEqual((result["action"], server.frequency, server.writes), ("updated", "daily", 1))
                result, = notification_settings(page.context, page, args)
                self.assertEqual((result["action"], server.writes), ("unchanged", 1))
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
