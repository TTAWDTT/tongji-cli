from contextlib import ExitStack
from urllib.parse import urlsplit

from playwright.sync_api import expect

from tongji_cli.common import QueryUnavailable


BOOK = "https://findtongji.libsp.cn/#/searchList/bookDetails/{}"
COPIES = "groupitems"
LOCATIONS = "getRequestAndEnreustList"


def holdings(page, book_id):
    url = BOOK.format(book_id)
    paths = ("getDetail", COPIES, LOCATIONS)
    with ExitStack() as stack:
        events = {name: stack.enter_context(watch(page, name)) for name in paths}
        page.goto(url, wait_until="commit")
    book = payload(events["getDetail"])
    if not book.get("clearTitle"):
        raise QueryUnavailable("馆藏目录未返回这条书目的题名")
    copies = table_rows(page, COPIES, payload(events[COPIES]), {"条码号": "barcode", "书刊状态": "processType"})
    locations = table_rows(page, LOCATIONS, payload(events[LOCATIONS]),
                           {"馆藏地": "locationName", "可借复本": "onShelfNum", "当前请求数": "requestNum"})
    return [{"id": book_id, "title": book["clearTitle"], "copies": copies, "locations": locations, "url": url}]


def watch(page, name):
    return page.expect_response(lambda r: urlsplit(r.url).path.endswith("/" + name))


def payload(event):
    response = event.value
    if response.ok:
        body = response.json()
        if isinstance(body, dict) and body.get("success") is True and isinstance(body.get("data"), dict):
            return body["data"]
    raise QueryUnavailable("馆藏目录未返回成功的书目查询")


def table_rows(page, route, data, keys):
    total = data["totalCount"]
    result = []
    while True:
        records = data["list"]
        if data["totalCount"] != total or not isinstance(records, list) or len(result) + len(records) > total:
            raise QueryUnavailable("馆方记录数与总数不符")
        if not records:
            if total == 0:
                return []
            raise QueryUnavailable("馆藏明细未返回完整记录")
        table = page.get_by_role("table")
        for title in keys:
            table = table.filter(has=page.get_by_role("columnheader", name=title, exact=True))
        heads = table.get_by_role("columnheader")
        heads.first.wait_for()
        titles = [text.strip() for text in heads.all_inner_texts()]
        rows = table.locator("tbody tr:visible")
        for title, field in keys.items():
            expected = [str(record[field]).strip() for record in records]
            expect(rows.locator(f"td:nth-child({titles.index(title) + 1})")).to_have_text(expected, use_inner_text=True)
        for row in rows.all():
            values = row.locator("td").all_inner_texts()
            if len(values) != len(titles):
                raise QueryUnavailable("馆藏明细表头与行列数不符")
            result.append({title: value.strip() for title, value in zip(titles, values) if title and title != "序号"})
        if len(result) == total:
            if route == COPIES:
                barcodes = [row["条码号"] for row in result if row["条码号"]]
                if len(set(barcodes)) != len(barcodes):
                    raise QueryUnavailable("馆方逐册列表出现重复条码，无法确认已完整读取")
            return result
        section = table.locator('xpath=ancestor::*[.//ul[contains(concat(" ", normalize-space(@class), " "), " ant-pagination ")]][1]')
        pager = section.locator("ul.ant-pagination:visible")
        more = pager.locator(".ant-pagination-next")
        if more.count() != 1 or more.get_attribute("aria-disabled") == "true":
            raise QueryUnavailable("仍有馆藏记录，页面未提供可核实的下一页")
        active = pager.locator(".ant-pagination-item-active")
        previous = active.inner_text()
        button = more.get_by_role("button")
        with watch(page, route) as next_page:
            (button if button.count() else more).click()
        data = payload(next_page)
        expect(active).not_to_have_text(previous)
