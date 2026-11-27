import unittest

from playwright.sync_api import sync_playwright

import notices
from queries import QueryUnavailable


class NoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = sync_playwright().start()
        cls.browser = cls.engine.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.engine.stop()

    def test_graduate_archive_counts_backwards_and_searches_full_title(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        root = notices.SOURCES["graduate"][1]
        archive = "https://gs.tongji.edu.cn/tzgg/3.htm"
        documents = {
            root: '<span id="fanye1">1/5</span>',
            archive: '''<ul class="list_list"><li><span class="listriqi">2025-05-07</span>
                <a href="../info/1092/123.htm" title="博士学位授予通知">博士学位授...</a></li></ul>''',
        }
        context.route("**/*", lambda route: route.fulfill(body=documents[route.request.url], content_type="text/html; charset=utf-8"))
        state, rows = notices.read_source(context, "graduate", 3, 1, "通知")
        self.assertEqual(state, {"status": "ok", "pages": [3]})
        self.assertEqual([(r["source_url"], r["url"], r["date"], r["title"]) for r in rows], [
            (archive, "https://gs.tongji.edu.cn/info/1092/123.htm", "2025-05-07", "博士学位授予通知")])

    def test_jiading_uses_the_article_link_inside_the_directory(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        root = notices.SOURCES["jiading"][1]
        second = root.replace("list.htm", "list2.htm")
        article = "/61/43/c5453a418115/page.htm"
        documents = {
            root: '<ul class="wp_paging"><li><a href="list2.htm"><span>尾页</span></a></li></ul>',
            second: f'''<table class="wp_article_list_table"><tr><td><li><span>2026-11-10</span>
                <a href="javascript:void(0)"><a href="{article}" title="短驳车发车点调整">短驳车</a></a>
                </li></td></tr></table>''',
        }
        context.route("**/*", lambda route: route.fulfill(body=documents[route.request.url],
                                                         content_type="text/html; charset=utf-8"))
        state, rows = notices.read_source(context, "jiading", 2, 1, "短驳车")
        self.assertEqual(state, {"status": "ok", "pages": [2]})
        row, = rows
        self.assertEqual((row["date"], row["title"], notices.article_source(row["url"])),
                         ("2026-11-10", "短驳车发车点调整", "jiading"))

    def test_pdf_and_image_only_articles(self):
        page = self.browser.new_page(java_script_enabled=False)
        self.addCleanup(page.close)
        url = "https://gs.tongji.edu.cn/info/1092/123.htm"
        for html, field, path in [
            ('<script>showVsbpdfIframe("/__local/file.pdf","100%")</script>', "attachments", "/__local/file.pdf"),
            ('<img alt="开放时间表" src="/__local/schedule.jpg">', "images", "/__local/schedule.jpg"),
        ]:
            with self.subTest(field=field):
                page.set_content(f'''<form name="_newscontent_fromname"><h1>通知</h1><div>2026年03月05日</div>
                    <div class="v_news_content">{html}</div></form>''')
                row = notices.article_record(page, "graduate", url)
                self.assertEqual(row["date"], "2026-03-05")
                self.assertEqual(row["body"], "")
                self.assertEqual(row[field][0]["url"], "https://gs.tongji.edu.cn" + path)

    def test_only_known_notice_sections_are_accepted(self):
        for url in (
            "https://example.org/info/1092/123.htm",
            "https://gs.tongji.edu.cn/info/1234/123.htm",
            "https://www.lib.tongji.edu.cn/index.php?classid=11979&newsid=1&t=show&other=1",
        ):
            with self.subTest(url=url), self.assertRaises(QueryUnavailable):
                notices.show_notice(url)

    def test_outage_keeps_notices_from_other_sources(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        html = {
            notices.SOURCES["graduate"][1]: '''<ul class="list_list"><li><span class="listriqi">2025-05-07</span>
                <a href="info/1092/123.htm" title="研究生公告">研究生公告</a></li></ul>''',
            notices.SOURCES["library"][1]: '''<div id="content"><div class="news"><dl>
                <dd class="title"><a href="?newsid=2">图书馆公告</a></dd>
                <span class="input_time">2026-04-01</span></dl></div></div>''',
        }
        def serve(route):
            body = html.get(route.request.url)
            route.fulfill(status=200 if body else 503, content_type="text/html; charset=utf-8", body=body or "")
        context.route("**/*", serve)
        entry = notices.read_sources(context, notices.SOURCES, 1, 1, "")
        self.assertEqual(entry["status"], "partial")
        self.assertEqual([r["title"] for r in entry["items"]], ["图书馆公告", "研究生公告"], entry)
        self.assertEqual(entry["sources"]["undergraduate"]["status"], "unverified")
        self.assertEqual(entry["sources"]["library"]["pages"], [1])
        self.assertIn("本科生院", entry["detail"])
        empty = notices.read_sources(context, notices.SOURCES, 1, 1, "无匹配")
        self.assertEqual((empty["status"], empty["items"]), ("partial", []))

    def test_failed_archive_page_keeps_earlier_and_later_pages(self):
        context = self.browser.new_context()
        self.addCleanup(context.close)
        def serve(route):
            url = route.request.url
            if url.endswith("/2.htm"):
                route.fulfill(status=503, body="Service unavailable")
                return
            title = "首页" if url.endswith("tzgg.htm") else "第三页"
            route.fulfill(content_type="text/html; charset=utf-8", body=f'''
                <span id="fanye1">1/3</span><ul class="list_list"><li>
                <span class="listriqi">2025-01-01</span><a title="{title}" href="a.htm">{title}</a></li></ul>''')
        context.route("**/*", serve)
        entry = notices.read_sources(context, ["graduate"], 1, 3, "")
        self.assertEqual(entry["status"], "partial")
        self.assertEqual(entry["sources"]["graduate"]["pages"], [1, 3])
        self.assertIn("第 2 页", entry["detail"])
        self.assertEqual([r["title"] for r in entry["items"]], ["首页", "第三页"])
