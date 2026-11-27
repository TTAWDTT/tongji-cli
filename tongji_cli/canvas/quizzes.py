from tongji_cli.canvas import api as canvas_api
from playwright.sync_api import Error as BrowserError
from tongji_cli.canvas.api import PlainText, courses, endpoint, listing, local_timestamp, request, select_course
from tongji_cli.common import QueryUnavailable


def quizzes(context, selector, state="active"):
    course = select_course(courses(context, state), selector, state)
    base = f"courses/{course['id']}"
    items = {}
    sources = {}
    for source in ("quizzes", "assignments"):
        try:
            for row in listing(context, f"{base}/{source}"):
                if source == "quizzes":
                    items["classic", row["id"]] = quiz_item(row, course, "classic")
                elif row.get("is_quiz_lti_assignment"):
                    items["new", row["id"]] = quiz_item(row, course, "new")
                elif row.get("quiz_id") and ("classic", row["quiz_id"]) not in items:
                    item = dict(row, id=row["quiz_id"], title=row["name"], html_url=f"{course['url']}/quizzes/{row['quiz_id']}")
                    items["classic", row["quiz_id"]] = dict(quiz_item(item, course, "classic"), source="assignments")
        except QueryUnavailable as exc:
            sources[source] = {"status": "unverified", "detail": str(exc)}
        except (BrowserError, ValueError, TypeError, KeyError):
            sources[source] = {"status": "unverified", "detail": "Canvas 响应未能读取或与测验格式不符"}
        else:
            sources[source] = {"status": "ok"}
    result = {"sources": sources, "items": sorted(items.values(), key=lambda item:
              (item["due"] is None, item["due"] or "", item["title"]))}
    failed = [f"{name}：{s['detail']}" for name, s in sources.items() if s["status"] == "unverified"]
    if failed:
        result.update(status="partial" if items or len(failed) < len(sources) else "unverified",
                      detail="；".join(failed))
    return result


def quiz_detail(context, selector, quiz_id, engine="classic", state="active"):
    course = select_course(courses(context, state), selector, state)
    row = read_quiz(context, course, quiz_id, engine)
    item = quiz_item(row, course, engine)
    item["instructions"] = PlainText.from_html(row.get("description"))
    if engine == "new":
        url = f"{canvas_api.CANVAS}/api/quiz/v1/courses/{course['id']}/quizzes/{quiz_id}"
        try:
            detail, _ = request(context, url)
        except QueryUnavailable as error:
            item["settings_unavailable"] = str(error)
        else:
            if detail.get("instructions"):
                item["instructions"] = PlainText.from_html(detail["instructions"])
            settings = detail.get("quiz_settings")
            if settings is None:
                item["settings_unavailable"] = "Canvas 未返回新测验设置"
            else:
                item.update(new_quiz_limits(settings))
    return [item]


def quiz_submission(context, selector, quiz_id, engine="classic", state="active"):
    course = select_course(courses(context, state), selector, state)
    row = read_quiz(context, course, quiz_id, engine)
    item = quiz_item(row, course, engine)
    base = f"courses/{course['id']}"
    if engine == "new":
        item.update(assignment_receipt(context, base, quiz_id))
    else:
        path = f"{base}/quizzes/{quiz_id}/submission"
        try:
            data, _ = request(context, endpoint(path, {"include[]": "submission"}))
        except QueryUnavailable as error:
            if not row.get("assignment_id"):
                raise
            item["assignment_receipt"] = assignment_receipt(context, base, row["assignment_id"])
            return {"status": "partial", "items": [item], "detail": f"测验尝试查询失败，已取得本人作业回执。{error}"}
        current = data["quiz_submissions"]
        sub = current[0] if current else {}
        # A graded quiz uses the grade released to the student in the Canvas gradebook.
        grades = data.get("submissions") or []
        grade = grades[0] if grades else {}
        score = grade.get("score")
        if row.get("quiz_type") == "practice_quiz" and not row.get("hide_results") and not row.get("one_time_results"):
            score = sub.get("kept_score", sub.get("score"))
        item.update(submission_state=sub["workflow_state"] if current else "not_started", attempt=sub.get("attempt"),
                    started_at=local_timestamp(sub.get("started_at")), submitted_at=local_timestamp(sub.get("finished_at")),
                    end_at=local_timestamp(sub.get("end_at")), extra_time_minutes=sub.get("extra_time"),
                    attempts_left=sub.get("attempts_left"), score=score, grade=grade.get("grade"))
    return [item]


def assignment_receipt(context, base, assignment_id):
    sub, _ = request(context, endpoint(f"{base}/assignments/{assignment_id}/submissions/self", {}))
    return {"assignment_id": assignment_id, "submission_state": sub["workflow_state"], "attempt": sub.get("attempt"),
            "submitted_at": local_timestamp(sub.get("submitted_at")), "score": sub.get("score"), "grade": sub.get("grade")}


def read_quiz(context, course, quiz_id, engine):
    resource = "quizzes" if engine == "classic" else "assignments"
    path = f"courses/{course['id']}/{resource}/{quiz_id}"
    row, _ = request(context, endpoint(path, {}))
    if engine == "new" and not row.get("is_quiz_lti_assignment"):
        raise QueryUnavailable("此作业不是 Canvas 新测验，请用测验目录中的 ID 和 engine")
    return row


def quiz_item(row, course, engine):
    classic = engine == "classic"
    resource = "quizzes" if classic else "assignments"
    return {"course_id": course["id"], "course": course["title"], "id": row["id"], "engine": engine,
            "title": row["title"] if classic else row["name"], "due": local_timestamp(row.get("due_at")),
            "unlock_at": local_timestamp(row.get("unlock_at")), "lock_at": local_timestamp(row.get("lock_at")),
            "locked": row.get("locked_for_user"), "points_possible": row.get("points_possible"),
            "time_limit_minutes": row.get("time_limit") if classic else None,
            "allowed_attempts": row.get("allowed_attempts") if classic else None,
            "url": row.get("html_url") or f"{course['url']}/{resource}/{row['id']}"}


def new_quiz_limits(settings):
    seconds = settings.get("session_time_limit_in_seconds") if settings.get("has_time_limit") else None
    multiple = settings.get("multiple_attempts") or {}
    allowed = None
    if multiple.get("multiple_attempts_enabled") is False:
        allowed = 1
    elif multiple.get("multiple_attempts_enabled") is True:
        if multiple.get("attempt_limit") is False:
            allowed = -1
        elif multiple.get("attempt_limit") is True:
            allowed = multiple.get("max_attempts")
    return {"time_limit_minutes": seconds / 60 if seconds is not None else None, "allowed_attempts": allowed}
