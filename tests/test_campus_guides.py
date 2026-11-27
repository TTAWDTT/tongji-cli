import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from campus_guides import clinic_hours, sports_hours
from queries import QueryUnavailable


class CampusGuidesTest(unittest.TestCase):
    def test_merged_cells_do_not_cross_campus(self):
        rows = [["一、嘉定校区"], ["1", "篮球场", "室外", "8:00-18:00"], ["2", "网球场", "周日开放"],
                ["二、沪西校区"], ["1", "网球馆", "室内", "9:00-17:00"]]
        item, = sports_hours(rows, "学期方案", "https://example.org", "嘉定", "网球")
        self.assertEqual((item["type"], item["hours"], item["source"]), ("室外", "周日开放", "学期方案"))
        with self.assertRaises(QueryUnavailable):
            sports_hours(rows[:-1] + [["1", "网球馆", "9:00-17:00"]], "学期方案", "", "", "")

    def test_clinic_hours_keeps_facilities_separate(self):
        guide = """同济大学门诊部（师生）
中医科：周三全天
普通门诊时间：周一至周六
普通门诊时间
同济大学医院（面向社会）
周六开设：内科、中医科
普通门诊时间：周一至周六
注：眼科开诊安排可能调整"""
        clinic, hospital = clinic_hours(guide, None, "中医科", "source")
        self.assertEqual((clinic["schedule"][0]["hours"], hospital["schedule"][0]["hours"]), ("周三全天", "周六"))
        self.assertEqual(clinic["hours"], "周一至周六")
        self.assertEqual(clinic_hours(guide, "同济大学门诊部", "内科", "source"), [])

    def test_balance_waits_for_amount(self):
        from playwright.sync_api import sync_playwright
        from campus_guides import card_balance

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""<a href="#center">个人中心</a>
                    <iframe name="comepage" srcdoc="<div> 账户余额： </div>
                        <script>setTimeout(()=>document.querySelector('div').append('0.00'),150)</script>"></iframe>""")
                row, = card_balance(page)
                self.assertEqual((row["balance"], row["currency"]), ("0.00", "CNY"))
            finally:
                browser.close()
