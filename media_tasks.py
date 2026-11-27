import re
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect

from queries import QueryUnavailable


TASKS = "https://look.tongji.edu.cn/personal/#/myStudy/myTask"
LIST_PATH = "/personal/courseapi/courseapi/v3/multi-search/get-my-sub-list"


def tasks(page, args):
    if args.operation == "tasks" and args.kind == "optional" and args.status:
        raise QueryUnavailable("校方仅对必做任务提供完成状态筛选")
    params = {"page": "1", "must": "1"}
    task_request(page, lambda: page.goto(TASKS, wait_until="domcontentloaded"), params)
    term, choices, names = term_menu(page)
    if args.operation == "terms":
        return [{"term": name} for name in names if name != "全部"]
    if args.term not in names:
        raise QueryUnavailable("媒体平台未列出这个学期，请用 media terms 核对")
    result = filtered_tasks(page, args, term, choices, params)
    items = []
    while True:
        items.extend(page_rows(page, result["list"], args.kind))
        total = int(result["total"])
        if len(items) == total:
            return items
        button = page.locator(".el-pagination .btn-next")
        if not result["list"] or len(items) > total or not button.is_enabled():
            raise QueryUnavailable("任务表与平台公布的结果总数不符")
        params["page"] = str(int(params["page"]) + 1)
        result, _ = task_request(page, button.click, params)


def term_menu(page):
    term = page.locator(".el-dropdown-selfdefine").first
    term.click()
    choices = page.locator(".el-dropdown-menu__item:visible")
    choices.first.wait_for()
    return term, choices, [name.strip() for name in choices.all_text_contents()]


def filtered_tasks(page, args, term, choices, params):
    option = choices.filter(has_text=re.compile(r"^\s*" + re.escape(args.term) + r"\s*$"))
    result, applied = task_request(page, option.click, params)
    expect(term).to_have_text(args.term)
    if args.term != "全部":
        if not applied.get("term"):
            raise QueryUnavailable("媒体平台未应用所选学期")
        params["term"] = applied["term"][0]
    if args.kind == "optional":
        params["must"] = "2"
        result, _ = task_request(page, page.get_by_role("button", name="选做", exact=True).click, params)
    if args.status:
        params["finish_status"] = {"已完成": "1", "未完成": "2"}[args.status]
        button = page.locator(".private-button-gounp").get_by_text(args.status, exact=True)
        result, _ = task_request(page, button.click, params)
    if args.task_type:
        page.get_by_placeholder("请选择任务类型").click()
        options = page.locator(".el-select-dropdown__item:visible")
        options.first.wait_for()
        choice = options.filter(has_text=re.compile(r"^\s*" + re.escape(args.task_type) + r"\s*$"))
        if choice.count() != 1:
            raise QueryUnavailable("这个任务类型不在校方选项中：" + "、".join(options.all_inner_texts()))
        result, applied = task_request(page, choice.click, params)
        params["sub_type"] = applied["sub_type"][0]
    if args.search:
        field = page.get_by_placeholder("请输入课程名称/任务名")
        field.fill(args.search)
        params["search"] = args.search
        result, _ = task_request(page, lambda: field.press("Enter"), params)
    return result


def task_request(page, action, params):
    def matches(response):
        url = urlsplit(response.url)
        if url.path != LIST_PATH or response.request.method != "GET":
            return False
        query = parse_qs(url.query)
        return all(query.get(key) == [value] for key, value in params.items())

    with page.expect_response(matches) as pending:
        action()
    response = pending.value
    if not response.ok:
        raise QueryUnavailable(f"媒体平台任务查询失败（HTTP {response.status}）")
    payload = response.json()
    if payload["code"] != 0 or not isinstance(payload["data"]["list"], list):
        raise QueryUnavailable("媒体平台未返回可核对的任务列表")
    return payload["data"], parse_qs(urlsplit(response.url).query)


def page_rows(page, records, kind):
    rows = page.locator(".el-table__body tbody tr")
    expect(rows.locator("td:nth-child(2)")).to_have_text([r["sub_title"] for r in records])
    expect(rows.locator("td:nth-child(3)")).to_have_text([r["course_title"] for r in records])
    columns = ["type", "title", "course"]
    if kind == "required":
        columns.append("completion_status")
    columns.extend(["start_time", "end_time", "action"])
    cells = rows.evaluate_all("rows => rows.map(r => Array.from(r.cells, c => c.innerText.trim()))")
    return [dict(zip(columns, values, strict=True), id=r["sub_id"], course_id=r["course_id"])
            for r, values in zip(records, cells, strict=True)]
