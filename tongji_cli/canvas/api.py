import json
import os
import re
from datetime import datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlencode, urljoin, urlsplit

from tongji_cli.common import QueryUnavailable, SHANGHAI

CANVAS = "https://canvas.tongji.edu.cn"


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"p", "li", "div", "tr"}:
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        resource = fields.get({"a": "href", "img": "src"}.get(tag))
        if resource:
            self.links.append((tag, resource, fields.get("alt") or fields.get("title")))
        if tag in {"p", "br", "li", "div", "tr"}:
            self.parts.append("\n")

    @classmethod
    def from_html(cls, value):
        parser = cls()
        parser.feed(value or "")
        return parser.text()

    def text(self):
        return "\n".join(line.strip() for line in "".join(self.parts).splitlines() if line.strip())

    @classmethod
    def document(cls, html, base_url):
        content = cls()
        content.feed(html or "")
        resources = [{"kind": tag, "url": urljoin(base_url, url), "label": label}
                     for tag, url, label in content.links
                     if urlsplit(urljoin(base_url, url)).scheme in {"https", "http"}]
        return {"body": content.text(), "resources": resources}


def endpoint(path, params):
    query = urlencode(params, doseq=True)
    return f"{CANVAS}/api/v1/{path}" + ("?" + query if query else "")


def request(context, url):
    if urlsplit(url)[:2] != urlsplit(CANVAS)[:2]:
        raise QueryUnavailable("Canvas 分页地址异常")
    response = context.request.get(url, timeout=20000, max_redirects=0)
    if not response.ok or "json" not in response.headers.get("content-type", ""):
        raise QueryUnavailable(f"Canvas 未能读取此资源（HTTP {response.status}）")
    return json.loads(response.text().removeprefix("while(1);")), response.headers


def listing(context, path, params=None):
    url = endpoint(path, {"per_page": 100, **(params or {})})
    while url:
        data, headers = request(context, url)
        if not isinstance(data, list):
            raise QueryUnavailable("Canvas 列表格式待核实")
        yield from data
        link = re.search(r'<([^>]+)>;\s*rel="next"', headers.get("link", ""))
        url = urljoin(url, link[1]) if link else None


def enrolled_courses(context, include=(), state="active"):
    params = {"enrollment_type": "student", "enrollment_state": state, "include[]": include}
    return (c for c in listing(context, "courses", params) if "name" in c)


def course_info(course):
    return {"id": course["id"], "title": course["name"], "code": course.get("course_code"),
            "url": f"{CANVAS}/courses/{course['id']}"}


def courses(context, state="active"):
    if state == "completed":
        return [dict(course_info(c), term=(c.get("term") or {}).get("name"))
                for c in enrolled_courses(context, ["term"], state)]
    return [course_info(c) for c in enrolled_courses(context, state=state)]


def select_course(available, selector, state="active"):
    term = selector.strip().casefold()
    matches = [c for c in available if term in {str(c["id"]), c["title"].casefold(), (c["code"] or "").casefold()}]
    if not matches:
        matches = [c for c in available if term in c["title"].casefold()]
    if len(matches) != 1:
        command = "canvas courses --state completed" if state == "completed" else "canvas courses"
        raise QueryUnavailable(f"未匹配到唯一课程，请用 {command} 返回的课程 ID")
    return matches[0]


def local_timestamp(value):
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(SHANGHAI).isoformat()
    return None


def assignment(data, course):
    sub = data.get("submission") or {}
    submitted = None
    if sub.get("submitted_at") or sub.get("workflow_state") == "submitted":
        submitted = True
    elif sub.get("workflow_state") == "unsubmitted":
        submitted = False
    return {"id": data["id"], "title": data["name"], "course_id": course["id"], "course": course["title"],
            "due": local_timestamp(data.get("due_at")), "submitted": submitted,
            "submission_state": sub.get("workflow_state"), "url": data["html_url"]}


