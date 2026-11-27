import re
from datetime import date
from urllib.parse import urlsplit

from playwright.sync_api import Error, TimeoutError as BrowserTimeout, expect, sync_playwright

from tongji_cli.browser_session import open_session
from tongji_cli.common import QueryUnavailable


DASHBOARD = "https://www.lib.tongji.edu.cn/my/home/dashboard"
LOGIN_DETAIL = "请运行 ./tongji login --site library 完成学校统一身份认证，再办理图书借阅业务。"


def loans(profile, history=False, renewal=None):
    result = {"status": "login_required", "items": [], "url": DASHBOARD}
    if not profile.exists():
        return dict(result, detail=LOGIN_DETAIL)

    try:
        with sync_playwright() as pw:
            context = open_session(pw, profile)
            try:
                page = context.new_page()
                try:
                    page.set_default_timeout(25000)
                    return reader_records(page, result, history, renewal)
                finally:
                    page.close()
            finally:
                context.close()
    except Error:
        return dict(result, status="unverified", detail="未能加载图书馆读者页面。")


def reader_records(page, result, history=False, renewal=None):
    login = page.get_by_text("登录统一身份认证", exact=True).filter(visible=True).first
    try:
        page.goto(DASHBOARD, wait_until="domcontentloaded")
        link = page.get_by_role("link", name="图书借阅", exact=True)
        link.or_(login).first.wait_for()
        if login.is_visible():
            return dict(result, detail=LOGIN_DETAIL)
        reader_url = link.get_attribute("href")
        if renewal is not None:
            return dict(result, status="ok", items=renew_book(page, reader_url, renewal))
        page.goto(reader_url, wait_until="commit")
        tab = page.get_by_role("tab", name="当前借阅", exact=True, selected=True)
        tab.or_(login).first.wait_for()
        if login.is_visible():
            return dict(result, detail=LOGIN_DETAIL)
        panel = page.get_by_role("tabpanel").filter(visible=True)
        sources = {}
        for kind in ("图书", "现刊"):
            try:
                if history:
                    route = "loanHistoryList" if kind == "图书" else "getIssueLoanHistory"
                    control = (page.get_by_role("tab", name="借阅历史", exact=True) if kind == "图书"
                               else panel.get_by_text(kind, exact=True))
                    data = loan_query(page, control.click, route)
                    page.get_by_role("tab", name="借阅历史", selected=True).wait_for()
                    expect(panel.locator("label.ant-radio-button-wrapper-checked")).to_have_text(kind)
                    history_pages(page, panel, kind, route, data, result["items"])
                else:
                    if kind == "现刊":
                        data = loan_query(page, panel.get_by_text(kind, exact=True).click, "getIssueLoanInfoList")
                    expect(panel.locator("label.ant-radio-button-wrapper-checked")).to_have_text(kind)
                    if kind == "图书":
                        panel.get_by_text(re.compile(r"纸本图书剩余可借数[：:]\s*\d+")).wait_for()
                    elif data["numFound"] == 0:
                        panel.get_by_text("暂无数据", exact=True).wait_for()
                        sources[kind] = "ok"
                        continue
                    loan_pages(page, panel, kind, result["items"])
                sources[kind] = "ok"
            except (Error, AssertionError, QueryUnavailable):
                sources[kind] = "unverified"
        if "unverified" in sources.values():
            failed = "、".join(kind for kind, state in sources.items() if state == "unverified")
            status = "partial" if result["items"] or "ok" in sources.values() else "unverified"
            return dict(result, status=status, sources=sources, detail=f"未能完整读取以下借阅分类：{failed}")
        return dict(result, status="ok", sources=sources)
    except (Error, AssertionError, QueryUnavailable) as exc:
        if urlsplit(page.url).hostname == "iam.tongji.edu.cn" and login.is_visible():
            return dict(result, detail=LOGIN_DETAIL)
        return dict(result, status="partial" if result["items"] else "unverified",
                    detail=str(exc) if isinstance(exc, QueryUnavailable) else "未能完整读取图书馆借阅页面。")


