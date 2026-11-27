import unittest
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.campus.dorm_energy import WATER, meter_balance, meter_history
from tongji_cli.common import QueryUnavailable


class MeterReadingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def test_balance_requires_selected_meter_and_preserves_zero(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        for value in ("0", "0.03", "-0.01"):
            page.set_content(f'<div class="crumb"><h6>示例表间电表剩余电量：{value} 度</h6></div>')
            self.assertEqual(meter_balance(page, "示例表间"), value)
            with self.assertRaises(QueryUnavailable):
                meter_balance(page, "另一表间")

    def test_water_meter_uses_school_heading_and_tonnes(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        page.set_content('<div class="crumb"><h6>示例表间水表剩余电量：0.00 吨</h6></div>')
        self.assertEqual(meter_balance(page, "示例表间", WATER), "0.00")
        with self.assertRaises(QueryUnavailable):
            meter_balance(page, "示例表间")
        page.locator("h6").evaluate("e => e.textContent = e.textContent.replace('吨', '度')")
        with self.assertRaises(QueryUnavailable):
            meter_balance(page, "示例表间", WATER)

    def test_history_reads_second_page_and_preserves_missing_day(self):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        dates = {"startDate": "2000-01-01", "endDate": "2000-01-03"}
        def serve(route):
            second = urlsplit(route.request.url).path == "/second"
            day, used = ("2000-01-01", "0.00") if second else ("2000-01-03", "2.10")
            route.fulfill(content_type="text/html; charset=utf-8", body=f"""
                <form action="/first"><input id="txtstart" value="2000-01-01"><input id="txtend" value="2000-01-03"><button id="btnser">查询</button></form>
                <div class="crumb"><h6>示例表间电表剩余电量：0 度</h6></div>
                <table class="dataTable"><tr><th>日期</th><th>电表名称</th><th>用量(度)</th><th>单价(元/度)</th></tr>
                <tr><td>{day}</td><td>示例表间电表</td><td>{used}</td><td>0.6200</td></tr></table>
                <div class="pageer">第 {2 if second else 1} 页 / 共 2 页 <a href="/second">下一页</a></div>""")
        page.route("http://school.test/**", serve)
        page.goto("http://school.test/query")
        rows = meter_history(page, "示例表间", dates)
        self.assertEqual([(r["date"], r["used_electricity"]) for r in rows],
                         [("2000-01-01", "0.00"), ("2000-01-03", "2.10")])
        self.assertTrue(all(r["unit_price_yuan_per_kwh"] == "0.6200" for r in rows))
