import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jw_major_timetable import CALENDARS, LIST, VIEW, major_timetable
from queries import QueryUnavailable


class MajorTimetableTest(unittest.TestCase):
    def setUp(self):
        self.pw=sync_playwright().start()
        self.browser=self.pw.chromium.launch(channel="chrome")
        self.addCleanup(self.pw.stop)
        self.addCleanup(self.browser.close)
        self.page=self.browser.new_page()
        self.rows=[{"value":"课程甲(1) 教室东","courseName":"课程甲","code":"1","dayOfWeek":2,
                    "timeStart":3,"timeEnd":4,"roomName":"教室东"},
                   {"value":"课程乙(2) 教室西","courseName":"课程乙","code":"2","dayOfWeek":2,
                    "timeStart":3,"timeEnd":4,"roomName":"教室西"}]
        self.calendar=11
        self.page.route("http://school.test/**",self.serve)
        self.page.goto("http://school.test/")

    def serve(self,route):
        path=urlsplit(route.request.url).path
        if path == CALENDARS:
            return route.fulfill(json={"code":"200","data":[{"id":11,"year":2026,"term":1}]})
        if path == LIST:
            return route.fulfill(json={"code":200,"data":self.rows})
        if path != VIEW:
            return route.fulfill(body="home")
        html="""
        <div class="el-form-item"><label>学年学期</label><input value="2026-2027学年第1学期"></div>
        <table><tr><th>节次/周次</th></tr><tr><td></td></tr></table>
        <script>
        fetch('CALENDARS');
        fetch('LIST?calendarId=ID').then(r=>r.json()).then(({data})=>{
            if(data.length) document.querySelector('td').innerHTML='<div class="el-popover__reference">'
                +data.map(r=>'<span>'+r.value+'</span>').join('')+'</div>';
        });
        </script>""".replace("CALENDARS",CALENDARS).replace("LIST",LIST).replace("ID",str(self.calendar))
        route.fulfill(content_type="text/html; charset=utf-8",body=html)

    def test_shared_period_and_empty_term(self):
        all_rows=major_timetable(self.page,None,None)
        self.assertEqual([r["课程序号"] for r in all_rows],["1","2"])
        self.assertEqual(major_timetable(self.page,"2026-2027第1学期","西"),[all_rows[1]])
        self.rows.clear()
        self.assertEqual(major_timetable(self.page,None,None),[])

    def test_response_must_match_selected_term(self):
        self.calendar=12
        with self.assertRaisesRegex(QueryUnavailable,"学期"):
            major_timetable(self.page,None,None)
