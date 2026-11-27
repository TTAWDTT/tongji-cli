import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_rooms import room_directory
from queries import QueryUnavailable


class LibraryRoomsTest(unittest.TestCase):
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
        self.days = ["2026-11-27", "2026-12-01"]
        self.page.set_content("""
            <button onclick="load(0)">研习室预约</button>
            <section class="section"><span>日期</span>
              <button onclick="document.querySelector('#later').hidden=false">全部展开&gt;&gt;</button>
              <div class="dayList"><div class="active"><span class="day">2026-11-27</span></div>
              <div id="later" hidden onclick="load(1)"><span class="day">2026-12-01</span></div></div></section>
            <script>async function load(n) {
                await fetch('http://fixture.local/reserve/index/quickSelect?day='+n)
                document.querySelector('.active').classList.remove('active')
                document.querySelectorAll('.day')[n].parentNode.classList.add('active')
            }</script>""")
        def reply(route):
            later = route.request.url.endswith("=1")
            data = {"date": self.days, "premises": [{"id": 1, "name": "甲馆"}, {"id": 2, "name": "乙馆"}],
                    "storey": [{"id": 21, "name": "二楼", "parentId": 1}, {"id": 22, "name": "二楼", "parentId": 2}],
                    "area": [{"id": str(i), "parentId": i, "name": "研习室", "type_name": "双人间"}
                             for i in ([22] if later else [21, 22])]}
            route.fulfill(json={"code": 0, "data": data}, headers={"Access-Control-Allow-Origin": "*"})
        self.page.route("**/quickSelect?*", reply)
        self.args = SimpleNamespace(action="list", date=None, branch=None, floor=None, room_type=None)

    def test_dates_and_same_named_rooms_across_branches(self):
        a = self.args
        a.action = "dates"
        self.assertEqual([(r["date"], r["selected"]) for r in room_directory(self.page,a)],
                         [(self.days[0],True), (self.days[1],False)])
        a.action = "list"
        self.assertEqual([r["branch"] for r in room_directory(self.page,a)], ["甲馆","乙馆"])
        a.date, a.branch, a.floor, a.room_type = date.fromisoformat(self.days[1]), "乙馆", "二楼", "双人间"
        row, = room_directory(self.page,a)
        self.assertEqual((row["date"],row["room_id"],row["room_name"]), (self.days[1],"22","研习室"))
        a.branch = "甲馆"
        self.assertEqual(room_directory(self.page,a), [])

    def test_successful_empty_date_window_without_selected_tab(self):
        self.page.locator(".dayList").evaluate("e=>e.remove()")
        self.page.get_by_text("研习室预约", exact=True).evaluate(
            "e=>e.onclick=()=>fetch('http://fixture.local/reserve/index/quickSelect?empty')")
        self.page.route("**/quickSelect?*", lambda r: r.fulfill(json={"code": 0, "data": {
            "premises": [], "storey": [], "area": [], "date": []}}, headers={"Access-Control-Allow-Origin": "*"}))
        for action in ("dates", "list"):
            self.args.action = action
            self.assertEqual(room_directory(self.page, self.args), [])
        self.args.date = date(2027, 1, 1)
        with self.assertRaisesRegex(QueryUnavailable, "尚未列出"):
            room_directory(self.page, self.args)

    def test_date_outside_offered_window_and_failed_directory(self):
        self.args.date = date(2027,1,1)
        with self.assertRaisesRegex(QueryUnavailable, "尚未列出"):
            room_directory(self.page,self.args)
        self.page.route("**/quickSelect?*",lambda r:r.fulfill(json={"code": 1,"data": {"premises": [], "storey": [], "area": [], "date": []}},
                        headers={"Access-Control-Allow-Origin": "*"}))
        with self.assertRaisesRegex(QueryUnavailable, "未返回完整"):
            room_directory(self.page,self.args)
