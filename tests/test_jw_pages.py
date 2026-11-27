import unittest
from datetime import date
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from tongji_cli.jw.records import PAGED_QUERIES, append_record_pages, check_withdrawal, enrollment_status, personal_plan, records, TIMETABLE_QUERY
from tongji_cli.common import QueryUnavailable
from tongji_cli.jw.timetable import timetable_range


class SchoolPagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def new_page(self, html):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.route("http://school.test/**", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=html))
        page.goto("http://school.test/")
        return page

    def test_plan_waits_past_summary(self):
        page = self.new_page("""<table><tr><th colspan=2>课程类别</th><th>课程编码</th><th>课程名称</th></tr>
            <tr id=total><td colspan=4>总计</td></tr></table><script>
            setTimeout(()=>total.insertAdjacentHTML('beforebegin','<tr><td colspan=2>必修</td><td>A</td><td>课程甲</td></tr>'),900)
            </script>""")
        row, = personal_plan(page)
        self.assertEqual(row["课程编码"], "A")

    def test_timetable_after_portal_reopens_last_enrollment_page(self):
        page = self.new_page("<button>个人课表</button>")
        page.goto("http://school.test/studentElect")
        html = """<input value="秋季"><div class="el-table"><table class="el-table__header"><tr>
            <th>课程名称</th><th>上课时间</th><th>上课地点</th></tr></table>
            <table class="el-table__body"><tr><td>课设</td><td>星期五 1-2节 [1-16]</td><td>教室</td></tr></table></div>"""
        page.route("**/GraduateStudentTimeTable", lambda r: r.fulfill(content_type="text/html; charset=utf-8", body=html))
        calendar = [{"semesterName": "秋季", "beginDay": "2026-09-07", "endDay": "2027-01-17"}]
        with patch("tongji_cli.jw.timetable.semester_list", return_value=calendar):
            row, = timetable_range(page, [date(2026, 11, 27)])
        self.assertEqual([item["detail"] for item in row["items"]], ["课设"])
        self.assertTrue(row["source"].endswith("/GraduateStudentTimeTable"))

    def test_course_term_picker_waits_for_filter_and_checks_rows(self):
        page = self.new_page("起始页面")
        html = """<div class="el-form-item"><label>学年学期：</label>
          <input value="2026-2027学年第1学期" readonly onclick="picker.hidden=false"></div>
          <div class="el-popover" id="picker" hidden><table class="calendar-table"><tr>
          <td onclick="window.year=this.textContent">2025-2026</td></tr></table>
          <table class="calendar-term-table"><tr><td onclick="pick(this)">第2学期</td></tr></table></div>
          <button onclick="load(true)">筛选</button>
          <div class="el-table"><div class="el-table__header-wrapper"><table><tr>
          <th>课程序号</th><th>课程名称</th><th>上课时间</th></tr></table></div>
          <div class="el-table__body-wrapper"><table><tr><td id="code"></td><td>同名课</td><td>周一</td>
          </tr></table></div></div><script>
          function pick(td){document.querySelector('input').value=year+'学年'+td.textContent;picker.hidden=true}
          async function load(filtered){
            const data=await (await fetch('ROUTE?term='+(filtered?'previous':'current'))).json();
            setTimeout(()=>code.textContent=data.data[0].display,filtered ? 900 : 40)
          }
          load(false)</script>""".replace("ROUTE", TIMETABLE_QUERY)
        page.route("**/GraduateStudentTimeTable", lambda r: r.fulfill(content_type="text/html; charset=utf-8", body=html))
        mismatch = False
        def reply(route):
            code = "OLD" if "previous" in route.request.url else "NOW"
            route.fulfill(json={"code": 200, "data": [{"classCode": code, "courseName": "同名课",
                                                      "display": "NOW" if mismatch else code}]})
        page.route("**" + TIMETABLE_QUERY + "*", reply)
        current, = records(page, "courses", requested_term="2026-2027学年第1学期")
        old, = records(page, "courses", requested_term="2025-2026第2学期")
        self.assertEqual((current["课程序号"], old["课程序号"], old["学期"]), ("NOW", "OLD", "2025-2026学年第2学期"))
        with self.assertRaisesRegex(QueryUnavailable, "未列出"):
            records(page, "courses", requested_term="2030-2031第2学期")
        mismatch = True
        with self.assertRaisesRegex(QueryUnavailable, "不符"):
            records(page, "courses", requested_term="2025-2026第2学期")

    def test_enrollment_waits_for_school_rounds(self):
        page = self.new_page("""<button>选择课程</button><div id=notice></div><script>
            setTimeout(async()=>{await fetch('/api/electionservice/student/getRounds');
            notice.textContent='当前没有对您开放的选课！'},900)</script>""")
        page.route("**/getRounds", lambda route: route.fulfill(json={"code": 200, "data": []}))
        row, = enrollment_status(page)
        self.assertEqual(row["state"], "closed")

    def test_duplicate_first_row_after_next_page(self):
        path = PAGED_QUERIES["requests"]
        page = self.new_page(f"""<div class="el-table"><div class="el-table__header-wrapper"><table>
            <tr><th>课程名称</th></tr></table></div><div class="el-table__body-wrapper"><table>
            <tr><td>相同</td></tr><tr><td id=name2>甲</td></tr></table></div></div>
            <div class="el-pagination"><span>共4条</span><ul class=el-pager><li class=active>1</li></ul>
            <button class=btn-next>下一页</button></div><script>
            document.querySelector('button').onclick=async function(){{
              await fetch('{path}');document.querySelector('.active').textContent='2';
              name2.textContent='乙';this.disabled=true;
            }}</script>""")
        page.route("**" + path, lambda route: route.fulfill(json={"code": "200", "data": {"pageNum": 2}}))
        rows = [{"课程名称": "相同"}, {"课程名称": "甲"}]
        append_record_pages(page, page.locator(".el-table"), rows, "requests")
        self.assertEqual([r["课程名称"] for r in rows], ["相同", "甲", "相同", "乙"])

    def test_verification_uses_class_id_and_semester(self):
        page = self.new_page("首页")
        template = """<div class="el-form-item"><label>学年学期：</label><input value="TERM"></div>
            <div class=el-table><div class=el-table__header-wrapper><table><tr><th>新课程序号</th>
            <th>课程名称</th><th>状态</th><th>上课时间</th></tr></table></div>
            <div class=el-table__body-wrapper><table><tr><td>CODE</td><td>同名课</td>
            <td>已退课</td><td>周一</td></tr></table></div></div>"""
        withdrawal = template.replace("TERM", "秋季").replace("CODE", "A") + f"<script>fetch('{PAGED_QUERIES['withdrawals']}')</script>"
        page.route("**/MidTermWithdrawalCourses", lambda r: r.fulfill(content_type="text/html; charset=utf-8", body=withdrawal))
        page.route("**" + PAGED_QUERIES["withdrawals"], lambda r: r.fulfill(json={"code": 200, "data": {}}))
        term = "秋季"
        page.route("**/GraduateStudentTimeTable", lambda r: r.fulfill(content_type="text/html; charset=utf-8",
                                                                    body=template.replace("TERM", term).replace("CODE", "B")))
        row, = check_withdrawal(page, "A")
        self.assertFalse(row["个人课表列有该课"])
        self.assertEqual(row["退课记录状态"], "已退课")
        term = "春季"
        with self.assertRaisesRegex(QueryUnavailable, "学期不一致"):
            check_withdrawal(page, "A")
