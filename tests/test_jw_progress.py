import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jw_progress import DETAIL, read_detail
from jw_records import watch_query
from queries import QueryUnavailable


class ProgressTest(unittest.TestCase):
    def setUp(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(channel="chrome")
        self.addCleanup(self.pw.stop)
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page()
        self.page.route("http://school.test/**", self.serve)

    def serve(self, route):
        if urlsplit(route.request.url).path == DETAIL:
            n = int(route.request.post_data)
            data = {"teachingProgress":{"id":"7","courseName":"实践课"},
                    "progressContents":{"pageNum_":n,"total_":2,"pageSize_":1,"list":[{"id":str(n)}]}}
            return route.fulfill(json={"code":200,"data":data})
        body = """
          <div class="el-table"><div class="el-table__header-wrapper"><table><tr><th>上课时间</th><th>上课内容</th></tr></table></div>
          <div class="el-table__body-wrapper"><table><tbody></tbody></table></div></div>
          <div class="el-pagination"><div class="el-pagination__jump"><input onkeydown="if(event.key==='Enter') load(+this.value)"></div></div>
          <script>
          async function load(n) {
            await (await fetch('DETAIL',{method:'POST',body:String(n)})).json();
            document.querySelector('.el-table__body-wrapper tbody').innerHTML='<tr><td>第'+n+'周</td><td>教学内容'+n+'</td></tr>';
          }
          load(1);
          </script>""".replace("DETAIL",DETAIL)
        route.fulfill(content_type="text/html; charset=utf-8", body=body)

    def read(self, status, identifier="7"):
        with watch_query(self.page, DETAIL) as first:
            self.page.goto("http://school.test/detail")
        return read_detail(self.page,{"id":identifier,"课程名称":"实践课","显示上课内容":status},first.value)

    def test_two_pages_preserve_order_and_course_visibility(self):
        self.assertEqual(self.read("开放")["授课安排"],
                         [{"上课时间":"第1周","上课内容":"教学内容1"},{"上课时间":"第2周","上课内容":"教学内容2"}])
        self.assertEqual(self.read("不开放")["授课安排"],[{"上课时间":"第1周"},{"上课时间":"第2周"}])

    def test_wrong_class(self):
        with self.assertRaisesRegex(QueryUnavailable,"不一致"):
            self.read("开放","8")
