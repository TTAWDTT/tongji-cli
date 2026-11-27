import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

from playwright.sync_api import sync_playwright

from tongji_cli.media import export as media_export
from tongji_cli.common import QueryUnavailable


class ExportSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        server = self.server
        headers = {}
        if url.path == "/room":
            content = ROOM.encode()
            mime = "text/html; charset=utf-8"
        elif url.path == media_export.EXPORT_PATH + "export-async":
            server.created += 1
            content, mime = self.json({"code": 0, "msg": "文件生成中"})
        elif url.path == media_export.EXPORT_PATH + "get-courseware-status":
            query = parse_qs(url.query)
            if query.get("sub_id") != ["123"] or query.get("type") != [server.parts]:
                return self.send_error(400)
            server.checks += 1
            if server.mode == "empty":
                payload = {"code": 5045, "msg": "导出失败,暂无课件内容"}
            elif server.mode == "fresh" and server.checks < 3:
                payload = {"code": 200, "msg": "导出中"} if server.created else {"code": 1, "msg": "未找到下载记录"}
            else:
                payload = {"code": 0, "msg": "课件生成成功",
                           "data": {"path_name": "/file", "file_name": server.filename}}
            content, mime = self.json(payload)
        elif url.path == "/file":
            content, mime = server.content, "application/octet-stream"
            headers["Content-Disposition"] = 'attachment; filename="' + server.filename + '"'
            server.downloads += 1
        else:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    @staticmethod
    def json(data):
        return json.dumps(data).encode(), "application/json"


ROOM = """
<span class="course_name">示例课 第1节</span><button onclick="panel.hidden=false">导出课件</button>
<div class="el-dialog" id="panel" hidden>
<label><input type="checkbox" value="1" checked>PPT课件</label>
<label><input type="checkbox" value="2">语音识别-原文</label>
<label><input type="checkbox" value="3">语音识别-译文</label>
<button id="confirm">确认导出 (PPT)</button>
</div>
<script>
function parts() {return Array.from(panel.querySelectorAll(':checked'),e=>e.value).join(',')}
panel.onchange=()=>confirmButton.textContent='确认导出 ('+(parts()==='1'?'PPT':'Word')+')'
const confirmButton=document.querySelector('#confirm');
confirmButton.onclick=async()=>{
  const q='?sub_id=123&type='+parts();
  const base='/courseapi/v2/export/';
  const r=await (await fetch(base+'get-courseware-status'+q)).json();
  if(r.code===1)await fetch(base+'export-async'+q);
  if(r.code===0){const a=document.createElement('a');a.href=r.data.path_name;
      a.download=r.data.file_name;document.body.append(a);a.click();a.remove();}
};
</script>"""


class ExportTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ExportSite)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.server.created = self.server.checks = self.server.downloads = 0
        self.server.mode, self.server.parts, self.server.filename = "cached", "1", "school.pptx"
        self.server.content = self.package("ppt/presentation.xml")
        row = {"id":"123", "title":"第1节", "course":"示例课",
               "url":f"http://127.0.0.1:{self.server.server_port}/room"}
        source = patch.object(media_export, "sessions", return_value=[row])
        source.start()
        self.addCleanup(source.stop)
        self.dest = Path(self.tmp.name) / "document"
        self.args = SimpleNamespace(id=123, course="示例课", include=None, output=self.dest)

    @staticmethod
    def package(member):
        result = io.BytesIO()
        with ZipFile(result, "w") as z:
            z.writestr(member, "<document/>")
        return result.getvalue()

    def test_cached_download_and_existing_path(self):
        result, = media_export.export_courseware(self.page, self.args)
        self.assertEqual(self.dest.read_bytes(), self.server.content)
        self.assertEqual((result["filename"], self.server.created, self.server.downloads), ("school.pptx",0,1))
        with self.assertRaisesRegex(QueryUnavailable, "新文件"):
            media_export.export_courseware(self.page, self.args)

    def test_generation_submitted_once_and_polled_before_saving_word(self):
        self.server.mode, self.server.parts, self.server.filename = "fresh", "2,3", "speech.docx"
        self.server.content = self.package("word/document.xml")
        self.args.include = ["transcript","translation"]
        result, = media_export.export_courseware(self.page, self.args)
        self.assertEqual(result["included"], ["语音识别-原文","语音识别-译文"])
        self.assertEqual((self.server.created,self.server.checks,self.server.downloads), (1,3,1))
        self.assertEqual(self.dest.read_bytes(),self.server.content)

    def test_unavailable_and_wrong_file_do_not_create_target(self):
        self.server.mode = "empty"
        with self.assertRaisesRegex(QueryUnavailable,"暂无课件内容"):
            media_export.export_courseware(self.page,self.args)
        self.assertFalse(self.dest.exists())
        self.server.mode, self.server.content = "cached", b"<html>login</html>"
        with self.assertRaisesRegex(QueryUnavailable,"文档格式不符"):
            media_export.export_courseware(self.page,self.args)
        self.assertFalse(self.dest.exists())
