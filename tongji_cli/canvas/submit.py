from collections import Counter
from pathlib import Path
import re
from time import monotonic
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError, expect

from tongji_cli.canvas import api as canvas_api
from tongji_cli.canvas.api import submission_text
from tongji_cli.common import QueryUnavailable


START = re.compile(r"^(开始作业|提交作业|重新提交作业|新尝试|开始尝试|Start Assignment|Submit Assignment|Re-submit Assignment|New Attempt)$", re.I)
NEW_ATTEMPT = re.compile(r"^(开始作业|重新提交作业|新尝试|开始尝试|Start Assignment|Re-submit Assignment|New Attempt)$", re.I)
SUBMIT = re.compile(r"^(提交作业|提交任务|Submit Assignment|提交|Submit)$", re.I)
LABELS = {"online_upload": "文件", "online_text_entry": "文本", "online_url": "网址"}
INPUTS = {
    "online_upload": 'input[type=file]',
    "online_text_entry": '#submission_body_ifr, #textentry_text_ifr, [data-testid="text-editor"] iframe',
    "online_url": '#online-url-input, input[name="submission[url]"]:visible, [data-testid="url-input"]',
}


def submit(context, page, selector, assignment_id, paths, preview, *, text=None, url=None):
    course = canvas_api.select_course(canvas_api.courses(context), selector)
    base = f"courses/{course['id']}/assignments/{assignment_id}"
    task, _ = canvas_api.request(context, canvas_api.endpoint(base, {}))
    kind, payload, files = prepare_submission(task, paths, text, url)
    summary = {"id": task["id"], "title": task["name"], "course_id": course["id"],
               "url": task["html_url"], "submission_type": kind, **payload}
    if preview:
        return [{**summary, "action": "preview"}]
    receipt_url = canvas_api.endpoint(base + "/submissions/self", {})
    previous, _ = canvas_api.request(context, receipt_url)
    try:
        form = open_form(page, task["html_url"], kind)
        if files:
            fill_files(form, files)
        elif kind == "online_text_entry":
            editor = form.locator(INPUTS[kind]).content_frame.locator('body[contenteditable="true"]')
            editor.fill(text, timeout=15000)
        else:
            form.locator(INPUTS[kind]).fill(url, timeout=10000)
        button = form.get_by_role("button", name=SUBMIT).filter(visible=True)
        expect(button).to_have_count(1, timeout=10000)
        expect(button).to_be_enabled(timeout=90000)
    except (BrowserError, AssertionError) as error:
        raise QueryUnavailable("页面未提供可用的作业输入框或提交按钮，请在作业页面核对要求") from error
    try:
        button.click(timeout=15000)
        receipt = wait_for_receipt(page, context, receipt_url, previous, summary)
    except (BrowserError, QueryUnavailable):
        raise QueryUnavailable("提交操作已发起，回执待确认。请先用 canvas submission 核对尝试次数和内容，再决定是否重试。") from None
    return [{**summary, "action": "submitted", "attempt": receipt["attempt"],
             "submitted_at": canvas_api.local_timestamp(receipt["submitted_at"])}]


def prepare_submission(task, paths, text, url):
    if sum((bool(paths), text is not None, url is not None)) != 1:
        raise QueryUnavailable("请在文件、文本和网址中选择一种提交方式")
    kind = "online_upload" if paths else "online_text_entry" if text is not None else "online_url"
    if task.get("locked_for_user") or kind not in task.get("submission_types", []):
        raise QueryUnavailable(f"该作业当前未向本人开放{LABELS[kind]}提交")
    if text is not None:
        if not text.strip():
            raise QueryUnavailable("作业文本为空")
        return kind, {"body": text}, []
    if url is not None:
        try:
            address = urlsplit(url)
            valid = address.scheme in {"http", "https"} and address.hostname and not re.search(r"\s", url)
            address.port  # urllib validates the port on access.
        except ValueError:
            valid = False
        if not valid:
            raise QueryUnavailable("请输入完整的 HTTP 或 HTTPS 网址")
        return kind, {"submission_url": url}, []
    files = [Path(path).expanduser().absolute() for path in paths]
    allowed = {ext.lower().lstrip(".") for ext in task.get("allowed_extensions") or []}
    for file in files:
        if not file.is_file():
            raise QueryUnavailable(f"找不到本地文件：{file.name}")
        if allowed and not any(file.name.lower().endswith("." + ext) for ext in allowed):
            raise QueryUnavailable(f"文件 {file.name} 的扩展名不符合课程要求：{', '.join(sorted(allowed))}")
    return kind, {"files": [{"name": f.name, "bytes": f.stat().st_size} for f in files]}, files


def open_form(page, url, kind):
    if urlsplit(url)[:2] != urlsplit(canvas_api.CANVAS)[:2]:
        raise QueryUnavailable("作业页面地址与当前 Canvas 站点不一致")
    page.goto(url, wait_until="domcontentloaded")
    classic = page.locator("#submit_assignment")
    if classic.count():
        if not classic.is_visible():
            start = page.get_by_role("button", name=START).or_(page.get_by_role("link", name=START))
            start.filter(visible=True).click(timeout=10000)
        form = classic.locator(f"#submit_{kind}_form")
        if not form.is_visible():
            classic.locator(f'a[href="#submit_{kind}_form"]').click(timeout=10000)
        form.wait_for(timeout=10000)
        return form

    field = page.locator(INPUTS[kind])
    start = page.get_by_role("button", name=NEW_ATTEMPT).or_(page.get_by_test_id("new-attempt-button"))
    choice = page.get_by_test_id("submission-type-selector").get_by_test_id(kind).get_by_role("button")
    field.or_(start).or_(choice).first.wait_for(state="attached", timeout=15000)
    if start.is_visible():
        start.click(timeout=10000)
    if not field.count():
        field.or_(choice).first.wait_for(state="attached", timeout=10000)
        if not field.count():
            choice.click(timeout=10000)
    return page


def fill_files(form, files):
    inputs = form.locator(INPUTS["online_upload"])
    inputs.first.wait_for(state="attached", timeout=10000)
    if inputs.count() == 1 and inputs.first.get_attribute("multiple") is not None:
        inputs.first.set_input_files(files)
        return
    for index, file in enumerate(files):
        if index >= inputs.count():
            add = form.get_by_text(re.compile(r"^(添加(另一个|其他)文件|Add Another File)$", re.I)).filter(visible=True)
            if add.count() != 1:
                raise QueryUnavailable("此提交页未显示继续添加文件的入口")
            add.click()
        inputs.nth(index).set_input_files(file)


def matches_submission(data, summary):
    kind = summary["submission_type"]
    if data.get("submission_type") != kind:
        return False
    if kind == "online_text_entry":
        expected = summary["body"].replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
        return submission_text(data.get("body")) == expected
    if kind == "online_url":
        return data.get("url") == summary["submission_url"]
    actual = Counter((f.get("display_name"), f.get("size")) for f in data.get("attachments") or [])
    return actual == Counter((f["name"], f["bytes"]) for f in summary["files"])


def wait_for_receipt(page, context, url, previous, summary):
    attempt = (previous.get("attempt") or 0) + 1
    deadline = monotonic() + 25
    while monotonic() < deadline:
        data, _ = canvas_api.request(context, url)
        if data.get("attempt") == attempt and data.get("submitted_at") and matches_submission(data, summary):
            return data
        page.wait_for_timeout(500)
    raise QueryUnavailable("尚未读到本次作业提交的回执")
