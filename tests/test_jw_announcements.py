import base64
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jw_announcements import DETAIL, LIST, VIEW, announcements
from queries import QueryUnavailable


PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII="
HTML = """<div class="el-table"><div>信息标题</div><div class="el-table__body-wrapper"><table><tbody></tbody></table></div></div>
<div class="el-pagination"><div class="el-pagination__jump"><input onkeydown="if(event.key==='Enter')load(Number(this.value))"></div></div>
<script>
async function read(path, args) {
    const r = await fetch(path, {method:"POST", body:JSON.stringify(args), headers:{"Content-Type":"application/json"}});
    return (await r.json()).data;
}
async function load(n) {
    const data = await read('LIST', {pageNum_:n});
    document.querySelector("tbody").innerHTML = data.list.map(x=>'<tr><td><button onclick="show('+x.id+')">'+x.title+'</button></td></tr>').join('');
}
async function show(id) {
    const d = await read('DETAIL', {id});
    document.body.insertAdjacentHTML("beforeend", '<div class="el-dialog"><span class="title-span">'+d.title+'</span>'+
        '<div class="info"><div class="info-content">'+d.content+'</div><div class="info-attach"></div></div></div>');
}
load(1);
</script>""".replace("'LIST'", repr(LIST)).replace("'DETAIL'", repr(DETAIL))


class AnnouncementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.rows = [{"id": n, "title": title, "publishTime": "2026-11-22 16:00:00.0"}
                     for n, title in enumerate(("公告", "同名公告", "同名公告 ", "末页考核"), 1)]
        self.details = []
        self.wrong = False
        self.page.route("http://school.test/**", self.serve)
        self.page.goto("http://school.test/")

    def serve(self, route):
        path = urlsplit(route.request.url).path
        if path == VIEW:
            return route.fulfill(content_type="text/html; charset=utf-8", body=HTML)
        if path == LIST:
            n = route.request.post_data_json["pageNum_"]
            data = {"list": self.rows[(n-1)*2:n*2], "pageNum_": n, "pageSize_": 2, "total_": len(self.rows)}
        elif path == DETAIL:
            id = route.request.post_data_json["id"]
            self.details.append(id)
            data = dict(self.rows[(2 if self.wrong else id)-1],
                        content=f'<p>正文{id}</p><a href="/guide">指南</a><img src="data:image/png;base64,{PNG}" alt="配图">')
        else:
            return route.fulfill(body="home")
        route.fulfill(json={"code":200, "data":data})

    def call(self, action, **args):
        return announcements(self.page, SimpleNamespace(action=action, **args))

    def test_all_pages_search_and_exact_identity(self):
        self.assertEqual([r["id"] for r in self.call("list", search="考核")], [4])
        self.assertEqual(self.details, [])
        self.rows[0]["publishTime"] = ""
        self.assertIsNone(self.call("list", search=None)[0]["date"])
        result, = self.call("show", id=3)
        self.assertEqual((result["id"], result["body"], result["date"]), (3, "正文3\n\n指南", "2026-11-22"))
        self.assertEqual(result["links"], [{"title":"指南","url":"http://school.test/guide"}])
        self.assertEqual(result["images"], [{"index":1,"alt":"配图","url":None}])
        self.wrong = True
        with self.assertRaisesRegex(QueryUnavailable, "编号不一致"):
            self.call("show", id=3)

    def test_image_is_original_and_existing_file_is_preserved(self):
        with TemporaryDirectory() as tmp:
            target=Path(tmp)/"poster.png"
            item, = self.call("image", id=3, index=1, output=target)
            self.assertEqual(target.read_bytes(), base64.b64decode(PNG))
            self.assertEqual((item["content_type"],item["bytes"]),("image/png",target.stat().st_size))
            with self.assertRaisesRegex(QueryUnavailable,"新文件名"):
                self.call("image", id=3, index=1, output=target)
            with self.assertRaisesRegex(QueryUnavailable,"图片序号"):
                self.call("image", id=3, index=2, output=Path(tmp)/"missing")

    def test_empty_and_page_with_repeated_id(self):
        self.rows[2] = self.rows[0]
        with self.assertRaisesRegex(QueryUnavailable, "重复"):
            self.call("list", search=None)
        self.rows.clear()
        self.assertEqual(self.call("list", search=None), [])
        with self.assertRaisesRegex(QueryUnavailable, "未找到"):
            self.call("show", id=1)
