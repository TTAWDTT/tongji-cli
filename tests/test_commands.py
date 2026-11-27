import json
import unittest
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from tongji_cli.schedule import week_view
from tongji_cli.canvas import api as canvas_api
from tongji_cli.common import QueryUnavailable, SHANGHAI
from tongji_cli.campus import school_calendar
from tongji_cli.jw.records import credit_categories, plan_courses
from playwright.sync_api import sync_playwright


class CanvasFixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path.removeprefix("/api/v1/")
        params = parse_qs(url.query)
        if url.path == "/v1/rt/onetongji/calendar":
            data = {"2026-11-23": "2", "2026-11-25": "99", "2026-11-26": "3"}
            start, end = params["fromDate"][0], params["endDate"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"code": "A00000", "data": {d: k for d, k in data.items() if start <= d <= end}}).encode())
            return
        if url.path == "/v1/rt/onetongji/classroom/get_timetable_by_classroom":
            if self.headers.get("Authorization") != "Bearer fixture" or params.get("classroomIds") != ["R1"]:
                self.send_error(403)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"code": "A00000", "data": {"data": [{
                "classroomName": "R1", "calendarName": "示例学期", "classroomOccupationList": []
            }]}}).encode())
            return
        if url.path in {"/sample-download", "/empty-download"}:
            self.send_response(200)
            self.send_header("Content-Disposition", 'attachment; filename="sample.txt"')
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(b"sample" if url.path == "/sample-download" else b"")
            return
        tasks = [
            {"id": 11, "name": "窗口首日", "due_at": "2026-11-26T16:00:00Z", "html_url": "/11",
             "submission": {"workflow_state": "submitted"}},
            {"id": 12, "name": "窗口之后", "due_at": "2026-12-03T16:00:00Z", "html_url": "/12"},
            {"id": 13, "name": "无截止", "due_at": None, "html_url": "/13"},
        ]
        tasks.append({**tasks[0], "id": 14, "submission_types": ["discussion_topic"]})
        tasks.append({**tasks[0], "id": 15, "is_quiz_assignment": True})
        tasks.append({**tasks[0], "id": 16, "is_quiz_lti_assignment": True})
        rows = {
            "courses": [{"id": 7, "name": "测试课", "course_code": "C7"}],
            "courses/7/assignments": tasks[1:] if "page" in params else tasks[:1],
            "courses/7/assignments/11": {**tasks[0], "description": "<p>阅读</p><p>附件</p>"},
            "courses/7/files/3": {"id": 3, "display_name": "样例文件", "size": 6, "url": canvas_api.CANVAS + "/sample-download"},
            "calendar_events": [{"id": 1, "title": "全天", "all_day": True, "all_day_date": "2026-11-27",
                                 "context_code": params.get("context_codes[]", ["self"])[0]}]
                if params.get("start_date") == ["2026-11-27T00:00:00+08:00"]
                and params.get("end_date") == ["2026-11-27T23:59:59+08:00"] and params.get("type") == ["event"] else [],
            "courses/8/discussion_topics": [{"id": 3, "title": "上学期的讨论", "html_url": "/3"}],
            "courses/8/discussion_topics/3": {"id": 3, "title": "上学期的讨论", "message": "讨论正文", "html_url": "/3"},
            "courses/8/discussion_topics/3/view": {"view": [{"id": 6, "message": "讨论回复"}]},
            "courses/7/discussion_topics/1": {"id": 1, "title": "先发言", "html_url": "/1", "user_can_see_posts": False},
            "courses/7/discussion_topics/2": {"id": 2, "title": "讨论", "html_url": "/2", "user_can_see_posts": True},
            "courses/7/discussion_topics/2/view": {"view": [{"id": 4, "message": "旧", "replies": [
                {"id": 5, "message": "<p>回复</p>", "parent_id": 4}]}], "new_entries": [{"id": 4, "message": "更新"}]},
            "planner/items": [
                {"plannable_type": "quiz", "plannable_id": 5, "plannable_date": "2026-11-27T12:00:00Z",
                 "plannable": {"title": "小测"}, "html_url": "/quiz/5"},
                {"plannable_type": "assignment", "plannable_id": 6, "plannable_date": "2026-12-03T16:00:00Z",
                 "plannable": {"title": "窗口外"}},
            ],
            "courses/7/pages/read": {"id": 7, "title": "阅读", "url": "read", "html_url": canvas_api.CANVAS + "/read",
                "body": '<p>阅读资料</p><a href="/file/3">讲义</a><img src="/fig.png" alt="图一">'},
            "courses/7/assignments/11/submissions/self": {"assignment_id": 11, "workflow_state": "graded",
                "score": 0, "attachments": [{"display_name": "样例", "size": 0}], "submission_comments": [{"comment": "修改", "author_name": "教师"}]},
            "courses/7/assignments/12/submissions/self": {"assignment_id": 12, "workflow_state": "submitted",
                "submission_type": "online_text_entry", "body": "<p>文字</p><p><br></p><p>    第二段</p>"},
            "courses/7/assignments/13/submissions/self": {"assignment_id": 13, "workflow_state": "submitted",
                "submission_type": "online_url", "url": "https://example.org/project"},
            "courses/7/modules": [{"id": 8, "name": "第一章"}],
            "courses/7/modules/8/items": [{"type": "File", "content_id": 3, "title": "模块资料", "html_url": "/3"},
                                         {"type": "Page", "title": "阅读", "html_url": "/page"}],
            "courses/7/files": [{"id": 3, "display_name": "相同附件"}, {"id": 9, "display_name": "额外附件"}],
            "announcements": [{"context_code": "course_7", "posted_at": "2026-11-26T18:00:00Z",
                               "html_url": "/notice", "title": "通知", "message": "<p>内容</p>"}],
        }
        group_page = {"title": "分工", "url": "team-work", "html_url": canvas_api.CANVAS + "/groups/3/pages/team-work"}
        if path == "groups/3/discussion_topics" and params.get("only_announcements") == ["true"]:
            notice = {"title": "周六分工", "html_url": "/groups/3/discussion_topics/2", "published": True,
                      "posted_at": "2026-11-20T16:00:00Z", "message": "<p>分配任务</p>"}
            rows[path] = [notice, dict(notice, posted_at="2026-11-20T15:59:59Z"), dict(notice, published=False),
                          dict(notice, delayed_post_at="2026-11-28T02:00:00Z"),
                          dict(notice, title="周四讨论", delayed_post_at="2026-11-26T02:00:00Z")]
        rows["groups/3/pages"] = [group_page]
        rows["groups/3/pages/team-work"] = {**group_page, "body": '<p>本周任务</p><a href="../files/4">文档</a>',
                                            "locked_for_user": False}
        if path == "courses" and params.get("enrollment_state") == ["completed"]:
            rows["courses"] = [{"id": 8, "name": "测试课", "course_code": "C7", "term": {"name": "往年"}}]
        archived = dict(tasks[0], id=21, name="往期作业", html_url="/courses/8/assignments/21")
        rows["courses/8/assignments"] = [archived]
        rows["courses/8/assignments/21"] = dict(archived, description="课程报告")
        rows["courses/8/assignments/21/submissions/self"] = dict(rows["courses/7/assignments/11/submissions/self"], assignment_id=21)
        archived_receipt = rows["courses/8/assignments/21/submissions/self"]
        archived_receipt["attachments"] = [{"id": 91, "display_name": "报告", "size": 6,
                                            "url": canvas_api.CANVAS + "/sample-download"}]
        archived_receipt["submission_comments"] = [{"comment": "修改", "attachments": [
            {"id": 92, "display_name": "报告", "size": 0, "url": canvas_api.CANVAS + "/empty-download"},
            {"id": 93, "display_name": "不完整", "size": 7, "url": canvas_api.CANVAS + "/sample-download"},
            {"id": 94, "display_name": "未开放", "size": 0, "locked_for_user": True}
        ]}]
        archived_receipt.update(attempt=2, submitted_at="2026-06-02T01:00:00Z")
        if params.get("include[]") == ["submission_history"]:
            archived_receipt["submission_history"] = [
                dict(archived_receipt),
                {"attempt": None, "workflow_state": "unsubmitted", "submitted_at": None},
                {"attempt": 1, "workflow_state": "submitted", "submitted_at": "2026-06-01T01:00:00Z",
                 "attachments": [{"id": 90, "size": 0, "display_name": "报告", "url": canvas_api.CANVAS + "/empty-download"}]}
            ]
        rows["courses/8/modules"] = []
        rows["courses/8/files"] = [{"id": 3, "display_name": "往期讲义", "size": 6}]
        rows["courses/8/files/3"] = dict(rows["courses/7/files/3"], display_name="往期讲义")
        rows["courses/8/pages/read"] = dict(rows["courses/7/pages/read"], title="往期页面")
        rows["courses/8/pages"] = [rows["courses/8/pages/read"]]
        if path not in rows:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if path == "courses/7/assignments" and "page" not in params:
            self.send_header("Link", '</api/v1/courses/7/assignments?page=2>; rel="next"')
        self.end_headers()
        self.wfile.write(json.dumps(rows[path]).encode())


class CommandsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), CanvasFixture)
        cls.worker = Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.origin = canvas_api.CANVAS
        canvas_api.CANVAS = f"http://127.0.0.1:{cls.server.server_port}"
        cls.engine = sync_playwright().start()
        cls.browser = cls.engine.chromium.launch(channel="chrome")
        cls.ctx = cls.browser.new_context()
        cls.day = date(2026, 11, 27)

    @classmethod
    def tearDownClass(cls):
        canvas_api.CANVAS = cls.origin
        cls.browser.close()
        cls.engine.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def test_personal_and_course_calendar(self):
        for selector, context in ((None, "self"), ("7", "course_7")):
            event, = canvas_api.calendar_events(self.ctx, self.day, 1, selector)
            self.assertEqual((event["context"], event["all_day"], event["date"]), (context, True, "2026-11-27"))

    def test_thread_restriction_and_revised_reply(self):
        locked, = canvas_api.discussions(self.ctx, "7", 1, True)
        self.assertFalse(locked["can_see_posts"])
        self.assertNotIn("replies", locked)
        thread, = canvas_api.discussions(self.ctx, "7", 2, True)
        self.assertEqual([(e["body"], e["parent_id"]) for e in thread["replies"]], [("更新", None), ("回复", 4)])

    def test_completed_course_discussion_and_replies(self):
        archived, = canvas_api.discussions(self.ctx, "测试课", state="completed")
        topic, = canvas_api.discussions(self.ctx, "测试课", archived["id"], True, "completed")
        self.assertEqual((topic["course_id"], topic["body"], topic["replies"][0]["body"]), (8, "讨论正文", "讨论回复"))
        with self.assertRaises(QueryUnavailable):
            canvas_api.discussions(self.ctx, "8")

    def test_date_range_and_all_tasks(self):
        items = canvas_api.tasks(self.ctx, self.day, 7)
        self.assertEqual([r["id"] for r in items], [11])
        self.assertTrue(items[0]["submitted"])
        all_tasks = canvas_api.tasks(self.ctx, self.day, None, "C7")
        self.assertEqual({r["id"] for r in all_tasks}, {11, 12, 13, 14, 15, 16})

    def test_planner_page_and_receipt(self):
        event, = canvas_api.planner(self.ctx, self.day, 7)
        self.assertEqual(event["type"], "quiz")
        self.assertIsNone(event["due"])
        page, = canvas_api.course_pages(self.ctx, "7", "read")
        self.assertIn("阅读资料", page["body"])
        self.assertEqual([r["kind"] for r in page["resources"]], ["a", "img"])
        receipt, = canvas_api.own_submission(self.ctx, "7", 11)
        self.assertEqual(receipt["score"], 0)
        self.assertEqual(receipt["attachment_details"], [{"id": None, "name": "样例", "bytes": 0}])
        self.assertEqual(receipt["feedback"][0]["comment"], "修改")

    def test_group_wiki_list_and_detail(self):
        group = {"id": 3, "title": "示例组"}
        row, = canvas_api.scoped_pages(self.ctx, "groups", group, None)
        self.assertEqual((row["group_id"], row["group_name"], row["slug"]), (3, "示例组", "team-work"))
        self.assertNotIn("course_id", row)
        item, = canvas_api.scoped_pages(self.ctx, "groups", group, row["slug"])
        self.assertEqual((item["body"], item["locked"]), ("本周任务\n文档", False))
        self.assertEqual(item["resources"][0]["url"], canvas_api.CANVAS + "/groups/3/files/4")

    def test_download_creates_a_new_file(self):
        with TemporaryDirectory() as tmp:
            destination = Path(tmp) / "material.txt"
            item, = canvas_api.download_file(self.ctx, "7", 3, destination)
            self.assertEqual(destination.read_bytes(), b"sample")
            self.assertEqual(item["bytes"], 6)
            with self.assertRaises(QueryUnavailable):
                canvas_api.download_file(self.ctx, "7", 3, destination)

    def test_completed_materials_pages_and_download(self):
        with self.assertRaises(QueryUnavailable):
            canvas_api.course_files(self.ctx, "8")
        file, = canvas_api.course_files(self.ctx, "测试课", "completed")
        self.assertEqual((file["course_id"], file["title"]), (8, "往期讲义"))
        material, = canvas_api.materials(self.ctx, "测试课", "completed")
        self.assertEqual(material["file_id"], file["id"])
        listed, = canvas_api.course_pages(self.ctx, "测试课", state="completed")
        shown, = canvas_api.course_pages(self.ctx, "8", listed["slug"], "completed")
        self.assertEqual((shown["course_id"], shown["title"]), (8, "往期页面"))
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "handout"
            downloaded, = canvas_api.download_file(self.ctx, "8", file["id"], dest, "completed")
            self.assertEqual((downloaded["course_id"], dest.read_bytes()), (8, b"sample"))

    def test_completed_course_assignments_and_personal_feedback(self):
        course = "测试课"
        row, = canvas_api.tasks(self.ctx, datetime.now(SHANGHAI).date(), None, course, state="completed")
        detail, = canvas_api.show_assignment(self.ctx, course, row["id"], "completed")
        receipt, = canvas_api.own_submission(self.ctx, course, row["id"], "completed")
        self.assertEqual((row["course_id"], detail["instructions"], receipt["course_id"]), (8, "课程报告", 8))
        self.assertEqual((receipt["id"], receipt["score"], receipt["feedback"][0]["comment"]), (21, 0, "修改"))
        with self.assertRaises(QueryUnavailable):
            canvas_api.own_submission(self.ctx, course, row["id"])

    def test_submission_and_feedback_attachment_download(self):
        row, = canvas_api.own_submission(self.ctx, "8", 21, "completed")
        uploaded, = row["attachment_details"]
        marked = row["feedback"][0]["attachment_details"][0]
        self.assertEqual((uploaded["name"], marked["name"]), ("报告", "报告"))
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "copy"
            for file, content, source in [(uploaded, b"sample", "submission"), (marked, b"", "feedback")]:
                result, = canvas_api.download_submission_attachment(self.ctx, "8", 21, file["id"], dest, "completed")
                self.assertEqual((dest.read_bytes(), result["source"], result["assignment_id"]), (content, source, 21))
                with self.assertRaisesRegex(QueryUnavailable, "已存在"):
                    canvas_api.download_submission_attachment(self.ctx, "8", 21, file["id"], dest, "completed")
                self.assertEqual(dest.read_bytes(), content)
                dest.unlink()
            for file_id, message in [(3, "没有该附件"), (93, "字节数"), (94, "开放下载")]:
                with self.assertRaisesRegex(QueryUnavailable, message):
                    canvas_api.download_submission_attachment(self.ctx, "8", 21, file_id, dest, "completed")
                self.assertFalse(dest.exists())

    def test_historical_attachment_is_scoped_to_its_attempt(self):
        versions = canvas_api.own_submission(self.ctx, "8", 21, "completed", history=True)
        self.assertEqual([r["attempt"] for r in versions], [1, 2])
        self.assertNotIn("feedback", versions[0])
        self.assertEqual([r["attachment_details"][0]["id"] for r in versions], [90, 91])
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "earlier"
            downloaded, = canvas_api.download_submission_attachment(self.ctx, "8", 21, 90, dest, "completed", attempt=1)
            self.assertEqual((downloaded["attempt"], dest.read_bytes()), (1, b""))
            dest.unlink()
            for attempt, attachment in [(None, 90), (1, 91), (2, 92), (3, 90)]:
                with self.subTest(attempt=attempt, attachment=attachment), self.assertRaises(QueryUnavailable):
                    canvas_api.download_submission_attachment(self.ctx, "8", 21, attachment, dest, "completed", attempt=attempt)
                self.assertFalse(dest.exists())
        with self.assertRaisesRegex(QueryUnavailable, "未提供"):
            canvas_api.own_submission(self.ctx, "7", 12, history=True)

    def test_read_back_submitted_text_and_link(self):
        text_row, = canvas_api.own_submission(self.ctx, "7", 12)
        self.assertEqual(text_row["body"], "文字\n\n    第二段")
        self.assertIn("<br>", text_row["body_html"])
        link_row, = canvas_api.own_submission(self.ctx, "7", 13)
        self.assertEqual(link_row["submission_url"], "https://example.org/project")
        self.assertNotEqual(link_row["url"], link_row["submission_url"])

    def test_details_and_materials(self):
        row, = canvas_api.show_assignment(self.ctx, "测试课", 11)
        self.assertEqual(row["instructions"], "阅读\n附件")
        items = canvas_api.materials(self.ctx, "7")
        self.assertEqual([r["title"] for r in items], ["模块资料", "阅读", "额外附件"])
        result, = canvas_api.announcements(self.ctx, 7, datetime(2026,11,27,12,tzinfo=SHANGHAI))
        self.assertEqual(result["posted"], "2026-11-27T02:00:00+08:00")

    def test_group_announcements_use_release_date_and_group(self):
        group = {"id": 3, "title": "小组"}
        now = datetime(2026, 11, 27, 12, tzinfo=SHANGHAI)
        items = canvas_api.announcements(self.ctx, 7, now, group=group)
        self.assertEqual([(r["title"], r["posted"]) for r in items], [
            ("周四讨论", "2026-11-26T10:00:00+08:00"), ("周六分工", "2026-11-21T00:00:00+08:00")])
        self.assertTrue(all(r["group_id"] == 3 and r["body"] == "分配任务" for r in items))

    def test_calendar_range_reports_missing_and_unknown_days(self):
        with patch.object(school_calendar, "API", canvas_api.CANVAS):
            start, end = date(2026, 11, 23), date(2026, 11, 26)
            span = school_calendar.calendar_range(start, end)
            self.assertEqual(span["status"], "partial")
            self.assertEqual([r["day_type"] for r in span["items"]], ["工作日", None, None, "周末"])
            self.assertEqual(school_calendar.calendar_range(end, end)["status"], "ok")
            self.assertEqual(school_calendar.calendar_range(self.day, self.day)["status"], "unverified")
            with self.assertRaisesRegex(QueryUnavailable, "结束日期"):
                school_calendar.calendar_range(end, start)

    def test_authorized_room_schedule(self):
        with patch.object(school_calendar, "API", canvas_api.CANVAS), patch.dict("os.environ", TONGJI_OPEN_TOKEN="fixture"):
            room, = school_calendar.room_schedule("R1", None)
            self.assertEqual(room["room"], "R1")
            self.assertEqual(room["schedule"], [])

    def test_plan_courses_expands_categories_and_skips_total(self):
        with self.ctx.new_page() as page:
            page.set_content("""<table><tr><th colspan="2">课程类别</th><th>课程编码</th><th>课程名称</th><th>成绩</th></tr>
                <tr><td rowspan="2">专业</td><td>必修</td><td>A</td><td>示例甲</td><td>0</td></tr>
                <tr><td>选修</td><td>B</td><td>示例乙</td><td></td></tr>
                <tr><th colspan="5">总计</th></tr></table>""")
            rows = plan_courses(page.locator("table"))
            self.assertEqual([(r["课程编码"], r["课程类别"], r["成绩"]) for r in rows],
                             [("A", "专业 / 必修", "0"), ("B", "专业 / 选修", None)])

    def test_credit_categories_keep_zero_and_empty_distinct(self):
        page = self.ctx.new_page()
        try:
            page.set_content("""<table>
                <tr><td rowspan="2">类别</td><td colspan="2">学位课</td></tr>
                <tr><td>基础课</td><td>专业课</td></tr>
                <tr><td>培养方案要求学分</td><td>4</td><td>6</td></tr>
                <tr><td>个人计划学分</td><td>4</td><td>8</td></tr>
                <tr><td>已完成学分</td><td>0</td><td></td></tr></table>""")
            base, major = credit_categories(page.locator("table"))
            self.assertEqual(base["课程类别"], "学位课 / 基础课")
            self.assertEqual(base["已完成学分"], "0")
            self.assertIsNone(major["已完成学分"])
        finally:
            page.close()

    def test_partial_week(self):
        inputs = {"jw": {"status": "login_required"}, "canvas": {"status": "authenticated",
                  "items": [{"due": "2026-11-28T10:00:00+08:00", "title": "作业"}]}}
        summary = week_view(inputs, self.day)["week"]
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(len(summary["items"]), 7)
        self.assertNotIn("classes", summary["items"][0])
        self.assertEqual(summary["items"][1]["assignments"][0]["title"], "作业")


if __name__ == "__main__":
    unittest.main()
