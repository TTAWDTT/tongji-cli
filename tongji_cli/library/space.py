import re
from datetime import date, datetime
from time import monotonic
from urllib.parse import urlsplit

from playwright.sync_api import Error, expect

from tongji_cli.library.services import SEATS
from tongji_cli.common import QueryUnavailable, SHANGHAI


RECORD_TYPES = {"seat": "座位预约记录", "room": "空间预约记录", "research": "研修专座预约记录"}


def reservation_history(page, kind, limit):
    if limit is not None and limit < 1:
        raise QueryUnavailable("预约记录条数必须大于零")
    record_link = page.get_by_text(RECORD_TYPES[kind], exact=True).filter(visible=True).first
    page.get_by_text("研习室预约", exact=True).filter(visible=True).first.or_(record_link).first.wait_for()
    page.get_by_text("我的中心", exact=True).click()
    record_link.click()
    listing = page.locator(".van-list:visible")
    cards = listing.locator(".contract_list > .item")
    finished = listing.get_by_text("没有更多了", exact=True)
    error = listing.locator(".van-list__error-text")
    cards.first.or_(finished).or_(error).first.wait_for()
    while (limit is None or cards.count() < limit) and not finished.is_visible():
        if error.is_visible():
            raise QueryUnavailable("馆方未能加载预约记录")
        previous = cards.count()
        listing.locator(".van-list__placeholder").scroll_into_view_if_needed()
        cards.nth(previous).or_(finished).or_(error).first.wait_for()
    items = []
    for card in cards.all()[:limit]:
        place = card.locator(".item_left .top")
        place.wait_for()
        time = card.locator(".item_left .bottom").inner_text().strip()
        items.append({"kind": kind, "location": place.inner_text().strip(),
                      "time": time.removeprefix("时间：").strip(),
                      "status": card.locator(".item_right").inner_text().strip(), "url": page.url.split("?")[0]})
    return items


STUDY_TYPES = {"research": "研修座位", "exam": "考研座位"}


def availability(page, requested_date=None, branch=None, floor=None, area=None, time_slot=None, *,
                 study_type=None, period="current"):
    if floor and not branch:
        raise QueryUnavailable("指定 --floor 时需要提供 --branch")
    seat_type_label = STUDY_TYPES[study_type] if study_type else "座位预约"
    open_seats = page.get_by_text(seat_type_label, exact=True).filter(visible=True).first
    data = None
    if branch or requested_date or study_type:
        data = load_choices(page, open_seats)
    else:
        open_seats.click()
    sections = page.locator(".section:visible")
    halls = sections.filter(has=page.get_by_text("馆舍", exact=True))
    if data is None or data["premises"]:
        halls.locator(".normalList > .item .info").first.wait_for(timeout=20000)
    dates = sections.filter(has=page.get_by_text("日期", exact=True))
    active = dates.locator(".dayList .active .day")
    day = date.fromisoformat(active.inner_text().strip()).isoformat()
    if requested_date and requested_date.isoformat() != day:
        day = requested_date.isoformat()
        date_option = dates.get_by_text(day, exact=True)
        if not date_option.is_visible():
            raise QueryUnavailable("馆方未开放所选预约日期")
        data = load_choices(page, date_option)
        expect(active).to_have_text(day)
    choices = data["premises"] if data is not None else None
    section = halls
    location = {}
    for key, value, label, child_key in (("branch", branch, "楼层", "storey"),
                                          ("floor", floor, "区域", "area"), ("area", area, None, None)):
        if choices is not None:
            verify_counts(section, choices)
        if value is None:
            if choices == []:
                return []
            rows = count_rows(page, section, key, location, day)
            return [dict(row, seat_type=seat_type_label) for row in rows] if study_type else rows
        matches = [row for row in choices if row["name"] == value]
        if len(matches) != 1:
            raise QueryUnavailable(f"馆方当前列表中找不到唯一的「{value}」")
        select_place(section, value)
        location[key] = value
        if child_key:
            choices = [row for row in data[child_key] if str(row["parentId"]) == str(matches[0]["id"])]
            section = sections.filter(has=page.get_by_text(label, exact=True))
    selector = page.get_by_text("确定选择", exact=True).filter(visible=True)
    if study_type:
        from tongji_cli.library.study import study_period
        return [study_period(page, selector, location, seat_type_label, period)]
    expected = load_seat_numbers(page, selector)
    return seat_list(page, location, day, time_slot, expected)


