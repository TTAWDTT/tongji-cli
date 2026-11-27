import sys
import runpy
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stadium import field_rows, slots, venues
from queries import QueryUnavailable


class StadiumTest(unittest.TestCase):
    def test_saved_login_can_replace_the_login_link_before_click(self):
        cli = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tongji"))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                url = "http://stadium.test/"
                page.route(url, lambda route: route.fulfill(content_type="text/html; charset=utf-8", body="""
                    <button disabled>登 录</button><script>
                    setTimeout(()=>document.body.innerHTML='<button>退出</button>',500);
                    </script>"""))
                with patch.dict(cli["SITES"], stadium=url):
                    self.assertEqual(cli["visit"](page, "stadium", False), "authenticated")
            finally:
                browser.close()

    def test_login_waits_for_confirmation_dialog(self):
        cli = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tongji"))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                url = "http://stadium.test/"
                page.route(url, lambda r: r.fulfill(content_type="text/html; charset=utf-8", body="""
                    <button onclick="setTimeout(()=>document.querySelector('[role=dialog]').hidden=false,350)">登 录</button>
                    <div role="dialog" hidden><button onclick="document.body.innerHTML='&lt;button&gt;退出&lt;/button&gt;'">
                    登 录</button></div>"""))
                with patch.dict(cli["SITES"], stadium=url):
                    self.assertEqual(cli["visit"](page, "stadium", False), "authenticated")
            finally:
                browser.close()

    def test_venues_filters_after_pagination(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.route("**/pc/", lambda r: r.fulfill(content_type="text/html; charset=utf-8", body="""
                    <div class="cardP15"></div><div class="el-pagination">
                    <button class="btn-next" onclick="load(2)">下一页</button></div>
                    <script>async function load(n) {
                        const data = await (await fetch('/manage/venue/listNoVenue?p='+n)).json();
                        document.querySelector('.cardP15').innerHTML =
                            data.rows.map(x=>'<h3>'+x.venueName+'</h3>').join('');
                    } load(1)</script>"""))
                campuses = ["沪西校区", "四平校区"]
                page.route("**/manage/venue/listNoVenue?*", lambda r: r.fulfill(json={
                    "total": 2, "code": 0, "rows": [{
                        "campusName": campuses[int(r.request.url[-1])-1],
                        "venueName": "网球场" + r.request.url[-1],
                        "venueAddr": "测试地址", "openTime": "09:00-21:00",
                    }],
                }))
                result, = venues(page, "四平", "网球")
                self.assertEqual((result["title"], result["hours"], result["campus"]),
                                 ("网球场2", "09:00-21:00", "四平校区"))
            finally:
                browser.close()

    def test_grid_uses_adjacent_time_marks_and_matches_fields(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""
                    <ul class="leftUl"><li>09:00</li><li>09:30</li><li>10:00</li></ul>
                    <div class="tables"><div class="inner-seat-wrapper">
                    <ul><li class="topsiteStyle">1号场</li></ul><div class="clearfix"></div>
                    <div class="clearfix"><div class="seat"><div class="inner-seat bought-seat"></div></div></div>
                    <div class="clearfix"><div class="seat"><div class="inner-seat bought-seat"></div></div></div>
                    </div></div>""")
                items = field_rows(page, ["1号场"], "场馆", "网球", "2026-11-28")
                self.assertEqual([(r["time_slot"], r["available"]) for r in items],
                                 [("09:00-09:30", False), ("09:30-10:00", False)])
                page.locator(".leftUl li").last.evaluate("e=>e.remove()")
                with self.assertRaisesRegex(QueryUnavailable, "网格未对齐"):
                    field_rows(page, ["1号场"], "场馆", "网球", "2026-11-28")
            finally:
                browser.close()

    def test_grid_uses_platform_states_and_keeps_unknown_cells(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""
                    <ul class="leftUl"><li>09:00</li><li>10:00</li></ul>
                    <div class="tables"><div class="inner-seat-wrapper">
                    <ul><li class="topsiteStyle">甲</li><li class="topsiteStyle">乙</li>
                    <li class="topsiteStyle">丙</li></ul>
                    <div class="clearfix">
                        <div class="seat"><div class="inner-seat unselected-seat"></div></div>
                        <div class="seat"><div class="inner-seat bought-seat"></div></div>
                        <div class="seat"><div class="inner-seat other-state"></div></div>
                    </div></div></div>""")
                items = field_rows(page, ["甲", "乙", "丙"], "场馆", "网球", "2026-11-28")
                self.assertEqual([(r["field"], r["status"], r["available"]) for r in items],
                                 [("甲", "可选择", True), ("乙", "不可选", False), ("丙", "未核实", None)])
            finally:
                browser.close()

    def test_slots_reads_the_requested_day_through_the_venue_ui(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.route("**/pc/", lambda r: r.fulfill(content_type="text/html; charset=utf-8", body="""
                    <div class="cardP15"><h3 onclick="load(27)"></h3></div>
                    <button role="tab" aria-selected="true">网球</button>
                    <button role="tab" class="el-tabs__item" id="tab-2026-11-27" onclick="load(27)">11月27日</button>
                    <button role="tab" class="el-tabs__item" id="tab-2026-11-28" onclick="load(28)">11月28日</button>
                    <div class="drawerText"><h2></h2></div>
                    <div class="tables"><div class="inner-seat-wrapper"><li class="topsiteStyle"></li>
                    <div class="clearfix"><div class="seat"><span class="inner-seat bought-seat"></span></div></div>
                    </div></div><ul class="leftUl"><li>15:00</li><li>16:00</li></ul>
                    <script>
                    fetch('/manage/venue/listNoVenue').then(r=>r.json()).then(r=>
                        document.querySelector('h3').textContent = r.rows[0].venueName);
                    async function load(d) {
                        const r = await (await fetch('/queryFieldSituation?day=' + d)).json();
                        for (const t of document.querySelectorAll('[id^=tab-]'))
                            t.setAttribute('aria-selected', t.id.endsWith(d));
                        document.querySelector('h2').textContent = '2026-11-' + d;
                        document.querySelector('.topsiteStyle').textContent = r.data[0].fieldName;
                    }</script>"""))
                page.route("**/manage/venue/listNoVenue", lambda r: r.fulfill(json={
                    "code": 0, "total": 1, "rows": [{"venueName": "网球馆", "campusName": "四平",
                                                     "venueAddr": "校园", "openTime": "09:00-18:00"}]}))
                page.route("**/queryFieldSituation?*", lambda r: r.fulfill(json={
                    "code": 0, "data": [{"fieldName": "场地" + r.request.url[-2:]}]}))
                item, = slots(page, "网球馆", date(2026, 11, 28))
                self.assertEqual((item["field"], item["date"], item["time_slot"]),
                                 ("场地28", "2026-11-28", "15:00-16:00"))
                with self.assertRaisesRegex(QueryUnavailable, "未开放所选日期"):
                    slots(page, "网球馆", date(2027, 11, 28))
            finally:
                browser.close()
