import re
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import expect

from jw_records import CALENDARS, calendar_for_term, choose_term, query_data, term_input, watch_query
from queries import QueryUnavailable


CATALOG = "/undergraduateQuery"
LIST = "/api/syllabusservice/syllabusEntryUnder/submit/getList"
DETAIL = "/api/syllabusservice/syllabusEntryUnder/getSyllabusById"


def syllabus(page, args):
    keyword = args.keyword.strip()
    if args.action == "search" and args.page < 1:
        raise QueryUnavailable("教学大纲页码从 1 开始")
    url = urljoin(page.url, CATALOG)
    with watch_query(page, CALENDARS) as calendars, watch_query(page, LIST) as initial:
        page.goto(url, wait_until="domcontentloaded")
    response = initial.value
    field = term_input(page)
    expect(field).not_to_have_value("")
    changed = args.term and choose_term(page, args.term)
    if keyword or changed:
        search = page.get_by_placeholder("请输入课程编码、代码、课程名称搜索")
        search.fill(keyword)
        with page.expect_request(lambda r: urlsplit(r.url).path == LIST and
                                 (r.post_data_json["condition"].get("course") or "") == keyword,
                                 timeout=18000) as filtered:
            if keyword:
                search.press("Enter")
            else:
                page.get_by_role("button", name="筛选", exact=True).click()
        response = filtered.value.response()
        if response is None:
            raise QueryUnavailable("教务系统未返回教学大纲查询结果")
    term = field.input_value()
    calendar_id = calendar_for_term(calendars.value, term)
    data = catalog_page(response, keyword, 1, calendar_id)
    total = int(data["total_"])
    size = int(data["pageSize_"])
    pages = (total + size - 1) // size
    if args.action == "search":
        if args.page > max(1, pages):
            raise QueryUnavailable(f"教学大纲共 {pages} 页，请核对页码")
        if args.page > 1:
            data = go_to_page(page, keyword, args.page, calendar_id)
        return {"items": [catalog_item(r, term, url) for r in data["list"]], "page": args.page,
                "total": total, "pages": pages, "detail": f"{term}，匹配 {total} 条，共 {pages} 页"}
    matches = []
    current_page = 1
    for number in range(1, pages + 1):
        if number != current_page:
            data = go_to_page(page, keyword, number, calendar_id)
            current_page = number
        for index, row in enumerate(data["list"]):
            codes = {str(row.get(k) or "").casefold() for k in ("newCode", "code")}
            if keyword.casefold() in codes and (args.id is None or str(row["id"]) == args.id):
                matches.append((number, index, row))
        if matches and args.id is not None:
            break
    if len(matches) != 1:
        raise QueryUnavailable("没有唯一匹配的教学大纲，请先用 jw syllabus search 核对课程编码和大纲编号，再用 --id 选择")
    number, index, row = matches[0]
    if number != current_page:
        data = go_to_page(page, keyword, number, calendar_id)
        indexes = [i for i, candidate in enumerate(data["list"]) if candidate["id"] == row["id"]]
        if len(indexes) != 1:
            raise QueryUnavailable("教学大纲目录发生变化，请重新查询")
        index = indexes[0]
    return [read_syllabus(page, index, row, term, url)]


def catalog_page(response, keyword, number, calendar_id):
    data = query_data(response)
    payload = response.request.post_data_json
    if (not isinstance(data, dict) or not isinstance(data.get("list"), list)
            or int(data["pageNum_"]) != number or int(data["pageSize_"]) < 1
            or (payload["condition"].get("course") or "") != keyword):
        raise QueryUnavailable("教务返回的教学大纲页与查询条件不一致")
    if (payload["condition"].get("calendarId") != calendar_id
            or any(row.get("calendarId") != calendar_id for row in data["list"])):
        raise QueryUnavailable("教学大纲查询结果与所选学期不一致")
    total, size = int(data["total_"]), int(data["pageSize_"])
    if len(data["list"]) != min(size, max(0, total - (number - 1) * size)):
        raise QueryUnavailable("教学大纲条数与分页信息不符")
    return data


def go_to_page(page, keyword, number, calendar_id):
    jump = page.locator(".el-pagination:visible .el-pagination__jump input")
    jump.fill(str(number))
    with watch_query(page, LIST) as response:
        jump.press("Enter")
    return catalog_page(response.value, keyword, number, calendar_id)


def catalog_item(row, term, url):
    return {"syllabus_id": str(row["id"]), "学期": term, "课程编码": row.get("newCode"),
            "课程代码": row.get("code"), "课程名称": row["name"], "开课学院": row.get("collegeName"),
            "培养层次": row.get("trainingLevelName"), "学分": row.get("credits"),
            "总学时": row.get("period"), "周学时": row.get("weekHour"), "url": url}


def read_syllabus(page, index, row, term, url):
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("课程编码", exact=True)).first
    listing = table.locator(".el-table__body-wrapper tr:visible").nth(index)
    expect(listing.get_by_text(row["name"], exact=True)).to_be_visible()
    with watch_query(page, DETAIL) as response:
        listing.get_by_role("button", name="查看", exact=True).click()
    detail = query_data(response.value)
    if str(detail["id"]) != str(row["id"]) or detail["name"] != row["name"]:
        raise QueryUnavailable("打开的教学大纲与所选目录记录不一致")
    basic = page.locator(".practiceTable:visible, .detail-container2 .el-card__body > section:visible"
                         ":not(:has(.practiceTable)):has(.big-title:text('模板基础信息'))")
    expect(basic).to_contain_text(row["name"])
    sections = page.locator(".chapterBox:visible > .chapter:visible:not(.chapter .chapter)")
    expect(sections).to_have_count(len(detail["chapters"]))
    content = []
    for section, chapter in zip(sections.all(), detail["chapters"]):
        title = section.locator("h1,h2,h3").first.inner_text().strip()
        if re.sub(r"^\d+\.\s*", "", title) != chapter["chapterName"].strip():
            raise QueryUnavailable("教学大纲的页面章节与所选大纲不一致")
        body = section.inner_text().strip().removeprefix(title).strip()
        content.append({"title": title, "body": body})
    return {**catalog_item(row, term, url), "基本信息": basic.inner_text().strip(), "章节": content}
