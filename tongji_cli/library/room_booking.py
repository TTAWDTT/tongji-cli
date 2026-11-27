import re
import sys
from datetime import date
from urllib.parse import urlsplit

from playwright.sync_api import Error, expect

from tongji_cli.library.rooms import room_directory
from tongji_cli.library.services import SEATS
from tongji_cli.library.space import reservation_history, select_place
from tongji_cli.common import QueryUnavailable


def room_booking(page, args, handoff=None):
    matches = [r for r in room_directory(page, args) if str(r["room_id"]) == args.room_id]
    if len(matches) != 1:
        raise QueryUnavailable("所选日期的目录中没有唯一匹配的空间编号，请用 library rooms list 核对")
    room = matches[0]
    panel, calendar = open_room(page, room)
    rows = [day_schedule(room, day) for day in calendar["list"]
            if args.date is None or day["date"] == args.date.isoformat()]
    if args.date and len(rows) != 1:
        raise QueryUnavailable("该日期的房间时段尚未公布，请用 rooms slots 不带 --date 查看已公布日期")
    if args.action == "slots":
        return rows
    result = prepare_room_form(page, panel, rows[0], args)
    if args.preview:
        return [dict(result, action="preview")]
    return [finish_booking(page, result, handoff)]


def open_room(page, room):
    sections = page.locator(".section:visible")
    for label, key in (("馆舍", "branch"), ("楼层", "floor")):
        section = sections.filter(has=page.get_by_text(label, exact=True))
        select_place(section, room[key])
    areas = sections.filter(has=page.get_by_text("区域", exact=True))
    areas.get_by_text(room["room_name"], exact=True).click()
    expect(areas.locator(".item.active .text")).to_have_text(room["room_name"])
    with page.expect_response(lambda r: urlsplit(r.url).path.lower() == "/api/seminar/v1seminar") as response:
        page.get_by_role("button", name="立即预约", exact=True).click()
    reply = response.value
    if not reply.ok or str(reply.request.post_data_json.get("room")) != str(room["room_id"]):
        raise QueryUnavailable("馆方时段响应与所选房间编号不符")
    payload = reply.json()
    calendar = payload.get("data") if isinstance(payload, dict) and payload.get("code") == 1 else None
    if not isinstance(calendar, dict) or not isinstance(calendar.get("date"), list) or not isinstance(calendar.get("list"), list):
        raise QueryUnavailable("馆方未返回该房间的时段表")
    if calendar["date"] != [day["date"] for day in calendar["list"]]:
        raise QueryUnavailable("馆方列出的日期与时段明细不符")
    panel = page.locator(".content:visible").filter(has=page.locator(".calendarHead")).last
    expect(panel.locator(".room-active")).to_have_text(room["room_name"])
    return panel, calendar


def hm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def day_schedule(room, day):
    info = day["info"]
    if not isinstance(info, dict) or not isinstance(info.get("list"), list):
        raise QueryUnavailable("馆方未列出当日占用明细")
    start, end = int(info["startTime"]), int(info["endTime"])
    if not 0 <= start <= end <= 1440:
        raise QueryUnavailable("馆方返回的开放时间无效")
    busy = []
    for item in info["list"]:
        left, right = int(item["beginNum"]), int(item["endNum"])
        if right <= left:
            raise QueryUnavailable("馆方返回的占用起止时间无效")
        left, right = max(start, left), min(end, right)
        if left < right:
            busy.append((left, right))
    occupied = []
    free = []
    cursor = start
    for left, right in sorted(busy):
        if cursor < left:
            free.append((cursor, left))
        occupied.append(f"{hm(left)}-{hm(right)}")
        cursor = max(cursor, right)
    if cursor < end:
        free.append((cursor, end))
    minimum = int(info["minTime"])
    candidates = [f"{hm(left)}-{hm(right)}" for left, right in free if right - left >= minimum]
    return {**room, "date": day["date"], "open_hours": f"{hm(start)}-{hm(end)}",
            "occupied": occupied, "unoccupied": [f"{hm(left)}-{hm(right)}" for left, right in free],
            "candidate_windows": candidates, "min_minutes": minimum,
            "max_minutes": int(info["maxTime"]), "min_people": int(info["minPerson"]), "max_people": int(info["maxPerson"])}


