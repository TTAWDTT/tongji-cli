import json
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queries
from canvas_inbox import conversation, inbox, recipients


class InboxSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlsplit(self.path)
        params = parse_qs(path.query)
        item = {"id": 9, "subject": "课程提醒", "workflow_state": self.server.current_state,
                "message_count": 1, "starred": True, "last_message_at": "2026-11-26T22:00:00Z"}
        link = None
        if path.path == "/api/v1/courses":
            data = [{"id": 17, "name": "课设", "course_code": "SE"}]
        elif path.path == "/api/v1/search/recipients":
            if params.get("context") != ["course_17"] or params.get("type") != ["user"]:
                self.send_error(400)
                return
            if params.get("search") == ["同学"]:
                data = [{"id": 5, "name": "示例同学", "common_courses": {"17": ["StudentEnrollment"]}}]
            else:
                data = []
        elif path.path == "/api/v1/conversations":
            if params.get("filter[]") != ["course_17"] or params.get("scope") != ["unread"]:
                self.send_error(400)
                return
            if params.get("page") == ["2"]:
                data = [dict(item, id=10)]
            else:
                data = [item]
                link = '</api/v1/conversations?filter%5B%5D=course_17&scope=unread&page=2>; rel="next"'
        elif path.path == "/api/v1/conversations/9":
            if params.get("auto_mark_as_read") != ["false"]:
                self.server.current_state = "read"
            msg = {"id": 3, "author_id": 5, "body": "纯文本 <原样>", "created_at": "2026-11-27T02:00:00Z"}
            data = dict(item, participants=[{"id": 5, "name": "同学"}], messages=[dict(msg,
                        attachments=[{"display_name": "讲义.pdf", "url": "/files/2"}],
                        forwarded_messages=[dict(msg, id=2, author_id=8, body="原消息")])])
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if link:
            self.send_header("Link", link)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


class InboxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), InboxSite)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.client = cls.pw.request.new_context()
        cls.host = patch.object(queries, "CANVAS", f"http://127.0.0.1:{cls.server.server_port}")
        cls.host.start()
        from types import SimpleNamespace
        cls.context = SimpleNamespace(request=cls.client)

    @classmethod
    def tearDownClass(cls):
        cls.host.stop()
        cls.client.dispose()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.server.current_state = "unread"

    def test_scoped_course_list_follows_pagination(self):
        rows = inbox(self.context, "unread", "SE")
        self.assertEqual([r["id"] for r in rows], [9, 10])
        self.assertEqual(rows[0]["updated_at"], "2026-11-27T06:00:00+08:00")

    def test_read_preserves_unread_state_and_message_structure(self):
        row, = conversation(self.context, 9)
        self.assertEqual(self.server.current_state, "unread")
        msg, = row["messages"]
        self.assertEqual((msg["author"], msg["body"]), ("同学", "纯文本 <原样>"))
        self.assertEqual(msg["forwarded"][0]["author_id"], 8)
        self.assertEqual(msg["attachments"], [{"name": "讲义.pdf", "url": "/files/2"}])

    def test_recipient_search_is_course_scoped(self):
        row, = recipients(self.context, "同学", "SE")
        self.assertEqual((row["id"], row["common_courses"]), (5, {"17": ["StudentEnrollment"]}))
        self.assertEqual(recipients(self.context, "无结果", "SE"), [])