def tasks(context, start_day, days, selector=None, overdue=False, state="active"):
    available = courses(context, state)
    if selector:
        available = [select_course(available, selector, state)]
    start = datetime.combine(start_day, time.min, SHANGHAI).isoformat()
    end = datetime.combine(start_day + timedelta(days=days), time.min, SHANGHAI).isoformat() if days else None
    result = []
    as_of = datetime.now(SHANGHAI).isoformat()
    for course in available:
        for row in listing(context, f"courses/{course['id']}/assignments", {"include[]": "submission"}):
            if days or overdue:
                kinds = row.get("submission_types") or []
                if (row.get("is_quiz_assignment") or row.get("is_quiz_lti_assignment")
                        or row.get("is_new_quiz") or row.get("quiz_id")
                        or "online_quiz" in kinds or "discussion_topic" in kinds):
                    continue
            item = assignment(row, course)
            due = item["due"]
            if overdue:
                excused = (row.get("submission") or {}).get("excused")
                if excused or not (due and due < as_of and item["submitted"] is False):
                    continue
            elif days and not (due and start <= due < end):
                continue
            result.append(item)
    return sorted(result, key=lambda item: (item["due"] is None, item["due"] or "", item["title"]))


def show_assignment(context, selector, task_id, state="active"):
    course = select_course(courses(context, state), selector, state)
    path = f"courses/{course['id']}/assignments/{task_id}"
    data, _ = request(context, endpoint(path, {"include[]": "submission"}))
    return [{**assignment(data, course), "instructions": PlainText.from_html(data.get("description")),
             "submission_types": data.get("submission_types", [])}]


def announcements(context, since_days, now, selector=None, state="active", *, group=None):
    start = datetime.combine(now.date() - timedelta(days=since_days - 1), time.min, SHANGHAI)
    if group is not None:
        return group_announcements(context, group, start, now)
    available = courses(context, state)
    if selector is not None:
        available = [select_course(available, selector, state)]
    names = {f"course_{c['id']}": c['title'] for c in available}
    if not names:
        return []
    params = {"context_codes[]": list(names), "start_date": start.isoformat(), "end_date": now.isoformat(),
              "active_only": "true"}
    items = [{"course": names[row["context_code"]], "title": row["title"],
              "posted": local_timestamp(row["posted_at"]), "url": row["html_url"],
              "body": PlainText.from_html(row.get("message"))} for row in listing(context, "announcements", params)]
    return sorted(items, key=lambda item: item["posted"], reverse=True)


def group_announcements(context, group, start, end):
    path = f"groups/{group['id']}/discussion_topics"
    items = []
    for row in listing(context, path, {"only_announcements": "true"}):
        published_at = row.get("delayed_post_at") or row.get("posted_at")
        if row.get("published") is False or not published_at:
            continue
        posted = local_timestamp(published_at)
        if start <= datetime.fromisoformat(posted) <= end:
            items.append({"group_id": group["id"], "group_name": group["title"], "title": row["title"],
                          "posted": posted, "url": row["html_url"], "body": PlainText.from_html(row.get("message"))})
    return sorted(items, key=lambda item: item["posted"], reverse=True)


def materials(context, selector, state="active"):
    course = select_course(courses(context, state), selector, state)
    base = f"courses/{course['id']}"
    found = []
    module_files = set()
    for module in listing(context, base + "/modules"):
        for item in listing(context, f"{base}/modules/{module['id']}/items"):
            found.append({"module": module["name"], "title": item["title"], "type": item["type"],
                          "url": item.get("html_url") or item.get("external_url"),
                          "file_id": item.get("content_id") if item["type"] == "File" else None,
                          "slug": item.get("page_url") if item["type"] == "Page" else None})
            if item["type"] == "File":
                module_files.add(item.get("content_id"))
    for file in listing(context, base + "/files"):
        if file["id"] not in module_files:
            found.append({"module": None, "title": file["display_name"], "type": "File", "file_id": file["id"],
                          "url": f"{CANVAS}/{base}/files/{file['id']}"})
    return found


