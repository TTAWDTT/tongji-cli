from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queries
from canvas_navigation import groups, navigation
from queries import QueryUnavailable


class NavigationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        base = patch.object(queries, "CANVAS", "https://school.test")
        base.start()
        self.addCleanup(base.stop)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.directory = """<h2>Current Groups</h2>No Groups<h2>Previous Groups</h2>
            <table id="previous_groups_table"><tr><td>往期组</td><td>课程甲</td><td></td></tr>
            <tr><td><a href="/groups/2">往期组</a></td><td>课程乙</td><td>秋季</td></tr></table>"""
        self.page.route("https://school.test/groups",
                        lambda r: r.fulfill(content_type="text/html; charset=utf-8",
                                            body=f'<main id="content">{self.directory}</main>'))

    def test_empty_current_and_mixed_access_to_past_groups(self):
        self.assertEqual(groups(self.page, "active"), [])
        rows = groups(self.page, "completed")
        self.assertIsNone(rows[0]["url"])
        self.assertEqual([r["id"] for r in rows], [None, 2])
        self.assertIsNone(rows[0]["term"])
        self.assertEqual(rows[1]["term"], "秋季")
        self.directory = "<h1>服务维护</h1><h2>稍后重试</h2>"
        with self.assertRaises(QueryUnavailable):
            groups(self.page, "active")

    def test_navigation_uses_only_visible_links_and_rejects_dashboard_redirect(self):
        target = "https://school.test/groups/2"
        self.page.route(target, lambda r: r.fulfill(content_type="text/html; charset=utf-8", body="""
            <ul id="section-tabs"><li><a href="/groups/2">主页<b class="nav-badge">1</b></a></li>
            <li hidden><a href="/restricted">未开放</a></li>
            <li><a href="https://tool.test/group">外部工具</a></li></ul>"""))
        args = SimpleNamespace(group=2, state="completed")
        self.assertEqual(navigation(None, self.page, args), [
            {"title": "主页", "url": target}, {"title": "外部工具", "url": "https://tool.test/group"}])
        self.page.unroute(target)
        self.page.route(target, lambda r: r.fulfill(content_type="text/html",
                                                   body="<script>history.replaceState(null, '', '/')</script>"))
        with self.assertRaisesRegex(QueryUnavailable, "未打开所选"):
            navigation(None, self.page, args)
