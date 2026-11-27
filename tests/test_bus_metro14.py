import argparse
import unittest
from unittest.mock import patch

from tongji_cli.campus import bus


class Metro14Test(unittest.TestCase):
    def setUp(self):
        self.cli = argparse.ArgumentParser()
        bus.configure(self.cli.add_subparsers())
        self.holiday = bus.BASE + "/national-day"
        self.summary = ("根据学校节假日安排，2026年国庆节（10月1日至10月7日）期间学生班车安排如下："
                        "二.轨道交通11号线短驳车（嘉定校区至上海汽车城）国庆节期间按双休日时刻表运行。"
                        "三.轨道交通14号线短驳车（嘉定校区至封浜站）国庆节期间正常运行。"
                        "注：9月20日（周日）、10月10日（周六）上课、上班，学生班车按工作日时刻表运行。")
        self.pages = {
            bus.INDEX: '<span>2026-09-17</span><a><a href="/national-day" title="关于国庆节期间学生班车安排的通知">'
                       '<span>2026-05-21</span><a><a href="/old" title="关于调整地铁14号线定制公交DZ1时间通知">',
            self.holiday: f'<div class="wp_articlecontent">{self.summary}</div>',
        }
        for mocked in (
            patch.object(bus, "regular_timetable_url", return_value=bus.SERVICES),
            patch.object(bus, "fetch", side_effect=lambda url: self.pages[url].encode()),
            patch.object(bus, "open_data", return_value={"2026-11-27": "2", "2026-11-28": "3", "2027-01-01": "1"}),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def timetable(self, day, *args):
        return bus.run(self.cli.parse_args(["bus", "shuttle", "--line", "14", "--date", day, *args]))

    def test_both_directions_weekday_and_weekend(self):
        outbound, inbound = self.timetable("2026-11-27")
        self.assertEqual(outbound["departures"], ["06:50", "08:10", "09:50", "16:10", "17:35", "19:10"])
        self.assertEqual(inbound["departures"], ["07:25", "08:45", "10:25", "16:45", "18:10", "19:45"])
        self.assertEqual(outbound["to"], inbound["from"])
        self.assertEqual(outbound["stop"], "嘉三路近七号楼入口处")
        self.assertIn("翔封路对面", inbound["stop"])
        self.assertIn("到站时间", inbound["notes"])
        weekend, = self.timetable("2026-11-28", "--from", "封浜")
        self.assertEqual(weekend["schedule"], "双休日")
        self.assertEqual(weekend["departures"], inbound["departures"])

    def test_uses_metro14_section_and_makeup_day(self):
        for day, label in (("2026-10-01", "公告指定正常运行"), ("2026-10-10", "工作日")):
            outbound, = self.timetable(day, "--from", "嘉定")
            self.assertEqual(outbound["schedule"], label)
            self.assertEqual(outbound["source"], self.holiday)
            self.assertEqual(len(outbound["departures"]), 6)
        self.pages[self.holiday] = self.pages[self.holiday].replace("国庆节期间正常运行", "具体安排见附图")
        with self.assertRaisesRegex(bus.QueryUnavailable, self.holiday):
            self.timetable("2026-10-01")

    def test_unconfirmed_holiday_and_nonmatching_station(self):
        with self.assertRaisesRegex(bus.QueryUnavailable, bus.INDEX):
            self.timetable("2027-01-01")
        with self.assertRaisesRegex(bus.QueryUnavailable, "嘉定、封浜"):
            self.timetable("2026-11-27", "--from", "上海汽车城")
