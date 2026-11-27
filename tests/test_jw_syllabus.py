import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jw_syllabus import CALENDARS, CATALOG, LIST, DETAIL, syllabus
from queries import QueryUnavailable


HTML = """<div class="el-form-item"><label>学年学期：</label><input id="term" value="2026-2027学年第1学期" onclick="picker.hidden=false"></div>
<div class="el-popover" id="picker" hidden><div class="calendar-table"><b>2025-2026</b></div>
<div class="calendar-term-table"><b onclick="term.value='2025-2026学年第2学期';picker.hidden=true;calendar=121">第2学期</b></div></div>
<button onclick="load(1)">筛选</button>
<input id="search" placeholder="请输入课程编码、代码、课程名称搜索" onkeydown="if(event.key==='Enter')load(1)">
<div class="el-table"><b>课程编码</b><div class="el-table__body-wrapper"><table><tbody></tbody></table></div></div>
<div class="el-pagination"><label class="el-pagination__jump"><input onkeydown="if(event.key==='Enter')load(+this.value)"></label></div>
<div id="shown"></div><script>
let calendar=122;
fetch('CALENDARS');
async function load(n,course=document.querySelector('#search').value){
 const payload={pageNum_:n,condition:{calendarId:calendar,course}};
 const r=await fetch('LIST',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
 const rows=(await r.json()).data.list;
 document.querySelector('tbody').innerHTML=rows.map(r=>'<tr><td>'+r.newCode+'</td><td>'+r.name+
  '</td><td><button onclick="show('+r.id+')">查看</button></td></tr>').join('')
}
async function show(id){
 const r=await fetch('DETAIL?id='+id);const d=(await r.json()).data;
 document.querySelector('#shown').innerHTML='<div class="practiceTable">课程教学大纲 '+d.name+'</div>'+
 '<ul class="chapterBox"><li class="chapter"><h1>考核</h1><table><tr><td>期末报告</td><td>40%</td></tr></table></li></ul>'
}
load(1)</script>""".replace("'CALENDARS'",repr(CALENDARS)).replace("'LIST'",repr(LIST)).replace("'DETAIL?id='",repr(DETAIL+"?id="))


class SyllabusTest(unittest.TestCase):
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
        self.rows = [{"id": n, "newCode": code, "code": str(300 + n), "name": "样例课" + str(n), "credits": 0}
                     for n, code in [(1, "C1"), (2, "C2"), (3, "C2")]]
        self.wrong_detail = False
        self.html = HTML
        self.page.route("http://school.test/**", self.serve)
        self.page.goto("http://school.test/")

    def serve(self, route):
        from urllib.parse import urlsplit, parse_qs
        url = urlsplit(route.request.url)
        if url.path == CATALOG:
            return route.fulfill(content_type="text/html; charset=utf-8", body=self.html)
        if url.path == CALENDARS:
            return route.fulfill(json={"code":200, "data":[{"year":2026,"term":1,"id":122},{"year":2025,"term":2,"id":121}]})
        if url.path == LIST:
            args = route.request.post_data_json
            n, term = args["pageNum_"], args["condition"]["course"]
            rows = [r for r in self.rows if any(term in r[k] for k in ("code", "newCode", "name"))]
            data = {"list": [dict(r, calendarId=args["condition"]["calendarId"]) for r in rows[n-1:n]], "pageNum_": n, "pageSize_": 1, "total_": len(rows)}
        elif url.path == DETAIL:
            index = int(parse_qs(url.query)["id"][0]) - 1
            data = dict(self.rows[0 if self.wrong_detail else index], chapters=[{"chapterName":"考核"}])
        else:
            return route.fulfill(body="home")
        route.fulfill(json={"code":200, "data":data})

    def call(self, action, keyword="", page=1, id=None, term=None):
        return syllabus(self.page, SimpleNamespace(action=action, keyword=keyword, page=page, id=id, term=term))

    def test_search_page_and_empty(self):
        result = self.call("search", "C2", page=2)
        self.assertEqual((result["total"],result["pages"],result["items"][0]["syllabus_id"]),(2,2,"3"))
        self.assertEqual(result["items"][0]["学分"], 0)
        self.assertEqual(self.call("search","缺课")["items"],[])
        with self.assertRaisesRegex(QueryUnavailable,"核对页码"):
            self.call("search","C1",page=2)

    def test_semester_comes_from_school_calendar_and_actual_filter(self):
        past = "2025-2026第2学期"
        result = self.call("search", "C2", page=2, term=past)
        self.assertEqual(result["items"][0]["学期"], "2025-2026学年第2学期")
        self.html = HTML.replace("calendarId:calendar", "calendarId:122")
        with self.assertRaisesRegex(QueryUnavailable, "所选学期"):
            self.call("search", "缺课", term=past)

    def test_term_refresh_with_empty_keyword_before_filtered_result(self):
        self.html = HTML.replace("if(event.key==='Enter')load(1)", "if(event.key==='Enter')load(1,'').then(()=>load(1))")
        row, = self.call("show", "C1", term="2025-2026第2学期")
        self.assertEqual(row["syllabus_id"], "1")

    def test_nested_chapter_and_wrong_rendered_heading(self):
        self.html = HTML.replace("<h1>考核</h1>", '<h1>2. 考核</h1><ul class="chapterBox"><li class="chapter"><h2>2.1 报告</h2></li></ul>')
        row, = self.call("show", "C1")
        self.assertEqual(len(row["章节"]), 1)
        self.assertIn("2.1 报告", row["章节"][0]["body"])
        self.html = HTML.replace("<h1>考核</h1>", "<h1>教材</h1>")
        with self.assertRaisesRegex(QueryUnavailable, "章节"):
            self.call("show", "C1")

    def test_course_template_basic_info_without_practice_table(self):
        self.html = HTML.replace('<div class="practiceTable">课程教学大纲 ', '<div class="detail-container2"><div class="el-card__body"><section><div class="big-title">1.模板基础信息</div>课程名称 ').replace("d.name+'</div>'", "d.name+'</section></div></div>'")
        row, = self.call("show", "C1")
        self.assertIn("课程名称 样例课1", row["基本信息"])
        self.assertNotIn("期末报告", row["基本信息"])

    def test_choose_one_of_two_matching_outlines_and_verify_body(self):
        with self.assertRaisesRegex(QueryUnavailable,"唯一"):
            self.call("show","C2")
        row, = self.call("show","C2",id="3")
        self.assertEqual(row["章节"],[{"title":"考核","body":"期末报告\t40%"}])
        self.assertEqual(row["课程代码"], "303")
        self.wrong_detail = True
        with self.assertRaisesRegex(QueryUnavailable,"不一致"):
            self.call("show","302")
