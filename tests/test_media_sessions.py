import unittest
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.media.sessions import session_rows


class MediaSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def test_status_text_and_canonical_link_for_replay_only(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        course = {"url": "https://media.test/coursedetail?course_id=9&tenant_code=school", "id": 9, "title": "样例课"}
        records = [{"id": n, "sub_title": "第%d节" % n, "type": "course_live"} for n in (1,2)]
        parts = []
        for name, label, css in (("第1节","回放","colorStatus"),("第2节","未开始","")):
            parts.append(f'<div class="content-inner-one"><p><span>-</span><span>{name}</span>'
                         f'<span>任课老师</span><span></span><span class="{css}">{label}</span></p></div>')
        page.set_content('<div class="content-list"><div><p class="cap-title-info">测试周</p>'
                         + ''.join(parts) + '</div></div>')
        sections = {"2000":{"01":{"1":records}}}
        names = {"course_live": {"name": "智播"}}
        rows = session_rows(page, course, sections, None, names)
        self.assertEqual([r["type"] for r in rows], ["智播", "智播"])
        self.assertEqual([r["status"] for r in rows], ["回放","未开始"])
        self.assertEqual(rows[0]["week"], "测试周")
        self.assertEqual(parse_qs(urlsplit(rows[0]["url"]).query),
                         {"course_id":["9"], "sub_id":["1"], "tenant_code":["school"]})
        self.assertNotIn("url", rows[1])
        self.assertEqual(session_rows(page, course, sections, "回放", names), rows[:1])
        page.set_content("<div>暂无内容</div>")
        self.assertEqual(session_rows(page, course, {}, None, names), [])
