"""Read-only Chaoxing queries against synthetic HTTP responses and a real HTML parser."""
import io
import unittest
from contextlib import redirect_stdout
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

from playwright.sync_api import Error, sync_playwright

from tongji_cli import auth, chaoxing, cli
from tongji_cli.browser_session import CHANNEL
from tongji_cli.common import QueryUnavailable, SHANGHAI
from tongji_cli.display import display
from tongji_cli.schedule import week_view


BASE = "https://i.chaoxing.com/base"
TASK = "https://mooc1.chaoxing.com/mooc2/work/task"
DAY = datetime(2026, 12, 1, 12, tzinfo=SHANGHAI)


def course_link(course="1", clazz="2", title="示例课", cpi="3"):
    return (f'<a href="/visit/stucoursemiddle?courseid={course}&amp;clazzid={clazz}'
            f'&amp;cpi={cpi}">{title}</a>')


def work_row(number, *, title="练习", state="未完成", time="", url=None):
    link = url if url is not None else f"/mooc2/work/task?workId={number}"
    return (f'<li data="{link}"><p class="overHidden2">{title}</p>'
            f'<p class="status">{state}</p>{time}</li>')


def header(text):
    return f'<div class="detailsHead"><div class="infoHead"><p>{text}</p></div></div>'


def response(url, html="", *, status=200, mime="text/html", location=None):
    headers = {"content-type": mime}
    if location:
        headers["location"] = location
    reply = Mock(url=url, status=status, ok=200 <= status < 300, headers=headers)
    reply.text.return_value = html
    return reply


def fixture(*, catalogue=None, works="", detail=None, extra=None, base="var fid = '1';"):
    pages = {
        BASE: base, chaoxing.COURSES: course_link() if catalogue is None else catalogue,
        chaoxing.MIDDLE: '<input id="workEnc" value="fixture">', chaoxing.WORKS: works,
    }
    pages.update(extra or {})

    def get(url, **kwargs):
        key = url.split("?", 1)[0]
        if key in pages:
            value = pages[key]
        elif urlsplit(url).path.endswith("/work/task"):
            value = detail if detail is not None else header("作答时间：待定")
        else:
            raise AssertionError("Unexpected request in local fixture")
        return response(url, value) if isinstance(value, str) else value

    context = Mock()
    context.request.get.side_effect = get
    return context


class QueryContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = sync_playwright().start()
        cls.browser = cls.engine.chromium.launch(channel=CHANNEL)
        cls.page = cls.browser.new_page()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.engine.stop()

    def assignments(self, context, selector=None):
        return chaoxing.assignments(context, self.page, selector)

    def catalogue(self, context):
        return chaoxing.run(SimpleNamespace(operation="courses"), context, self.page, DAY)

    def test_empty_requires_a_visible_message_for_the_requested_list(self):
        for content in ('<script>const empty = "暂无作业";</script>',
                        '<div hidden>暂无作业</div>', '<!-- 暂无作业 -->',
                        '<span>请核对是否没有作业权限</span>'):
            with self.subTest(content=content):
                self.assertNotEqual(self.assignments(fixture(works=content))["status"], "ok")
        with self.assertRaises(QueryUnavailable):
            self.catalogue(fixture(catalogue='<script>const empty = "暂无课程"</script>'))
        for content in ("暂无作业", '<div class="null-data">暂无作业</div>'):
            with self.subTest(content=content):
                self.assertEqual(self.assignments(fixture(works=content))["status"], "ok")

    def test_permission_notice_wins_over_empty_and_is_checked_on_detail(self):
        denied = "<p>你暂时没有权限查看此课程</p>"
        with self.assertRaises(QueryUnavailable):
            self.catalogue(fixture(catalogue=denied + "<p>暂无课程</p>"))
        for notice in ("抱歉，该课程权限不足", "您没有查看权限"):
            with self.subTest(notice=notice):
                listing = "<p>" + notice + '</p><p class="empty">暂无作业</p>'
                self.assertEqual(self.assignments(fixture(works=listing))["status"], "partial")
        for page in ('<form>用户登录<input type="password"></form>',
                     '<script src="/antispider.js"></script><p>请完成验证码</p>'):
            with self.subTest(page=page):
                self.assertEqual(self.assignments(fixture(works=page + '<p class="empty">暂无作业</p>'))["status"],
                                 "partial")
        result = self.assignments(fixture(works=work_row(1), detail=denied))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["items"][0]["detail_status"], "unverified")
        self.assertIn("权限", result["errors"][0]["detail"])

    def test_coursework_text_is_not_a_page_error(self):
        result = self.assignments(fixture(works=work_row(1, title="用户登录和权限不足的界面设计")))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["items"]), 1)

    def test_empty_notice_from_another_region_is_not_a_list_result(self):
        html = '<aside><p class="empty">暂无作业</p></aside><div class="task-list">加载中</div>'
        self.assertNotEqual(self.assignments(fixture(works=html))["status"], "ok")

    def test_sidebar_assignment_and_pager_do_not_belong_to_the_work_list(self):
        sidebar = '<aside>' + work_row(9) + '<nav class="paging"><a href="?p=2">下一页</a></nav></aside>'
        context = fixture(works=sidebar + '<div class="task-list"><p class="empty">暂无作业</p></div>')
        result = self.assignments(context)
        self.assertEqual((result["status"], result["items"]), ("ok", []))
        self.assertEqual(context.request.get.call_count, 4)
        self.assertNotEqual(self.assignments(fixture(works='<aside>暂无作业</aside>'))["status"], "ok")

    def test_conflicting_or_malformed_institution_does_not_select_a_directory(self):
        for base in ('{"fid":"1invalid"}', '<script>var fid="1"; var config={"fid":"2"}</script>'):
            with self.subTest(base=base):
                context = fixture(base=base)
                with self.assertRaisesRegex(QueryUnavailable, "机构"):
                    self.catalogue(context)
                self.assertEqual(context.request.get.call_count, 1)

    def test_first_page_and_rows_after_a_bad_or_missing_link_survive(self):
        bad = '<li><p class="overHidden2">缺链接</p><p class="status">未交</p></li>'
        bad_duplicate = work_row(1)
        pager = '<div class="pagination"><a rel="next" href="?page=2">下一页</a></div>'
        result = self.assignments(fixture(works=work_row(1) + bad + bad_duplicate + work_row(3) + pager))
        self.assertEqual(result["status"], "partial")
        self.assertEqual([x["id"] for x in result["items"]], ["1:2:1", "1:2:3"])
        reasons = [x["detail"] for x in result["errors"]]
        for text in ("下一页", "链接", "重复"):
            self.assertTrue(any(text in s for s in reasons), reasons)
        self.assertTrue(all(e.get("course_id") == "1" and e.get("class_id") == "2"
                            for e in result["errors"]))

    def test_directory_partial_preserves_known_classes_and_refuses_name_guess(self):
        pager = '<div class="paging"><button onclick="nextPage()">下一页</button></div>'
        html = course_link() + '<a href="stucoursemiddle?courseid=8">另一门课</a>' + pager
        directory = self.catalogue(fixture(catalogue=html))
        self.assertEqual(directory["status"], "partial")
        self.assertEqual([c["id"] for c in directory["items"]], ["1:2"])
        self.assertTrue(any("下一页" in e["detail"] for e in directory["errors"]))
        result = self.assignments(fixture(catalogue=html, works=work_row(1)), "1:2")
        self.assertEqual([x["id"] for x in result["items"]], ["1:2:1"])
        context = fixture(catalogue=html)
        with self.assertRaisesRegex(QueryUnavailable, "目录"):
            self.assignments(context, "示例课")
        self.assertEqual(context.request.get.call_count, 2)

    def test_card_text_and_script_link_beside_placeholder_href(self):
        html = """<div class="course"><a href="#" onclick="openCourse(
          '/visit/stucoursemiddle?courseid=1&amp;clazzid=2&amp;cpi=3')"><img></a>
          <span class="course-name">示例课</span></div>"""
        self.assertEqual(chaoxing.courses(fixture(catalogue=html), self.page)[0]["title"], "示例课")

    def test_conflicting_course_context_does_not_create_duplicate_public_id(self):
        html = course_link() + course_link(cpi="4") + course_link("7", "8")
        directory = self.catalogue(fixture(catalogue=html))
        self.assertEqual(directory["status"], "partial")
        self.assertEqual([x["id"] for x in directory["items"]], ["7:8"])

    def test_composite_id_takes_precedence_over_another_course_title(self):
        html = course_link() + course_link("7", "8", title="1:2")
        result = self.assignments(fixture(catalogue=html, works=work_row(1)), "1:2")
        self.assertEqual([x["id"] for x in result["items"]], ["1:2:1"])

    def test_empty_selector_stops_before_contacting_the_catalogue(self):
        context = fixture()
        with self.assertRaisesRegex(QueryUnavailable, "不能为空"):
            self.assignments(context, "  ")
        context.request.get.assert_not_called()

    def test_present_blank_or_repeated_identity_values_do_not_select_a_task(self):
        for query in ("workId=1&amp;workId=", "workId=1&amp;classId=", "workId=1&amp;courseId=1&amp;courseId="):
            with self.subTest(query=query):
                context = fixture(works=work_row(1, url="/mooc2/work/task?" + query))
                self.assertEqual(self.assignments(context)["status"], "partial")
                self.assertEqual(context.request.get.call_count, 4)

    def test_time_is_taken_from_detail_header_and_retains_unparsed_official_text(self):
        known = "<p>截止时间：2026-12-01 09:00</p>"
        for text in ("待教师公布", "2026-12-01", "2026-12-01 09:00（待确认）"):
            with self.subTest(text=text):
                detail = '<section class="question">' + known + "</section>" + header("截止时间：" + text)
                item = self.assignments(fixture(works=work_row(1), detail=detail))["items"][0]
                self.assertIsNone(item["due"])
                self.assertEqual(item["due_as_listed"], text)

    def test_short_detail_confirms_a_full_list_date_only_if_the_end_matches(self):
        row = work_row(1, time="<p>截止时间：2026-12-01 09:00</p>")
        for end, expected in (("12-01 09:00", "2026-12-01T09:00:00+08:00"), ("12-03 09:00", None),
                              ("2026-12-05 10:00", "2026-12-05T10:00:00+08:00")):
            with self.subTest(end=end):
                item = self.assignments(fixture(works=row, detail=header("截止时间：" + end)))["items"][0]
                self.assertEqual(item["due_as_listed"], end)
                self.assertEqual(item["due"], expected)

    def test_list_title_is_not_an_official_time_field(self):
        row = work_row(1, title="截止时间：2026-12-01 09:00")
        item = self.assignments(fixture(works=row, detail=header("已发布")))["items"][0]
        self.assertIsNone(item["due"])
        self.assertIsNone(item["due_as_listed"])

    def test_two_official_fields_must_agree_on_the_end(self):
        period = "作答时间：11-30 12:00 至 12-01 09:00"
        for end, due in (("12-01", "2026-12-01T09:00:00+08:00"), ("12-05", None)):
            with self.subTest(end=end):
                detail = header(period + "</p><p>截止时间：2026-" + end + " 09:00")
                item = self.assignments(fixture(works=work_row(1), detail=detail))["items"][0]
                self.assertEqual(item["due"], due)
                self.assertIn("11-30", item["due_as_listed"])

    def test_missing_state_keeps_the_identified_assignment_and_error_scope(self):
        result = self.assignments(fixture(works=work_row(1, state="") + work_row(2)))
        self.assertEqual(result["status"], "partial")
        self.assertEqual([x["id"] for x in result["items"]], ["1:2:1", "1:2:2"])
        self.assertIsNone(result["items"][0]["submitted"])
        self.assertEqual(result["errors"][0]["id"], "1:2:1")

    def test_unrecognized_detail_preserves_known_list_metadata_as_partial(self):
        row = work_row(1, time="<p>截止时间：2026-12-01 09:00</p>")
        result = self.assignments(fixture(works=row, detail="<html><body>系统维护中</body></html>"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["items"][0]["due"], "2026-12-01T09:00:00+08:00")

    def test_mixed_submission_evidence_and_yearless_start_with_seconds(self):
        self.assertIsNone(chaoxing.submitted("未提交 / 已提交"))
        self.assertTrue(chaoxing.submitted("已截止，已提交"))
        self.assertFalse(chaoxing.submitted("已截止，未提交"))
        self.assertEqual(chaoxing.deadline("作答时间:11-30 09:00:00 至 2026-12-01 09:00:00"),
                         "2026-12-01T09:00:00+08:00")

    def test_list_relative_detail_uses_the_final_list_address(self):
        moved = "https://mooc2-ans.chaoxing.com/mooc-ans/mooc2/work/list"
        context = fixture(extra={
            chaoxing.WORKS: response(chaoxing.WORKS, status=302, location=moved),
            moved: work_row(1, url="task?workId=1&amp;name=A%2BB"),
        })
        result = self.assignments(context)
        expected = moved.rsplit("/", 1)[0] + "/task?workId=1&name=A%2BB"
        self.assertEqual(result["items"][0]["url"], expected)
        self.assertEqual(context.request.get.call_args.args[0], expected)

    def test_detail_follows_only_recognized_read_only_views(self):
        other = "https://mooc1.chaoxing.com/help"
        context = fixture(works=work_row(1), extra={
            TASK: response(TASK, status=302, location=other), other: header("截止时间：待定"),
        })
        result = self.assignments(context)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["items"][0]["detail_status"], "unverified")
        self.assertNotIn(other, [call.args[0] for call in context.request.get.call_args_list])

    def test_redirect_to_different_work_or_class_does_not_supply_a_deadline(self):
        view = TASK.rsplit("/", 1)[0] + "/view"
        for query in ("workId=2", "clazzId=8", "courseId="):
            with self.subTest(query=query):
                target = view + "?" + query
                context = fixture(works=work_row(1), extra={
                    TASK: response(TASK, status=302, location=target), view: header("截止时间：2026-12-01 09:00"),
                })
                result = self.assignments(context)
                self.assertEqual(result["status"], "partial")
                self.assertIsNone(result["items"][0]["due"])
                self.assertNotIn(target, [call.args[0] for call in context.request.get.call_args_list])

    def test_pager_rel_tokens_button_and_disabled_container(self):
        for control, expected in (
            ('<a rel="alternate next" href="?p=2">→</a>', True),
            ('<button onclick="nextPage()" aria-label="下一页">→</button>', True),
            ('<fieldset disabled><button onclick="nextPage()">下一页</button></fieldset>', False),
        ):
            with self.subTest(control=control):
                html = '<div class="pagination">' + control + "</div>"
                self.assertEqual(chaoxing.document(self.page, html, "has_next"), expected)

    def test_hidden_duplicate_menu_does_not_mask_visible_authenticated_navigation(self):
        self.page.set_content("<span hidden>课程</span><nav><a>课程</a></nav>")
        page = SimpleNamespace(url="https://i.chaoxing.com/", get_by_text=self.page.get_by_text,
                               locator=self.page.locator)
        self.assertEqual(auth.observe(page, "chaoxing"), "authenticated")
        self.page.set_content('<form><input type="password"></form><nav><a>课程</a></nav>')
        self.assertEqual(auth.observe(page, "chaoxing"), "login_required")

    def test_today_and_next_window_midnight_and_unknown_dates(self):
        rows = "".join(work_row(n) for n in range(1, 5))
        times = {1: "2026-11-30 23:59", 2: "2026-12-01 00:00", 3: "2026-12-02 00:00", 4: "待定"}

        def context():
            result = fixture(works=rows)
            original = result.request.get.side_effect

            def get(url, **kwargs):
                if url.startswith(TASK + "?workId="):
                    return response(url, header("截止时间：" + times[int(url.split("=")[-1])]))
                return original(url, **kwargs)

            result.request.get.side_effect = get
            return result

        direct = chaoxing.run(SimpleNamespace(operation="assignments", course=None, next=1), context(), self.page, DAY)
        today = cli.site_items(SimpleNamespace(command="today"), "chaoxing", context(), self.page, DAY)
        self.assertEqual([x["id"] for x in direct["items"]], ["1:2:2", "1:2:4"])
        self.assertEqual([x["id"] for x in today["items"]], ["1:2:2"])
        self.assertEqual([x["id"] for x in today["undated_assignments"]], ["1:2:4"])

    def test_partial_week_and_terminal_do_not_claim_zero_on_unverified_days(self):
        result = self.assignments(fixture(works="<p>权限不足</p>"))
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(display({"chaoxing": result}, False), 1)
        self.assertNotIn("共 0 项", output.getvalue())
        sources = {"jw": {"status": "ok", "items": []}, "canvas": {"status": "ok", "items": []},
                   "chaoxing": result}
        week = week_view(sources, date(2026, 12, 1))["week"]
        self.assertEqual(week["status"], "partial")
        self.assertTrue(all("chaoxing_assignments" not in day for day in week["items"]))


