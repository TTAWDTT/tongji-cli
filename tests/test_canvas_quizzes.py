import json
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queries
from canvas_quizzes import quiz_detail, quiz_submission, quizzes


CLASSIC = "/api/v1/courses/11/quizzes"
ASSIGNMENTS = "/api/v1/courses/11/assignments"
NEW = "/api/quiz/v1/courses/11/quizzes/5"
CLASSIC_ROW = {"id": 5, "title": "第一章", "quiz_type": "assignment", "time_limit": 30, "allowed_attempts": -1,
               "due_at": "2026-11-30T16:00:00Z", "unlock_at": "2026-11-01T00:00:00Z",
               "points_possible": 10, "description": "<p>带草稿纸</p>"}
NEW_ROW = {"id": 5, "name": "新测验", "is_quiz_lti_assignment": True, "description": "见课程说明",
           "allowed_attempts": 99, "points_possible": 5}


class QuizSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.headers.get("User-Agent") != "tongji-quiz-test":
            self.send_error(404)
            return
        self.server.calls.append(self.path)
        resource = urlsplit(self.path)
        response = self.server.responses.get(self.path, self.server.responses.get(resource.path))
        if resource.path == "/api/v1/courses" and parse_qs(resource.query).get("enrollment_state") == ["completed"]:
            response = [{"id": 12, "name": "课程"}]
        if isinstance(response, int) or response is None:
            self.send_error(response or 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if self.path == CLASSIC + "?per_page=100":
            self.send_header("Link", f'<{CLASSIC}?page=2>; rel="next"')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


class QuizTest(unittest.TestCase):
    def setUp(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), QuizSite)
        Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        server.calls = self.calls = []
        server.responses = self.data = {
            "/api/v1/courses": [{"id": 11, "name": "课程"}], CLASSIC: [CLASSIC_ROW],
            CLASSIC + "?page=2": [{"id": 6, "title": "练习"}],
            ASSIGNMENTS: [NEW_ROW, {"id": 7, "name": "其他 LTI", "submission_types": ["external_tool"]}],
            CLASSIC + "/5": CLASSIC_ROW, ASSIGNMENTS + "/5": NEW_ROW,
        }
        origin = patch.object(queries, "CANVAS", f"http://127.0.0.1:{server.server_port}")
        origin.start()
        self.addCleanup(origin.stop)
        pw = sync_playwright().start()
        self.addCleanup(pw.stop)
        browser = pw.chromium.launch(channel="chrome")
        self.addCleanup(browser.close)
        self.ctx = browser.new_context(user_agent="tongji-quiz-test")

    def test_catalog_and_details_keep_engine_ids_separate(self):
        result = quizzes(self.ctx, "课程")
        items = result["items"]
        self.assertEqual(result["sources"]["quizzes"]["status"], "ok")
        self.assertEqual({(r["id"], r["engine"]) for r in items}, {(5, "classic"), (6, "classic"), (5, "new")})
        self.assertIn(ASSIGNMENTS + "?per_page=100", self.calls)
        classic, = quiz_detail(self.ctx, "11", 5)
        self.assertEqual((classic["due"], classic["time_limit_minutes"], classic["allowed_attempts"],
                          classic["instructions"]), ("2026-12-01T00:00:00+08:00", 30, -1, "带草稿纸"))
        self.data[NEW] = {"instructions": "<p>新说明</p>", "quiz_settings": {"has_time_limit": True,
                          "session_time_limit_in_seconds": 90, "student_access_code": "private-code",
                          "multiple_attempts": {"multiple_attempts_enabled": True, "attempt_limit": True,
                                                "max_attempts": 2}}}
        new, = quiz_detail(self.ctx, "11", 5, "new")
        self.assertEqual((new["time_limit_minutes"], new["allowed_attempts"], new["instructions"]), (1.5, 2, "新说明"))
        self.assertNotIn("private-code", str(new))
        self.data[NEW] = 403
        limited, = quiz_detail(self.ctx, "11", 5, "new")
        self.assertIn("403", limited["settings_unavailable"])
        self.assertEqual((limited["instructions"], limited["allowed_attempts"]), ("见课程说明", None))

    def test_completed_course_quiz_list_detail_and_submission(self):
        base = "/api/v1/courses/12"
        self.data.update({base + "/quizzes": [CLASSIC_ROW], base + "/assignments": [],
                          base + "/quizzes/5": CLASSIC_ROW,
                          base + "/quizzes/5/submission": {"quiz_submissions": [{"workflow_state": "complete", "attempt": 2}]}})
        item, = quizzes(self.ctx, "课程", "completed")["items"]
        detail, = quiz_detail(self.ctx, "课程", item["id"], "classic", "completed")
        result, = quiz_submission(self.ctx, "课程", item["id"], "classic", "completed")
        self.assertEqual((item["course_id"], detail["instructions"], result["attempt"]), (12, "带草稿纸", 2))

    def test_restricted_quiz_attempt_separates_gradebook_receipt(self):
        self.data[CLASSIC + "/5"] = dict(CLASSIC_ROW, assignment_id=71)
        self.data[CLASSIC + "/5/submission"] = 401
        self.data[ASSIGNMENTS + "/71/submissions/self"] = {"workflow_state": "graded", "score": 0, "attempt": 2}
        result = quiz_submission(self.ctx, "11", 5)
        item, = result["items"]
        self.assertEqual(result["status"], "partial")
        self.assertNotIn("started_at", item)
        self.assertNotIn("attempt", item)
        receipt = item["assignment_receipt"]
        self.assertEqual((receipt["assignment_id"], receipt["attempt"], receipt["score"]), (71, 2, 0))

    def test_missing_quiz_tab_keeps_quizzes_found_in_assignments(self):
        self.data[CLASSIC] = 404
        self.data[ASSIGNMENTS] = [NEW_ROW, {"id": 71, "quiz_id": 5, "name": "经典测验作业"}]
        result = quizzes(self.ctx, "11")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"]["assignments"]["status"], "ok")
        self.assertIn("404", result["sources"]["quizzes"]["detail"])
        self.assertEqual({(r["id"], r["engine"]) for r in result["items"]}, {(5, "classic"), (5, "new")})
        self.data[ASSIGNMENTS] = []
        self.assertEqual(quizzes(self.ctx, "11")["status"], "partial")
        self.data[ASSIGNMENTS] = 403
        self.assertEqual(quizzes(self.ctx, "11")["status"], "unverified")
        self.data[CLASSIC] = [CLASSIC_ROW]
        self.data[ASSIGNMENTS] = [{"is_quiz_lti_assignment": True, "id": 7}]
        malformed = quizzes(self.ctx, "11")
        self.assertEqual(malformed["status"], "partial")
        self.assertEqual(malformed["sources"]["assignments"]["status"], "unverified")
        self.assertEqual({r["id"] for r in malformed["items"]}, {5, 6})

    def test_current_classic_attempt_and_released_grade(self):
        path = CLASSIC + "/5/submission"
        self.data[path] = {"quiz_submissions": []}
        empty, = quiz_submission(self.ctx, "11", 5)
        self.assertEqual((empty["submission_state"], empty["attempt"]), ("not_started", None))
        sub = {"workflow_state": "complete", "attempt": 2, "started_at": "2026-11-29T02:00:00Z",
               "finished_at": "2026-11-29T03:10:00Z", "attempts_left": 0, "extra_time": 2,
               "score": 9, "validation_token": "private-token"}
        self.data[path] = {"quiz_submissions": [sub], "submissions": [{"score": None, "grade": None}]}
        hidden, = quiz_submission(self.ctx, "11", 5)
        self.assertIsNone(hidden["score"])
        self.data[path]["submissions"] = [{"score": 0, "grade": "0"}]
        row, = quiz_submission(self.ctx, "11", 5)
        self.assertEqual((row["attempt"], row["attempts_left"], row["extra_time_minutes"], row["score"]), (2, 0, 2, 0))
        self.assertEqual(row["submitted_at"], "2026-11-29T11:10:00+08:00")
        self.assertNotIn("private-token", str(row))
        self.assertEqual({urlsplit(url).path for url in self.calls}, {"/api/v1/courses", CLASSIC + "/5", path})

    def test_new_quiz_uses_own_lms_submission(self):
        path = ASSIGNMENTS + "/5/submissions/self"
        self.data[path] = {"workflow_state": "graded", "attempt": 3, "score": 0, "grade": "0"}
        row, = quiz_submission(self.ctx, "11", 5, "new")
        self.assertEqual((row["engine"], row["submission_state"], row["attempt"], row["score"]), ("new", "graded", 3, 0))
        self.assertEqual({urlsplit(url).path for url in self.calls}, {"/api/v1/courses", ASSIGNMENTS + "/5", path})
        self.data[ASSIGNMENTS + "/7"] = {"id": 7, "name": "其他 LTI", "submission_types": ["external_tool"]}
        with self.assertRaisesRegex(queries.QueryUnavailable, "不是 Canvas 新测验"):
            quiz_submission(self.ctx, "11", 7, "new")
        self.assertNotIn(ASSIGNMENTS + "/7/submissions/self", self.calls)