def load_choices(page, control):
    with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/reserve/index/quickSelect")) as result:
        control.click()
    if not result.value.ok:
        raise QueryUnavailable("馆方未能加载所选日期的预约目录")
    payload = result.value.json()
    data = payload.get("data") if isinstance(payload, dict) and payload.get("code", 0) == 0 else None
    if not isinstance(data, dict) or not all(isinstance(data.get(k), list) for k in ("premises", "storey", "area")):
        raise QueryUnavailable("馆方未返回完整的馆舍、楼层和区域目录")
    return data


def verify_counts(section, choices):
    entries = section.locator(".normalList > .item:visible")
    if not choices:
        expect(entries).to_have_count(0)
        return
    expected = [re.compile(rf"^\s*{re.escape(row['name'])}\s*空余[：:]\s*{row['free_num']}\s*总数[：:]\s*{row['total_num']}\s*$")
                for row in choices]
    expect(entries).to_have_text(expected, use_inner_text=True)


def select_place(section, value):
    choices = section.locator(".normalList > .item:visible")
    choice = choices.filter(has=section.page.get_by_text(value, exact=True))
    if choice.count() != 1:
        raise QueryUnavailable(f"馆方当前列表中找不到唯一的「{value}」")
    choice.click()
    expect(section.locator(".normalList > .active .text")).to_have_text(value)


def count_rows(page, section, key, location, day):
    entries = section.locator(".normalList > .item:visible")
    entries.first.locator(".info").wait_for()
    observed = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    items = []
    for text in entries.all_inner_texts():
        counts = re.fullmatch(r"\s*(.+?)\s+空余[：:]\s*(\d+)\s+总数[：:]\s*(\d+)\s*", text)
        if not counts or int(counts[2]) > int(counts[3]):
            raise QueryUnavailable("列表未显示完整的空余与总数")
        items.append({**location, key: counts[1], "available": int(counts[2]), "total": int(counts[3]),
                      "date": day, "observed_at": observed, "url": page.url.split("?")[0]})
    return items


def load_seat_numbers(page, control, path="/api/seat/seat"):
    with page.expect_response(lambda r: urlsplit(r.url).path.lower() == path) as response:
        control.click()
    if not response.value.ok:
        raise QueryUnavailable("馆方座位列表加载失败")
    data = response.value.json()
    if not isinstance(data, dict) or data.get("code") != 1 or not isinstance(data.get("data"), list):
        raise QueryUnavailable("馆方未返回可核实的座位列表")
    return sorted(str(row["name"]).strip() for row in data["data"] if row["status_name"] == "空闲")


def seat_list(page, location, day, time_slot, expected):
    panel = page.locator(".SeatSelect:visible")
    title = "-".join(location.values())
    expect(panel.locator(".seat-info .title")).to_have_text(title)
    selected = date.fromisoformat(day)
    displayed_day = re.compile(rf"^0?{selected.month}月0?{selected.day}日")
    expect(panel.locator(".reg-date.active")).to_have_text(displayed_day)
    if time_slot is not None:
        options = panel.locator(".reg-time:visible")
        pattern = slot_pattern(time_slot)
        panel.locator(".reg-time.active").wait_for()
        target = options.filter(has_text=pattern)
        if target.count() != 1:
            raise QueryUnavailable("馆方未列出唯一的指定时段")
        if not panel.locator(".reg-time.active").filter(has_text=pattern).count():
            expected = load_seat_numbers(page, target)
        expect(panel.locator(".reg-time.active")).to_have_text(pattern)
    labels = verified_seat_labels(page, panel, expected)
    observed = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    slot = panel.locator(".reg-time.active").inner_text().strip()
    return [{**location, "date": day, "time_slot": slot, "seat": label,
             "observed_at": observed, "url": page.url.split("?")[0]} for label in labels]