def planner(context, start_day, days):
    start = datetime.combine(start_day, time.min, SHANGHAI)
    end = start + timedelta(days=days)
    params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
    items = []
    for row in listing(context, "planner/items", params):
        date = local_timestamp(row["plannable_date"])
        if not start.isoformat() <= date < end.isoformat():
            continue
        item = row["plannable"]
        link = row.get("html_url")
        items.append({"id": row["plannable_id"], "type": row["plannable_type"], "title": item.get("title"),
                      "scheduled": date, "due": local_timestamp(item.get("due_at")),
                      "course_id": row.get("course_id"), "course": row.get("context_name"),
                      "url": urljoin(CANVAS, link) if link else None})
    return sorted(items, key=lambda item: item["scheduled"])


def course_pages(context, selector, slug=None, state="active"):
    course = select_course(courses(context, state), selector, state)
    return scoped_pages(context, "courses", course, slug)


def scoped_pages(context, scope, owner, slug):
    path = f"{scope}/{owner['id']}/pages"
    fields = ({"course": owner["title"], "course_id": owner["id"]} if scope == "courses"
              else {"group_name": owner["title"], "group_id": owner["id"]})
    if slug is None:
        pages = listing(context, path)
    else:
        detail, _ = request(context, endpoint(f"{path}/{quote(slug, safe='')}", {}))
        pages = [detail]
    items = []
    for page in pages:
        item = {**fields, "title": page["title"], "slug": page["url"], "url": page["html_url"],
                "updated": local_timestamp(page.get("updated_at"))}
        if slug is not None:
            item.update(PlainText.document(page.get("body"), page["html_url"]))
            item["locked"] = page.get("locked_for_user")
        items.append(item)
    return items


def syllabus(context, selector, state="active"):
    course = select_course(courses(context, state), selector, state)
    data, _ = request(context, endpoint(f"courses/{course['id']}", {"include[]": "syllabus_body"}))
    url = course["url"] + "/assignments/syllabus"
    content = PlainText.document(data.get("syllabus_body"), url)
    return [{"course_id": course["id"], "course": course["title"], "url": url,
             "has_content": bool(content["body"] or content["resources"]), **content}]


class _EntryText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lines = []
        self.inline = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.inline.append(None)
        elif tag in {"p", "div"} and self.inline:
            self.end_block()

    def handle_endtag(self, tag):
        if tag in {"p", "div"}:
            self.end_block()

    def handle_data(self, data):
        # TinyMCE serializes sibling paragraphs with a formatting newline.
        if not self.inline and self.lines and data.isspace() and "\n" in data:
            return
        self.inline.append(data)

    def end_block(self, caret_placeholder=True):
        # A final <br> inside a paragraph holds the caret, including in an empty paragraph.
        if caret_placeholder and self.inline and self.inline[-1] is None:
            self.inline.pop()
        self.lines.append("".join("\n" if part is None else part for part in self.inline))
        self.inline.clear()


def submission_text(html):
    parser = _EntryText()
    parser.feed(html or "")
    parser.close()
    if parser.inline:
        parser.end_block(caret_placeholder=False)
    return "\n".join(parser.lines).replace("\xa0", " ")


def submission_record(context, selector, task_id, state, *, history=False):
    course = select_course(courses(context, state), selector, state)
    path = f"courses/{course['id']}/assignments/{task_id}/submissions/self"
    data, _ = request(context, endpoint(path, {"include[]": "submission_history" if history else "submission_comments"}))
    if data.get("assignment_id") != task_id:
        raise QueryUnavailable("Canvas 返回的本人提交记录与所选作业不符")
    return course, data


def attachment_details(files):
    return [{"id": f.get("id"), "name": f.get("display_name"), "bytes": f.get("size")} for f in files or []]


