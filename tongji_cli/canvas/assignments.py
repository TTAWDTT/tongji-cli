import json
from datetime import datetime, time, timedelta
from urllib.parse import urljoin

from tongji_cli.canvas import api as canvas_api
from tongji_cli.common import SHANGHAI


def assignments(context, day):
    start = datetime.combine(day, time.min, SHANGHAI)
    end = start + timedelta(days=1)
    items = canvas_api.listing(context, "planner/items", {"start_date": start.isoformat(), "end_date": end.isoformat()})
    found = []
    for item in items:
        if item["plannable_type"] != "assignment":
            continue
        task = item["plannable"]
        raw_due = task.get("due_at")
        if not raw_due:
            continue
        due = datetime.fromisoformat(raw_due.replace("Z", "+00:00")).astimezone(SHANGHAI)
        if not start <= due < end:
            continue
        submission = item.get("submissions")
        submitted = submission.get("submitted") if isinstance(submission, dict) else None
        if submitted is None:
            submitted = submission_status(context, item["course_id"], item["plannable_id"])
        found.append({
            "title": task["title"], "course": item.get("context_name"),
            "id": item["plannable_id"], "course_id": item["course_id"],
            "due": due.isoformat(), "url": urljoin(canvas_api.CANVAS, item["html_url"]),
            "submitted": submitted,
        })
    return sorted(found, key=lambda task: task["due"])


def submission_status(context, course_id, assignment_id):
    url = f"{canvas_api.CANVAS}/api/v1/courses/{int(course_id)}/assignments/{int(assignment_id)}/submissions/self"
    response = context.request.get(url, timeout=20000, max_redirects=0)
    if response.ok and "json" in response.headers.get("content-type", ""):
        submission = json.loads(response.text().removeprefix("while(1);"))
        if submission.get("submitted_at"):
            return True
        if submission.get("workflow_state") == "unsubmitted":
            return False
    return None