def loan_pages(page, panel, kind, items):
    empty = panel.get_by_text("暂无数据", exact=True)
    table = panel.locator("table:visible:not(.ant-table-body-inner table)")
    rows = table.locator("tbody tr:visible")
    while True:
        empty.or_(rows.first).first.wait_for()
        page.wait_for_load_state("networkidle")
        error_message = page.locator(".ant-message-error:visible, .ant-notification-notice-error:visible")
        if error_message.count():
            raise QueryUnavailable("馆藏系统显示错误，无法核实当前借阅。")
        if empty.is_visible() and not rows.count():
            return
        headers = [h.strip() for h in table.locator("thead th:visible").all_inner_texts()]
        if not {"题名", "应还日期"}.issubset(headers):
            raise QueryUnavailable("借阅列表的题名或应还日期列无法识别。")
        for row in rows.all():
            values = row.locator("td:visible").all_inner_texts()
            if len(headers) != len(values):
                raise QueryUnavailable("借阅列表的表头与数据列数不符。")
            fields = dict(zip(headers, (v.strip() for v in values)))
            if not fields["题名"] or not fields["应还日期"]:
                raise QueryUnavailable("借阅记录缺少题名或应还日期。")
            item = {"kind": kind, "title": fields["题名"], "due_date": fields["应还日期"]}
            if fields.get("借阅日期"):
                item["borrowed_date"] = fields["借阅日期"]
            if fields.get("条码号"):
                item["barcode"] = fields["条码号"]
            items.append(item)
        next_page = panel.locator(".ant-pagination-next:visible")
        if not next_page.count() or next_page.get_attribute("aria-disabled") == "true":
            return
        active = panel.locator(".ant-pagination-item-active")
        previous = active.inner_text()
        next_page.click()
        expect(active).not_to_have_text(previous)


def loan_query(page, action, route):
    with page.expect_response(lambda reply: urlsplit(reply.url).path.endswith("/" + route)) as event:
        action()
    reply = event.value
    if not reply.ok:
        raise QueryUnavailable("馆方未能查询该借阅分类")
    body = reply.json()
    if not isinstance(body, dict) or body.get("success") is not True:
        raise QueryUnavailable("馆方未返回成功的借阅查询")
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("numFound"), int) or not isinstance(data.get("searchResult"), list):
        raise QueryUnavailable("借阅查询缺少总数或记录列表")
    if data["numFound"] < 0 or not all(isinstance(row, dict) for row in data["searchResult"]):
        raise QueryUnavailable("馆方返回的借阅记录格式异常")
    return data


def history_pages(page, panel, kind, route, data, items):
    start = len(items)
    total = data["numFound"]
    while True:
        records = data["searchResult"]
        if data["numFound"] != total or len(items) - start + len(records) > total:
            raise QueryUnavailable("馆方返回的借阅历史条数不一致")
        if records:
            table = panel.locator("table:visible").filter(has=page.get_by_role("columnheader", name="实还日期", exact=True))
            headers = table.locator("thead th")
            headers.first.wait_for()
            titles = [h.strip() for h in headers.all_inner_texts()]
            fields = {"题名": ("title", "title"), "条码号": ("barcode", "barcode"),
                      "借阅日期": ("borrowed_date", "loanDate"), "应还日期": ("due_date", "normReturnDate"),
                      "实还日期": ("returned_date", "returnDate")}
            if not set(fields).issubset(titles):
                raise QueryUnavailable("借阅历史未显示可核对的题名、条码号和日期")
            rows = table.locator("tbody tr:visible")
            for title, (_, key) in fields.items():
                expected = [str(r.get(key) or "").strip() for r in records]
                expect(rows.locator(f"td:nth-child({titles.index(title) + 1})")).to_have_text(expected, use_inner_text=True)
            items.extend({"kind": kind, **{field: row.get(key) or None for field, key in fields.values()}}
                         for row in records)
        if len(items) - start == total:
            return
        if not records:
            raise QueryUnavailable("借阅历史中途出现空页")
        link = panel.locator(".ant-pagination-next:visible")
        active = panel.locator(".ant-pagination-item-active")
        previous = active.inner_text()
        data = loan_query(page, link.click, route)
        expect(active).not_to_have_text(previous)


