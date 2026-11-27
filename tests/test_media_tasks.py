from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.media import tasks as media_tasks
from tongji_cli.common import QueryUnavailable


class MediaTasksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        source = patch.object(media_tasks, "TASKS", "http://media.test/task")
        source.start()
        self.addCleanup(source.stop)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.route("http://media.test/**", self.serve)
        self.fail = False
        self.args = SimpleNamespace(operation="tasks", term="全部", kind="required", task_type=None,
                                    status=None, search=None)

    def serve(self, route):
        url = urlsplit(route.request.url)
        if url.path == media_tasks.LIST_PATH:
            n = int(parse_qs(url.query)["page"][0])
            item = {"sub_title": "第一节" if n == 1 else "第二节", "course_title": "示例课",
                    "course_id": 123, "sub_id": n}
            return route.fulfill(json={"code": 1 if self.fail else 0, "data": {"total": "2", "list": [item]}})
        route.fulfill(content_type="text/html; charset=utf-8", body="""
            <button class="el-dropdown-selfdefine" onclick="choices.hidden=false">请选择学期</button>
            <div id="choices" hidden><button class="el-dropdown-menu__item" onclick="selectTerm()">全部</button>
            <button class="el-dropdown-menu__item">样例学期</button></div>
            <table class="el-table__body"><tbody></tbody></table>
            <div class="el-pagination"><button class="btn-next" onclick="load(2)">下一页</button></div>
            <script>
            function selectTerm() {
                document.querySelector('.el-dropdown-selfdefine').textContent='全部';choices.hidden=true;load(1)
            }
            async function load(n) {
                const payload = await (await fetch('PATH?must=1&page='+n)).json();
                setTimeout(()=>{
                    const r=payload.data.list[0];
                    const tr=document.querySelector('tbody');tr.replaceChildren();
                    const row=tr.insertRow();
                    for(const text of ['教学视频',r.sub_title,r.course_title,'未完成','开始','结束','查看']) {
                        row.insertCell().textContent=text;
                    }
                },40);
            }
            load(1);
            </script>""".replace("PATH", media_tasks.LIST_PATH))

    def test_required_tasks_wait_for_second_page_and_preserve_status(self):
        rows = media_tasks.tasks(self.page, self.args)
        self.assertEqual([(r["title"], r["id"]) for r in rows], [("第一节", 1), ("第二节", 2)])
        self.assertEqual(rows[-1]["completion_status"], "未完成")
        self.assertEqual(rows[-1]["end_time"], "结束")

    def test_school_failure_and_unknown_term(self):
        self.fail = True
        with self.assertRaisesRegex(QueryUnavailable, "未返回可核对"):
            media_tasks.tasks(self.page, self.args)
        self.fail = False
        self.args.term = "不存在"
        with self.assertRaisesRegex(QueryUnavailable, "未列出这个学期"):
            media_tasks.tasks(self.page, self.args)
