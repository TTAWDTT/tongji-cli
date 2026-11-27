import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.jw.schemes import DETAIL, LIST, VIEW, scheme_table, schemes
from tongji_cli.common import QueryUnavailable


class SchemesTest(unittest.TestCase):
    def setUp(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(channel="chrome")
        self.addCleanup(self.pw.stop)
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page()
        self.wrong_id = False
        self.page.route("http://school.test/**", self.serve)
        self.page.goto("http://school.test/")

    def serve(self, route):
        url = urlsplit(route.request.url)
        if url.path == LIST:
            return route.fulfill(json={"code": 200, "data": [{"id": 1, "name": "甲"}, {"id": 2, "name": "乙"}]})
        if url.path == DETAIL:
            title = "说明" if parse_qs(url.query)["cultureId"] == ["1"] else "实践课程"
            body = "甲正文" if title == "说明" else "乙正文"
            return route.fulfill(json={"code": 200, "data": [{"name": title, "contentType": 1, "content": body}]})
        if url.path != VIEW:
            return route.fulfill(body="home")
        html = """
          <input placeholder="请选择培养方案" readonly onclick="document.querySelector('ul').hidden=false">
          <ul class="el-select-dropdown" hidden><li class="el-select-dropdown__item" onclick="load(2)"><span>乙</span></li></ul>
          <div class="scrollBar"><h2></h2><section><h3></h3><p></p></section></div>
          <script>
          async function load(id) {
            const result=await (await fetch('DETAIL?cultureId='+IDENTIFIER)).json();
            const name=id===1?'甲':'乙';
            document.querySelector('input').value=name;
            document.querySelector('ul').hidden=true;
            document.querySelector('h2').textContent=name;
            document.querySelector('h3').textContent='一、'+result.data[0].name;
            document.querySelector('p').textContent=name+'正文';
          }
          fetch('LIST').then(()=>load(1));
          </script>""".replace("DETAIL",DETAIL).replace("LIST",LIST).replace("IDENTIFIER","1" if self.wrong_id else "id")
        route.fulfill(content_type="text/html; charset=utf-8", body=html)

    def test_switch_scheme_and_select_chapter(self):
        listed=schemes(self.page,SimpleNamespace(action="list"))
        self.assertEqual([r["名称"] for r in listed], ["甲","乙"])
        row,=schemes(self.page,SimpleNamespace(action="show", id="2",chapter="实践课程"))
        self.assertEqual(row["章节"], [{"标题":"实践课程","正文":"乙正文","表格":[],"配图":[]}])
        with self.assertRaisesRegex(QueryUnavailable,"没有这个章节"):
            schemes(self.page,SimpleNamespace(action="show",id="1",chapter="实践课程"))

    def test_selected_title_cannot_validate_wrong_response(self):
        self.wrong_id=True
        with self.assertRaisesRegex(QueryUnavailable,"编号"):
            schemes(self.page,SimpleNamespace(action="show",id="2",chapter=None))


    def test_course_table_reads_fixed_column_and_merged_group_once(self):
        self.page.set_content("""
            <div class="el-table">
            <div class="el-table__header-wrapper"><table>
            <tr><th class="is-hidden" rowspan="2"></th><th colspan="2">学期</th></tr>
            <tr><th>一</th><th>二</th></tr></table></div>
            <div class="el-table__body-wrapper"><table>
            <tr><td class="is-hidden"></td><td>2</td><td>4</td></tr></table></div>
            <div class="el-table__fixed-header-wrapper"><table>
            <tr><th rowspan="2">课程名称</th></tr></table></div>
            <div class="el-table__fixed-body-wrapper"><table><tr><td>实践课程</td></tr></table></div>
            </div>""")
        result = scheme_table(self.page.locator(".el-table"))
        self.assertEqual(result["行"], [{"课程名称": "实践课程", "学期 / 一": "2", "学期 / 二": "4"}])
