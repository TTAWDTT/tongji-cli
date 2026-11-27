import re
from contextlib import contextmanager

from playwright.sync_api import Error, TimeoutError, sync_playwright

from browser_session import CHANNEL
from queries import QueryUnavailable


SOURCE = "http://classroom.tongji.edu.cn:10010/classroom-info-release/"
PAGE_CLOCK = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}号\s+\d{2}:\d{2}:\d{2}$")


def search_rooms(keyword):
    with public_search(keyword) as page:
        return {"keyword": keyword, "rooms": page.get_by_role("option").all_inner_texts(), "source": SOURCE}


def room_status(room):
    with public_search(room) as page:
        option = page.get_by_role("option", name=room, exact=True)
        if not option.count():
            raise QueryUnavailable("未找到该教室，请使用 rooms search 返回的完整名称")
        option.click()
        page.locator(".el-icon-search").click()
        return read_status(page, room)


@contextmanager
def public_search(keyword):
    if not keyword.strip():
        raise QueryUnavailable("请输入教室名称或编号")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel=CHANNEL)
            try:
                page = browser.new_page()
                page.set_default_timeout(10000)
                page.goto(SOURCE, wait_until="networkidle")
                search = page.get_by_placeholder("请输入")
                search.click()
                page.get_by_role("option").first.wait_for()
                search.fill(keyword)
                # 联想列表在输入框声明的防抖时间后才更新，包括无匹配时收起列表。
                delay = int(search.get_attribute("debounce") or 300)
                page.wait_for_timeout(delay + 100)
                # 空结果会隐藏整个列表。页面按大小写匹配教室名。
                page.wait_for_function("""keyword => [...document.querySelectorAll('[role="option"]')]
                    .filter(option => option.getClientRects().length)
                    .every(option => option.textContent.includes(keyword))""", arg=keyword)
                yield page
            finally:
                browser.close()
    except Error as error:
        raise QueryUnavailable("未能读取校方教室信息发布页面") from error


def read_status(page, room):
    heading = re.compile(r"^\s*" + re.escape(room) + r"\s*(?:[(（][^()（）]+[)）])?\s*$")
    title = page.locator(".classroom-type-title").filter(has_text=heading)
    try:
        title.wait_for()
    except TimeoutError as error:
        raise QueryUnavailable(f"校方详情未显示所选教室 {room}") from error
    table = page.locator(".el-table").filter(has=page.get_by_role("columnheader", name="自习可用时长"))
    row = table.get_by_role("row").filter(has=page.get_by_role("cell", name=room, exact=True))
    row.or_(table.get_by_text("暂无数据", exact=True)).first.wait_for()
    page.wait_for_load_state("networkidle")
    usage = study_time = None
    if row.count():
        cells = [cell.strip() for cell in row.get_by_role("cell").all_inner_texts()]
        headers = [label.strip() for label in table.get_by_role("columnheader").all_inner_texts()]
        fields = dict(zip(headers, cells))
        usage = fields["教室情况"] or None
        study_time = fields["自习可用时长"] or None
    status_text = title.locator("span").all_inner_texts()
    return {
        "room": room,
        "status": status_text[0].strip().strip("()（）") if status_text else None,
        "usage": usage,
        "study_time": study_time,
        "observed_at": page.get_by_text(PAGE_CLOCK).inner_text(),
        "source": SOURCE,
    }
