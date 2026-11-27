from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as BrowserTimeout, expect

from queries import QueryUnavailable


def transactions(page, start, end):
    if start > end:
        raise QueryUnavailable("起始日期不能晚于截止日期")
    page.get_by_role("link", name="个人中心", exact=True).click()
    frame = page.frame_locator('iframe[name="comepage"]')
    menu = page.locator(".side-menu-box h2").filter(has_text="我的校园卡").first
    menu.hover(position={"x": 25, "y": 12})
    link = menu.get_by_text("流水信息", exact=True).filter(visible=True).last
    with report_response(page):
        link.click()
    dates = frame.locator("input.textbox-text:visible")
    choose_date(frame, dates.nth(0), start)
    choose_date(frame, dates.nth(1), end)
    with report_response(page) as first:
        frame.get_by_text("查询", exact=True).filter(visible=True).click()
    return read_pages(page, frame, first.value)


def choose_date(frame, field, day):
    field.click()
    calendar = frame.locator(".calendar:visible")
    cell = calendar.locator(f'td.calendar-day[abbr="{day.year},{day.month},{day.day}"]')
    if not cell.count() or "calendar-other-month" in (cell.get_attribute("class") or ""):
        calendar.locator(".calendar-title").click()
        calendar.locator(".calendar-menu-year").fill(str(day.year))
        calendar.locator(f'.calendar-menu-month[abbr="{day.month}"]').click()
    cell.click(timeout=5000)
    if field.input_value() != day.isoformat():
        raise QueryUnavailable("日期选择器未选中指定日期")


def report_response(page):
    return page.expect_response(lambda r: r.request.frame.name == "comepage" and
                                urlsplit(r.url).path == "/Report/GetPersonTrjn", timeout=20000)


def read_pages(page, frame, response):
    grid = frame.locator(".datagrid-view2:visible")
    headers = grid.locator(".datagrid-header td[field]:visible")
    headers.first.wait_for(timeout=10000)
    columns = headers.evaluate_all("es=>es.map(e=>[e.getAttribute('field'),e.innerText.trim()])")
    labels = [label for _, label in columns]
    fields = [key for key, _ in columns]
    if not {"OCCTIME", "TRANAMT", "TRANNAME"}.issubset(fields):
        raise QueryUnavailable("一卡通流水表头待核实")
    items = []
    total = None
    number = 1
    while True:
        if not response.ok:
            raise QueryUnavailable(f"一卡通查询返回 HTTP {response.status}")
        # 校方正常返回流水时也会给出 issucceed=false，按页码、总数和实际显示的记录核对。
        data = response.json()
        if total is None:
            total = data["total"]
        if total != data["total"] or not isinstance(total, int) or not isinstance(data["rows"], list):
            raise QueryUnavailable("一卡通流水总数或分页数据待核实")
        expected = [[row[key] for key in fields] for row in data["rows"]]
        try:
            expect(frame.locator("input.pagination-num")).to_have_value(str(number if total else 0))
            values = rendered_rows(page.frame(name="comepage"), fields, expected)
        except (AssertionError, BrowserTimeout):
            raise QueryUnavailable("页面显示的流水记录与一卡通本次查询结果不一致") from None
        items.extend(dict(zip(labels, (value or None for value in row))) for row in values)
        if len(items) == total:
            return items
        next_page = frame.locator("a:visible").filter(has=frame.locator(".pagination-next"))
        if not expected or len(items) > total or not next_page.count() or "l-btn-disabled" in (next_page.get_attribute("class") or ""):
            raise QueryUnavailable("已加载流水记录数与一卡通总数不一致")
        with report_response(page) as following:
            next_page.click()
        response = following.value
        number += 1


def rendered_rows(frame, fields, expected):
    snapshot = frame.wait_for_function("""({fields, expected}) => {
        const grid = [...document.querySelectorAll('.datagrid-view2')].find(e => e.getClientRects().length);
        if (!grid) return false;
        const rows = [...grid.querySelectorAll('.datagrid-body tr.datagrid-row')].filter(r => r.getClientRects().length);
        if (rows.length !== expected.length) return false;
        const values = [];
        for (const [i, row] of rows.entries()) {
            const cells = [...row.querySelectorAll('td[field]')].filter(c => c.getClientRects().length);
            if (cells.length !== fields.length) return false;
            const display = [];
            for (const [j, cell] of cells.entries()) {
                if (cell.getAttribute('field') !== fields[j]) return false;
                const text = cell.innerText.trim();
                const raw = expected[i][j];
                if (text !== String(raw ?? '').trim()) {
                    if (raw == null || raw === '' || !text || !['TRANAMT', 'CARDBAL'].includes(fields[j]) ||
                        Number(text) !== Number(raw)) return false;
                }
                display.push(text);
            }
            values.push(display);
        }
        return values;
    }""", arg={"fields": fields, "expected": expected}, timeout=10000)
    try:
        return snapshot.json_value()
    finally:
        snapshot.dispose()
