import re
from collections import Counter
import os
from pathlib import Path
from time import monotonic
from tempfile import TemporaryDirectory
from zipfile import ZipFile, BadZipFile
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import TimeoutError as BrowserTimeout, expect

from queries import QueryUnavailable


# 这些地址来自个人工作台各折叠菜单中的二级链接。
VIEWS = {
    "courses": ("研究生个人课表", "/GraduateStudentTimeTable", "上课时间"),
    "exams": ("我的考试", "/StuExamEnquiries", "考试时间"),
    "grades": ("选课网我的成绩", "/oldStysteMyGrades", "成绩性质"),
    "requests": ("个人选课", "/studentElect", "回复说明"),
    "withdrawals": ("期中退课", "/MidTermWithdrawalCourses", "新课程序号"),
    "credits": ("我的培养计划", "/traningPlanMy", "已完成学分"),
}


PAGED_QUERIES = {
    "exams": "/api/electionservice/undergraduateExamQuery/getStudentListPage",
    "requests": "/api/electionservice/electionApply/stuApplyCourseList",
    "withdrawals": "/api/electionservice/elcMedWithdraw/page",
}


def watch_query(page, path):
    return page.expect_response(lambda response: urlsplit(response.url).path == path, timeout=18000)


def query_data(response):
    if not response.ok:
        raise QueryUnavailable(f"教务查询返回 HTTP {response.status}")
    body = response.json()
    if str(body.get("code")) != "200":
        raise QueryUnavailable(body.get("msg") or "教务系统未能完成查询")
    return body["data"]


def record_pages(page, url, path, title):
    with watch_query(page, path) as first:
        page.goto(url, wait_until="domcontentloaded")
    yield from record_batches(page, path, title, first.value)