def verified_seat_labels(page, panel, expected):
    panel.get_by_text("列表模式", exact=True).click()
    grid = panel.locator(".grid-seat:visible")
    grid.wait_for()
    status = panel.locator(".seat-info .status")
    seats = grid.locator(":scope > .btn:visible")
    expect(status).to_have_text(re.compile(rf"^空余\s*{len(expected)}$"))
    deadline = monotonic() + 10
    while True:
        labels = [text.strip() for text in seats.all_inner_texts()]
        if sorted(labels) == expected:
            break
        if monotonic() >= deadline:
            raise QueryUnavailable("该时段的座位号与馆方刚返回的列表不符")
        page.wait_for_timeout(100)
    if any(not label for label in labels) or len(labels) != len(set(labels)):
        raise QueryUnavailable("座位号缺失或重复，请在馆方页面核对")
    return labels


def slot_pattern(slot):
    match = re.fullmatch(r"\s*(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})\s*", slot)
    if not match:
        raise QueryUnavailable("请按馆方时段输入起止时间，例如 08:00-22:00")
    return re.compile(rf"^\s*{match[1]}\s*-\s*{match[2]}\s*$")


def reserve_seat(page, args):
    seats = availability(page, args.date, args.branch, args.floor, args.area, args.time_slot)
    seat = next((item for item in seats if item["seat"] == args.seat), None)
    if seat is None:
        raise QueryUnavailable("指定座位号未出现在该时段的可选列表")
    panel = page.locator(".SeatSelect:visible")
    number = re.escape(args.seat)
    panel.locator(".grid-seat > .btn:visible").filter(has_text=re.compile(rf"^\s*{number}\s*$")).click()
    expect(panel.locator(".seat-selected")).to_have_text(re.compile(rf"^已选座位号[：:]\s*{number}$"))
    submit = panel.get_by_role("button", name=re.compile(r"立即预约$"))
    label = submit.inner_text().strip()
    ready = label == "立即预约" and submit.is_enabled()
    if args.preview:
        return [{**seat, "action": "preview", "booking_available": ready, "booking_button": label}]
    if not ready:
        raise QueryUnavailable(f"馆方暂未开放该座位的预约，按钮显示「{label}」")

    history = page.context.new_page()
    try:
        if seat_receipt(history, seat):
            raise QueryUnavailable("本人记录中已有相同地点、座位和时段的有效预约")
        expect(panel.locator(".seat-selected")).to_have_text(re.compile(rf"^已选座位号[：:]\s*{number}$"))
        expect(panel.locator(".reg-time.active")).to_have_text(slot_pattern(args.time_slot))
        try:
            panel.get_by_role("button", name="立即预约", exact=True).click()
            for attempt in range(3):
                if attempt:
                    history.wait_for_timeout(900)
                receipt = seat_receipt(history, seat)
                if receipt:
                    return [{**seat, "action": "reserved", "receipt": receipt}]
        except (Error, AssertionError, QueryUnavailable) as exc:
            raise QueryUnavailable("预约操作的结果尚未确认，请先查 library reservations 核对本人记录") from exc
        raise QueryUnavailable("本人记录中尚未查到匹配的新预约，请先查 library reservations 核对结果")
    finally:
        history.close()


def seat_receipt(page, seat):
    page.goto(SEATS, wait_until="domcontentloaded")
    records = reservation_history(page, "seat", 10)
    place = "-".join(seat[key] for key in ("branch", "floor", "area"))
    location = re.compile(rf"^{re.escape(place)}[：:]\s*{re.escape(seat['seat'])}$")
    for row in records:
        if row["status"] not in {"已预约", "预约成功", "待签到", "已签到", "使用中", "进行中"}:
            continue
        timing = re.fullmatch(r"(\d{2}-\d{2})\s+(.+)", row["time"])
        if (location.fullmatch(row["location"]) and timing and timing[1] == seat["date"][5:]
                and slot_pattern(seat["time_slot"]).fullmatch(timing[2])):
            return row
    return None
