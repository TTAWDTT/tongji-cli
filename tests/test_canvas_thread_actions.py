import json
import unittest
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.canvas import api as canvas_api
from tongji_cli.common import QueryUnavailable
from tongji_cli.canvas.thread_actions import reply, set_state
from test_canvas_compose import CanvasMail


class ThreadSite(CanvasMail):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/api/v1/conversations/21":
            if parse_qs(url.query).get("auto_mark_as_read") != ["false"]:
                self.server.state = "read"
            return self.reply(200, {"id": 21, "subject": "样例", "workflow_state": self.server.state,
                                    "starred": self.server.star, "audience": self.server.audience,
                                    "messages": self.server.messages})
        if url.path == "/conversations":
            additional = '<input type=hidden name="recipients[]" value="9">' if "9" in self.server.audience else ""
            return self.reply(200, PAGE.replace("ADDITIONAL", additional).replace("STATE", json.dumps(self.server.state))
                              .replace("STAR", json.dumps(self.server.star)), "text/html; charset=utf-8")
        super().do_GET()

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"])).decode()
        if self.path == "/ui/state":
            self.server.state = data
        elif self.path == "/ui/star":
            self.server.star = json.loads(data)
        elif self.path == "/conversations/21/add_message":
            self.server.sent += 1
            form = parse_qs(data)
            self.server.received_by = form["recipients[]"]
            msg = {"id": self.server.post_id, "author_id": 5, "body": form["body"][0]}
            if self.server.post_id != 1:
                self.server.messages.append(msg)
            return self.reply(200, {"id": 21, "messages": [msg]})
        else:
            return self.send_error(404)
        self.reply(200, {})


PAGE = """<meta charset=utf-8><select id=conversation_filter_select>
<option>inbox</option><option>sent</option><option>archived</option></select>
<ul class=messages><li><div id=conversation-checkbox-21></div><span id=title>样例</span>
<button class=star-btn>星</button></li></ul><button id=reply-btn hidden>回复</button>
<button id=reply-all-btn hidden>回复所有人</button><button id=archive-btn hidden>归档</button><button id=admin-btn hidden>设置</button>
<button id=mark hidden></button>
<div class=compose-message-dialog hidden><form class=compose_form action="/conversations/21/add_message">
<input type=hidden name="recipients[]" value="8">ADDITIONAL<textarea name=body></textarea></form>
<button id=send>发送</button></div>
<script>
let state=STATE,star=STAR;
const q=s=>document.querySelector(s),post=(path,body)=>fetch(path,{method:'POST',body});
const render=()=>{q('li').hidden=(q('select').value==='archived')!==(state==='archived');
q('.star-btn').setAttribute('aria-checked',String(star))};
render();q('select').onchange=render;
q('.star-btn').onclick=async()=>{star=!star;await post('/ui/star',String(star));render()};
q('#title').onclick=async()=>{if(state==='unread'){state='read';await post('/ui/state',state)}
for(let id of ['reply','reply-all','archive','admin']) q('#'+id+'-btn').hidden=false};
q('#reply-btn').onclick=()=>q('.compose-message-dialog').hidden=false;
q('#reply-all-btn').onclick=q('#reply-btn').onclick;
q('#send').onclick=()=>post('/conversations/21/add_message',new URLSearchParams(new FormData(q('form'))));
q('#archive-btn').onclick=async()=>{state=state==='archived'?'read':'archived';await post('/ui/state',state);render()};
q('#admin-btn').onclick=()=>{q('#mark').textContent=state==='read'?'标记为未读':'标记为已读';q('#mark').hidden=false};
q('#mark').onclick=async()=>{state=state==='read'?'unread':'read';await post('/ui/state',state);q('#mark').hidden=true};
</script>"""


class ThreadActionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ThreadSite)
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
        self.server.state, self.server.star = "unread", False
        self.server.audience = ["8"]
        self.server.sent, self.server.post_id = 0, 2
        self.server.messages = [{"id": 1, "author_id": 5, "body": "复核"}]
        self.ctx = self.browser.new_context()
        self.p = self.ctx.new_page()
        self.addCleanup(self.ctx.close)

    def test_preview_keeps_unread_and_reply_matches_new_id(self):
        row, = reply(self.ctx, self.p, 21, "复核", True)
        self.assertEqual((row["editor_checked"], self.server.state, self.server.sent), (False, "unread", 0))
        row, = reply(self.ctx, self.p, 21, "复核", False)
        self.assertEqual((row["message_id"], self.server.sent), (2, 1))
        self.server.post_id = 1
        with self.assertRaisesRegex(QueryUnavailable, "回复回执未核实"):
            reply(self.ctx, self.p, 21, "复核", False)
        self.assertEqual(self.server.sent, 2)

    def test_star_preserves_unread_and_transition_between_folders(self):
        def change(state=None, star=None, preview=False):
            row, = set_state(self.ctx, self.p, 21, state, star, preview)
            return row["action"]

        self.assertEqual(change(star="on", preview=True), "preview")
        self.assertFalse(self.server.star)
        self.assertEqual(change(star="on"), "updated")
        self.assertTrue(self.server.star)
        self.assertEqual(self.server.state, "unread")
        self.assertEqual(change(star="on"), "unchanged")
        for state in ["read", "unread", "archived", "unread", "archived", "read"]:
            self.assertEqual(change(state), "updated")
            self.assertEqual(self.server.state, state)

    def test_group_reply_keeps_direct_audience(self):
        self.server.audience = ["8", "9"]
        self.server.state = "read"
        preview, = reply(self.ctx, self.p, 21, "组内回复", True)
        self.assertTrue(preview["editor_checked"])
        self.assertEqual(self.server.sent, 0)
        posted, = reply(self.ctx, self.p, 21, "组内回复", False)
        self.assertEqual((posted["recipient_ids"], self.server.sent), ([8, 9], 1))
        self.assertEqual(self.server.received_by, ["8", "9"])