def submitted_attempts(data):
    history = data.get("submission_history")
    if not isinstance(history, list):
        raise QueryUnavailable("Canvas 未提供本人提交的尝试历史")
    return sorted((row for row in history if row.get("attempt") and row.get("submitted_at")),
                  key=lambda row: row["attempt"])


def own_submission(context, selector, task_id, state="active", *, history=False):
    course, data = submission_record(context, selector, task_id, state, history=history)
    if history:
        return [submission_item(course, task_id, row) for row in submitted_attempts(data)]
    item = submission_item(course, task_id, data)
    comments = [{"author": c.get("author_name"), "comment": c.get("comment"),
                 "created": local_timestamp(c.get("created_at")),
                 "attachments": [a.get("display_name") for a in c.get("attachments") or []],
                 "attachment_details": attachment_details(c.get("attachments"))}
                for c in data.get("submission_comments") or []]
    return [dict(item, feedback=comments)]


def submission_item(course, task_id, data):
    item = {"course": course["title"], "course_id": course["id"], "id": task_id,
             "submission_type": data.get("submission_type"),
             "submission_state": data["workflow_state"], "attempt": data.get("attempt"),
             "submitted_at": local_timestamp(data.get("submitted_at")), "late": data.get("late"),
             "grade": data.get("grade"), "score": data.get("score"),
             "attachments": [a.get("display_name") for a in data.get("attachments") or []],
             "attachment_details": attachment_details(data.get("attachments")),
             "url": f"{course['url']}/assignments/{task_id}"}
    if data.get("submission_type") == "online_text_entry":
        item["body"] = submission_text(data["body"]) if data.get("body") is not None else None
        item["body_html"] = data.get("body")
    elif data.get("submission_type") == "online_url":
        item["submission_url"] = data.get("url")
    return item


def download_submission_attachment(context, selector, task_id, attachment_id, output, state="active", *, attempt=None):
    course, data = submission_record(context, selector, task_id, state, history=attempt is not None)
    if attempt is not None:
        matches = [row for row in submitted_attempts(data) if row["attempt"] == attempt]
        if len(matches) != 1:
            raise QueryUnavailable("提交历史中没有唯一匹配的尝试，请用 canvas submission --history 核对")
        data = matches[0]
    groups = [("submission", data.get("attachments"))]
    if attempt is None:
        groups.extend(("feedback", c.get("attachments")) for c in data.get("submission_comments") or [])
    for source, files in groups:
        for file in files or []:
            if file.get("id") == attachment_id:
                path = save_canvas_file(context, file, output)
                return [{"course_id": course["id"], "assignment_id": task_id, "attachment_id": attachment_id,
                         "source": source, "attempt": data.get("attempt") if source == "submission" else None,
                         "title": file["display_name"], "bytes": file["size"], "path": str(path)}]
    raise QueryUnavailable("所选提交记录中没有该附件编号，请用 canvas submission 核对")


def course_files(context, selector, state="active"):
    course = select_course(courses(context, state), selector, state)
    return scoped_files(context, "courses", course["id"])


def scoped_files(context, scope, owner_id):
    path = f"{scope}/{owner_id}/files"
    owner = "course_id" if scope == "courses" else "group_id"
    return [{"id": f["id"], "title": f["display_name"], "bytes": f["size"], "mime": f.get("content-type"),
             owner: owner_id, "url": f"{CANVAS}/{path}/{f['id']}"}
            for f in listing(context, path)]


def download_file(context, selector, file_id, output, state="active"):
    course = select_course(courses(context, state), selector, state)
    return download_scoped_file(context, "courses", course["id"], file_id, output)


def download_scoped_file(context, scope, owner_id, file_id, output):
    path = f"{scope}/{owner_id}/files/{file_id}"
    file, _ = request(context, endpoint(path, {}))
    dest = save_canvas_file(context, file, output)
    owner = "course_id" if scope == "courses" else "group_id"
    return [{"id": file_id, owner: owner_id, "title": file["display_name"],
             "bytes": file["size"], "path": str(dest), "url": f"{CANVAS}/{path}"}]


