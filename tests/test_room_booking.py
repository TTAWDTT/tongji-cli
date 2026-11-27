import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from library_room_booking import day_schedule, lookup_room_receipts, room_booking
from queries import QueryUnavailable


SITE = "http://rooms.local/"
DAY = "2026-11-28"
HOME = """
<button onclick="openRooms()">研习室预约</button>
<section class="section"><b>日期</b><div class="dayList"><div class="active"><span class="day">2026-11-28</span></div></div></section>
<section class="section"><b>馆舍</b><div class="normalList"><div class="item active"><span class="text">样例馆</span></div></div></section>
<section class="section"><b>楼层</b><div class="normalList"><div class="item active"><span class="text">二楼</span></div></div></section>
<section class="section"><b>区域</b><div class="item active"><span class="text">自习室2</span></div></section>
<button id="open" onclick="schedule()">立即预约</button>
<div class="content" hidden><div class="room-active">自习室2</div><div class="reg-date"><span>11月28日</span></div>
  <div class="calendarHead"></div>
  <div class="v-slider-track" style="position:relative;width:560px;height:24px;background:#ddd">
    <div role="slider" aria-valuemin="480" aria-valuemax="1320" aria-valuenow="480"></div>
    <div role="slider" aria-valuemin="480" aria-valuemax="1320" aria-valuenow="540"></div>
  </div>
  <button onclick="previewForm()">确定选择</button></div>
<div class="upload" hidden><div class="view1_item"><span class="titles">预约时间</span><span id="result"></span></div>
  <div class="view1_item"><span class="titles">预约房间</span><span>自习室2</span></div>
  <div class="v-select"><label>申请主题</label><button class="v-field" onclick="document.querySelector('[role=listbox]').hidden=false">选择</button>
    <span class="v-select__selection-text"></span></div>
  <div role="listbox" hidden><button class="v-list-item-title" onclick="choose(this)">自主学习</button></div>
  <div class="view3"><textarea></textarea></div>
  <button onclick="fetch('/save')">立即预约</button></div>
<script>
function choose(el){ document.querySelector('.v-select__selection-text').textContent=el.innerText;el.parentElement.hidden=true }
document.onkeydown=e=>{if(e.key==='Escape')document.querySelector('[role=listbox]').hidden=true}
function openRooms(){ return fetch('/reserve/index/quickSelect') }
async function schedule(){
  await fetch('/api/seminar/v1seminar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room:'7'})})
  document.querySelector('#open').hidden=true; document.querySelector('.content').hidden=false; sync()
}
function time(n){return [Math.floor(n/60),n%60].map(v=>String(v).padStart(2,'0')).join(':')}
function sync(){
  const [a,b]=document.querySelectorAll('[role=slider]')
  for (const el of [a,b]) {
    const n=Number(el.getAttribute('aria-valuenow'))
    el.style.cssText='position:absolute;top:0;width:20px;height:24px;transform:translateX(-50%);left:'+((n-480)/840*100)+'%'
  }
  document.querySelector('.calendarHead').textContent='2026-11-28 开始时间：['+time(a.getAttribute('aria-valuenow'))+'] 结束时间：['+time(b.getAttribute('aria-valuenow'))+']'
}
for (const el of document.querySelectorAll('[role=slider]')) {
  el.onpointerdown=e=>el.setPointerCapture(e.pointerId)
  el.onpointermove=e=>{
    if (!el.hasPointerCapture(e.pointerId)) return
    const rail=el.parentElement.getBoundingClientRect()
    const n=480+Math.round((e.clientX-rail.left)/rail.width*56)*15
    el.setAttribute('aria-valuenow',String(n)); sync()
  }
}
async function previewForm(){
  if (window.pendingAdjustment) await window.pendingAdjustment
  await fetch('/api/seminar/seminar')
  const [a,b]=document.querySelectorAll('[role=slider]')
  result.textContent='2026-11-28 '+time(a.getAttribute('aria-valuenow'))+'-'+time(b.getAttribute('aria-valuenow'))
  document.querySelector('.content').hidden=true; document.querySelector('.upload').hidden=false
}
</script>"""


class RoomBookingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.ctx = self.browser.new_context()
        self.addCleanup(self.ctx.close)
        host = patch("library_room_booking.SEATS", SITE + "history")
        host.start()
        self.addCleanup(host.stop)
        self.page = self.ctx.new_page()
        self.times = {"startTime": 480, "endTime": 1320, "minTime": 60, "maxTime": 240,
                      "minPerson": "1", "maxPerson": "4", "list": [{"beginNum": 570, "endNum": 690}]}
        self.schedule_dates = [DAY]
        self.cards = []
        self.saves = 0
        self.ctx.route(SITE + "**", self.serve)
        self.args = SimpleNamespace(action="reserve", room_id="7", date=date.fromisoformat(DAY),
                                    time_slot="13:00-14:30", preview=True, topic=None, purpose=None)

    def serve(self, route):
        path = route.request.url.removeprefix(SITE)
        if path == "":
            return route.fulfill(content_type="text/html; charset=utf-8", body=HOME)
        if path == "history":
            # 馆方先显示底部导航，再挂载首页预约入口。提前点击会留在首页。
            history = "".join(f'<div class="item"><div class="item_left"><p class="top">{place}</p>'
                              f'<p class="bottom">时间：{when}</p></div><p class="item_right">{state}</p></div>'
                              for place, when, state in self.cards)
            return route.fulfill(content_type="text/html; charset=utf-8", body=(
                '<button id="nav">我的中心</button><button id="ready" hidden>研习室预约</button>'
                '<button id="record" hidden>空间预约记录</button><div class="van-list" hidden><div class="contract_list">'
                + history + '</div><p>没有更多了</p></div>'
                '''<script>setTimeout(()=>{ready.hidden=false;nav.onclick=()=>record.hidden=false},80)
                 record.onclick=async()=>{await fetch('/api/Member/seminar'); document.querySelector('.van-list').hidden=false}</script>''' ))
        if path == "api/Member/seminar":
            rows = []
            for n, (place, when, state) in enumerate(self.cards):
                day, span = when.split(" ")
                start, end = span.split("-")
                rows.append({"id": str(n + 1), "day": day, "start": start, "end": end,
                             "nameMerge": place, "statusname": state, "title": f"样例申请 {n + 1}",
                             "createTime": DAY + " 07:00:00"})
            return route.fulfill(json={"code": 1, "data": {"current_page": 1, "total": len(rows), "data": rows}})
        if path == "save":
            self.saves += 1
            return route.fulfill(body="ok")
        if path == "reserve/index/quickSelect":
            data = {"premises": [{"id": "1", "name": "样例馆"}],
                    "storey": [{"id": "2", "parentId": "1", "name": "二楼"}],
                    "area": [{"id": "7", "parentId": "2", "name": "自习室2", "type_name": "研习室"}], "date": [DAY]}
            return route.fulfill(json={"code": 0, "data": data})
        if path == "api/seminar/v1seminar":
            return route.fulfill(json={"code": 1, "data": {"date": self.schedule_dates, "list": [{"date": day, "info": self.times} for day in self.schedule_dates]}})
        if path == "api/seminar/seminar":
            return route.fulfill(json={"code": 1, "data": self.times})
        route.fulfill(status=404)

    def run_cli(self, handoff=None):
        self.page.goto(SITE)
        return room_booking(self.page, self.args, handoff)

    def test_slots_and_preview_select_exact_time_without_submitting(self):
        self.args.action = "slots"
        row, = self.run_cli()
        self.assertEqual((row["min_people"], row["max_people"], row["min_minutes"]), (1, 4, 60))
        self.assertEqual(row["unoccupied"], ["08:00-09:30", "11:30-22:00"])
        self.args.action = "reserve"
        row, = self.run_cli()
        self.assertEqual((row["action"], row["room_id"], row["time_slot"], self.saves),
                         ("preview", "7", "13:00-14:30", 0))
        for invalid, message in (("09:00-10:00","已有占用"), ("11:30-12:00","时长"), ("12:16-13:30","选择器")):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(QueryUnavailable, message):
                self.args.time_slot = invalid
                self.run_cli()

    def test_distant_time_survives_the_room_slider_duration_adjustment(self):
        self.page.add_init_script("""addEventListener('pointerup', event => {
          const handles = [...document.querySelectorAll('[role=slider]')]
          if (event.target !== handles[1]) return
          const [start, end] = handles.map(e => Number(e.getAttribute('aria-valuenow')))
          if (end - start <= 240) return
          window.pendingAdjustment = new Promise(resolve => setTimeout(() => {
            handles[0].setAttribute('aria-valuenow', String(end - 240))
            sync()
            resolve()
          }, 160))
        })""")
        self.args.time_slot = "16:15-17:45"
        result, = self.run_cli()
        self.assertEqual(result["time_slot"], self.args.time_slot)
        self.assertEqual(self.page.locator("#result").inner_text(), DAY + " 16:15-17:45")
        self.assertEqual(self.saves, 0)

    def test_room_calendar_can_offer_a_date_outside_general_directory(self):
        self.schedule_dates.append("2026-11-29")
        self.args.action = "slots"
        self.args.date = date(2026, 11, 29)
        row, = self.run_cli()
        self.assertEqual(row["date"], "2026-11-29")
        self.args.date = date(2026, 12, 1)
        with self.assertRaisesRegex(QueryUnavailable, "房间时段尚未公布"):
            self.run_cli()

    def test_topic_and_purpose_stay_in_preview(self):
        self.args.topic = "自主学习"
        self.args.purpose = "课程项目讨论"
        row, = self.run_cli()
        self.assertEqual(row["topic_options"], ["自主学习"])
        self.assertEqual(row["topic"], self.args.topic)
        self.assertTrue(row["purpose_filled"])
        self.assertEqual(self.page.locator(".view3 textarea").input_value(), self.args.purpose)
        self.args.topic = "不存在"
        with self.assertRaisesRegex(QueryUnavailable, "可选主题：自主学习"):
            self.run_cli()
        self.assertEqual(self.saves, 0)

    def test_receipt_keeps_approval_state_and_requires_new_exact_record(self):
        self.args.preview = False
        target = ("样例馆-二楼-自习室2", DAY + " 13:00:00-14:30:00", "待审核")
        self.cards.extend([(target[0], "2025-11-28 13:00:00-14:30:00", "已预约"),
                           (target[0]+"0", target[1], "已预约"), (target[0], target[1], "已取消")])
        with self.assertRaisesRegex(QueryUnavailable, "尚未核实"):
            self.run_cli(lambda row: None)
        result, = self.run_cli(lambda row: self.cards.append(target))
        self.assertEqual((result["action"], result["receipt"]["status"]), ("applied", "待审核"))
        with self.assertRaisesRegex(QueryUnavailable, "已有"):
            self.run_cli(lambda row: self.fail("duplicate"))

    def test_receipt_lookup_matches_id_and_keeps_ended_records(self):
        self.cards.extend([("样例馆-二楼-自习室2", DAY + " 09:00:00-10:00:00", "已使用"),
                           ("样例馆-二楼-自习室2", DAY + " 11:00:00-12:00:00", "已取消")])
        args = SimpleNamespace(receipt_id=None, limit=1)
        latest, = lookup_room_receipts(self.page, args)
        self.assertEqual(latest["receipt_id"], "1")
        args.receipt_id = "2"
        selected, = lookup_room_receipts(self.page, args)
        self.assertEqual((selected["title"], selected["status"], selected["created_at"]),
                         ("样例申请 2", "已取消", DAY + " 07:00:00"))
        args.receipt_id = "02"
        with self.assertRaisesRegex(QueryUnavailable, "没有找到"):
            lookup_room_receipts(self.page, args)

    def test_old_booking_that_changes_state_is_not_a_new_receipt(self):
        self.args.preview = False
        where, when = "样例馆-二楼-自习室2", DAY + " 13:00:00-14:30:00"
        self.cards.append((where, when, "处理中"))
        def approve_old(row):
            self.cards[0] = (where, when, "已预约")
        with self.assertRaisesRegex(QueryUnavailable, "尚未核实"):
            self.run_cli(approve_old)
        self.assertEqual(self.saves, 0)

    def test_union_touching_intervals_and_missing_occupancy(self):
        self.times["list"] = [{"beginNum": 470, "endNum": 600}, {"beginNum": 550, "endNum": 610},
                              {"beginNum": 610, "endNum": 660}, {"beginNum": 1260, "endNum": 1450}]
        output = day_schedule({}, {"date": DAY, "info": self.times})
        self.assertEqual(output["unoccupied"], ["11:00-21:00"])
        self.times["list"] = []
        self.assertEqual(day_schedule({}, {"date": DAY, "info": self.times})["unoccupied"], ["08:00-22:00"])
        del self.times["list"]
        with self.assertRaisesRegex(QueryUnavailable, "占用明细"):
            day_schedule({}, {"date": DAY, "info": self.times})
