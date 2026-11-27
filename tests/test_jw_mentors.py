import unittest
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.jw.mentors import MEETING_LIST, MEETING_VIEW, MY_TUTOR, mentor_meetings, mentor_profile
from tongji_cli.common import QueryUnavailable


class MentorTest(unittest.TestCase):
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
        self.page.route("http://school.test/**", self.serve)
        self.page.goto("http://school.test/")
        self.wrong_type = False

    def serve(self, route):
        path = urlsplit(route.request.url).path
        if path == MY_TUTOR:
            return route.fulfill(json={"code":200,"data":{"teacherName":None}})
        if path == "/myCollegeTutor":
            html = f'<p>您目前没有导师</p><script>fetch("{MY_TUTOR}?type={1 if self.wrong_type else 2}")</script>'
        elif path == MEETING_LIST:
            n = int(route.request.post_data)
            return route.fulfill(json={"code":200,"data":{"pageNum_":n,"pageSize_":1,"total_":2,
                   "list":[{"id":n,"meetingTime":f"时间{n}","meetingLocation":"教室"}]}})
        elif path == MEETING_VIEW:
            html = """
              <div class="el-table">
              <div class="el-table__header-wrapper"><table><tr><th class="is-hidden"></th><th class="is-hidden"></th>
              <th class="is-hidden"></th><th>导师所属学院</th><th>见面时间</th><th>见面地点</th><th>备注</th><th>发布时间</th></tr></table></div>
              <div class="el-table__fixed-header-wrapper"><table><tr><th>学期</th><th>学生</th><th>导师</th></tr></table></div>
              <div class="el-table__body-wrapper"><table><tbody></tbody></table></div>
              <div class="el-table__fixed-body-wrapper"><table><tbody></tbody></table></div></div>
              <div class="el-pagination"><div class="el-pagination__jump"><input onkeydown="if(event.key==='Enter')load(+this.value)"></div></div>
              <script>
              async function load(n) {
                const {data}=await (await fetch('API',{method:'POST',body:String(n)})).json();
                document.querySelector('.el-table__body-wrapper tbody').innerHTML='<tr><td class="is-hidden"></td>'
                  +'<td class="is-hidden"></td><td class="is-hidden"></td><td>学院</td><td>'+data.list[0].meetingTime+'</td>'
                  +'<td>教室</td><td></td><td>发布日</td></tr>';
                document.querySelector('.el-table__fixed-body-wrapper tbody').innerHTML='<tr><td>学期</td><td>学生组</td><td>导师'+n+'</td></tr>';
              }
              load(1);
              </script>""".replace("API", MEETING_LIST)
        else:
            return route.fulfill(body="home")
        return route.fulfill(content_type="text/html; charset=utf-8", body=html)

    def test_empty_college_profile_requires_correct_school_category(self):
        result = mentor_profile(self.page,"college")
        self.assertEqual(result["items"],[])
        self.assertIn("学院导师",result["detail"])
        self.wrong_type=True
        with self.assertRaisesRegex(QueryUnavailable,"导师类别"):
            mentor_profile(self.page,"college")

    def test_fixed_columns_on_both_meeting_pages(self):
        rows=mentor_meetings(self.page)
        self.assertEqual([(r["导师"],r["见面时间"]) for r in rows],[("导师1","时间1"),("导师2","时间2")])
        self.assertTrue(all(r["学期"]=="学期" and r["备注"] is None and "学生" not in r for r in rows))
