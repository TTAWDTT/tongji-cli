from urllib.parse import urljoin

from playwright.sync_api import expect

from tongji_cli.jw.records import course_rows, query_data, watch_query
from tongji_cli.common import QueryUnavailable


DEFENSE_VIEW = "/viewReplyArrangement"
DEFENSE_LIST = "/api/designservice/defenseGroup/getStudentDefenseInfo"
TASK_VIEW = "/taskView"
TASK_LIST = "/api/designservice/doc/task/book/list"
TASK_STATES = {"草稿": "WaitCommit", "已通过": "End", "已撤销": "Recall"}


def defenses(page):
    url = urljoin(page.url, DEFENSE_VIEW)
    with watch_query(page, DEFENSE_LIST) as opened:
        page.goto(url, wait_until="domcontentloaded")
    records = query_data(opened.value)
    if not isinstance(records, list):
        raise QueryUnavailable("学校未返回答辩安排清单")
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("答辩时间", exact=True))
    rows = course_rows(page, table)
    if len(rows) != len(records):
        raise QueryUnavailable("答辩安排表与学校返回的记录数不一致")
    return [{**row, "url": url} for row in rows]


def task_books(page, args):
    if args.page < 1:
        raise QueryUnavailable("任务书目录页码从 1 开始")
    if args.year is not None and not 1000 <= args.year <= 9999:
        raise QueryUnavailable("课题年份请使用四位年份")
    url = urljoin(page.url, TASK_VIEW)
    with watch_query(page, TASK_LIST) as opened:
        page.goto(url, wait_until="domcontentloaded")
    response = opened.value
    if args.year or args.state or args.title or args.advisor:
        fill_task_filters(page, args)
        with watch_query(page, TASK_LIST) as filtered:
            page.get_by_role("button", name="筛选", exact=True).click()
        response = filtered.value
    data = task_page(response, args, 1)
    if args.page > max(data["pages"], 1):
        raise QueryUnavailable(f"任务书目录共 {data['pages']} 页，请核对页码")
    if args.page > 1:
        jump = page.locator(".el-pagination:visible .el-pagination__jump input")
        jump.fill(str(args.page))
        with watch_query(page, TASK_LIST) as turned:
            jump.press("Enter")
        data = task_page(turned.value, args, args.page)
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("课题性质", exact=True))
    rows = course_rows(page, table)
    if len(rows) != len(data["list"]):
        raise QueryUnavailable("任务书目录的行数与教务返回的当前页不一致")
    summary = (f"任务书目录共 {data['total']} 条，第 {args.page}/{data['pages']} 页"
               if data["pages"] else "教务目录中没有符合条件的任务书")
    return {"detail": summary, "page": args.page, "pages": data["pages"], "total": data["total"],
            "items": [{**row, "url": url} for row in rows]}


def fill_task_filters(page, args):
    fields = page.locator(".el-form-item:visible")
    for label, value in (("课题名称：", args.title), ("导师：", args.advisor)):
        if value:
            fields.filter(has=page.get_by_text(label, exact=True)).locator("input").fill(value)
    if args.year:
        year = fields.filter(has=page.get_by_text("课题年份：", exact=True)).locator("input")
        year.fill(str(args.year))
        year.press("Enter")
    if args.state:
        state = fields.filter(has=page.get_by_text("状态：", exact=True)).locator("input")
        state.click()
        page.locator(".el-select-dropdown:visible").get_by_text(args.state, exact=True).click()
        expect(state).to_have_value(args.state)


def task_page(response, args, number):
    data = query_data(response)
    request = response.request.post_data_json
    condition = request["condition"]
    if (request["pageNum_"] != number or str(condition.get("grade") or "") != str(args.year or "")
            or (condition.get("status") or "") != TASK_STATES.get(args.state, "")
            or (condition.get("projectName") or "") != (args.title or "")
            or (condition.get("teacherNum") or "") != (args.advisor or "")):
        raise QueryUnavailable("教务任务书查询与筛选条件或页码不一致")
    total, size = data["total"], data["pageSize"]
    if total < 0 or size <= 0 or data["pages"] != (total + size - 1) // size:
        raise QueryUnavailable("教务任务书分页信息不一致")
    empty_first = number == 1 and total == 0 and data["pageNum"] == 0
    if ((data["pageNum"] != number and not empty_first)
            or len(data["list"]) != min(size, max(0, total - (number - 1) * size))):
        raise QueryUnavailable("教务任务书目录与返回页不一致")
    return data
