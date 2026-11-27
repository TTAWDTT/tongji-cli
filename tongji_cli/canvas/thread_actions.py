import json
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Error, TimeoutError

from tongji_cli.canvas import api as canvas_api
from tongji_cli.canvas.api import endpoint, request
from tongji_cli.common import QueryUnavailable


def read_thread(context, thread_id):
    item, _ = request(context, endpoint(f"conversations/{thread_id}", {"auto_mark_as_read": "false"}))
    if item["id"] != thread_id:
        raise QueryUnavailable("Canvas 返回了不同的会话")
    return item


def thread_row(page, thread):
    page.goto(canvas_api.CANVAS + "/conversations", wait_until="domcontentloaded")
    folders = page.locator("#conversation_filter_select")
    row = page.locator(".messages li").filter(has=page.locator(f'#conversation-checkbox-{thread["id"]}'))
    scopes = ["archived"] if thread["workflow_state"] == "archived" else ["inbox", "sent"]
    for scope in scopes:
        if folders.input_value() != scope:
            folders.select_option(scope, force=True)
        try:
            row.wait_for(timeout=1500)
            return row
        except TimeoutError:
            pass
        cards = page.locator(".messages li .star-btn")
        count = cards.count()
        while count:
            cards.last.scroll_into_view_if_needed(timeout=4000)
            try:
                cards.nth(count).wait_for(timeout=1800)
            except TimeoutError:
                break
            if row.is_visible():
                return row
            count = cards.count()
    raise QueryUnavailable("未能在本人 Canvas 会话列表定位该会话")


def open_thread(row, thread):
    title = row.get_by_text(thread["subject"], exact=True) if thread["subject"] else row
    if title.count() == 1:
        title.click()
    else:
        row.click()


def reply(context, page, thread_id, body, preview):
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    if not body.strip():
        raise QueryUnavailable("请输入回复正文")
    thread = read_thread(context, thread_id)
    if thread.get("can_reply") is False:
        raise QueryUnavailable("Canvas 未允许本人回复此会话")
    audience = {int(uid) for uid in thread["audience"]}
    if not audience:
        raise QueryUnavailable("Canvas 没有列出会话收件人")
    details = {"id": thread_id, "title": thread["subject"], "recipient_ids": sorted(audience), "body": body}
    if preview and thread["workflow_state"] != "read":
        return [dict(details, action="preview", editor_checked=False)]
    open_thread(thread_row(page, thread), thread)
    page.locator("#reply-btn" if len(audience) == 1 else "#reply-all-btn").click(timeout=6000)
    panel = page.locator(".compose-message-dialog:visible")
    form = panel.locator("form.compose_form")
    form.wait_for()
    action = urlsplit(urljoin(page.url, form.get_attribute("action") or ""))
    path = f"/conversations/{thread_id}/add_message"
    if action[:2] != urlsplit(canvas_api.CANVAS)[:2] or action.path not in {path, "/api/v1" + path}:
        raise QueryUnavailable("当前编辑框属于其他会话")
    addresses = form.locator('input[name="recipients[]"]').evaluate_all("els => els.map(e => e.value)")
    if set(addresses) != {str(uid) for uid in audience}:
        raise QueryUnavailable("编辑框收件人与原会话收件人不一致")
    form.locator('textarea[name="body"]').fill(body)
    send = panel.get_by_role("button", name=re.compile(r"^(发送|Send)$", re.I))
    if not send.is_enabled():
        raise QueryUnavailable("Canvas 没有开放此回复的发送按钮")
    if preview:
        return [dict(details, action="preview", editor_checked=True)]
    owner, _ = request(context, endpoint("users/self/profile", {}))
    old = {m["id"] for m in thread["messages"]}
    try:
        def posted(r):
            url = urlsplit(r.url)
            return (r.request.method == "POST" and url[:2] == action[:2]
                    and url.path.removesuffix(".json") in {path, "/api/v1" + path})
        with page.expect_response(posted, timeout=15000) as pending:
            send.click(timeout=5000)
        response = pending.value
        if not response.ok:
            raise ValueError
        receipt = json.loads(response.text().removeprefix("while(1);"))
        new, = receipt["messages"]
        latest = read_thread(context, thread_id)
        match = next(m for m in latest["messages"] if m["id"] == new["id"])
        if (receipt["id"] != thread_id or new["id"] in old or match["author_id"] != owner["id"]
                or match["body"].replace("\r\n", "\n").replace("\r", "\n") != body
                or {int(uid) for uid in latest["audience"]} != audience):
            raise ValueError
    except (Error, QueryUnavailable, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise QueryUnavailable("回复回执未核实，请用 canvas conversation show 核对后再决定是否重发") from exc
    return [dict(details, message_id=new["id"], action="replied")]


def set_state(context, page, thread_id, state, star, preview):
    thread = read_thread(context, thread_id)
    field, desired = ("starred", star == "on") if star is not None else ("workflow_state", state)
    change = {"id": thread_id, "attribute": field, "previous": thread[field], "target": desired}
    if preview or thread[field] == desired:
        return [dict(change, action="preview" if preview else "unchanged")]
    row = thread_row(page, thread)
    if field == "starred":
        button = row.locator(".star-btn")
        if button.get_attribute("aria-checked") != str(desired).lower():
            button.click()
    else:
        open_thread(row, thread)
        if desired == "archived" or thread["workflow_state"] == "archived":
            page.locator("#archive-btn:enabled").click(timeout=6000)
            if thread["workflow_state"] == "archived":
                restored = wait_for_field(context, page, thread_id, "workflow_state", {"read", "unread"})
                if restored["workflow_state"] != desired:
                    open_thread(thread_row(page, restored), restored)
                    mark_thread(page, desired)
        elif desired == "unread":
            mark_thread(page, "unread")
        elif read_thread(context, thread_id)["workflow_state"] != "read":
            mark_thread(page, "read")
    result = wait_for_field(context, page, thread_id, field, {desired})
    if field == "starred" and result["workflow_state"] != thread["workflow_state"]:
        raise QueryUnavailable("星标已更新，但会话已读状态发生变化，请用 canvas conversation show 核对")
    return [dict(change, action="updated")]


def mark_thread(page, state):
    title = r"^(标记为未读|Mark as unread)$" if state == "unread" else r"^(标记为已读|Mark as read)$"
    page.locator("#admin-btn:enabled").click(timeout=5000)
    option = page.get_by_text(re.compile(title, re.I)).filter(visible=True)
    if state == "read" and not option.count():
        return
    option.click(timeout=5000)


def wait_for_field(context, page, thread_id, field, expected):
    deadline = monotonic() + 6
    while monotonic() < deadline:
        latest = read_thread(context, thread_id)
        if latest[field] in expected:
            return latest
        page.wait_for_timeout(200)
    raise QueryUnavailable("会话状态变更未核实，请用 canvas conversation show 核对")
