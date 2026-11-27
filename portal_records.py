import re
from collections import Counter
from time import monotonic
from urllib.parse import urlsplit

from playwright.sync_api import Error, TimeoutError as BrowserTimeout, expect, sync_playwright

from library_services import PORTAL
from browser_session import open_session
from queries import QueryUnavailable


TASK_TABS = {"pending": "待办任务", "processed": "已办任务"}
LOGIN_DETAIL = "请运行 ./tongji login --site service 完成学校统一身份认证，再查询个人办件。"


def records(profile, operation, state=None, with_flow=False):
    if not profile.exists():
        return {"status": "login_required", "detail": LOGIN_DETAIL}
    tabs = ["我发起的"] if operation == "applications" else (
        [TASK_TABS[state]] if state else list(TASK_TABS.values())
    )
    with sync_playwright() as pw:
        context = open_session(pw, profile)
        try:
            page = context.new_page()
            try:
                page.set_default_timeout(25000)
                return personal_records(page, tabs, with_flow)
            finally:
                page.close()
        finally:
            context.close()


def personal_records(page, tabs, with_flow=False):
    try:
        page.goto(PORTAL, wait_until="commit")
        frame = page.frame_locator('iframe[src*="CUS_TEMPLATE_TONGJI"]')
        frame.get_by_text("个人中心", exact=True).filter(visible=True).first.click()
        panel = frame.locator(".task-wrap:visible").filter(has=frame.get_by_text("我的办件", exact=True))
        active = panel.locator(".task-nav .active")
        active.wait_for()
        panel.locator(".todoList-table:visible").wait_for()
        page.wait_for_load_state("networkidle")
        panel.locator(".we-loading-mask:visible").first.wait_for(state="hidden", timeout=60000)
    except Error:
        if urlsplit(page.url).hostname == "iam.tongji.edu.cn":
            return {"status": "login_required", "detail": LOGIN_DETAIL}
        return {"status": "unverified", "detail": "未能打开一网通办个人中心的「我的办件」。"}

    items, sources = [], {}
    for tab in tabs:
        try:
            if active.inner_text().strip() != tab:
                panel.locator(".task-nav").get_by_text(tab, exact=True).click()
                expect(active).to_have_text(tab)
                # 切换到另一个页签时，空表先于加载遮罩出现。
                try:
                    panel.locator(".we-loading-mask:visible").first.wait_for(timeout=4000)
                except BrowserTimeout:
                    pass
            tab_records(page, frame, panel, tab, items, with_flow)
            sources[tab] = "ok"
        except (Error, AssertionError, QueryUnavailable):
            sources[tab] = "unverified"
    result = {"status": "ok", "items": items, "sources": sources, "url": PORTAL}
    missing = [tab for tab, status in sources.items() if status != "ok"]
    if missing:
        result.update(status="partial" if items or "ok" in sources.values() else "unverified",
                      detail="未能完整读取一网通办个人中心的" + "、".join(missing) + "。")
    if any(item.get("流转记录读取状态") == "unverified" for item in items):
        result.update(status="partial", detail="部分办件的流转记录未能核实，已保留其办件摘要。")
    return result


def tab_records(page, frame, panel, tab, items, with_flow=False):
    table = panel.locator(".todoList-table:visible")
    rows = table.locator(".task-items:visible")
    empty = table.get_by_text("暂无相关数据", exact=True).filter(visible=True)
    headers = ["流程标题", "状态" if tab == "我发起的" else "发起人", "系统来源", "最近处理时间", "操作"]
    start = len(items)
    while True:
        expect(table.locator(".table-header > *")).to_have_text(headers, use_inner_text=True)
        rows.first.or_(empty).first.wait_for()
        # 切换页签时旧行或空提示会留在加载遮罩后，直到服务器返回。
        page.wait_for_load_state("networkidle")
        panel.locator(".we-loading-mask:visible").first.wait_for(state="hidden", timeout=60000)
        if frame.locator(".we-message--error:visible").count():
            raise QueryUnavailable("一网通办显示加载错误")
        if not rows.count():
            if len(items) == start and empty.is_visible():
                break
            raise QueryUnavailable("未显示记录或明确的空提示")
        for row in rows.all():
            cells = row.locator(":scope > *").all_inner_texts()
            if len(cells) != len(headers):
                raise QueryUnavailable("办件表头与数据列数不符")
            item = {"分类": tab, **dict(zip(headers[:-1], (v.strip() or None for v in cells[:-1])))}
            items.append(item)
            if with_flow:
                item.update(flow_history(page, frame, row))
        next_page = panel.locator(".btn-next:visible")
        if not next_page.count() or not next_page.is_enabled():
            break
        active = panel.locator(".we-pager .active:visible")
        previous = active.inner_text()
        next_page.click()
        expect(active).not_to_have_text(previous)
    total = panel.locator(".we-pagination__total:visible").all_inner_texts()
    if total and not re.fullmatch(rf"共\s*{len(items)-start}\s*条", total[0].strip()):
        raise QueryUnavailable("办件记录数与页面总数不符")


def flow_history(page, frame, row):
    action = row.locator(":scope > *").last.get_by_text("流程", exact=True)
    unknown = {"流转记录读取状态": "unverified"}
    if not action.is_visible():
        return unknown
    dialog = frame.locator(".we-dialog:visible").filter(has=frame.get_by_text("流转记录", exact=True))
    try:
        with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/process_list")) as response:
            action.click()
        dialog.wait_for()
        if not response.value.ok:
            return unknown
        payload = response.value.json()
        if not isinstance(payload, dict) or payload.get("code") != "A00000":
            return unknown
        steps = payload.get("data")
        if not isinstance(steps, list):
            return unknown
        listing = dialog.locator(".step")
        listing.wait_for(state="attached")
        entries = listing.locator(":scope > *:visible")
        expect(entries).to_have_count(len(steps))
        deadline = monotonic() + 5
        while monotonic() < deadline:
            texts = [text.strip() for text in entries.all_inner_texts()]
            if len(texts) == len(steps) and all(step_matches(text, step) for text, step in zip(texts, steps)):
                return {"流转记录读取状态": "ok", "流转记录": texts}
            page.wait_for_timeout(100)
        return unknown
    except (Error, AssertionError, ValueError):
        return unknown
    finally:
        if dialog.is_visible():
            dialog.locator(".we-dialog__headerbtn").click()
            dialog.wait_for(state="hidden")


def step_matches(text, step):
    values = step.values() if isinstance(step, dict) else (step,)
    if any(isinstance(value, (list, dict)) for value in values):
        return False
    expected = [str(value).strip() for value in values if value is not None and str(value).strip()]
    visible = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(visible) and Counter(visible) == Counter(expected)
