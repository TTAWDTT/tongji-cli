from collections import Counter
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.sync_api import expect

from jw_records import CALENDARS, calendar_for_term, choose_term, query_data, term_input, watch_query
from queries import QueryUnavailable


VIEW = "/StudentMajorTimeTable"
LIST = "/api/arrangementservice/timetable/major"


def major_timetable(page, requested_term, search):
    url = urljoin(page.url, VIEW)
    with watch_query(page, CALENDARS) as calendars, watch_query(page, LIST) as initial:
        page.goto(url, wait_until="domcontentloaded")
    field = term_input(page)
    expect(field).not_to_have_value("")
    term = field.input_value()
    response = initial.value
    if requested_term and requested_term.strip() not in (term, term.replace("学年", "")):
        with watch_query(page, LIST) as changed:
            choose_term(page, requested_term)
        response = changed.value
        term = field.input_value()
    selected = calendar_for_term(calendars.value, term)
    if parse_qs(urlsplit(response.url).query).get("calendarId") != [str(selected)]:
        raise QueryUnavailable("专业课表返回的学期与所选学期不一致")
    records = query_data(response)
    grid = page.locator("table:visible").filter(has=page.get_by_text("节次/周次", exact=True))
    grid.wait_for()
    page.wait_for_load_state("networkidle")
    entries = grid.locator(".el-popover__reference:visible").evaluate_all("""cards => cards.flatMap(card => {
        const spans = Array.from(card.querySelectorAll(':scope > span'));
        return (spans.length ? spans : [card]).map(el => el.innerText.trim());
    })""")
    if Counter(entries) != Counter(r["value"].strip() for r in records):
        raise QueryUnavailable("专业课表的可见排课与所选学期的查询结果不一致")
    return [{"学期": term, "课程名称": r["courseName"], "课程序号": r["code"], "星期": r["dayOfWeek"],
             "开始节次": r["timeStart"], "结束节次": r["timeEnd"], "教室": r.get("roomName"),
             "排课": r["value"].strip(), "url": url}
            for r in sorted(records, key=lambda r: (r["dayOfWeek"], r["timeStart"]))
            if not search or search.casefold() in r["value"].casefold()]
