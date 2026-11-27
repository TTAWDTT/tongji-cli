import re
from urllib.parse import urljoin

from playwright.sync_api import expect

from tongji_cli.jw.records import CALENDARS, calendar_for_term, choose_term, course_rows, query_data, record_batches, term_input, watch_query
from tongji_cli.common import QueryUnavailable


VIEW = "/auditProgressList"
LIST = "/api/arrangementservice/teachingProgress/progressQuery"
DETAIL = "/api/arrangementservice/teachingProgress/getPageContentById"


def progress(page, args):
    url = urljoin(page.url, VIEW)
    with watch_query(page, CALENDARS) as calendars, watch_query(page, LIST) as initial:
        page.goto(url, wait_until="domcontentloaded")
    response = initial.value
    field = term_input(page)
    expect(field).not_to_have_value("")
    if args.term and choose_term(page, args.term):
        with watch_query(page, LIST) as changed:
            page.get_by_role("button", name="筛选", exact=True).click()
        response = changed.value
    term = field.input_value()
    calendar_id = calendar_for_term(calendars.value, term)

    def selected_semester(result):
        data = query_data(result)
        if (result.request.post_data_json["condition"]["calendarId"] != calendar_id
                or any(r["calendarId"] != calendar_id for r in data["list"])):
            raise QueryUnavailable("教学进度的查询结果与所选学期不一致")
        return data

    items = []
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("教学进度状态", exact=True))
    for batch in record_batches(page, LIST, "教学进度", response, selected_semester):
        rows = course_rows(page, table)
        if [(r["课程名称"], r["新课程序号"]) for r in rows] != [(r["courseName"], r["newCourseSeq"] or None) for r in batch]:
            raise QueryUnavailable("教务教学进度表与所选学期的教学班不一致")
        for index, (record, row) in enumerate(zip(batch, rows)):
            item = {"id": str(record["id"]), "学期": term, **row, "url": url}
            if args.action == "show":
                if item["id"] == args.id:
                    return [progress_detail(page, table, index, item)]
            elif not args.search or any(args.search.casefold() in (row[key] or "").casefold()
                                        for key in ("课程名称", "课程编码", "课程代码", "课程序号", "新课程序号", "授课老师")):
                items.append(item)
    if args.action == "show":
        raise QueryUnavailable("该学期的本人教学进度中未找到这个 ID")
    return items


def progress_detail(page, table, index, item):
    button = table.locator(".el-table__body-wrapper tr:visible").nth(index).get_by_role("button", name="查看", exact=True)
    existing = set(page.locator(".el-tabs__item[id]:visible").evaluate_all("tabs=>tabs.map(t=>t.id)"))
    with watch_query(page, DETAIL) as opened:
        button.click()
        limit = page.get_by_text(re.compile("最多.*10.*页签")).filter(visible=True)
        if limit.count():
            raise QueryUnavailable("教务已达到 10 个页签上限，请在教务工作台关闭一个页签后重试")

    try:
        return read_detail(page, item, opened.value)
    finally:
        tab = page.locator(".el-tabs__item.is-active:visible").filter(has_text="查看教学进度")
        if tab.count() == 1 and tab.get_attribute("id") not in existing:
            tab.locator(".el-icon-close").click()


def read_detail(page, item, response):
    url = page.url

    def session_page(response):
        result = query_data(response)
        selected = result["teachingProgress"]
        if str(selected["id"]) != item["id"] or selected["courseName"] != item["课程名称"]:
            raise QueryUnavailable("打开的教学进度与所选记录不一致")
        return result["progressContents"]

    timetable = page.locator(".el-table:visible").filter(has=page.get_by_text("上课时间", exact=True))
    timetable.wait_for()
    page.wait_for_load_state("networkidle")
    fields = {}
    for group in page.locator(".el-form-item:visible").all():
        label = group.locator(".el-form-item__label")
        if label.count():
            key = label.inner_text().strip().rstrip("：:")
            if key:
                fields[key] = group.locator(".el-form-item__content").inner_text().strip() or None
    history = page.locator(".el-table:visible").filter(has=page.get_by_text("审批结果", exact=True))
    approval = course_rows(page, history) if history.count() else []
    sessions = []
    for batch in record_batches(page, DETAIL, "授课安排", response, session_page):
        rows = course_rows(page, timetable)
        if len(rows) != len(batch):
            raise QueryUnavailable("教学进度详情的课次数与教务页面不符")
        if item["显示上课内容"] != "开放":
            for row in rows:
                row.pop("上课内容", None)
        sessions.extend(rows)
    return {**item, "课程信息": fields, "授课安排": sessions,
            "审批进度": approval, "url": url}