def renew_book(page, reader_url, args):
    entry, row, panel = find_borrowed_book(page, reader_url, args.barcode)
    if entry["due_date"] != args.due.isoformat():
        raise QueryUnavailable("馆方显示的应还日期与 --due 不符，请重新查 library loans")
    checkbox = row.get_by_role("checkbox")
    submit = panel.get_by_role("button", name="批量续借", exact=True)
    if checkbox.count() != 1 or not checkbox.is_enabled() or not submit.is_visible():
        raise QueryUnavailable("这本书的借阅行未提供可用的续借选择")
    checkbox.check()
    if panel.locator(".ant-table-body tbody input[type=checkbox]:checked").count() != 1:
        raise QueryUnavailable("未能核实只选中这一本书，无法提交批量续借")
    if not submit.is_enabled():
        raise QueryUnavailable("馆方未开放所选图书的续借")
    if args.preview:
        return [{**entry, "action": "preview"}]

    submit.click()
    confirm = page.get_by_role("dialog").filter(has_text="续借").filter(visible=True)
    notice = page.locator(".ant-message-notice:visible")
    try:
        confirm.or_(notice).first.wait_for(timeout=3000)
    except BrowserTimeout:
        pass
    if confirm.is_visible():
        confirm.get_by_role("button", name=re.compile(r"^确\s*定$")).click()
    verification = page.context.new_page()
    try:
        for attempt in range(3):
            if attempt:
                verification.wait_for_timeout(800)
            updated, _, _ = find_borrowed_book(verification, reader_url, args.barcode)
            if (updated["title"] == entry["title"] and updated["borrowed_date"] == entry["borrowed_date"]
                    and date.fromisoformat(updated["due_date"]) > args.due):
                return [{**updated, "action": "renewed", "previous_due_date": entry["due_date"]}]
    except (Error, QueryUnavailable, ValueError) as exc:
        raise QueryUnavailable("已点击续借，未能确认新的应还日期，请先查 library loans") from exc
    finally:
        verification.close()
    message = page.locator(".ant-message-error:visible").all_inner_texts()
    raise QueryUnavailable("尚未确认应还日期延后，请先查 library loans" + ("：" + " ".join(message) if message else ""))


def find_borrowed_book(page, reader_url, barcode):
    data = loan_query(page, lambda: page.goto(reader_url, wait_until="domcontentloaded"), "loanList")
    panel = page.get_by_role("tabpanel").filter(visible=True)
    expect(panel.locator("label.ant-radio-button-wrapper-checked")).to_have_text("图书")
    seen = 0
    while True:
        records = data["searchResult"]
        matches = [r for r in records if str(r.get("barcode", "")) == barcode]
        if matches:
            if len(matches) != 1:
                raise QueryUnavailable("馆方列表中有多条相同条码的借阅记录")
            record = matches[0]
            entry = {"kind": "图书", "title": record["title"], "barcode": barcode,
                     "due_date": record["normReturnDate"], "borrowed_date": record["loanDate"]}
            table = panel.locator(".ant-table-body table").filter(has=page.get_by_role("columnheader", name="条码号", exact=True))
            headers = table.get_by_role("columnheader")
            headers.first.wait_for()
            names = [s.strip() for s in headers.all_inner_texts()]
            row = table.locator("tbody tr").filter(has=page.get_by_role("cell", name=barcode, exact=True))
            for header, key in (("条码号", "barcode"), ("题名", "title"), ("借阅日期", "borrowed_date"), ("应还日期", "due_date")):
                expect(row.locator("td").nth(names.index(header))).to_have_text(entry[key], use_inner_text=True)
            return entry, row, panel
        seen += len(records)
        if seen >= data["numFound"]:
            raise QueryUnavailable("本人的当前在借图书中没有这个条码号")
        if not records:
            raise QueryUnavailable("在借图书列表中途出现空页")
        data = loan_query(page, panel.locator(".ant-pagination-next:visible").click, "loanList")
