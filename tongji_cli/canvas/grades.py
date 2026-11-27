from tongji_cli.canvas.api import course_info, courses, endpoint, enrolled_courses, listing, request, select_course


def grades(context, selector=None, state="active"):
    rows = list(enrolled_courses(context, ["total_scores", "restrict_quantitative_data"], state))
    if selector is not None:
        chosen = select_course([course_info(row) for row in rows], selector, state)
        rows = [row for row in rows if row["id"] == chosen["id"]]
    result = []
    for row in rows:
        course = course_info(row)
        hidden = row.get("hide_final_grades")
        marks = []
        for entry in row.get("enrollments") or []:
            if hidden or entry["type"] != "student":
                continue
            mark = {key: entry.get("computed_" + key) for key in ("current_score", "current_grade", "final_score", "final_grade")}
            if row.get("restrict_quantitative_data"):
                mark.update(current_score=None, final_score=None,
                            current_grade=entry.get("computed_current_letter_grade") or mark["current_grade"])
            marks.append(mark)
        result.append({"course_id": course["id"], "course": course["title"], "totals_hidden": hidden,
                       "marks": marks, "url": course["url"] + "/grades"})
    return result


def grading(context, selector, state="active"):
    course = select_course(courses(context, state), selector, state)
    base = f"courses/{course['id']}"
    info, _ = request(context, endpoint(base, {"include[]": "restrict_quantitative_data"}))
    weighted = info.get("apply_assignment_group_weights")
    groups = []
    for row in listing(context, base + "/assignment_groups", {"include[]": ["assignments", "submission"]}):
        rules = row.get("rules") or {}
        groups.append({"id": row["id"], "title": row["name"], "weight_percent": row.get("group_weight") if weighted else None,
                       "drop_lowest": rules.get("drop_lowest", 0), "drop_highest": rules.get("drop_highest", 0),
                       "never_drop": rules.get("never_drop") or [],
                       "assignments": [assignment_grade(task, info.get("restrict_quantitative_data")) for task in row["assignments"]]})
    return [{"course_id": course["id"], "course": course["title"], "weighted": weighted,
             "groups": groups, "url": course["url"] + "/assignments"}]


def assignment_grade(task, restrict_points):
    sub = task.get("submission") or {}
    published = bool(sub.get("posted_at"))
    restrict_points = restrict_points or task.get("restrict_quantitative_data")
    return {"id": task["id"], "title": task["name"], "url": task.get("html_url"),
            "points_possible": None if restrict_points else task.get("points_possible"),
            "score": sub.get("score") if published and not restrict_points else None,
            "grade": sub.get("grade") if published and not (restrict_points and task.get("grading_type") in {"points", "percent"}) else None,
            "submission_state": sub.get("workflow_state"), "excused": sub.get("excused"),
            "omit_from_final_grade": task.get("omit_from_final_grade")}


def rubric(context, selector, task_id, state="active"):
    course = select_course(courses(context, state), selector, state)
    data, _ = request(context, endpoint(f"courses/{course['id']}/assignments/{task_id}", {}))
    item = {"course_id": course["id"], "id": data["id"], "title": data["name"], "url": data["html_url"]}
    if data.get("rubric") is None:
        return [dict(item, rubric=None)]
    settings = data.get("rubric_settings") or {}
    hide_points = settings.get("hide_points") or data.get("restrict_quantitative_data")
    free_form = settings.get("free_form_criterion_comments", data.get("free_form_criterion_comments"))
    criteria = []
    for row in data["rubric"]:
        criterion = {key: row.get(key) for key in ("id", "description", "long_description", "criterion_use_range", "ignore_for_scoring")}
        criterion["points"] = None if hide_points else row.get("points")
        criterion["ratings"] = [{"id": r["id"], "description": r.get("description"),
                                 "long_description": r.get("long_description"), "points": None if hide_points else r.get("points")}
                                for r in (row["ratings"] if not free_form else [])]
        criteria.append(criterion)
    return [dict(item, rubric={"title": settings.get("title"), "used_for_grading": data.get("use_rubric_for_grading"),
                               "points_possible": None if hide_points or settings.get("hide_score_total") else settings.get("points_possible"),
                               "free_form_comments": free_form, "criteria": criteria})]
