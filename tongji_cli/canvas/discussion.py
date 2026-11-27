import json
import re
from urllib.parse import urlsplit

from playwright.sync_api import Error

from tongji_cli.canvas.api import PlainText, discussion_context, discussion_entries, endpoint, request
from tongji_cli.common import QueryUnavailable


def create_topic(context, page, selector, title, message, preview, *, group=None):
    title = title.strip()
    if not title or not message.strip():
        raise QueryUnavailable("请输入讨论标题和正文")
    scope, owner = discussion_context(context, selector, "active", group)
    path = f"{scope}/{owner['id']}/discussion_topics"
    directory = owner["url"] + "/discussion_topics"
    editor, title_field, save = new_topic_form(page, directory, path)
    key = "group_id" if group is not None else "course_id"
    result = {key: owner["id"], "title": title, "body": message, "url": page.url}
    if preview:
        return [{**result, "action": "preview"}]
    title_field.fill(title)
    editor.fill(message)
    api = urlsplit(endpoint(path, {}))
    try:
        with page.expect_response(lambda r: r.request.method == "POST" and
                                  urlsplit(r.url.removesuffix(".json"))[:3] == api[:3], timeout=12000) as created:
            save.click(timeout=6000)
        response = created.value
        if not response.ok:
            raise QueryUnavailable(f"Canvas 保存讨论时返回 HTTP {response.status}")
        topic_id = int(json.loads(response.text().removeprefix("while(1);"))["id"])
        topic, _ = request(context, endpoint(f"{path}/{topic_id}", {}))
        body = "\n".join(line.strip() for line in message.splitlines() if line.strip())
        if (topic["id"] != topic_id or topic["title"] != title or
                PlainText.from_html(topic.get("message")) != body or
                urlsplit(topic["html_url"])[:3] != urlsplit(f"{directory}/{topic_id}")[:3]):
            raise ValueError
    except (Error, QueryUnavailable, ValueError, KeyError, TypeError) as error:
        raise QueryUnavailable("讨论保存回执未核实，请先用 canvas discussions 查看再决定是否重试") from error
    return [{**result, "action": "created", "id": topic_id, "url": topic["html_url"],
             "published": topic.get("published")}]


def new_topic_form(page, directory, path):
    page.goto(directory, wait_until="domcontentloaded")
    try:
        create = page.locator(f'#content a[href="/{path}/new"]:visible').first
        create.click(timeout=6000)
        if urlsplit(page.url)[:3] != urlsplit(directory + "/new")[:3]:
            raise QueryUnavailable("Canvas 未打开指定的讨论创建页")
        form = page.locator("#content form").filter(has=page.locator('input[name="title"]'))
        title = form.locator('input[name="title"]:visible')
        frame = form.frame_locator('iframe[id$="_ifr"]:visible').locator('body[contenteditable="true"]')
        plain = form.locator('textarea[name="message"]:visible')
        frame_owner = form.locator('iframe[id$="_ifr"]:visible')
        frame_owner.or_(plain).first.wait_for(timeout=6000)
        editor = frame if frame_owner.count() else plain
        editor.wait_for(timeout=6000)
        save = form.get_by_role("button", name=re.compile("^(Save|保存)$"))
        if not title.is_editable() or not editor.is_editable() or save.count() != 1 or not save.is_visible():
            raise QueryUnavailable("Canvas 未显示可核对的讨论编辑框和保存按钮")
        return editor, title, save
    except Error as error:
        raise QueryUnavailable("Canvas 未开放新讨论入口或编辑表单") from error


