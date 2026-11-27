import io
import json
import os
import unittest
from contextlib import redirect_stdout
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tongji_cli.display import display
from tongji_cli.campus import dorm_energy
from tongji_cli.campus import school_calendar
from tongji_cli.common import QueryUnavailable


class EnergySite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        if self.headers.get("Authorization") != "Bearer local-example":
            return self.send_error(403)
        if url.path == dorm_energy.ELECTRICITY and not url.query:
            data = {"elecInfo": {"all": "9.750", "remaining": 0, "used": "9.750"}}
        elif url.path == dorm_energy.ELECTRICITY + "/record" and parse_qs(url.query) == {
                "startDate": ["2026-11-20"], "endDate": ["2026-11-26"]}:
            data = {"elecUsedRecord": {"elecUsedRecord": self.server.rows}}
        else:
            return self.send_error(400)
        data["roomInfoToElectricity"] = self.server.room
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"code": "A00000", "data": data}).encode())


class EnergyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), EnergySite)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.host = patch.object(school_calendar, "API", f"http://127.0.0.1:{cls.server.server_port}")
        cls.host.start()

    @classmethod
    def tearDownClass(cls):
        cls.host.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        env = patch.dict(os.environ, TONGJI_USER_TOKEN="local-example")
        env.start()
        self.addCleanup(env.stop)
        self.server.room = {"accomBuildingName": "示例楼", "accomRoomNo": "示例房间"}
        self.server.rows = [{"rdate": "2026-11-25T16:08:00+00:00", "used": 1.2},
                            {"rdate": "2026-11-19T16:00:00Z", "used": 0},
                            {"rdate": "2026-11-26T16:00:00Z", "used": 2}]

    def read(self, action, start=None, end=None):
        args = SimpleNamespace(operation=action, start_date=start, end_date=end)
        return dorm_energy.energy(args, date(2026, 11, 26))[0]

    def test_authorized_zero_balance_and_room(self):
        info = self.read("electricity")
        self.assertEqual((info["dorm_room"], info["remaining_electricity"], info["purchased_electricity"]),
                         ("示例房间", 0, "9.750"))
        self.server.room = {}
        with self.assertRaisesRegex(QueryUnavailable, "宿舍房间"):
            self.read("electricity")

    def test_room_labels_in_default_output(self):
        with redirect_stdout(io.StringIO()) as output:
            display({"dorm": {"status": "ok", "items": [self.read("electricity")]}}, False)
        self.assertIn("宿舍楼", output.getvalue())
        self.assertIn("宿舍号", output.getvalue())
        self.assertNotIn("教室", output.getvalue())

    def test_default_week_uses_shanghai_days_and_preserves_raw_time(self):
        readings = self.read("usage")["readings"]
        self.assertEqual([(r["date"], r["used_electricity"]) for r in readings],
                         [("2026-11-20", 0), ("2026-11-26", 1.2)])
        self.assertEqual(readings[0]["recorded_at"], self.server.rows[1]["rdate"])
        self.server.rows = []
        self.assertEqual(self.read("usage")["readings"], [])

    def test_missing_permission_and_invalid_dates(self):
        with patch.dict(os.environ, TONGJI_USER_TOKEN=""):
            with self.assertRaisesRegex(QueryUnavailable, "开放平台授权"):
                self.read("electricity")
        with patch.dict(os.environ, TONGJI_USER_TOKEN="not-authorized"):
            with self.assertRaisesRegex(QueryUnavailable, "HTTP 403"):
                self.read("usage")
        with self.assertRaisesRegex(QueryUnavailable, "起始日期"):
            self.read("usage", date(2026, 11, 27), date(2026, 11, 23))
