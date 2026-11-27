import json
import unittest
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.media.courses import COURSE_LIST, courses
from tongji_cli.common import QueryUnavailable


class MediaCoursesTest(unittest.TestCase):
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
        self.page.route("http://media.test/**", self.serve)
        self.fail = False
        self.page.goto("http://media.test/")

    def serve(self, route):
        url = urlsplit(route.request.url)
        if url.path == COURSE_LIST:
            params = parse_qs(url.query)
            n = int(params["nowpage"][0])
            data = None if params.get("search") == ["无匹配"] else [{"Id": n, "Title": f"课程{n}", "TermName": "秋季", "TenantCode": "sample"}]
            return route.fulfill(json={"code": 500 if self.fail else 1000, "status": 200,
                                       "params": {"result": {"page": n, "total": 2 if data else 0, "data": data}}})
        if url.path == "/":
            return route.fulfill(content_type="text/html; charset=utf-8",
                                 body='<button>我的课程</button><iframe id="inlineFrameExample" src="/personal/"></iframe>')
        route.fulfill(content_type="text/html; charset=utf-8", body="""
            <input placeholder="课程名称/教师名称"><button onclick="load(1)">搜索</button>
            <div class="my-course-list"></div><div class="el-pagination"><button class="btn-next" onclick="load(2)">下页</button></div>
            <script>
            async function load(n) {
                const query = new URLSearchParams({nowpage:n,search:document.querySelector('input').value});
                const res = await fetch(PATH + '?' + query);
                const {data} = (await res.json()).params.result;
                document.querySelector('.my-course-list').innerHTML = (data || []).map(r =>
                    '<div class="courseInfo"><span class="course-label">'+r.Title+
                    '</span><p class="course-desc-p">主讲教师：甲</p><p class="course-desc-p">上次学习：</p>'+
                    '<p class="course-desc-p">任务数：0</p></div>').join('');
            }
            </script>""".replace("PATH", json.dumps(COURSE_LIST)))

    def test_buffered_pages_and_successful_empty_search(self):
        result = courses(self.page, "")
        self.assertEqual([(r["id"], r["title"], r["task_count"], r["last_studied"]) for r in result],
                         [(1, "课程1", 0, None), (2, "课程2", 0, None)])
        self.assertEqual(courses(self.page, "无匹配"), [])

    def test_failed_search_is_distinct_from_empty(self):
        self.fail = True
        with self.assertRaisesRegex(QueryUnavailable, "未确认课程查询成功"):
            courses(self.page, "")
