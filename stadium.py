import re
from datetime import datetime
from urllib.parse import urlsplit

from playwright.sync_api import expect

from queries import QueryUnavailable, SHANGHAI


DIRECTORY = "https://stadium.tongji.edu.cn/pc/#/Venue/1"


def venues(page, campus="", venue=""):
    return [row for batch in directory_pages(page) for row in batch
            if campus in row["campus"] and venue in row["title"]]


def directory_pages(page):
    def is_directory(response):
        return urlsplit(response.url).path == "/manage/venue/listNoVenue"

    with page.expect_response(is_directory) as result:
        if page.url == DIRECTORY:
            page.reload(wait_until="domcontentloaded")
        else:
            page.goto(DIRECTORY, wait_until="domcontentloaded")
    seen = 0
    while True:
        response = result.value
        data = response.json() if response.ok else {}
        if data.get("code") != 0 or not isinstance(data.get("rows"), list) or not isinstance(data.get("total"), int):
            raise QueryUnavailable("预约平台未返回场馆目录")
        rows = [{"campus": row["campusName"], "title": row["venueName"], "address": row["venueAddr"],
                 "hours": row["openTime"], "url": DIRECTORY} for row in data["rows"]]
        try:
            expect(page.locator(".cardP15 h3")).to_have_text([row["title"] for row in rows])
        except AssertionError as exc:
            raise QueryUnavailable("预约平台页面与返回的场馆名称不一致") from exc
        seen += len(rows)
        if seen > data["total"] or (seen < data["total"] and not rows):
            raise QueryUnavailable("预约平台的场馆目录条数不符")
        yield rows
        if seen == data["total"]:
            return
        with page.expect_response(is_directory) as result:
            page.locator(".el-pagination .btn-next").click()


def slots(page, venue, date, sport=None):
    for batch in directory_pages(page):
        if any(row["title"] == venue for row in batch):
            fields = load_fields(page, page.locator(".cardP15 h3").filter(has_text=re.compile(rf"^{re.escape(venue)}$")))
            break
    else:
        raise QueryUnavailable("预约平台没有此场馆，请用 sports venues 核对完整名称")

    sport_tabs = page.get_by_role("tab").filter(has_not_text=re.compile(r"\d+月\d+日"), visible=True)
    sports = [name.strip() for name in sport_tabs.all_inner_texts()]
    if sport is None and len(sports) == 1:
        sport = sports[0]
    if sport not in sports:
        raise QueryUnavailable("请用 --sport 指定页面上的运动项目：" + "、".join(sports))
    project = page.get_by_role("tab", name=sport, exact=True)
    if project.get_attribute("aria-selected") != "true":
        fields = load_fields(page, project)

    day = date.isoformat()
    tab = page.locator(f'[role="tab"][id="tab-{day}"]:visible')
    if not tab.count() or "is-disabled" in (tab.get_attribute("class") or "").split():
        raise QueryUnavailable("预约平台未开放所选日期")
    if tab.get_attribute("aria-selected") != "true":
        fields = load_fields(page, tab)
    expect(tab).to_have_attribute("aria-selected", "true")
    expect(page.locator(".drawerText h2:visible")).to_contain_text(day)
    return field_rows(page, fields, venue, sport, day)


def load_fields(page, control):
    with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/queryFieldSituation")) as result:
        control.click()
    response = result.value
    body = response.json() if response.ok else {}
    if body.get("code") != 0 or not isinstance(body.get("data"), list):
        raise QueryUnavailable("预约平台未返回该场馆的场地状态")
    page.locator(".tables .el-loading-mask:visible").wait_for(state="hidden")
    return [field["fieldName"] for field in body["data"]]


def field_rows(page, fields, venue, sport, day):
    table = page.locator(".tables:visible")
    expect(table.locator(".inner-seat-wrapper .topsiteStyle")).to_have_text(fields)
    if not fields:
        return []
    times = [text.strip() for text in page.locator(".leftUl:visible li").all_inner_texts()]
    grid = table.locator(".inner-seat-wrapper > div.clearfix").evaluate_all("""rows => rows.map(row =>
        Array.from(row.querySelectorAll('.seat'), seat => seat.querySelector('.inner-seat')?.className || '')
    ).filter(row => row.length)""")
    if len(times) != len(grid) + 1 or any(len(row) != len(fields) for row in grid):
        raise QueryUnavailable("预约平台的场地、时间刻度和状态网格未对齐")
    observed = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    items = []
    for i, row in enumerate(grid):
        for field, classes in zip(fields, row):
            status = next((label for key, label in CELL_STATES.items() if key in classes.split()), "未核实")
            items.append({"venue": venue, "sport": sport, "date": day, "field": field,
                          "time_slot": f"{times[i]}-{times[i + 1]}", "available": {"可选择": True, "不可选": False}.get(status),
                          "status": status, "observed_at": observed, "url": DIRECTORY})
    return items


CELL_STATES = {"bought-seat": "不可选", "unselected-seat": "可选择", "selected-seat": "选中的"}
