import unittest
from datetime import datetime
from html import escape
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.jw.personal_changes import personal_change
from tongji_cli.jw.records import PAGED_QUERIES
from tongji_cli.common import QueryUnavailable, SHANGHAI


TERM = "2026-2027学年第1学期"
OPEN = datetime(2026, 10, 28, 12, tzinfo=SHANGHAI)
CLOSED = datetime(2026, 11, 27, 12, tzinfo=SHANGHAI)


class PersonalChangeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.term = TERM
        self.withdraw_term = TERM
        self.timetable = {"AB"}
        self.withdrawals = {"A": "未退课", "AB": "未退课"}
        self.withdrawal_message = ""
        self.rounds = [1]
        self.submissions = []
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.context.route("http://school.test/**", self.handle)
        self.page = self.context.new_page()
        self.page.goto("http://school.test/workbench")

    def handle(self, route):
        path = urlsplit(route.request.url).path
        if path == "/api/electionservice/student/getRounds":
            return route.fulfill(json={"code": 200, "data": self.rounds})
        if path == PAGED_QUERIES["withdrawals"]:
            return route.fulfill(json={"code": 200, "data": list(self.withdrawals.values())})
        if path.startswith("/fixture/"):
            action, code = path.split("/")[-2:]
            self.submissions.append((action, code))
            if action == "withdraw":
                self.withdrawals[code] = "已退课"
                self.timetable.discard(code)
            else:
                self.timetable.add(code)
            return route.fulfill(body="OK")
        if path == "/GraduateStudentTimeTable":
            html = self.table(self.term, ["新课程序号", "上课时间"], [(code, "周一") for code in self.timetable])
        elif path == "/MidTermWithdrawalCourses":
            rows = [[code, "同名课", status] for code, status in self.withdrawals.items()]
            html = self.table(self.withdraw_term, ["新课程序号", "课程名称", "状态"], rows)
            html += f"<p>{self.withdrawal_message}</p>"
            html += f"<script>fetch('{PAGED_QUERIES['withdrawals']}')</script>" + self.button("withdraw")
        elif path == "/studentElect":
            html = "<script>fetch('/api/electionservice/student/getRounds')</script>"
            html += "<button>选择课程</button>" if self.rounds else "<p>当前没有对您开放的选课！</p>"
            html += self.button("enroll")
        else:
            html = "工作台"
        route.fulfill(content_type="text/html; charset=utf-8", body=html)

    def table(self, term, headers, rows):
        labels = "".join(f"<th>{h}</th>" for h in headers)
        items = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in row) + "</tr>" for row in rows)
        empty = "" if items else "<div class=el-table__empty-text>暂无数据</div>"
        return (f"<div class=el-form-item><label>学年学期：</label><input value='{term}'></div>"
                f"<div class=el-table><div class=el-table__header-wrapper><table><tr>{labels}</tr></table></div>"
                f"<div class=el-table__body-wrapper><table>{items}</table>{empty}</div></div>")

    def button(self, action):
        return (f"<button id=save onclick=\"fetch('/fixture/{action}/'+code.value,{{method:'POST'}})\">"
                "本人确认</button><input id=code value=A>")

    def student_click(self, result, enrolling, code="A"):
        self.assertEqual(self.submissions, [])
        self.page.locator("#code").fill(code)
        with self.page.expect_response("**/fixture/**"):
            self.page.locator("#save").click()

    def run_change(self, kind, **options):
        return personal_change(self.page, kind, TERM, "A", **options)[0]

    def test_enrollment_saved_and_verified_by_exact_class(self):
        row = self.run_change("enroll", handoff=self.student_click)
        self.assertEqual(row["state"], "verified")
        self.assertFalse(row["办理前"]["个人课表列有该课"])
        self.assertTrue(row["办理后"]["个人课表列有该课"])
        self.assertEqual(self.submissions, [("enroll", "A")])
        self.assertEqual(self.run_change("enroll")["state"], "already")

    def test_withdrawal_requires_both_records(self):
        self.timetable.add("A")
        row = self.run_change("withdraw", now=OPEN, handoff=self.student_click)
        self.assertEqual(row["办理前"]["退课记录状态"], "未退课")
        self.assertEqual(row["办理后"]["退课记录状态"], "已退课")
        self.assertFalse(row["办理后"]["个人课表列有该课"])
        self.assertEqual(self.run_change("withdraw", now=OPEN)["state"], "already")
        self.assertEqual(self.submissions, [("withdraw", "A")])

    def test_different_course_saved_or_user_cancelled(self):
        with self.assertRaisesRegex(QueryUnavailable, "办理后：个人课表无该课"):
            self.run_change("enroll", handoff=lambda *args: self.student_click(*args, code="B"))
        with self.assertRaisesRegex(QueryUnavailable, "办理结果未核实"):
            self.run_change("enroll", handoff=lambda *_: None)
        self.assertEqual(self.submissions, [("enroll", "B")])

    def test_withdrawal_row_changed_but_course_still_listed(self):
        self.timetable.add("A")
        def partial(*_):
            self.withdrawals["A"] = "已退课"
        with self.assertRaisesRegex(QueryUnavailable, "办理后：个人课表有该课，退课记录为已退课"):
            self.run_change("withdraw", now=OPEN, handoff=partial)

    def test_wrong_term_on_either_source_or_after_handoff(self):
        self.timetable.add("A")
        self.withdraw_term = "另一学期"
        with self.assertRaisesRegex(QueryUnavailable, "学期与教务页面不一致"):
            self.run_change("withdraw", now=OPEN)
        self.term = "另一学期"
        with self.assertRaisesRegex(QueryUnavailable, "学期与教务页面不一致"):
            self.run_change("enroll")
        self.term = TERM
        self.timetable.discard("A")
        with self.assertRaisesRegex(QueryUnavailable, "学期与教务页面不一致"):
            self.run_change("enroll", handoff=lambda *_: setattr(self, "term", "另一学期"))
        self.assertEqual(self.submissions, [])

    def test_closed_windows_and_open_preview(self):
        self.rounds.clear()
        self.assertEqual(self.run_change("enroll", preview=True)["state"], "closed")
        with self.assertRaisesRegex(QueryUnavailable, "当前没有对您开放"):
            self.run_change("enroll")
        self.timetable.add("A")
        row = self.run_change("withdraw", preview=True, now=CLOSED)
        self.assertEqual(row["state"], "closed")
        self.assertIn("本科生院", row["detail"])
        self.assertIn("bksy.tongji.edu.cn", row["通知链接"])
        with self.assertRaisesRegex(QueryUnavailable, "10-30 16:00"):
            self.run_change("withdraw", now=CLOSED)
        self.assertEqual(self.run_change("withdraw", preview=True, now=OPEN)["state"], "preview")
        self.assertEqual(self.submissions, [])

    def test_other_terms_use_page_message_not_previous_notice_or_visible_button(self):
        self.term = self.withdraw_term = "2027-2028学年第1学期"
        self.timetable.add("A")
        def preview():
            return personal_change(self.page, "withdraw", self.term, "A", preview=True)[0]
        self.assertIn("核对该学期", preview()["detail"])
        self.withdrawal_message = "当前不在期中退课时间范围内"
        row = preview()
        self.assertEqual((row["state"], row["detail"]), ("closed", self.withdrawal_message))
        self.assertNotIn("通知链接", row)
        self.assertEqual(self.submissions, [])
