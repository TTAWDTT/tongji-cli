import sys
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_session import CHANNEL
from rooms_public import read_status


class PublicRoomStatusTest(unittest.TestCase):
    def test_report_matches_selected_room_and_published_usage(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel=CHANNEL)
            try:
                page = browser.new_page()
                room = "四平路校区-北楼-101"
                page.set_content(f"""
                    <div>2026年11月27号 08:19:00</div>
                    <div class="classroom-type-title">{room}A <span>(空闲)</span></div>
                    <div class="classroom-type-title">{room} <span>(占用)</span></div>
                    <div class="el-table"><table>
                    <tr><th>教室</th><th>自习可用时长</th><th>教室情况</th></tr>
                    <tr><td>{room}A</td><td>3小时</td><td>自习</td></tr>
                    <tr><td>{room}</td><td>—</td><td>上课</td></tr>
                    </table></div>""")
                result = read_status(page, room)
                self.assertEqual((result["status"], result["usage"], result["study_time"]),
                                 ("占用", "上课", "—"))
                self.assertEqual(result["observed_at"], "2026年11月27号 08:19:00")

                page.locator("tr:has(td)").evaluate_all("rows => rows.forEach(row => row.remove())")
                page.locator(".el-table").evaluate("e => e.insertAdjacentHTML('beforeend', '<p>暂无数据</p>')")
                empty = read_status(page, room)
                self.assertEqual((empty["status"], empty["usage"], empty["study_time"]), ("占用", None, None))
            finally:
                browser.close()
