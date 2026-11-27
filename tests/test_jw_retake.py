import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jw_retake import retakes
from queries import QueryUnavailable


APP = """<!doctype html><meta charset=utf-8>
<div class=float-right><button id=apply>申请</button></div>
<div class=el-table><div class=el-table__header-wrapper><table><tr>
<th></th><th>序号</th><th>学期</th><th>新课程序号</th><th>课程序号</th><th>课程名称</th>
<th>成绩</th><th>重考性质</th><th>申请状态</th><th>申请时间</th><th>备注</th><th>操作</th>
</tr></table></div><div class=el-table__body-wrapper><table><tbody id=rows></tbody></table>
<div class=el-table__empty-text hidden>暂无数据</div></div></div>
<div class=el-pagination><span class=el-pagination__total></span><button class=btn-prev>上页</button>
<ul class=el-pager><li class=active></li></ul><button class=btn-next>下页</button></div>
<div class=el-message-box hidden><div id=notice></div><button id=confirm>确定</button></div>
<script>
let number = 1;
const one = q => document.querySelector(q);
async function load(){
 const res=await fetch('/api/electionservice/undergraduateExamReexam/getStudentReExamCourseListPage?p='+number);
 const body=await res.json();
 if(!res.ok) {
    notice.textContent=body.message; one('.el-message-box').hidden=false; return;
 }
 if(body.code!==200) return;
 const {items=[],total=0} = body.data || {};
 one('.active').textContent=number;
 one('.el-pagination__total').textContent='共 '+total+' 条';
 one('.btn-next').disabled=number>=total;
 one('.btn-prev').disabled=number===1;
 rows.replaceChildren();
 for(const course of items) {
   const row=rows.insertRow();
   row.insertCell().innerHTML='<label class="el-checkbox"><input type=checkbox></label>';
   for(const v of [number, '第一学期', course.code,'A','课程甲',55,'重考',course.status,
                   course.time,'','']) row.insertCell().textContent=v;
 }
 one('.el-table__empty-text').hidden=items.length>0;
}
one('.btn-next').onclick=()=>{number++;load()};
one('.btn-prev').onclick=()=>{number--;load()};
async function submit(){
 const code=one('input:checked').closest('tr').cells[3].textContent;
 await fetch('/fixture-submission',{method:'POST',body:code});
 one('.el-message-box').hidden=true;
 await load();
}
apply.onclick=async()=>{
 if(FIXTURE_CONFIRM){notice.textContent='是否确认申请重考？'; one('.el-message-box').hidden=false;}
 else await submit();
};
one('#confirm').onclick=submit;
fetch('/api/electionservice/underGraduateExamSwitch/getExamCalendar');load();
</script>"""


class RetakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def site(self, codes=("A", "AB"), confirm=True, error=None, changed_code=None):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        self.writes = []
        courses = [{"code": code, "status": "未申请", "time": ""} for code in codes]

        def handle(route):
            url = urlsplit(route.request.url)
            if url.path.endswith("getExamCalendar"):
                route.fulfill(json={"code": 200, "data": {"isOpen": 1, "startTime": None, "endTime": None,
                                                         "calendarIdI18n": "第一学期"}})
            elif url.path.endswith("getStudentReExamCourseListPage"):
                if error:
                    status, body = error
                    route.fulfill(status=status, json=body)
                else:
                    number = int(parse_qs(url.query)["p"][0])
                    route.fulfill(json={"code": 200, "data": {"total": len(courses), "items": courses[number-1:number]}})
            elif url.path == "/fixture-submission":
                code = route.request.post_data
                self.writes.append(code)
                for course in courses:
                    if course["code"] == (changed_code or code):
                        course.update(status="已申请", time="2026-11-27 12:00")
                route.fulfill(json={"ok": True})
            elif url.path == "/applyMakeupExam":
                route.fulfill(content_type="text/html; charset=utf-8", body=APP.replace("FIXTURE_CONFIRM", json.dumps(confirm)))
            elif url.path == "/traningPlanMy":
                route.fulfill(content_type="text/html; charset=utf-8", body='<li class="el-menu-item"><a href="/applyMakeupExam?t=123">申请重考</a></li>')
            else:
                route.fulfill(content_type="text/html", body="workbench")

        page.route("http://school.test/**", handle)
        page.goto("http://school.test/workbench")
        return page

    def test_closed_with_official_message_and_open_flag(self):
        msg = "当前时间没有开放重考申请"
        page = self.site(error=(400, {"message": msg}))
        state, = retakes(page)
        self.assertEqual((state["state"], state["detail"], state["学期"]), ("closed", msg, "第一学期"))
        with self.assertRaisesRegex(QueryUnavailable, msg):
            retakes(page, "A")
        self.assertEqual(self.writes, [])

    def test_failed_list_is_not_empty_or_closed(self):
        for status, body in [(400, {"message": "查询失败"}), (503, {}), (200, {"code": 403, "msg": "无权限"}),
                             (200, {"code": 200, "data": None}), (200, {"code": 200, "data": {}})]:
            with self.subTest(status=status):
                with self.assertRaises(QueryUnavailable):
                    retakes(self.site(error=(status, body)))

    def test_available_empty_list(self):
        state, = retakes(self.site(codes=[]))
        self.assertEqual(state["state"], "available")

    def test_reads_pages_and_previews_exact_new_class_id(self):
        page = self.site()
        state, first, second = retakes(page)
        self.assertEqual([first["新课程序号"], second["新课程序号"]], ["A", "AB"])
        row, = retakes(page, "A", preview=True)
        self.assertEqual((row["action"], row["新课程序号"]), ("preview", "A"))
        self.assertEqual(self.writes, [])

    def test_duplicate_class_id_across_pages_is_refused(self):
        page = self.site(codes=["A", "A"])
        with self.assertRaisesRegex(QueryUnavailable, "唯一"):
            retakes(page, "A")
        self.assertEqual(self.writes, [])

    def test_submit_and_reread_with_or_without_confirmation(self):
        for confirm, code in [(True, "A"), (False, "AB")]:
            with self.subTest(confirm=confirm):
                page = self.site(confirm=confirm)
                row, = retakes(page, code)
                self.assertEqual((row["action"], row["新课程序号"], row["申请状态"], row["申请时间"]),
                                 ("submitted", code, "已申请", "2026-11-27 12:00"))
                with self.assertRaises(QueryUnavailable):
                    retakes(page, code)
                self.assertEqual(self.writes, [code])

    def test_different_row_changed_does_not_confirm_submission(self):
        with self.assertRaisesRegex(QueryUnavailable, "回执"):
            retakes(self.site(changed_code="AB"), "A")
        self.assertEqual(self.writes, ["A"])