def prepare_room_form(page, panel, day, args):
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)\s*-\s*([01]\d|2[0-3]|24):([0-5]\d)", args.time_slot.strip())
    if not match:
        raise QueryUnavailable("请输入 HH:MM-HH:MM 格式的房间时段")
    h1, m1, h2, m2 = map(int, match.groups())
    start, end = h1 * 60 + m1, h2 * 60 + m2
    if not start < end <= 1440:
        raise QueryUnavailable("房间预约的结束时间必须晚于开始时间且不超过当天")
    if not day["min_minutes"] <= end - start <= day["max_minutes"]:
        raise QueryUnavailable(f"该房间预约时长须在 {day['min_minutes']} 至 {day['max_minutes']} 分钟之间")
    if not any(left <= hm(start) and hm(end) <= right for left, right in (span.split("-") for span in day["unoccupied"])):
        raise QueryUnavailable("该房间的所选时间超出开放范围或已有占用")
    day_label = date.fromisoformat(day["date"]).strftime("%m月%d日")
    panel.locator(".reg-date").get_by_text(day_label, exact=True).click()
    heading = panel.locator(".calendarHead")
    expect(heading).to_contain_text(day["date"])
    sliders = panel.get_by_role("slider")
    first, last = sliders.nth(0), sliders.nth(1)
    track = panel.locator(".v-slider-track")
    track.scroll_into_view_if_needed()
    rail = track.bounding_box()
    low, high = int(first.get_attribute("aria-valuemin")), int(last.get_attribute("aria-valuemax"))
    for attempt in range(2):
        handles = [(first, start), (last, end)]
        if start >= int(last.get_attribute("aria-valuenow")):
            handles.reverse()
        for control, target in handles:
            if int(control.get_attribute("aria-valuenow")) != target:
                position_slider(page, control, target, rail, low, high)
                # 馆方在松手后校正另一端。下一次拖动要从校正后的手柄位置开始。
                page.wait_for_timeout(250)
        if all(int(control.get_attribute("aria-valuenow")) == target for control, target in handles):
            break
    else:
        raise QueryUnavailable("馆方时间选择器未能选中该时刻，请核对房间可选时间")
    time_slot = f"{hm(start)}-{hm(end)}"
    expect(heading).to_contain_text(f"[{hm(start)}]")
    expect(heading).to_contain_text(f"[{hm(end)}]")
    with page.expect_response(lambda r: urlsplit(r.url).path.lower() == "/api/seminar/seminar") as check:
        page.get_by_role("button", name="确定选择", exact=True).click()
    response = check.value
    confirmation = response.json() if response.ok else None
    if not isinstance(confirmation, dict) or confirmation.get("code") != 1 or not isinstance(confirmation.get("data"), dict):
        raise QueryUnavailable("馆方未能核实该时段的申请条件")
    form = page.locator(".upload:visible")
    fields = form.locator(".view1_item")
    expect(fields.filter(has=page.get_by_text("预约时间", exact=True))).to_contain_text(day["date"] + " " + time_slot)
    expect(fields.filter(has=page.get_by_text("预约房间", exact=True)).locator(":scope > :last-child")).to_have_text(day["room_name"])
    form.get_by_role("button", name="立即预约", exact=True).wait_for()
    return {**day, "time_slot": time_slot, "form_fields": form.locator(".titles:visible, label:visible").all_inner_texts(),
            **fill_application(form, args.topic, args.purpose)}


def fill_application(form, topic, purpose):
    subject = form.locator(".v-select:visible").filter(has_text="申请主题")
    options = []
    if subject.is_visible():
        subject.locator(".v-field").click()
        menu = form.page.locator('[role="listbox"]:visible')
        menu.wait_for()
        items = menu.locator(".v-list-item-title:visible")
        items.first.wait_for()
        options = items.all_inner_texts()
        if topic is None:
            form.page.keyboard.press("Escape")
        elif topic in options:
            menu.get_by_text(topic, exact=True).click()
            expect(subject.locator(".v-select__selection-text")).to_have_text(topic)
    if topic is not None and topic not in options:
        raise QueryUnavailable("馆方未列出指定的申请主题。可选主题：" + "、".join(options))
    if purpose is not None:
        notes = form.locator(".view3 textarea:visible")
        if not notes.is_visible():
            raise QueryUnavailable("馆方申请表未显示申请内容输入框")
        notes.fill(purpose)
        expect(notes).to_have_value(purpose)
    return {"topic_options": options, "topic": topic, "purpose_filled": purpose is not None}


