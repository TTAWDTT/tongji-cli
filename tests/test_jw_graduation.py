import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jw_graduation import DEFENSE_LIST, DEFENSE_VIEW, TASK_LIST, TASK_VIEW, defenses, task_books
from queries import QueryUnavailable


class GraduationTest(unittest.TestCase):
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
        self.page.route("http://school.test/**", self.serve)
        self.page.goto("http://school.test/")
        self.empty = False
        self.wrong = False

    def serve(self, route):
        path = urlsplit(route.request.url).path
        if path == DEFENSE_LIST:
            data = [] if self.empty else [{"title":"系统设计","time":"","room":"A101"}]
            return route.fulfill(json={"code":403 if self.wrong else 200,"data":data})
        if path == TASK_LIST:
            n = route.request.post_data_json["pageNum_"]
            rows = [] if self.empty else [{"title":f"课题{n}","state":"已通过"}]
            return route.fulfill(json={"code":200, "data":{"total":0 if self.empty else 2, "pageSize":1,
                 "pageNum":0 if self.empty else (1 if self.wrong else n), "pages":0 if self.empty else 2,"list":rows}})
        if path not in (DEFENSE_VIEW, TASK_VIEW):
            return route.fulfill(body="home")
        defense = path == DEFENSE_VIEW
        labels = ["课题名称","答辩时间","答辩地点"] if defense else ["课题名称","课题性质","状态"]
        html = """
          <div class="el-table"><div class="el-table__header-wrapper"><table><tr>HEADERS</tr></table></div>
          <div class="el-table__body-wrapper"><table><tbody></tbody></table></div>
          <span class="el-table__empty-text" hidden>暂无数据</span></div>
          <div class="el-pagination"><div class="el-pagination__jump"><input onkeydown="if(event.key==='Enter') load(+this.value)"></div></div>
          <script>
          const defense=DEFENSE;
          async function load(n) {
            const payload={pageNum_:n,condition:{}};
            const res=await fetch(SOURCE,defense?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
            const {data}=await res.json(), rows=defense?data:data.list;
            document.querySelector('.el-table__body-wrapper tbody').innerHTML=rows.map(r=>'<tr><td>'+r.title
                +'</td><td>'+(defense?r.time:'设计')+'</td><td>'+(defense?r.room:r.state)+'</td></tr>').join('');
            document.querySelector('.el-table__empty-text').hidden=rows.length>0;
          }
          load(1);
          </script>"""
        html = html.replace("HEADERS","".join(f"<th>{label}</th>" for label in labels))
        html = html.replace("DEFENSE",json.dumps(defense)).replace("SOURCE",json.dumps(DEFENSE_LIST if defense else TASK_LIST))
        route.fulfill(content_type="text/html; charset=utf-8", body=html)

    def tasks(self, number):
        return task_books(self.page, SimpleNamespace(page=number, year=None, state=None, advisor=None, title=None))

    def test_defense_keeps_missing_time_and_permission_error(self):
        item, = defenses(self.page)
        self.assertEqual((item["课题名称"],item["答辩时间"],item["答辩地点"]),("系统设计",None,"A101"))
        self.empty = True
        self.assertEqual(defenses(self.page), [])
        self.wrong = True
        with self.assertRaises(QueryUnavailable):
            defenses(self.page)

    def test_task_pages_and_official_zero_page(self):
        result = self.tasks(2)
        self.assertEqual((result["page"],result["pages"],result["total"]),(2,2,2))
        self.assertEqual(result["items"][0]["课题名称"],"课题2")
        self.wrong = True
        with self.assertRaisesRegex(QueryUnavailable, "返回页"):
            self.tasks(2)
        self.empty = True
        self.assertEqual(self.tasks(1),{"detail":"教务目录中没有符合条件的任务书",
                                        "page":1,"pages":0,"total":0,"items":[]})
        with self.assertRaisesRegex(QueryUnavailable, "共 0 页"):
            self.tasks(2)
