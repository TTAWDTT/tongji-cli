import re
from time import monotonic
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Error as BrowserError, expect

from jw_records import course_rows, query_data, watch_query
from queries import QueryUnavailable


CALENDAR = "/api/electionservice/underGraduateExamSwitch/getExamCalendar"
COURSES = "/api/electionservice/undergraduateExamReexam/getStudentReExamCourseListPage"
CLOSED = "当前时间没有开放重考申请"


def retakes(page, code=None, preview=False):
    status, table, count = open_retakes(page)
    if status["state"] == "closed":
        if code is not None:
            raise QueryUnavailable(status["detail"])
        return [status]
    rows = read_pages(page, table, count)
    source = {"source": status["source"], "url": status["url"]}
    if code is None:
        return [status, *(dict(row, **source) for _, row in rows)]

    number, before = match_course(rows, code)
    button = select_course(page, table, number, before)
    if preview:
        return [dict(before, action="preview", **source)]

    try:
        apply_once(page, button)
        after = read_receipt(page, before)
    except (BrowserError, QueryUnavailable, AssertionError, ValueError, KeyError) as exc:
        detail = f"（{exc}）" if isinstance(exc, QueryUnavailable) else ""
        raise QueryUnavailable(f"重考申请操作已发起，回执待核实。请先查询该课的申请状态。{detail}") from None
    return [dict(after, action="submitted", **source)]


def select_course(page, table, number, before):
    while page.locator(".el-pagination .el-pager .active:visible").count() and current_page(page) > number:
        turn_page(page, "prev", current_page(page) - 1)
    choice = course_selector(page, table, before["新课程序号"])
    button = page.get_by_role("button", name="申请", exact=True).filter(visible=True)
    if before["申请状态"] not in (None, "未申请", "待申请", "可申请", "未提交") or not choice.is_enabled():
        raise QueryUnavailable("该课当前不允许申请重考，请核对校方申请状态")
    if not choice.is_checked():
        label = choice.locator("xpath=ancestor::label[1]")
        (label if label.count() else choice).click()
    if (not choice.is_checked() or table.locator('.el-table__body-wrapper input:checked').count() != 1
            or button.count() != 1 or not button.is_enabled()):
        raise QueryUnavailable("未能在教务页面单独选中该课并启用申请按钮")
    return button


def read_receipt(page, before):
    state, table, count = open_retakes(page)
    if state["state"] == "closed":
        raise QueryUnavailable(CLOSED)
    _, after = match_course(read_pages(page, table, count), before["新课程序号"])
    if (after["学期"] != before["学期"] or after["课程名称"] != before["课程名称"]
            or after["申请状态"] == before["申请状态"]
            or not re.fullmatch(r"已申请|申请成功|已提交|待审核|待审批|审核中|审批中|已通过|审核通过|审批通过",
                                after["申请状态"] or "")):
        raise QueryUnavailable("课程申请状态未能核实")
    return after


def open_retakes(page):
    page.goto(urljoin(page.url, "/traningPlanMy"), wait_until="domcontentloaded", timeout=20000)
    link = page.locator('li.el-menu-item a[href^="/applyMakeupExam"]').filter(has_text=re.compile(r"^申请重考$"))
    link.wait_for(state="attached", timeout=15000)
    if not link.is_visible():
        section = link.locator("xpath=ancestor::div[contains(concat(' ',normalize-space(@class),' '),' el-collapse-item ')][1]")
        section.locator(".el-collapse-item__header").click()
    with watch_query(page, CALENDAR) as window, watch_query(page, COURSES) as listing:
        link.click()
    url = urljoin(page.url, "/applyMakeupExam")
    calendar = retake_data(window.value)
    if not isinstance(calendar, dict):
        raise QueryUnavailable("未能读取教务重考申请日历")
    response = listing.value
    source = {"学期": calendar.get("calendarIdI18n"), "source": "申请重考", "url": url}
    error = response.json() if response.status == 400 else None
    if isinstance(error, dict) and error.get("message") == CLOSED:
        return dict(source, state="closed", detail=CLOSED), None, None
    count = page_row_count(response)
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("重考性质", exact=True))
    table.wait_for(timeout=10000)
    return dict(source, state="available", detail="教务系统已返回重考课程列表"), table, count