def save_canvas_file(context, file, output):
    if file.get("locked_for_user") or not file.get("url"):
        raise QueryUnavailable("此文件尚未开放下载")
    if not isinstance(file.get("size"), int) or file["size"] < 0:
        raise QueryUnavailable("Canvas 未提供可核对的文件大小")
    dest = Path(output).expanduser().absolute()
    if dest.exists():
        raise QueryUnavailable("目标文件已存在，请选择另一文件名")
    if not dest.parent.is_dir():
        raise QueryUnavailable("目标目录不存在")
    with TemporaryDirectory(dir=dest.parent) as tmp:
        staging = Path(tmp) / "download"
        page = context.new_page()
        try:
            with page.expect_download(timeout=45000) as pending:
                page.evaluate("""url => {
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = '';
                    document.body.append(a);
                    a.click();
                }""", file["url"])
            pending.value.save_as(staging)
            if staging.stat().st_size != file["size"]:
                raise QueryUnavailable("下载字节数与 Canvas 文件信息不符")
            os.link(staging, dest)
        finally:
            page.close()
    return dest


def calendar_events(context, start_day, days, selector=None):
    start = datetime.combine(start_day, time.min, SHANGHAI)
    end = start + timedelta(days=days) - timedelta(seconds=1)
    params = {"start_date": start.isoformat(), "end_date": end.isoformat()}
    if selector:
        course = select_course(courses(context), selector)
        params["context_codes[]"] = f"course_{course['id']}"
    items = []
    for kind in ("event", "assignment"):
        for row in listing(context, "calendar_events", {**params, "type": kind}):
            items.append({"id": row["id"], "type": kind, "title": row["title"],
                          "start": local_timestamp(row.get("start_at")), "end": local_timestamp(row.get("end_at")),
                          "all_day": row.get("all_day"), "date": row.get("all_day_date"),
                          "context": row.get("context_code"), "location": row.get("location_name"),
                          "url": row.get("html_url")})
    return sorted(items, key=lambda item: (item["start"] or item["date"] or "", item["title"]))


def discussion_context(context, selector, state, group):
    if group is not None:
        return "groups", group
    return "courses", select_course(courses(context, state), selector, state)


def discussions(context, selector, topic_id=None, replies=False, state="active", *, group=None):
    scope, owner = discussion_context(context, selector, state, group)
    base = f"{scope}/{owner['id']}/discussion_topics"
    if topic_id is None:
        topics = listing(context, base)
    else:
        topic, _ = request(context, endpoint(f"{base}/{topic_id}", {}))
        topics = [topic]
    items = []
    for topic in topics:
        key = "group_id" if group is not None else "course_id"
        item = {"id": topic["id"], "title": topic["title"], key: owner["id"], "url": topic["html_url"],
                "reply_count": topic.get("discussion_subentry_count"), "unread": topic.get("unread_count"),
                "can_see_posts": topic.get("user_can_see_posts")}
        if topic_id is not None:
            item["body"] = PlainText.from_html(topic.get("message"))
        if replies and item["can_see_posts"] is not False:
            view, _ = request(context, endpoint(f"{base}/{topic_id}/view", {"include_new_entries": 1}))
            item["replies"] = discussion_entries(view)
        items.append(item)
    return items


def discussion_entries(view):
    entries = {}
    pending = [(entry, None) for entry in reversed(view["view"])]
    while pending:
        entry, parent = pending.pop()
        entries[entry["id"]] = (entry, entry.get("parent_id", parent))
        pending.extend((child, entry["id"]) for child in reversed(entry.get("replies") or []))
    for entry in view.get("new_entries") or []:
        previous_parent = entries.get(entry["id"], (None, None))[1]
        entries[entry["id"]] = (entry, entry.get("parent_id", previous_parent))
    return [{"id": entry["id"], "parent_id": parent, "body": PlainText.from_html(entry.get("message")),
             "deleted": entry.get("deleted")} for entry, parent in entries.values()]
