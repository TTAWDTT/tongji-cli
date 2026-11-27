import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from tongji_cli.canvas import api as canvas_api
from tongji_cli.common import QueryUnavailable
from tongji_cli.canvas.submit import matches_submission, submit, submission_text


TYPES = ("online_text_entry", "online_url")
PATH = "/courses/3/assignments/6"
EDITOR = '<iframe id="submission_body_ifr" srcdoc="<body contenteditable=true>"></iframe>'
URL_FIELD = '<input type="hidden" name="submission[url]"><input id="online-url-input">'
BUTTON = '<button type="button" onclick="send(this)">Submit Assignment</button>'
SCRIPT = """
async function send(button) {
  const form = button.closest('section')
  const frame = form.querySelector('iframe')
  const values = frame ? {submission_type:'online_text_entry', body:frame.contentDocument.body.innerHTML}
                       : {submission_type:'online_url', url:form.querySelector('input:not([type=hidden])').value}
  await fetch('/submit', {method:'POST', body: JSON.stringify(values)})
}
"""
CLASSIC = """
<button onclick="document.getElementById('submit_assignment').hidden=false">Start Assignment</button>
<div id="submit_assignment" hidden>
<a href="#submit_online_text_entry_form" onclick="show('online_text_entry')">Text Entry</a>
<a href="#submit_online_url_form" onclick="show('online_url')">Website URL</a>
""" + "".join(f'<section id="submit_{kind}_form" hidden>{field}{BUTTON}</section>'
               for kind, field in zip(TYPES, (EDITOR, URL_FIELD))) + """
</div>
<script>function show(kind) {
  for (const el of document.querySelectorAll('section')) el.hidden = el.id !== 'submit_'+kind+'_form'
}</script>
"""
MODERN = """
<button data-testid="new-attempt-button" onclick="this.remove();document.querySelector('main').hidden=false">
New Attempt</button>
<main hidden><div data-testid="submission-type-selector">
""" + "".join(f'<div data-testid="{kind}"><button onclick="choose(\'{kind}\')">{kind}</button></div>'
               for kind in TYPES) + '</div><section></section></main>' + """
<template id="online_text_entry"><div data-testid="text-editor">
<iframe id="textentry_text_ifr" srcdoc="<body contenteditable=true>"></iframe></div></template>
<template id="online_url"><input data-testid="url-input" type="url"></template>
<script>function choose(kind) {
  document.querySelector('section').replaceChildren(document.getElementById(kind).content.cloneNode(true),
      document.getElementById('button').content.cloneNode(true))
}</script>
""" + '<template id="button">' + BUTTON + '</template>'


class EntrySite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, content_type, body):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == PATH:
            self.server.form_reads += 1
            self.respond("text/html", self.server.layout + "<script>" + SCRIPT + "</script>")
            return
        if path.endswith("/submissions/self") and self.server.pending_reads:
            self.respond("application/json", json.dumps(self.server.pending_reads.pop(0)))
            return
        data = {
            "/api/v1/courses": [{"id": 3, "name": "course"}],
            "/api/v1" + PATH: {"id": 6, "name": "assignment", "submission_types": self.server.types,
                               "html_url": canvas_api.CANVAS + PATH},
            "/api/v1" + PATH + "/submissions/self": self.server.receipt,
        }
        if path not in data:
            self.send_error(404)
            return
        self.respond("application/json", json.dumps(data[path]))

    def do_POST(self):
        if self.path != "/submit":
            self.send_error(404)
            return
        record = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.writes.append(record)
        self.server.receipt = {**record, "attempt": self.server.receipt["attempt"] + 1,
                               "submitted_at": "2026-11-27T00:00:00Z"}
        # A stale attempt with identical contents may be visible immediately after submit.
        self.server.pending_reads.append({**self.server.receipt, "attempt": self.server.receipt["attempt"] - 1})
        self.respond("application/json", "{}")


class EntryTest(unittest.TestCase):
    def test_submission_contents(self):
        text = {"submission_type": "online_text_entry", "body": "if ok:\n    a < b\n\nfinish"}
        receipt = {"submission_type": "online_text_entry",
                   "body": "<p>if ok:</p>\n<p>&nbsp; &nbsp; a &lt; b</p>\n<p><br></p>\n<p>finish</p>"}
        self.assertTrue(matches_submission(receipt, text))
        for wrong in (receipt["body"].replace("&nbsp; ", ""), receipt["body"].replace("<p><br></p>", ""),
                      receipt["body"].replace("a &lt; b", "a &gt; b")):
            self.assertFalse(matches_submission({**receipt, "body": wrong}, text))
        self.assertFalse(matches_submission({**receipt, "submission_type": "online_url"}, text))
        url = {"submission_type": "online_url", "submission_url": "https://example.org/a?draft=2"}
        self.assertFalse(matches_submission({"submission_type": "online_url", "url": "https://example.org/a"}, url))
        self.assertEqual(submission_text("one<div><br></div><div>two</div>"), "one\n\ntwo")

    def test_browser_submit(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), EntrySite) as server:
            server.types = TYPES
            server.receipt = {"attempt": 2}
            server.writes = []
            server.form_reads = 0
            server.pending_reads = []
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(canvas_api, "CANVAS", f"http://127.0.0.1:{server.server_port}"), sync_playwright() as pw:
                    browser = pw.chromium.launch(channel="chrome")
                    context = browser.new_context()
                    page = context.new_page()
                    body = "if ok:\n    answer = 'A<&B'\n\nfinish"
                    url = "https://example.org/path?a=1&b=2#answer"
                    for bad in ({}, {"text": " "}, {"text": "yes", "url": url}, {"url": "file:///tmp/a"}):
                        with self.assertRaises(QueryUnavailable):
                            submit(context, page, "3", 6, [], True, **bad)
                    server.types = ["online_text_entry"]
                    with self.assertRaisesRegex(QueryUnavailable, "未向本人开放"):
                        submit(context, page, "3", 6, None, False, url=url)
                    server.types = TYPES
                    for options in ({"text": body}, {"url": url}):
                        preview, = submit(context, page, "3", 6, None, True, **options)
                        self.assertEqual(preview["action"], "preview")
                    self.assertEqual(server.form_reads, 0)
                    self.assertEqual(server.writes, [])
                    for layout in (CLASSIC, MODERN):
                        server.layout = layout
                        for kind, options in zip(TYPES, ({"text": body}, {"url": url})):
                            previous = len(server.writes)
                            receipt, = submit(context, page, "3", 6, None, False, **options)
                            self.assertEqual(len(server.writes), previous + 1)
                            self.assertEqual(receipt["attempt"], previous + 3)
                            self.assertEqual(receipt["submission_type"], kind)
                            self.assertTrue(matches_submission(server.receipt, receipt))
                    browser.close()
            finally:
                server.shutdown()
