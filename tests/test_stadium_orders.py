import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from queries import QueryUnavailable
from stadium_orders import orders, reserve


APP = """<!doctype html><meta charset=utf-8>
<button onclick="showOrders(1)">我的订单</button><div class="el-tab-pane"></div>
<div class="el-pagination"><button class="btn-next" onclick="showOrders(2)">下一页</button></div>
<div class="cardP15"><h3 onclick="showGrid()"></h3></div>
<button role="tab" aria-selected=true>羽毛球</button>
<button role="tab" aria-selected=true id="tab-2026-12-03">12月03日</button>
<div class="tables"><div class="inner-seat-wrapper"><p class="topsiteStyle">场地1</p>
<div class="clearfix"><div class="seat"><button class="inner-seat unselected-seat"
 onclick="this.className='inner-seat selected-seat'; basket.hidden=false">可选</button></div></div></div></div>
<ul class="leftUl"><li>12:00</li><li>13:00</li></ul>
<div class="drawerText"><h2>2026-12-03 星期四</h2><div id=basket hidden>
<div class="textrow"><div class="el-col-15">场地1 12:00-13:00</div></div>
<div class="textrow"><div class="el-col-12">合计</div><div class="el-col-12">￥0元</div></div></div></div>
<button onclick="fetch('/local-checkout',{method:'POST'})">立即下单</button>
<script>
async function showOrders(n){
 location.hash='/Order';
 const data=await(await fetch('/venue/personal/personalOrderlist?page='+n)).json();
 document.querySelector('.el-tab-pane').innerHTML=data.records.map(r=>
 '<div class=card><p class=pStyle>'+r.spaceInfo+'</p><div class=noSelect><span>已预约</span></div></div>').join('');
}
async function showGrid(){await fetch('/queryFieldSituation')}
function directory(){fetch('/manage/venue/listNoVenue').then(r=>r.json()).then(x=>document.querySelector('h3').textContent=x.rows[0].venueName)}
window.onhashchange=()=>{if(location.hash.includes('/Venue/'))directory()};
if(location.hash==='#/Order')showOrders(1);else directory();
</script>"""


class StadiumOrders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.writes = []
        self.create_receipt = True
        self.receipts = [self.record("old")]
        self.args = SimpleNamespace(date=date(2026, 12, 3), venue="羽毛球馆", sport=None, field="场地1",
                                    time_slot="12:00-13:00", preview=False)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.route("**/*", self.site)
        self.page.goto("https://stadium.tongji.edu.cn/pc/#/Venue/1")

    def record(self, number):
        return dict(pOrderid=number, venuename="羽毛球馆", venname="羽毛球", scDate="2026-12-03",
                    spaceInfo="羽毛球 场地1 (12:00-13:00)", countprice=0)

    def site(self, route):
        addr = urlsplit(route.request.url)
        if addr.path == "/pc/":
            return route.fulfill(content_type="text/html; charset=utf-8", body=APP)
        if addr.path.endswith("/personalOrderlist"):
            n = int(addr.query.split("=")[-1])
            return route.fulfill(json=dict(records=self.receipts[n-1:n], total=len(self.receipts), current=n))
        if addr.path == "/local-checkout":
            self.writes.append(route.request.method)
            if self.create_receipt:
                self.receipts.append(self.record("new"))
        if addr.path.endswith("/listNoVenue"):
            return route.fulfill(json=dict(code=0,total=1,rows=[dict(campusName="沪西",venueName="羽毛球馆",
                                                                    venueAddr="校内",openTime="12:00-13:00")]))
        return route.fulfill(json={"code":0, "data":[{"fieldName":"场地1"}]})

    def checkout(self, row, price):
        self.assertEqual(price, "￥0元")
        with self.page.expect_response("**/local-checkout"):
            self.page.get_by_role("button",name="立即下单").click()

    def test_orders_and_preview(self):
        self.assertEqual(orders(self.page)[0]["status"], "已预约")
        self.args.preview = True
        item, = reserve(self.page, self.args, self.checkout)
        self.assertEqual((item["action"],item["amount"]), ("preview", "￥0元"))
        self.assertEqual(self.writes, [])

    def test_handled_checkout_matches_new_order_on_second_page(self):
        item, = reserve(self.page, self.args, self.checkout)
        self.assertEqual((item["id"],item["action"]), ("new","order_recorded"))
        self.assertEqual(self.writes, ["POST"])

    def test_old_order_does_not_prove_new_reservation(self):
        self.create_receipt = False
        with self.assertRaisesRegex(QueryUnavailable,"新订单"):
            reserve(self.page, self.args, self.checkout)
        self.assertEqual(self.writes, ["POST"])

    def test_unlisted_field_never_reaches_checkout(self):
        self.args.field = "场地11"
        with self.assertRaisesRegex(QueryUnavailable,"不可选"):
            reserve(self.page, self.args, self.checkout)
        self.assertEqual(self.writes, [])
