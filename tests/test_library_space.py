import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_space import availability, reserve_seat


class AvailabilityTest(unittest.TestCase):
    def test_selected_day_and_zero_available(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""
                    <button>座位预约</button>
                    <section class="section"><p>日期</p><div class="dayList">
                        <div class="item"><b class="day">2026-11-26</b></div>
                        <div class="item active"><b class="day">2026-11-27</b></div></div></section>
                    <section class="section"><p>馆舍</p><div class="normalList"><div class="item">
                        <div>样例馆</div><div class="info"><p>空余：0</p><p>总数：10</p></div>
                    </div></div></section>""")
                row, = availability(page)
                self.assertEqual((row["date"], row["available"], row["total"]), ("2026-11-27", 0, 10))
            finally:
                browser.close()

    def test_named_area_preserves_seat_numbers_and_does_not_book(self):
        from datetime import date
        from queries import QueryUnavailable

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                sample_area(page)
                area, = availability(page, branch="样例馆", floor="一楼")
                self.assertEqual((area["area"], area["available"], area["total"]), ("阅览室", 2, 3))
                items = availability(page, date(2026, 11, 27), "样例馆", "一楼", "阅览室")
                self.assertEqual([item["seat"] for item in items], ["001", "A2"])
                self.assertIsNone(page.evaluate("window.booked"))
                with self.assertRaisesRegex(QueryUnavailable, "未开放"):
                    availability(page, date(2026, 12, 1))
                with self.assertRaisesRegex(QueryUnavailable, "找不到"):
                    availability(page, branch="另一馆")
            finally:
                browser.close()

    def test_reservation_checks_the_personal_receipt(self):
        from datetime import date
        from queries import QueryUnavailable

        with sync_playwright() as pw, patch("library_space.SEATS", "http://fixture.local/records"):
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_context().new_page()
                sample_area(page)
                stored = []
                location = "样例馆-一楼-阅览室：001"
                timing = "11-27 08:00-22:00"

                def records(route):
                    cards = "".join(f'<div class="item"><div class="item_left"><p class="top">{place}</p>'
                                    f'<p class="bottom">时间：{time}</p></div><p class="item_right">{state}</p></div>'
                                    for place, time, state in stored)
                    route.fulfill(content_type="text/html; charset=utf-8", body=(
                        '<button>我的中心</button><button>座位预约记录</button><div class="van-list">'
                        f'<div class="contract_list">{cards}</div><p>没有更多了</p></div>'))

                page.context.route("http://fixture.local/records", records)
                saves = []
                receipt = [(location + "0", timing, "待签到"), (location, "11-28 08:00-22:00", "待签到"),
                           (location, timing, "已结束"), (location, "11-27 09:00-22:00", "待签到")]

                def save(route):
                    saves.append(1)
                    stored[:] = receipt
                    route.fulfill(status=200, body="ok", headers={"Access-Control-Allow-Origin": "*"})

                page.route("http://fixture.local/save", save)
                page.get_by_text("立即预约", exact=True).evaluate(
                    "el => el.onclick=()=>fetch('http://fixture.local/save')")
                args = SimpleNamespace(date=date(2026, 11, 27), branch="样例馆", floor="一楼", area="阅览室",
                                       time_slot="08:00-22:00", seat="001", preview=True)
                preview, = reserve_seat(page, args)
                self.assertEqual((preview["action"], preview["seat"], len(saves)), ("preview", "001", 0))
                button = page.get_by_role("button", name="立即预约", exact=True)
                button.evaluate("b => b.textContent='03:58:13 立即预约'")
                waiting, = reserve_seat(page, args)
                self.assertFalse(waiting["booking_available"])
                self.assertEqual(waiting["booking_button"], "03:58:13 立即预约")
                args.preview = False
                with self.assertRaisesRegex(QueryUnavailable, "暂未开放"):
                    reserve_seat(page, args)
                self.assertEqual(len(saves), 0)
                page.get_by_text("03:58:13 立即预约").evaluate("b => b.textContent='立即预约'")
                with self.assertRaisesRegex(QueryUnavailable, "尚未查到"):
                    reserve_seat(page, args)
                self.assertEqual(len(saves), 1)
                receipt.append((location, timing, "待签到"))
                confirmed, = reserve_seat(page, args)
                self.assertEqual((confirmed["action"], confirmed["receipt"]["location"]), ("reserved", location))
                with self.assertRaisesRegex(QueryUnavailable, "已有"):
                    reserve_seat(page, args)
                self.assertEqual(len(saves), 2)
            finally:
                browser.close()

    def test_equal_free_counts_after_slot_change(self):
        from datetime import date

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                sample_area(page)
                page.route("**/api/Seat/seat?second", lambda route: route.fulfill(
                    json={"code": 1, "data": [{"name": name, "status_name": "空闲"} for name in ("B1", "B2")]},
                    headers={"Access-Control-Allow-Origin": "*"}))
                page.locator(".reg-time").evaluate("""first => {
                    const second = first.cloneNode()
                    second.className = 'reg-time'
                    second.innerText = '09:00 - 10:00'
                    second.onclick = async () => {
                        first.classList.remove('active')
                        second.classList.add('active')
                        await fetch('http://fixture.local/api/Seat/seat?second')
                        setTimeout(() => {
                            document.querySelector('.grid-seat').innerHTML = '<div class="btn">B1</div><div class="btn">B2</div>'
                        }, 400)
                    }
                    first.after(second)
                }""")
                items = availability(page, date(2026, 11, 27), "样例馆", "一楼", "阅览室", "09:00-10:00")
                self.assertEqual([row["seat"] for row in items], ["B1", "B2"])
            finally:
                browser.close()

    def test_date_change_waits_for_initial_query(self):
        from datetime import date

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""
                    <button onclick="load(1)">座位预约</button>
                    <section class="section"><p>日期</p><div class="dayList">
                      <div class="item active"><b class="day">2026-11-27</b></div>
                      <div class="item" onclick="document.querySelector('.active').classList.remove('active');
                        this.classList.add('active');load(9)"><b class="day">2026-11-28</b></div></div></section>
                    <section class="section"><p>馆舍</p><div class="normalList"><div class="item">
                      <div>样例馆</div><div class="info">空余：1 总数：10</div></div></div></section>
                    <script>
                    function load(n) {
                      setTimeout(async () => {
                        const r = await fetch('http://fixture.local/reserve/index/quickSelect?n='+n)
                        const body=await r.json()
                        document.querySelector('.info').textContent='空余：'+body.data.premises[0].free_num+' 总数：10'
                      }, n === 1 ? 150 : 400)
                    }
                    </script>""")

                def reply(route):
                    free = int(route.request.url.split("n=")[1])
                    route.fulfill(json={"data": {"premises": [{"name": "样例馆", "free_num": free, "total_num": 10}],
                                                 "storey": [], "area": []}},
                                  headers={"Access-Control-Allow-Origin": "*"})

                page.route("**/quickSelect?*", reply)
                entry, = availability(page, requested_date=date(2026, 11, 28))
                self.assertEqual((entry["date"], entry["available"]), ("2026-11-28", 9))
            finally:
                browser.close()