def record_batches(page, path, title, response, unpack=query_data):
    data = unpack(response)
    total, size = int(data["total_"]), int(data["pageSize_"])
    if size <= 0 or total < 0:
        raise QueryUnavailable(f"教务「{title}」分页信息无效")
    seen = set()
    for number in range(1, max(1, (total + size - 1) // size) + 1):
        if number > 1:
            jump = page.locator(".el-pagination:visible .el-pagination__jump input")
            jump.fill(str(number))
            with watch_query(page, path) as turn:
                jump.press("Enter")
            data = unpack(turn.value)
        rows = data["list"]
        if (data["pageNum_"] != number or data["total_"] != total or data["pageSize_"] != size
                or len(rows) != min(size, total - (number - 1) * size)):
            raise QueryUnavailable(f"教务「{title}」目录发生变化，请重新查询")
        ids = {row["id"] for row in rows}
        if len(ids) != len(rows) or seen.intersection(ids):
            raise QueryUnavailable(f"教务「{title}」目录编号重复，请重新查询")
        seen.update(ids)
        yield rows


CALENDARS = "/api/baseresservice/schoolCalendar/list"
TIMETABLE_QUERY = "/api/electionservice/reportManagement/findStudentTimetab"


def calendar_for_term(response, term):
    ids = [c["id"] for c in query_data(response)
           if f"{c['year']}-{int(c['year']) + 1}学年第{c['term']}学期" == term]
    if len(ids) != 1:
        raise QueryUnavailable("教务校历未能确认所选学期")
    return ids[0]


def term_courses(page, url, requested):
    with watch_query(page, TIMETABLE_QUERY) as response:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    rows = query_data(response.value)
    if not choose_term(page, requested):
        return rows
    with watch_query(page, TIMETABLE_QUERY) as response:
        page.get_by_role("button", name="筛选", exact=True).click()
    return query_data(response.value)


def choose_term(page, requested):
    match = re.fullmatch(r"(\d{4}-\d{4})(?:学年)?(第\d+学期)", requested.strip())
    if not match:
        raise QueryUnavailable("请使用 calendar terms 所列的完整学期名，例如 2025-2026第2学期")
    year, semester = match.groups()
    expected = year + "学年" + semester
    field = term_input(page)
    expect(field).not_to_have_value("")
    if field.input_value() == expected:
        return False
    field.click()
    picker = page.locator(".el-popover:visible").filter(has=page.locator(".calendar-table"))
    picker.wait_for()
    for table, name in ((".calendar-table", year), (".calendar-term-table", semester)):
        option = picker.locator(table).get_by_text(name, exact=True)
        if not option.is_visible():
            raise QueryUnavailable("教务学期选择器未列出「" + name + "」")
        option.click()
    expect(field).to_have_value(expected)
    return True


def records(page, operation, *, requested_term=None):
    title, path, marker = VIEWS[operation]
    url = urljoin(page.url, path)
    try:
        if requested_term is not None:
            term_rows = term_courses(page, url, requested_term)
        elif operation in PAGED_QUERIES:
            with watch_query(page, PAGED_QUERIES[operation]) as result_page:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            query_data(result_page.value)
        else:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if operation == "credits":
            table = page.locator("table:visible").filter(has=page.get_by_text(marker, exact=True)).first
            table.wait_for(timeout=10000)
            result = credit_categories(table)
        else:
            tables = page.locator(".el-table:visible").filter(has=page.get_by_text(marker, exact=True))
            tables.first.wait_for(timeout=10000)
            if requested_term is not None:
                result = verified_term_rows(page, tables, term_rows)
            else:
                result = [row for table in tables.all() for row in course_rows(page, table)]
            if operation in PAGED_QUERIES:
                append_record_pages(page, tables.first, result, operation)
            if operation in {"courses", "withdrawals"}:
                term = selected_term(page)
                for row in result:
                    row["学期"] = term
    except BrowserTimeout:
        raise QueryUnavailable(f"未能完整读取教务「{title}」。请在 1 系统核对当前身份、菜单及结果表。") from None
    return [dict(row, source=title, url=url) for row in result]


def verified_term_rows(page, tables, term_rows):
    expected = Counter((str(r["classCode"] or "").strip(), r["courseName"]) for r in term_rows)
    deadline = monotonic() + 5
    while True:
        rows = [row for table in tables.all() for row in course_rows(page, table)]
        if Counter((r["课程序号"] or "", r["课程名称"]) for r in rows) == expected:
            return rows
        if monotonic() >= deadline:
            raise QueryUnavailable("所选学期的课程序号、名称或条数与教务返回的课表不符")
        page.wait_for_timeout(100)


def course_rows(page, table):
    table.locator(".el-table__body-wrapper tr:visible, .el-table__empty-text:visible").first.wait_for(timeout=10000)
    page.wait_for_load_state("networkidle", timeout=12000)
    labels = table.locator(".el-table__header-wrapper th:not(.gutter)").all_inner_texts()
    labels = [s.strip() for s in labels]
    semester_text = table.evaluate("e => e.previousElementSibling?.innerText || ''")
    semester = re.search(r"20\d{2}\s*[-－]\s*20\d{2}学年第[一二三四\d]+学期", semester_text)
    values = table.locator(".el-table__body-wrapper tr:visible").evaluate_all(
        "rows => rows.map(row => Array.from(row.cells, cell => cell.innerText.trim()))"
    )
    if not values and not table.locator(".el-table__empty-text:visible").count():
        raise QueryUnavailable("教务结果仍在加载")
    result = []
    for cells in values:
        if len(labels) != len(cells):
            raise QueryUnavailable("教务表头和数据列不匹配")
        entry = {label: value or None for label, value in zip(labels, cells) if label not in {"", "序号", "操作"}}
        if semester:
            entry["学期"] = semester.group()
        result.append(entry)
    return result


def append_record_pages(page, table, result, operation):
    title = VIEWS[operation][0]
    pagination = page.locator(".el-pagination:visible")
    if not pagination.count():
        return
    total = re.search(r"共\s*(\d+)\s*条", pagination.inner_text())
    next_page = pagination.locator("button.btn-next")
    while next_page.is_enabled():
        active = pagination.locator(".el-pager .active")
        next_number = int(active.inner_text()) + 1
        with watch_query(page, PAGED_QUERIES[operation]) as result_page:
            next_page.click()
        query_data(result_page.value)
        try:
            expect(active).to_have_text(str(next_number), timeout=10000)
        except AssertionError:
            raise QueryUnavailable(f"未能核实「{title}」已经换页") from None
        result.extend(course_rows(page, table))
    if total and int(total[1]) != len(result):
        raise QueryUnavailable(f"「{title}」记录数与页面总数不符")


def table_grid(table, fixed_wrapper=None):
    return table.evaluate("""(table, fixedWrapper) => {
        const fixed = fixedWrapper && table.closest('.el-table').querySelector(fixedWrapper);
        const grid = [];
        for (const [i, row] of Array.from(table.rows).entries()) {
            grid[i] ??= [];
            let j = 0;
            for (const cell of row.cells) {
                const visible = fixed && cell.classList.contains("is-hidden")
                    ? fixed.rows[i].cells[cell.cellIndex] : cell;
                const value = visible.innerText.trim();
                while (grid[i][j] !== undefined) j++;
                for (let y = i; y < i + cell.rowSpan; y++) {
                    grid[y] ??= [];
                    for (let x = j; x < j + cell.colSpan; x++) grid[y][x] = value;
                }
                j += cell.colSpan;
            }
        }
        return grid;
    }""", fixed_wrapper)


def credit_categories(table):
    grid = table_grid(table)
    metrics = {"培养方案要求学分", "个人计划学分", "已完成学分"}
    headers, values = [], {}
    for row in grid:
        if row[0] in metrics:
            values[row[0]] = row
        elif not values:
            headers.append(row)
    if not headers or values.keys() != metrics:
        raise QueryUnavailable("培养计划页未显示完整的学分类别与要求、计划、已完成学分")
    width = len(headers[0])
    if width < 2 or any(len(row) != width for row in [*headers, *values.values()]):
        raise QueryUnavailable("培养计划学分类别与分值列不匹配")
    categories = []
    for column in range(1, width):
        levels = dict.fromkeys(row[column] for row in headers if row[column])
        entry = {"课程类别": " / ".join(levels)}
        entry.update({name: row[column] or None for name, row in values.items()})
        categories.append(entry)
    return categories


def personal_plan(page, output=None):
    title, path, _ = VIEWS["credits"]
    url = urljoin(page.url, path)
    page.goto(url, wait_until="domcontentloaded")
    table = page.locator("table:visible").filter(has=page.get_by_text("课程编码", exact=True)).first
    summary = page.get_by_text(re.compile(r"^\s*(总计|合计)\s*$"))
    course = table.locator("tr").filter(has=page.locator("td")).filter(has_not=summary)
    course.first.wait_for(timeout=18000)
    if output is not None:
        return export_plan(page, output, url)
    return [dict(row, source=title, url=url) for row in plan_courses(table)]


def plan_courses(table):
    header, *rows = table_grid(table)
    if header[:2] != ["课程类别", "课程类别"] or "课程名称" not in header or "课程编码" not in header:
        raise QueryUnavailable("培养计划课程表头待核实")
    found = []
    for row in rows:
        if row[0] in {"总计", "合计"}:
            continue
        if len(row) != len(header):
            raise QueryUnavailable("培养计划课程字段与表头不符")
        entry = dict(zip(header[2:], (value or None for value in row[2:])))
        if not entry["课程名称"]:
            raise QueryUnavailable("培养计划课程行未显示课程名称")
        entry["课程类别"] = " / ".join(dict.fromkeys(v for v in row[:2] if v))
        found.append(entry)
    return found


def export_plan(page, output, url):
    dest = Path(output).expanduser().absolute()
    if dest.exists() or not dest.parent.is_dir():
        raise QueryUnavailable("请在已有目录中指定一个新文件名")
    with TemporaryDirectory(dir=dest.parent) as directory:
        staged = Path(directory) / "plan.zip"
        with page.expect_download(timeout=30000) as pending:
            page.get_by_role("button", name="导出个人计划", exact=True).click()
        pending.value.save_as(staged)
        try:
            with ZipFile(staged) as archive:
                if not any(not entry.is_dir() and entry.file_size for entry in archive.infolist()) or archive.testzip():
                    raise QueryUnavailable("教务导出的培养计划压缩包不完整")
        except BadZipFile:
            raise QueryUnavailable("教务导出文件不是有效的 ZIP 压缩包") from None
        os.link(staged, dest)
    return [{"path": str(dest), "bytes": dest.stat().st_size, "source": "导出个人计划", "url": url}]


def enrollment_status(page):
    title, path, _ = VIEWS["requests"]
    url = urljoin(page.url, path)
    with watch_query(page, "/api/electionservice/student/getRounds") as result:
        page.goto(url, wait_until="domcontentloaded")
    rounds = query_data(result.value)
    if not isinstance(rounds, list):
        raise QueryUnavailable("教务选课轮次格式待核实")
    if not rounds:
        page.get_by_text(re.compile(r"当前没有对您开放的选课")).filter(visible=True).first.wait_for(timeout=10000)
        return [{"state": "closed", "detail": "当前没有对您开放的选课", "source": title, "url": url}]
    page.get_by_text("选择课程", exact=True).filter(visible=True).first.wait_for(timeout=10000)
    return [{"state": "entry_visible", "detail": "个人选课页显示选择课程入口", "source": title, "url": url}]


def term_input(page):
    term_field = page.locator(".el-form-item:visible").filter(has=page.get_by_text(re.compile(r"^(学年学期|学期学年)：?$")))
    return term_field.locator("input:visible")


def selected_term(page):
    return term_input(page).input_value(timeout=5000).strip()


def check_withdrawal(page, class_id):
    withdrawals = records(page, "withdrawals")
    matches = [row for row in withdrawals if row.get("新课程序号") == class_id]
    if len(matches) != 1:
        raise QueryUnavailable("请使用当前学期期中退课列表中唯一的新课程序号")
    row = matches[0]
    courses = records(page, "courses")
    term = selected_term(page)
    if not term or term != row.get("学期"):
        raise QueryUnavailable("退课记录与个人课表所选学期不一致")
    return [{"新课程序号": class_id, "课程名称": row["课程名称"], "学期": term, "退课记录状态": row["状态"],
             "个人课表列有该课": any(course.get("新课程序号") == class_id for course in courses),
             "退课记录链接": row["url"], "个人课表链接": page.url}]
