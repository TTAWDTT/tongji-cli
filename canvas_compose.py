import json
import re
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import Error

import queries
from canvas_api import courses, endpoint, listing, request, select_course
from queries import QueryUnavailable


def send_message(context, page, selector, recipient, subject, body, preview):
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    if not subject.strip() or not body.strip():
        raise QueryUnavailable("消息需要主题和正文")
    if "\n" in subject or "\r" in subject:
        raise QueryUnavailable("消息主题只能有一行")
    course = select_course(courses(context), selector)
    people = list(listing(context, "search/recipients", {"user_id": recipient}))
    course_code = f"course_{course['id']}"
    if (len(people) != 1 or str(people[0]["id"]) != str(recipient)
            or str(course["id"]) not in (people[0].get("common_courses") or {})):
        raise QueryUnavailable("未能核对收件人及共同课程，请用 canvas recipients 按课程查找")
    target = urlencode({"user_id": recipient, "user_name": people[0]["name"], "context_id": course_code})
    page.goto(f"{queries.CANVAS}/conversations?{target}", wait_until="domcontentloaded")
    form = page.locator("form.compose_form:visible")
    form.wait_for(timeout=10000)
    addresses = form.locator('input[name="recipients[]"]')
    if (addresses.count() != 1 or addresses.input_value() != str(recipient)
            or form.locator('input[name="context_code"]').input_value() != course_code):
        raise QueryUnavailable("Canvas 编辑框中的收件人或课程不匹配")
    form.locator('[name="subject"]').fill(subject)
    form.locator('textarea[name="body"]').fill(body)
    panel = page.locator(".compose-message-dialog, [role=dialog]").filter(has=form)
    send = panel.get_by_role("button", name=re.compile(r"^(发送|Send)$", re.I))
    if not send.is_visible() or not send.is_enabled():
        raise QueryUnavailable("Canvas 未显示可用的发送按钮")
    draft = {"recipient_id": recipient, "course_id": course["id"], "title": subject, "body": body}
    if preview:
        return [dict(draft, action="preview")]
    owner, _ = request(context, endpoint("users/self/profile", {}))
    try:
        with page.expect_response(created_conversation, timeout=15000) as pending:
            send.click(timeout=5000)
        response = pending.value
        if response.status != 201:
            raise ValueError
        thread, = json.loads(response.text().removeprefix("while(1);"))
        posted, = thread["messages"]
        detail, _ = request(context, endpoint(f"conversations/{int(thread['id'])}", {"auto_mark_as_read": "false"}))
        received = next(msg for msg in detail["messages"] if msg["id"] == posted["id"])
        if (detail["id"] != thread["id"] or {int(uid) for uid in detail["audience"]} != {recipient}
                or received["author_id"] != owner["id"]
                or received["body"].replace("\r\n", "\n").replace("\r", "\n") != body):
            raise ValueError
    except (Error, QueryUnavailable, KeyError, TypeError, ValueError, StopIteration) as e:
        raise QueryUnavailable("消息发送回执未核实，请先用 canvas inbox --scope sent 核对") from e
    return [dict(draft, title=detail["subject"], action="sent", id=thread["id"], message_id=received["id"])]


def created_conversation(response):
    url = urlsplit(response.url)
    return (response.request.method == "POST" and url[:2] == urlsplit(queries.CANVAS)[:2]
            and url.path.removesuffix(".json") in {"/conversations", "/api/v1/conversations"})