class TransportContractTest(unittest.TestCase):
    def test_browser_startup_failure_names_the_configured_browser(self):
        for detail in ("temporary failure", "SingletonLock"):
            with self.subTest(detail=detail), patch.object(cli, "arguments"), \
                    patch.object(cli, "run", side_effect=Error(detail)):
                with self.assertRaises(SystemExit) as caught:
                    cli.main()
                self.assertIn(CHANNEL.lower(), str(caught.exception).lower())

    def test_redirect_budget_and_missing_location(self):
        for location, count in (("/base", 6), (None, 1)):
            with self.subTest(location=location):
                context = Mock()
                context.request.get.return_value = response(BASE, status=302, location=location)
                with self.assertRaises(QueryUnavailable):
                    chaoxing.read(context, BASE)
                self.assertEqual(context.request.get.call_count, count)
                for call in context.request.get.call_args_list:
                    self.assertEqual((call.kwargs["timeout"], call.kwargs["max_redirects"]), (20000, 0))

    def test_content_type_and_response_lifetime(self):
        for mime, accepted in (("text/html; charset=utf-8", True), ("Application/XHTML+XML", True),
                               ("text/plain; note=html", False)):
            with self.subTest(mime=mime):
                final = response(BASE, "ok", mime=mime)
                hop = response(BASE, status=302, location="/base?page=2")
                context = Mock()
                context.request.get.side_effect = [hop, final]
                if accepted:
                    chaoxing.read(context, BASE)
                else:
                    with self.assertRaises(QueryUnavailable):
                        chaoxing.read(context, BASE)
                for reply in (hop, final):
                    reply.dispose.assert_called_once_with()

    def test_body_read_error_is_sanitized_and_releases_response(self):
        final = response(BASE)
        final.text.side_effect = Error("synthetic transport detail")
        context = Mock()
        context.request.get.return_value = final
        with self.assertRaises(QueryUnavailable) as caught:
            chaoxing.read(context, BASE)
        self.assertNotIn("synthetic", str(caught.exception))
        final.dispose.assert_called_once_with()
