import re
import sys
from datetime import date, datetime
from urllib.parse import urlsplit

from playwright.sync_api import Error, expect

from library_services import SEATS
from library_space import availability, load_seat_numbers, reservation_history, verified_seat_labels
from queries import QueryUnavailable, SHANGHAI


STUDY_SEATS = "/api/study/studyareadetail"


def study_period(page, open_area, location, label, period):
    with page.expect_response(lambda r: urlsplit(r.url).path.lower() == "/api/study/studyopentimecheck") as check:
        seats = load_seat_numbers(page, open_area, STUDY_SEATS)
    response = check.value
    if not response.ok:
        raise QueryUnavailable("馆方未能加载研修预约周期")
    data = response.json()
    if not isinstance(data, dict) or data.get("code") != 1 or not isinstance(data.get("data"), list):
        raise QueryUnavailable("馆方未返回预约周期")
    periods = [{"start_date": date.fromisoformat(p["startDay"]).isoformat(),
                "end_date": date.fromisoformat(p["endDay"]).isoformat()} for p in data["data"]]
    index = 0 if period == "current" else 1
    if index >= len(periods):
        raise QueryUnavailable("馆方尚未列出所选预约周期")
    panel = page.locator(".SeatSelect:visible")
    expect(panel.locator(".seat-info .title")).to_have_text("-".join(location.values()))
    tabs = panel.locator(".reg-date:visible")
    labels = [f"{p['start_date'][5:7]}月{p['start_date'][8:]}日 - {p['end_date'][5:7]}月{p['end_date'][8:]}日" for p in periods]
    expect(tabs).to_have_text(labels)
    if panel.locator(".reg-date.active").inner_text().strip() != labels[index]:
        seats = load_seat_numbers(page, tabs.nth(index), STUDY_SEATS)
    expect(panel.locator(".reg-date.active")).to_have_text(labels[index])
    which = "本期" if period == "current" else "下期"
    permissions = panel.locator(".permissions:visible")
    rule = re.compile(rf"{which}预约权限[：:]\s*(未获得|已获得)")
    expect(permissions).to_contain_text(rule)
    permission_text = rule.search(permissions.inner_text())[1]
    numbers = verified_seat_labels(page, panel, seats)
    return {**location, "seat_type": label, **periods[index], "periods": periods, "permission": permission_text,
            "available": len(numbers), "seat_numbers": numbers,
            "observed_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"), "url": SEATS}


def reserve_study(page, args, handoff=None):
    row, = availability(page, branch=args.branch, floor=args.floor, area=args.area,
                        study_type=args.study_type, period=args.period)
    if args.seat not in row.pop("seat_numbers"):
        raise QueryUnavailable("该期空闲列表中没有指定的座位号")
    panel = page.locator(".SeatSelect:visible")
    panel.locator(".grid-seat > .btn:visible").filter(has_text=re.compile(rf"^\s*{re.escape(args.seat)}\s*$")).click()
    expect(panel.locator(".seat-selected")).to_have_text(re.compile(rf"^已选座位号[：:]\s*{re.escape(args.seat)}$"))
    button = panel.locator("button.confirm:visible")
    text = " ".join(button.inner_text().split())
    ready = row["permission"] == "已获得" and text == "立即预约" and button.is_enabled()
    result = {**row, "seat": args.seat, "booking_available": ready, "booking_button": text}
    if args.preview:
        return [dict(result, action="preview")]
    if not ready:
        raise QueryUnavailable(f"馆方当前无法办理：预约权限「{row['permission']}」，按钮显示「{text}」")
    records = page.context.new_page()
    try:
        if matching_record(records, result):
            raise QueryUnavailable("本人已有这项有效预约")
        page.bring_to_front()
        (handoff or finish_on_site)(result)
        try:
            for attempt in range(3):
                if attempt:
                    records.wait_for_timeout(900)
                receipt = matching_record(records, result)
                if receipt:
                    return [dict(result, action="reserved", receipt=receipt)]
        except (Error, QueryUnavailable) as error:
            raise QueryUnavailable("请用 library reservations --kind research 核对办理后的记录") from error
        raise QueryUnavailable("未核实该座号和完整周期的新记录，请查 library reservations --kind research")
    finally:
        records.close()


def finish_on_site(row):
    print(f"{row['seat_type']}，{row['branch']}{row['floor']}{row['area']}，{row['seat']} 号，"
          f"{row['start_date']} 至 {row['end_date']}。请在馆方窗口完成办理，再回终端按回车核对记录。",
          file=sys.stderr, flush=True)
    try:
        input()
    except EOFError:
        raise QueryUnavailable("请在交互终端运行，或加 --preview 查看座位") from None


def matching_record(page, seat):
    page.goto(SEATS, wait_until="domcontentloaded")
    place = "-".join(seat[key] for key in ("branch", "floor", "area"))
    expected = re.compile(rf"^{re.escape(place)}[：:]\s*{re.escape(seat['seat'])}$")
    period = [seat["start_date"], seat["end_date"]]
    for row in reservation_history(page, "research", 10):
        if expected.fullmatch(row["location"]) and row["status"] in {"待签到", "已预约", "预约成功", "已签到", "使用中", "进行中"}:
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", row["time"])
            if dates == period:
                return row
    return None
