import unittest
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from tongji_cli.library.space import availability
from tongji_cli.library.study import reserve_study
from tongji_cli.common import QueryUnavailable
from test_library_space import sample_area


class StudySeatsTest(unittest.TestCase):
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
        self.page = self.ctx.new_page()
        p = self.page
        sample_area(p)
        p.get_by_text("座位预约", exact=True).evaluate("e=>e.textContent='研修座位'")
        p.evaluate("""() => {
            const panel = document.querySelector('.SeatSelect')
            panel.querySelector('.reg-time').remove()
            const tab = panel.querySelector('.reg-date')
            tab.textContent = '11月01日 - 11月30日'
            const second = tab.cloneNode(true)
            second.className = 'reg-date'
            second.textContent = '12月01日 - 12月31日'
            tab.after(second)
            panel.querySelector('button:last-child').classList.add('confirm')
            panel.insertAdjacentHTML('afterbegin','<div class="permissions"><p><span>本期预约权限：</span><b>已获得</b></p><p><span>下期预约权限：</span><b>未获得</b></p></div>')
            async function load(period) {
                const r = await fetch('http://fixture.local/api/Study/StudyAreaDetail?period='+period)
                const {data} = await r.json()
                const free = data.filter(s=>s.status_name==='空闲')
                panel.querySelector('.status').textContent='空余 '+free.length
                panel.querySelector('.grid-seat').innerHTML=free.map(s=>'<div class="btn">'+s.name+'</div>').join('')
            }
            document.querySelector('button[onclick*="SeatSelect"]').onclick=async()=>{
                tab.classList.add('active'); second.classList.remove('active')
                panel.hidden=false
                await fetch('http://fixture.local/api/Study/StudyOpenTimeCheck')
                await load(0)
            }
            second.onclick=()=>{
                tab.classList.remove('active'); second.classList.add('active')
                const button=panel.querySelector('.confirm')
                button.disabled=true; button.innerText='预约开放时间 12:00'
                load(1)
            }
        }""")
        allow = {"Access-Control-Allow-Origin": "*"}
        self.periods = [{"startDay": "2026-11-01", "endDay": "2026-11-30"},
                        {"startDay": "2026-12-01", "endDay": "2026-12-31"}]
        p.route("**/StudyOpenTimeCheck", lambda r: r.fulfill(json={"code": 1, "data": self.periods}, headers=allow))
        p.route("**/StudyAreaDetail?*", lambda r: r.fulfill(json={"code": 1, "data": [
            {"name": "001" if r.request.url.endswith("=0") else "A2", "status_name": "空闲"},
            {"name": "003", "status_name": "锁定"}]}, headers=allow))
        self.args = SimpleNamespace(branch="样例馆", floor="一楼", area="阅览室", study_type="research",
                                    period="current", seat="001", preview=True)

    def test_period_specific_list_and_disabled_preview(self):
        a = self.args
        a.period, a.seat = "next", "A2"
        row, = reserve_study(self.page, a)
        self.assertEqual((row["end_date"],row["permission"],row["available"]),("2026-12-31","未获得",1))
        self.assertFalse(row["booking_available"])
        self.assertIsNone(self.page.evaluate("window.booked"))
        a.preview = False
        with self.assertRaisesRegex(QueryUnavailable, "当前无法办理"):
            reserve_study(self.page, a, handoff=lambda _: self.fail("disabled"))

    def test_both_seat_types_preserve_labels_at_each_level(self):
        for kind, label in (("research", "研修座位"), ("exam", "考研座位")):
            self.page.locator("button").first.evaluate("(e,t)=>e.textContent=t", label)
            opts = {}
            for key in ("branch", "floor", "area"):
                row, = availability(self.page, **opts, study_type=kind)
                self.assertEqual(row["seat_type"], label)
                opts[key] = row[key]
            row, = availability(self.page, **opts, study_type=kind)
            self.assertEqual(row["seat_type"], label)
            self.args.study_type = kind
            row, = reserve_study(self.page, self.args)
            self.assertEqual(row["seat_type"], label)

    def test_invalid_period_response(self):
        self.page.route("**/StudyOpenTimeCheck", lambda r: r.fulfill(body="null", content_type="application/json",
                        headers={"Access-Control-Allow-Origin": "*"}))
        with self.assertRaisesRegex(QueryUnavailable, "未返回预约周期"):
            reserve_study(self.page, self.args)

    def test_missing_period(self):
        self.periods.pop()
        self.page.locator(".reg-date").last.evaluate("e=>e.remove()")
        with self.assertRaisesRegex(QueryUnavailable, "尚未列出"):
            availability(self.page, branch="样例馆",floor="一楼",area="阅览室",study_type="research",period="next")

    def test_actual_readback_requires_place_period_and_seat(self):
        stored = []
        def history(route):
            cards = "".join(f'<div class="item"><div class="item_left"><p class="top">样例馆-一楼-阅览室：{n}</p>'
                            f'<p class="bottom">时间：{t}</p></div><p class="item_right">已预约</p></div>' for n,t in stored)
            route.fulfill(content_type="text/html; charset=utf-8", body='<button>我的中心</button><button>研修专座预约记录</button>'
                          f'<div class="van-list"><div class="contract_list">{cards}</div><p>没有更多了</p></div>')
        self.ctx.route("http://fixture.local/history",history)
        a=self.args
        a.preview=False
        stored.extend([("001","2025-11-01 至 2025-11-30"),("01","2026-11-01 至 2026-11-30")])
        with patch("tongji_cli.library.study.SEATS","http://fixture.local/history"):
            with self.assertRaisesRegex(QueryUnavailable,"未核实"):
                reserve_study(self.page,a,handoff=lambda row: None)
            row,=reserve_study(self.page,a,handoff=lambda row: stored.append(("001","2026-11-01 至 2026-11-30")))
            self.assertEqual(row["action"],"reserved")
            with self.assertRaisesRegex(QueryUnavailable,"已有"):
                reserve_study(self.page,a,handoff=lambda _: self.fail("duplicate"))
