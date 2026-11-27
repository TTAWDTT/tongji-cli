import json
import os
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_calendar as calendar


class Rooms(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        key = (url.path.rsplit("/", 1)[-1], url.query)
        if self.headers.get("Authorization") != "Bearer local-test":
            self.send_error(403)
            return
        if key == ("all_classroom_list", "campus=3"):
            data = {"list": [{"name": "教学楼", "campusI18n": "嘉定", "code": "01_A"}], "total_": 1}
        elif key == ("get_classroom_by_tower", "towerCode=01_A"):
            data = {"list": [{"name": "301", "towerName": "教学楼", "id": 17, "campusI18n": "嘉定"}],
                    "total_": self.server.count}
        elif key == ("get_timetable_by_classroom", "classroomIds=17"):
            data = {"data": [{"classroomName": "301", "calendarName": "秋季", "classroomOccupationList": []}]}
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"code": "A00000", "data": data}).encode())


class RoomTest(unittest.TestCase):
    def test_directory_ids_feed_schedule(self):
        with ThreadingHTTPServer(("127.0.0.1", 0), Rooms) as server:
            server.count = 1
            Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch.object(calendar, "API", f"http://127.0.0.1:{server.server_port}"), patch.dict(
                    os.environ, TONGJI_OPEN_TOKEN="local-test"
                ):
                    building, = calendar.room_directory(campus="嘉定")
                    room, = calendar.room_directory(building=building["code"])
                    schedule, = calendar.room_schedule(room["id"], None)
                    self.assertEqual(schedule["room"], room["room"])
                    server.count = 2
                    with self.assertRaisesRegex(calendar.QueryUnavailable, "记录数"):
                        calendar.room_directory(building=building["code"])
            finally:
                server.shutdown()