def sample_area(page):
    page.set_content("""
        <button>座位预约</button>
        <section class="section"><p>日期</p><div class="dayList">
            <div class="active"><b class="day">2026-11-27</b></div></div></section>
        <section class="section"><p>馆舍</p><div class="normalList"><div class="item active">
            <span class="text">样例馆</span><div class="info">空余：2 总数：3</div>
        </div></div></section>
        <section class="section"><p>楼层</p><div class="normalList"><div class="item active">
            <span class="text">一楼</span><div class="info">空余：2 总数：3</div>
        </div></div></section>
        <section class="section"><p>区域</p><div class="normalList"><div class="item active">
            <span class="text">阅览室</span><div class="info">空余：2 总数：3</div>
        </div></div></section>
        <button onclick="document.querySelector('.SeatSelect').hidden=false;fetch('http://fixture.local/api/Seat/seat')">确定选择</button>
        <div class="SeatSelect" hidden><div class="seat-info"><span class="title">样例馆-一楼-阅览室</span>
          <span class="status">空余 2</span></div>
          <div class="reg-date active">11月27日 今天</div><div class="reg-time active">08:00 - 22:00</div>
          <button onclick="document.querySelector('.grid-seat').hidden=false">列表模式</button>
          <span class="seat-selected">已选座位号：-</span>
          <div class="grid-seat" hidden onclick="document.querySelector('.seat-selected').textContent='已选座位号：'+event.target.innerText"><div class="btn">001</div><div class="btn">A2</div></div>
          <button onclick="window.booked=true">立即预约</button></div>""")
    page.route("**/api/Seat/seat", lambda route: route.fulfill(
        json={"code": 1, "data": [{"name": label, "status_name": "空闲"} for label in ("001", "A2")]},
        headers={"Access-Control-Allow-Origin": "*"}))
    official = {
        "premises": [{"id": 1, "name": "样例馆", "free_num": 2, "total_num": 3}],
        "storey": [{"id": 2, "parentId": 1, "name": "一楼", "free_num": 2, "total_num": 3}],
        "area": [{"id": 3, "parentId": 2, "name": "阅览室", "free_num": 2, "total_num": 3}]}
    page.route("**/reserve/index/quickSelect", lambda route: route.fulfill(
        json={"data": official}, headers={"Access-Control-Allow-Origin": "*"}))
    page.get_by_text("座位预约", exact=True).evaluate("""el => el.onclick = () => {
        fetch('http://fixture.local/reserve/index/quickSelect')
        const room = document.querySelectorAll('.normalList .info')[2]
        room.innerText = '空余：8 总数：30'
        setTimeout(() => { room.innerText = '空余：2 总数：3' }, 350)
    }""")