def current_page(page):
    return int(page.locator(".el-pagination:visible .el-pager .active").inner_text())


def turn_page(page, direction, number):
    pager = page.locator(".el-pagination:visible")
    with watch_query(page, COURSES) as listing:
        pager.locator(f".btn-{direction}").click()
    count = page_row_count(listing.value)
    expect(pager.locator(".el-pager .active")).to_have_text(str(number), timeout=10000)
    return count


def retake_data(response):
    try:
        return query_data(response)
    except (AttributeError, KeyError, ValueError, TypeError):
        raise QueryUnavailable("教务重考查询返回的数据格式未能核实") from None


def page_row_count(response):
    data = retake_data(response)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for field in ("list", "records", "content", "rows", "items"):
            if isinstance(data.get(field), list):
                return len(data[field])
        if data.get("total") == 0:
            return 0
        return None
    raise QueryUnavailable("教务未返回有效的重考课程列表")


def read_pages(page, table, count):
    pager = page.locator(".el-pagination:visible")
    next_page = pager.locator(".btn-next")
    found = []
    while True:
        number = current_page(page) if pager.locator(".el-pager .active").count() else 1
        rows = course_rows(page, table)
        if (count is None and not rows) or (count is not None and len(rows) != count):
            raise QueryUnavailable("重考列表响应与页面课程数未能核对")
        if any("新课程序号" not in row or "申请状态" not in row for row in rows):
            raise QueryUnavailable("未能读取完整的重考课程编号与申请状态")
        found.extend((number, row) for row in rows)
        if not next_page.count() or not next_page.is_enabled():
            break
        count = turn_page(page, "next", number + 1)
    if pager.count():
        total = re.search(r"共\s*(\d+)\s*条", pager.inner_text())
        if total and int(total[1]) != len(found):
            raise QueryUnavailable("重考课程记录数与页面总数不符")
    return found


def match_course(rows, code):
    matches = [(number, row) for number, row in rows if row["新课程序号"] == code]
    if len(matches) != 1:
        raise QueryUnavailable("请使用重考课程列表中唯一的新课程序号")
    return matches[0]


def course_selector(page, table, code):
    labels = table.locator(".el-table__header-wrapper th:not(.gutter)").all_inner_texts()
    column = [label.strip() for label in labels].index("新课程序号") + 1
    cell = page.locator(f"td:nth-child({column})").filter(has_text=re.compile(r"^\s*" + re.escape(code) + r"\s*$"))
    row = table.locator(".el-table__body-wrapper tr:visible").filter(has=cell)
    choice = row.locator('input[type="checkbox"], input[type="radio"]')
    if choice.count() != 1:
        raise QueryUnavailable("教务页面未显示该课的重考选择框")
    return choice


def apply_once(page, button):
    refreshed = []

    def record_listing(response):
        if urlsplit(response.url).path == COURSES:
            refreshed.append(response)

    page.on("response", record_listing)
    try:
        button.click()
        deadline = monotonic() + 15
        confirmed = False
        while monotonic() < deadline:
            box = page.locator(".el-message-box:visible, .el-dialog:visible")
            if box.count():
                message = box.inner_text()
                if "申请成功" in message or "提交成功" in message:
                    return
                confirm = box.get_by_role("button", name=re.compile(r"^(确定|确认|确认申请)$"))
                if not confirmed and re.search(r"(是否|确认|确定).*申请|申请.*[？?]", message) and confirm.count() == 1:
                    confirm.click()
                    confirmed = True
                elif not confirmed:
                    raise QueryUnavailable(message)
            if refreshed:
                retake_data(refreshed[-1])
                return
            if page.locator(".el-message--success:visible").count():
                return
            error = page.locator(".el-message--error:visible")
            if error.count():
                raise QueryUnavailable(error.first.inner_text())
            page.wait_for_timeout(100)
    finally:
        page.remove_listener("response", record_listing)
