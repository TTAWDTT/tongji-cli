import html
import json
import runpy
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright

import queries
from canvas_discussion import reply


TOPIC = "/courses/1/discussion_topics/2"
API = "/api/v1" + TOPIC
MODERN = """
<button data-testid="discussion-topic-reply" onclick="openBox(null)">Reply</button>
<div data-entry-wrapper-id="5">
  <div data-entry-wrapper-id="6"><button data-testid="threading-toolbar-reply" onclick="openBox(6)">Reply</button></div>
  <button data-testid="threading-toolbar-reply" onclick="openBox(5)">Reply</button>
</div>
<div data-testid="DiscussionEdit-container" hidden>
  <iframe srcdoc='<body contenteditable="true"></body>'></iframe>
  <button data-testid="DiscussionEdit-submit" onclick="post()">Post</button>
</div>
<script>
let parentId;
function openBox(id) { parentId=id; document.querySelector('[hidden]').hidden=false; }
function post() { fetch('/api/graphql',{method:'POST',body:JSON.stringify({
operationName:'CreateDiscussionEntry', parentId, message: document.querySelector('iframe').contentDocument.body.innerText})}); }
</script>"""
CLASSIC = """
<div class="discussion-entry-reply-area"><button data-event="addReply" onclick="document.querySelector('form').hidden=false">Reply</button></div>
<div class="discussion-entry-reply-area"><form class="discussion-reply-form" hidden
onsubmit="event.preventDefault();fetch('/api/v1/courses/1/discussion_topics/2/entries',{
method:'POST',body:JSON.stringify({parentId:null,message:this.querySelector('textarea').value})})">
<textarea id="root_reply_message_for_2"></textarea><button type="submit">Post</button></form></div>"""


class DiscussionSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, data):
        document = isinstance(data, str)
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if document else "application/json")
        self.end_headers()
        self.wfile.write((data if document else json.dumps(data)).encode())

    def do_GET(self):
        path = urlsplit(self.path).path
        group_topic = TOPIC.replace("/courses/1/", "/groups/9/")
        group_api = "/api/v1" + group_topic
        if path == "/groups":
            self.respond('<main id="content"><h2>Previous Groups</h2><table id="current_groups_table">'
                         '<tr><td><a href="/groups/9">Team</a></td><td>Course</td><td>Term</td></tr></table></main>')
        elif path == "/groups/9/discussion_topics":
            self.respond('<main id="content"><a href="/groups/9/discussion_topics/new">Discussion</a></main>')
        elif path == "/groups/9/discussion_topics/new":
            self.respond("""<main id="content"><form onsubmit="event.preventDefault();fetch(
            '/api/v1/groups/9/discussion_topics',{method:'POST',body:JSON.stringify({
            title:this.querySelector('input').value,message:this.querySelector('iframe').contentDocument.body.innerText})})">
            <input name="title"><iframe id="message_ifr" srcdoc='<body contenteditable="true"></body>'></iframe>
            <button type="submit">Save</button></form></main>""")
        elif path == "/api/v1/groups/9/discussion_topics/20":
            topic = self.server.created_topic
            self.respond(dict(topic, title="other topic") if self.server.bad_receipt else topic)
        elif path in (TOPIC, group_topic):
            self.respond(self.server.page)
        elif path == "/api/v1/courses":
            self.respond([{"id": 1, "name": "test"}])
        elif path == "/api/v1/groups/9/discussion_topics":
            self.respond([{"id": 2, "title": "Team topic", "html_url": group_topic}])
        elif path in (API, group_api):
            self.respond({"id": 2, "title": "test topic", "html_url": group_topic if path == group_api else TOPIC,
                          "message": "<p>Topic body</p>", "locked_for_user": self.server.locked,
                          "anonymous_state": self.server.anonymity, "user_can_see_posts": True})
        elif path in (API + "/view", group_api + "/view"):
            entries = [{"id": 5, "message": "initial", "replies": [{"id": 6, "message": "child"}]}]
            self.respond({"view": entries, "new_entries": self.server.posts})
        else:
            self.send_error(404)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/v1/groups/9/discussion_topics":
            self.server.created_topic = {"id": 20, "title": data["title"], "published": False,
                "message": html.escape(data["message"]).replace("\n", "<br>"),
                "html_url": queries.CANVAS + "/groups/9/discussion_topics/20"}
            self.respond(self.server.created_topic)
            return
        entry_id = 10 + len(self.server.posts)
        self.server.posts.append({"id": entry_id, "parent_id": data["parentId"],
                                 "message": html.escape(data["message"]).replace("\n", "<br>")})
        if self.server.bad_receipt:
            entry_id += 1000
        if self.path == "/api/graphql":
            self.respond({"data": {"createDiscussionEntry": {"discussionEntry": {"_id": str(entry_id)}}}})
        elif self.path in (API + "/entries", "/api/v1/groups/9/discussion_topics/2/entries"):
            self.respond({"id": entry_id})
        else:
            self.send_error(404)