def position_slider(page, control, target, rail, low, high):
    box = control.bounding_box()
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + box["width"] / 2, y)
    page.mouse.down()
    try:
        x = rail["x"] + (target - low) / (high - low) * rail["width"]
        page.mouse.move(x, y, steps=6)
    finally:
        page.mouse.up()


def finish_booking(page, result, handoff):
    history = page.context.new_page()
    try:
        previous = room_records(history, None)
        previous_ids = {record["receipt_id"] for record in previous}
        if any(matches_application(record, result) for record in previous):
            raise QueryUnavailable("本人已有相同房间和时段的办理记录")
        page.bring_to_front()
        if handoff:
            handoff(result)
        else:
            print(f"请在馆方窗口核对「{result['branch']} {result['room_name']}」"
                  f" {result['date']} {result['time_slot']}，填写申请并提交后，回到终端按回车。",
                  file=sys.stderr, flush=True)
            try:
                input()
            except EOFError:
                raise QueryUnavailable("请通过 library reservations --kind room 核对办理记录") from None
        try:
            for attempt in range(3):
                if attempt:
                    history.wait_for_timeout(900)
                matches = [record for record in room_records(history, 10)
                           if record["receipt_id"] not in previous_ids and matches_application(record, result)]
                if len(matches) == 1:
                    return dict(result, action="applied", receipt=matches[0])
        except (Error, QueryUnavailable) as exc:
            raise QueryUnavailable("提交结果待核实，请先查 library reservations --kind room") from exc
        raise QueryUnavailable("本人记录中尚未核实这项新申请，请先查 library reservations --kind room")
    finally:
        history.close()


def lookup_room_receipts(page, args):
    if args.receipt_id is None:
        if args.limit < 1:
            raise QueryUnavailable("预约记录条数必须大于零")
        return room_records(page, args.limit)
    records = room_records(page, None)
    for record in records:
        if record["receipt_id"] == args.receipt_id:
            return [record]
    raise QueryUnavailable("在本人空间预约记录中没有找到该编号")


def room_records(page, limit):
    page.goto(SEATS, wait_until="domcontentloaded")
    responses = []

    def capture(response):
        if urlsplit(response.url).path.lower() == "/api/member/seminar":
            responses.append(response)

    page.on("response", capture)
    try:
        cards = reservation_history(page, "room", limit)
    finally:
        page.remove_listener("response", capture)
    pages = {}
    for response in responses:
        payload = response.json() if response.ok else None
        data = payload.get("data") if isinstance(payload, dict) and payload.get("code") == 1 else None
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise QueryUnavailable("馆方未返回可核对的空间预约记录")
        pages[int(data["current_page"])] = data
    if 1 not in pages:
        raise QueryUnavailable("未能核对馆方空间预约记录首页")
    total = int(pages[1]["total"])
    expected = total if limit is None else min(total, limit)
    rows = [row for n in sorted(pages) for row in pages[n]["data"]][:limit]
    if len(rows) != expected or len(cards) != expected:
        raise QueryUnavailable("馆方记录总数、明细与页面显示不符")
    for card, row in zip(cards, rows):
        stamp = f"{row['day']} {row['start']}-{row['end']}"
        if (card["location"], card["time"], card["status"]) != (row["nameMerge"], stamp, row["statusname"]):
            raise QueryUnavailable("预约卡片的地点、时间或状态与馆方明细不符")
        if row.get("id") in (None, ""):
            raise QueryUnavailable("馆方记录缺少预约编号")
        card.update(receipt_id=str(row["id"]), title=row.get("title"), created_at=row.get("createTime"))
    if len({card["receipt_id"] for card in cards}) != len(cards):
        raise QueryUnavailable("预约记录中出现重复的预约编号")
    return cards


def matches_application(row, desired):
    location = "-".join(desired[k] for k in ("branch", "floor", "room_name"))
    if row["location"] != location or row["status"] not in {"已预约", "预约成功", "待签到", "已签到", "待审核", "审核中", "待审批", "等待管理员审核", "使用中"}:
        return False
    match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})(?::00)?\s*-\s*(\d{2}:\d{2})(?::00)?", row["time"])
    return bool(match and match[1] == desired["date"] and f"{match[2]}-{match[3]}" == desired["time_slot"])
