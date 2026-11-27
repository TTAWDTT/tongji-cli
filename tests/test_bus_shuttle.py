import argparse
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bus


class ShuttleTest(unittest.TestCase):
    def setUp(self):
        self.parser = argparse.ArgumentParser()
        bus.configure(self.parser.add_subparsers())
        self.pages = {
            bus.SERVICES: '<a href="/poster" title="学生班车时刻表">',
            bus.BASE + "/poster": b'<div class="wp_articlecontent"><img src="/poster.jpg"></div>',
            bus.BASE + "/poster.jpg": b"printed timetable",
            bus.INDEX: '<span>2026-11-10</span><a><a href="/move" title="关于11月14日短驳车发车点临时调整的通知">'
                       '<span>2026-09-17</span><a><a href="/holiday" title="关于2026年国庆节期间嘉定校区学生班车安排的通知">'
                       '<span>2026-07-02</span><a><a href="/summer" title="关于2026年暑假期间嘉定校区学生班车安排的通知">',
            bus.BASE + "/move": '<div class="wp_articlecontent"><table><tr><td>涉及出发时刻</td><td>原发车点</td>'
                                '<td>临时调整发车点</td></tr><tr><td><p>13:30</p><p>14:05</p><p>14:40</p></td>'
                                '<td>嘉三路近七号楼入口处</td><td>仰望星空</td></tr></table></div>',
            bus.BASE + "/holiday": '<div class="wp_articlecontent">2026年国庆节（10月1日至10月7日）期间学生班车安排如下：'
                                   '二.轨道交通11号线短驳车（嘉定校区至上海汽车城）国庆节期间按双休日时刻表运行。'
                                   '三.轨道交通14号线短驳车。9月20日（周日）、10月10日（周六）上课、上班，学生班车按工作日时刻表运行。</div>',
            bus.BASE + "/summer": '<div class="wp_articlecontent">2026年暑假期间（7月6日至9月13日），学生班车安排如下：'
                                  '二、轨道交通11号线短驳车（嘉定校区至上海汽车城站）短驳车正常运行至7月31日（周五），'
                                  '8月1日（周六）至9月13日（周日）期间按以下时刻表运行：<table><tr>'
                                  '<td>嘉定校区发车时间</td><td>上海汽车城站返回时间</td></tr>'
                                  '<tr><td>6:40</td><td>6:55</td></tr><tr><td>21:45</td><td>22:20</td></tr>'
                                  '</table>三、轨道交通14号线短驳车</div>',
        }
        for key, page in self.pages.items():
            if isinstance(page, str):
                self.pages[key] = page.encode()
        self.enter_patch(patch.object(bus, "fetch", side_effect=self.pages.__getitem__))
        self.enter_patch(patch.object(bus, "POSTER_SHA", hashlib.sha256(b"printed timetable").hexdigest()))
        self.enter_patch(patch.object(bus, "open_data", return_value={
            "2026-11-14": "3", "2026-11-26": "2", "2026-11-27": "2", "2026-11-28": "3"}))

    def enter_patch(self, mock):
        mock.start()
        self.addCleanup(mock.stop)

    def timetable(self, day, *args):
        return bus.run(self.parser.parse_args(["bus", "shuttle", "--date", day, *args]))

    def test_weekday_friday_weekend(self):
        thursday, = self.timetable("2026-11-26", "--from", "嘉定")
        self.assertEqual(len(thursday["departures"]), 28)
        self.assertNotIn("16:00", thursday["departures"])
        friday, back = self.timetable("2026-11-27")
        self.assertEqual(len(friday["departures"]), 29)
        self.assertIn("16:00", friday["departures"])
        self.assertEqual(back["departures"][-1], "22:20")
        self.assertIn("822路", back["stop"])
        saturday, = self.timetable("2026-11-28", "--from", "嘉定")
        self.assertEqual(len(saturday["departures"]), 24)
        self.assertEqual(saturday["departures"][0], "06:40")
        self.assertNotIn("15:15", saturday["departures"])

    def test_three_pickups_moved_for_one_direction(self):
        usual, moved, back = self.timetable("2026-11-14")
        self.assertEqual(moved["departures"], ["13:30", "14:05", "14:40"])
        self.assertEqual(moved["stop"], "仰望星空")
        self.assertTrue(moved["stop_source"].endswith("/move"))
        self.assertNotIn("13:30", usual["departures"])
        self.assertIn("13:45", back["departures"])

    def test_holiday_makeup_and_summer(self):
        holiday, = self.timetable("2026-10-01", "--from", "嘉定")
        self.assertEqual(holiday["schedule"], "双休日")
        self.assertEqual(len(holiday["departures"]), 24)
        makeup, = self.timetable("2026-10-10", "--from", "嘉定")
        self.assertEqual(makeup["departures"][0], "06:25")
        self.assertTrue(makeup["source"].endswith("/holiday"))
        before, = self.timetable("2026-07-31", "--from", "嘉定")
        self.assertIn("16:00", before["departures"])
        summer, = self.timetable("2026-08-01", "--from", "上海汽车城")
        self.assertEqual(summer["departures"], ["06:55", "22:20"])

    def test_unverified_timetables_report_source(self):
        self.pages[bus.BASE + "/poster.jpg"] = b"replacement"
        with self.assertRaisesRegex(bus.QueryUnavailable, "/poster"):
            self.timetable("2026-11-27")
        self.pages[bus.BASE + "/poster.jpg"] = b"printed timetable"
        self.pages[bus.BASE + "/summer"] = self.pages[bus.BASE + "/summer"].replace(
            "嘉定校区发车时间".encode(), "停运".encode())
        with self.assertRaisesRegex(bus.QueryUnavailable, "/summer"):
            self.timetable("2026-08-01")