def reply(context, page, selector, topic_id, parent, message, preview, *, group=None):
    if not message.strip():
        raise QueryUnavailable("回复正文为空")
    scope, owner = discussion_context(context, selector, "active", group)
    path = f"{scope}/{owner['id']}/discussion_topics/{topic_id}"
    topic, _ = request(context, endpoint(path, {}))
    if topic["id"] != topic_id or topic.get("locked_for_user") or topic.get("locked"):
        raise QueryUnavailable("当前主题未开放回复")
    if topic.get("anonymous_state") in {"full_anonymity", "partial_anonymity"}:
        raise QueryUnavailable("匿名讨论的发言回执暂无法核实，请在 Canvas 主题页回复")
    url = f"{owner['url']}/discussion_topics/{topic_id}"
    if parent is not None:
        if topic.get("user_can_see_posts") is False:
            raise QueryUnavailable("请先按课程要求发言，再查看和回复已有发言")
        existing = visible_entries(context, path)
        if not any(e["id"] == parent and not e["deleted"] for e in existing):
            raise QueryUnavailable("此主题中未找到可回复的指定发言")
    target = url if parent is None else f"{url}?entry_id={parent}"
    page.goto(target, wait_until="domcontentloaded")
    if urlsplit(page.url)[:3] != urlsplit(url)[:3]:
        raise QueryUnavailable("Canvas 未打开指定的讨论主题")
    editor, send = open_editor(page, parent)
    key = "group_id" if group is not None else "course_id"
    result = {key: owner["id"], "topic_id": topic_id, "title": topic["title"],
              "parent_id": parent, "body": message, "url": target}
    if preview:
        return [{**result, "action": "preview"}]
    editor.fill(message)
    try:
        with page.expect_response(lambda r: create_response(r, path, parent, url), timeout=12000) as response:
            send.click(timeout=6000)
        created = response.value
        if not created.ok:
            raise ValueError
        data = created.json()
        entry = (data["data"]["createDiscussionEntry"]["discussionEntry"]["_id"]
                 if urlsplit(created.url).path.endswith("/graphql") else data["id"])
        receipt = next(e for e in visible_entries(context, path) if e["id"] == int(entry))
        body = "\n".join(line.strip() for line in message.splitlines() if line.strip())
        if receipt["parent_id"] != parent or receipt["deleted"] or receipt["body"] != body:
            raise ValueError
    except (Error, QueryUnavailable, ValueError, KeyError, TypeError, StopIteration) as error:
        raise QueryUnavailable("发言回执未核实，请先用 canvas discussion show --replies 查看再决定是否重发") from error
    return [{**result, "id": receipt["id"], "action": "posted", "url": f"{url}?entry_id={receipt['id']}"}]


def visible_entries(context, path):
    view, _ = request(context, endpoint(path + "/view", {"include_new_entries": 1}))
    return discussion_entries(view)


def create_response(response, path, parent, topic_url):
    url = urlsplit(response.url)
    if response.request.method != "POST" or url[:2] != urlsplit(topic_url)[:2]:
        return False
    rest = "/api/v1/" + path + "/entries" + ("" if parent is None else f"/{parent}/replies")
    if url.path.removesuffix(".json") == rest:
        return True
    return url.path.endswith("/graphql") and "creatediscussionentry" in (response.request.post_data or "").lower()


def open_editor(page, parent):
    if parent is None:
        classic = page.locator('textarea[id^="root_reply_message"]').locator(
            'xpath=ancestor::div[contains(@class,"discussion-entry-reply-area")][1]/preceding-sibling::div[1]'
        ).locator('[data-event="addReply"]')
        trigger = page.get_by_test_id("discussion-topic-reply").or_(classic)
    else:
        scope = f'[data-entry-wrapper-id="{parent}"]'
        modern = f'{scope} [data-testid="threading-toolbar-reply"]'
        nested = f'{scope} [data-entry-wrapper-id] [data-testid="threading-toolbar-reply"]'
        classic = f'#entry-{parent} > article [data-event="addReply"]'
        trigger = page.locator(f'{modern}:not({nested}), {classic}')
    try:
        trigger.filter(visible=True).first.click(timeout=6000)
        panel = page.locator('[data-testid="DiscussionEdit-container"]:visible, form.discussion-reply-form:visible')
        panel.wait_for(timeout=6000)
        quote = panel.locator('[data-testid="quotedReplyToggle"]:checked')
        if quote.count():
            quote.uncheck()
        frame = panel.locator('iframe:visible')
        plain = panel.locator('textarea:visible')
        frame.or_(plain).first.wait_for(timeout=6000)
        editor = frame.content_frame.locator('body[contenteditable="true"]') if frame.count() else plain
        editor.wait_for(timeout=6000)
        send = panel.locator('[data-testid="DiscussionEdit-submit"], button[type="submit"]').filter(visible=True)
        if send.count() != 1:
            raise QueryUnavailable("页面没有唯一的发言按钮")
        return editor, send
    except Error as error:
        raise QueryUnavailable("指定发言的回复按钮或编辑框未开放") from error