class ReplyTest(unittest.TestCase):
    def test_group_discussion_cli_list_detail_preview_and_receipt(self):
        app = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tongji"))
        with ThreadingHTTPServer(("127.0.0.1", 0), DiscussionSite) as server:
            server.posts = []
            server.locked = server.bad_receipt = False
            server.anonymity = None
            server.page = CLASSIC.replace("/courses/1/", "/groups/9/")
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(queries, "CANVAS", f"http://127.0.0.1:{server.server_port}"), sync_playwright() as pw:
                    browser = pw.chromium.launch(channel="chrome")
                    page = browser.new_page()
                    def cli(*args):
                        with patch.object(sys, "argv", ["tongji", "canvas", *args, "--group", "9"]):
                            parsed = app["arguments"]()
                        return app["site_items"](parsed, "canvas", page.context, page, datetime.now())
                    topic, = cli("discussions")
                    self.assertEqual((topic["id"], topic["group_id"]), (2, 9))
                    self.assertNotIn("course_id", topic)
                    detail, = cli("discussion", "show", "2", "--replies")
                    self.assertEqual((detail["body"], detail["replies"][1]["parent_id"]), ("Topic body", 5))
                    with self.assertRaisesRegex(queries.QueryUnavailable, "可进入小组"):
                        cli("discussions", "--state", "completed")
                    posting = ("discussion", "reply", "2", "--message", "group note")
                    preview, = cli(*posting, "--preview")
                    self.assertEqual((preview["action"], preview["group_id"], server.posts), ("preview", 9, []))
                    receipt, = cli(*posting)
                    self.assertEqual((receipt["action"], receipt["body"], receipt["group_id"]), ("posted", "group note", 9))
                    server.page = MODERN
                    nested, = cli(*posting, "--parent", "5")
                    self.assertEqual((nested["parent_id"], nested["id"], len(server.posts)), (5, 11, 2))
                    new_topic = ("discussion", "create", "--title", "New topic", "--message", "one < two\nsecond")
                    preview, = cli(*new_topic, "--preview")
                    self.assertEqual(preview["action"], "preview")
                    self.assertFalse(hasattr(server, "created_topic"))
                    created, = cli(*new_topic)
                    self.assertEqual((created["action"], created["id"], created["group_id"], created["published"]),
                                     ("created", 20, 9, False))
                    server.bad_receipt = True
                    with self.assertRaisesRegex(queries.QueryUnavailable, "保存回执未核实"):
                        cli(*new_topic)
                    browser.close()
            finally:
                server.shutdown()

    def test_browser_preview_creation_and_receipts(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), DiscussionSite) as server:
            server.posts = []
            server.locked = server.bad_receipt = False
            server.anonymity = None
            server.page = MODERN
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(queries, "CANVAS", f"http://127.0.0.1:{server.server_port}"), sync_playwright() as pw:
                    browser = pw.chromium.launch(channel="chrome")
                    ctx = browser.new_context()
                    page = ctx.new_page()
                    message = "one < two & three\nsecond"
                    def send(parent=None, preview=False):
                        return reply(ctx, page, "1", 2, parent, message, preview)[0]
                    self.assertEqual(send(preview=True)["action"], "preview")
                    with self.assertRaisesRegex(queries.QueryUnavailable, "未找到"):
                        send(99)
                    self.assertEqual(server.posts, [])
                    self.assertEqual(send()["id"], 10)
                    self.assertEqual(send(5)["parent_id"], 5)
                    self.assertEqual(server.posts[-1]["parent_id"], 5)
                    server.page = CLASSIC
                    self.assertEqual(send()["id"], 12)
                    server.bad_receipt = True
                    with self.assertRaisesRegex(queries.QueryUnavailable, "回执未核实"):
                        send()
                    server.locked = True
                    with self.assertRaisesRegex(queries.QueryUnavailable, "未开放"):
                        send()
                    server.locked = False
                    server.anonymity = "full_anonymity"
                    with self.assertRaisesRegex(queries.QueryUnavailable, "匿名讨论"):
                        send()
                    self.assertEqual(len(server.posts), 4)
                    browser.close()
            finally:
                server.shutdown()
