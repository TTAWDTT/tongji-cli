import json
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queries
from canvas_api import courses, syllabus
from canvas_grades import grades, grading, rubric


class GradeSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urlsplit(self.path)
        params = parse_qs(url.query)
        included = params.get("include[]", [])
        link = None
        task = {"id": 13, "name": "实验报告", "html_url": "/courses/1/assignments/13", "points_possible": 10}
        if url.path == "/api/v1/courses" and params.get("enrollment_state") == ["completed"]:
            if params.get("enrollment_type") != ["student"]:
                return self.send_error(400)
            second = params.get("page") == ["2"]
            if not second:
                link = f'<{self.path}&page=2>; rel="next"'
            data = [{"id": 22 if second else 21, "name": "学科1", "course_code": "HIST",
                     "term": {"name": "上学期"} if "term" in included else None,
                     "enrollments": [{"type": "student", "computed_current_score": 88}]}]
        elif url.path == "/api/v1/courses":
            if params.get("enrollment_type") != ["student"] or params.get("enrollment_state") != ["active"]:
                return self.send_error(400)
            entries = [{"type": "student", "computed_current_score": 0, "computed_final_grade": "C",
                        "unposted_current_score": 63}, {"type": "teacher", "computed_current_score": 100}]
            data = [{"id": n, "name": f"学科{n}", "course_code": f"SE{n}", "hide_final_grades": n == 2,
                     "enrollments": entries if "total_scores" in included else []} for n in [1, 2, 3]]
            data[-1]["restrict_quantitative_data"] = "restrict_quantitative_data" in included
            data[-1]["enrollments"] = [dict(entries[0], computed_current_letter_grade="B")]
        elif url.path == "/api/v1/courses/1":
            data = {"apply_assignment_group_weights": self.server.weighted}
            if "syllabus_body" in included:
                data["syllabus_body"] = self.server.syllabus
        elif url.path == "/api/v1/courses/1/assignment_groups":
            if set(included) != {"assignments", "submission"}:
                return self.send_error(400)
            item = dict(task, submission={"posted_at": None, "score": 99, "grade": "99"})
            if params.get("page") != ["2"]:
                link = f'<{url.path}?include%5B%5D=assignments&include%5B%5D=submission&page=2>; rel="next"'
                data = [{"id": 2, "name": "实验", "group_weight": 70,
                         "assignments": [item, dict(task, id=14, submission={"score": 99, "grade": "99"})],
                         "rules": {"drop_lowest": 1, "never_drop": [13]}}]
            else:
                item.update(id=17, name="期末", submission={"posted_at": "2026-11-26T00:00:00Z", "score": 0, "grade": "F"})
                data = [{"id": 3, "name": "期末", "group_weight": 30, "assignments": [item]}]
        elif url.path == "/api/v1/courses/1/assignments/13":
            data = dict(task, **self.server.rubric)
        else:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if link:
            self.send_header("Link", link)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


class GradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), GradeSite)
        Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.host = patch.object(queries, "CANVAS", f"http://127.0.0.1:{cls.server.server_port}")
        cls.host.start()
        cls.pw = sync_playwright().start()
        cls.client = cls.pw.request.new_context()
        cls.ctx = SimpleNamespace(request=cls.client)

    @classmethod
    def tearDownClass(cls):
        cls.client.dispose()
        cls.pw.stop()
        cls.host.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def test_visible_course_totals_and_hidden_or_restricted_marks(self):
        first, hidden, restricted = grades(self.ctx)
        self.assertEqual(first["marks"], [{"current_score": 0, "current_grade": None, "final_score": None, "final_grade": "C"}])
        self.assertTrue(hidden["totals_hidden"])
        self.assertEqual(hidden["marks"], [])
        self.assertIsNone(restricted["marks"][0]["current_score"])
        self.assertEqual(restricted["marks"][0]["current_grade"], "B")
        self.assertEqual(grades(self.ctx, "SE1"), [first])

    def test_completed_courses_are_paged_and_selected_within_state(self):
        history = courses(self.ctx, "completed")
        self.assertEqual([(c["id"], c["term"]) for c in history], [(21, "上学期"), (22, "上学期")])
        self.assertEqual([c["id"] for c in courses(self.ctx)], [1, 2, 3])
        with self.assertRaisesRegex(queries.QueryUnavailable, "canvas courses --state completed"):
            grades(self.ctx, "学科1", "completed")
        selected, = grades(self.ctx, "22", "completed")
        self.assertEqual(selected["marks"][0]["current_score"], 88)
        self.assertEqual(grades(self.ctx, "学科1")[0]["course_id"], 1)
        with self.assertRaises(queries.QueryUnavailable):
            grades(self.ctx, "22")

    def test_paged_groups_keep_rules_and_published_zero(self):
        self.server.weighted = True
        report, = grading(self.ctx, "SE1")
        lab, exam = report["groups"]
        self.assertEqual((lab["weight_percent"], lab["drop_lowest"], lab["never_drop"]), (70, 1, [13]))
        self.assertIsNone(lab["assignments"][0]["score"])
        self.assertIsNone(lab["assignments"][0]["grade"])
        self.assertIsNone(lab["assignments"][1]["score"])
        self.assertIsNone(lab["assignments"][1]["grade"])
        self.assertEqual(exam["assignments"][0]["score"], 0)
        self.server.weighted = False
        report, = grading(self.ctx, "SE1")
        self.assertIsNone(report["groups"][0]["weight_percent"])

    def test_rubric_scores_and_advisory_scale(self):
        self.server.rubric = {}
        self.assertIsNone(rubric(self.ctx, "SE1", 13)[0]["rubric"])
        settings = {"title": "实验标准", "points_possible": 5, "hide_score_total": True}
        self.server.rubric = {"rubric_settings": settings, "use_rubric_for_grading": False,
                              "rubric": [{"id": "c", "description": "过程", "points": 5,
                                          "ratings": [{"id": "r", "description": "未说明", "points": 0}]}]}
        scale = rubric(self.ctx, "1", 13)[0]["rubric"]
        self.assertFalse(scale["used_for_grading"])
        self.assertIsNone(scale["points_possible"])
        self.assertEqual(scale["criteria"][0]["ratings"][0]["points"], 0)
        settings["hide_points"] = True
        scale = rubric(self.ctx, "1", 13)[0]["rubric"]
        self.assertIsNone(scale["criteria"][0]["points"])
        self.assertIsNone(scale["criteria"][0]["ratings"][0]["points"])
        settings.update(hide_points=False, free_form_criterion_comments=True)
        criterion, = rubric(self.ctx, "1", 13)[0]["rubric"]["criteria"]
        self.assertEqual((criterion["points"], criterion["ratings"]), (5, []))

    def test_syllabus_content_resources_and_empty(self):
        self.server.syllabus = '<p>每周实验</p><a href="/files/5">材料</a><img src="img.png" alt="课程图"><a href="javascript:x">链接</a>'
        row, = syllabus(self.ctx, "SE1")
        self.assertTrue(row["has_content"])
        self.assertIn("每周实验", row["body"])
        self.assertEqual([(r["kind"], urlsplit(r["url"]).path) for r in row["resources"]],
                         [("a", "/files/5"), ("img", "/courses/1/assignments/img.png")])
        self.server.syllabus = "<p> </p>"
        self.assertFalse(syllabus(self.ctx, "SE1")[0]["has_content"])
