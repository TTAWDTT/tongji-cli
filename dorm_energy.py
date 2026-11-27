import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urljoin

from playwright.sync_api import expect, sync_playwright

import school_calendar
from queries import QueryUnavailable, SHANGHAI


GUIDE = "https://hqc.tongji.edu.cn/29/83/c30795a338307/page.htm"
SERVICES = "https://hqc.tongji.edu.cn/30784/list.htm"
ELECTRICITY = "/v1/rt/nyzx/electricity/user"


@dataclass(frozen=True)
class Meter:
    label: str
    unit: str
    key: str
    price_key: str


POWER = Meter("电", "度", "electricity", "unit_price_yuan_per_kwh")
WATER = Meter("水", "吨", "water", "unit_price_yuan_per_tonne")


def configure(commands):
    dorm = commands.add_parser("dorm", help="宿舍用水用电查询").add_subparsers(dest="operation", required=True)
    dorm.add_parser("guide", help="后勤处用电指南及校内水电查询入口")
    locations = dorm.add_parser("locations", help="查校方水电页面的校区、楼栋和楼层选项")
    locations.add_argument("--campus", help="完整校区或计量系统名称")
    locations.add_argument("--building", help="该校区下的完整楼栋名称")
    balance = dorm.add_parser("electricity", help="查询本人宿舍剩余电量")
    usage = dorm.add_parser("usage", help="查询本人宿舍逐日用电量")
    water = dorm.add_parser("water", help="查询本人宿舍水表余量（吨）")
    water_usage = dorm.add_parser("water-usage", help="查询本人宿舍逐日用水量")
    for command in (balance, usage, water, water_usage):
        command.add_argument("--meter", required=command in (water, water_usage), nargs=4,
                             metavar=("校区", "楼栋", "楼层", "房号"),
                             help="在后勤处校内网页查询本人水表或电表，可用 dorm locations 查看目录")
    for command in (usage, water_usage):
        command.add_argument("--from", dest="start_date", type=date.fromisoformat, metavar="YYYY-MM-DD")
        command.add_argument("--to", dest="end_date", type=date.fromisoformat, metavar="YYYY-MM-DD")


def energy(args, today):
    if args.operation == "guide":
        return energy_guide()
    params = {}
    path = ELECTRICITY
    if args.operation in ("usage", "water-usage"):
        end = args.end_date or today
        start = args.start_date or end - timedelta(days=6)
        if start > end:
            raise QueryUnavailable("起始日期不能晚于截止日期")
        params = {"startDate": start.isoformat(), "endDate": end.isoformat()}
        path += "/record"
    meter = getattr(args, "meter", None)
    if args.operation == "locations" or meter:
        if args.operation == "locations" and args.building and not args.campus:
            raise QueryUnavailable("选择楼栋时也请用 --campus 指定校区")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                if meter:
                    kind = WATER if args.operation in ("water", "water-usage") else POWER
                    return meter_report(page, *meter, params, kind)
                return meter_locations(page, args.campus, args.building)
            finally:
                browser.close()
    token = os.environ.get("TONGJI_USER_TOKEN")
    if not token:
        raise QueryUnavailable("宿舍用电接口需要本人的开放平台授权码模式令牌（TONGJI_USER_TOKEN）。"
                               "校内可用 --meter 校区 楼栋 楼层 房号 查询，或用 dorm guide 查看入口。")
    data = school_calendar.open_data(path, params, token=token)
    room = data.get("roomInfoToElectricity") if isinstance(data, dict) else None
    if not isinstance(room, dict) or not room.get("accomRoomNo"):
        raise QueryUnavailable("能源中心未返回可核对的宿舍房间，请在后勤处水电查询中核对")
    result = {"campus": room.get("accomRegionName"), "dorm_building": room.get("accomBuildingName"),
              "dorm_room": room["accomRoomNo"], "source": school_calendar.API + path}
    if args.operation == "electricity":
        info = data.get("elecInfo")
        if not isinstance(info, dict) or info.get("remaining") in (None, ""):
            raise QueryUnavailable("能源中心未返回可核对的剩余电量")
        return [dict(result, remaining_electricity=info["remaining"], purchased_electricity=info.get("all"),
                     used_electricity=info.get("used"))]
    rows = data["elecUsedRecord"]["elecUsedRecord"]
    if not isinstance(rows, list):
        raise QueryUnavailable("能源中心未返回逐日用电列表")
    readings = []
    for row in rows:
        raw = row["rdate"]
        timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        day = timestamp.astimezone(SHANGHAI).date() if timestamp.tzinfo else timestamp.date()
        if start <= day <= end:
            readings.append({"date": day.isoformat(), "recorded_at": raw, "used_electricity": row["used"]})
    return [dict(result, **params, readings=sorted(readings, key=lambda r: r["date"]))]


def energy_guide():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        try:
            page = browser.new_page()
            response = page.goto(GUIDE, wait_until="domcontentloaded")
            if not response or not response.ok:
                raise QueryUnavailable("后勤处用电指南暂不可用")
            article = page.locator(".wp_articlecontent")
            text = article.inner_text(timeout=10000).strip()
            if not text:
                raise QueryUnavailable("后勤处未返回指南正文")
            images = article.locator("img[src]").evaluate_all("images => images.map(i => i.src)")
            entry = energy_entry(page)
            return [{"title": "如何购电、查询水电余额？", "body": text, "images": images, "url": GUIDE,
                     "campus_query": entry}]
        finally:
            browser.close()


def energy_entry(page):
    directory = page.goto(SERVICES, wait_until="domcontentloaded")
    entry = page.get_by_role("link", name="水电查询", exact=True)
    if not directory or not directory.ok or entry.count() != 1:
        raise QueryUnavailable("后勤处服务中心未列出唯一的水电查询入口")
    return urljoin(page.url, entry.get_attribute("href"))


def open_meter_directory(page):
    entry = energy_entry(page)
    response = page.goto(entry, wait_until="domcontentloaded")
    if not response or not response.ok:
        raise QueryUnavailable("后勤处的校内水电查询页面不可用")
    return entry


DIRECTORY_FIELDS = (
    ("#drlouming", "校区", "campus"),
    ("#drceng", "楼栋", "dorm_building"),
    ("#dr_ceng", "楼层", "floor"),
)


def directory_options(page, selector, caption):
    options = page.locator(selector).locator("option").all_text_contents()
    if not options or options[0].strip() != caption:
        raise QueryUnavailable(f"水电查询页面未返回可核对的{caption}列表")
    return [v.strip() for v in options[1:]]


def select_location(page, selector, caption, choice):
    if choice not in directory_options(page, selector, caption):
        raise QueryUnavailable(f"水电查询目录未列出这个{caption}，请核对完整名称")
    field = page.locator(selector)
    with page.expect_navigation(wait_until="domcontentloaded") as posted:
        field.select_option(label=choice)
    response = posted.value
    if not response or not response.ok or response.request.method != "POST":
        raise QueryUnavailable(f"水电查询未能加载所选{caption}")
    expect(field.locator("option:checked")).to_have_text(choice)


def meter_locations(page, campus, building):
    entry = open_meter_directory(page)
    selected = {}
    for (selector, caption, key), choice in zip(DIRECTORY_FIELDS, (campus, building, None)):
        if choice is None:
            return [{**selected, key: name, "url": entry} for name in directory_options(page, selector, caption)]
        select_location(page, selector, caption, choice)
        selected[key] = choice


def meter_report(page, campus, building, floor, room, dates, kind=POWER):
    entry = open_meter_directory(page)
    for (selector, caption, _), choice in zip(DIRECTORY_FIELDS, (campus, building, floor)):
        select_location(page, selector, caption, choice)
    field = page.locator("#drfangjian")
    options = field.locator("option").all_text_contents()[1:]
    matches = [name for name in options if name in (room, building + room)]
    if len(matches) != 1:
        raise QueryUnavailable("所选楼层没有唯一匹配的房号，请核对房间名称")
    label = matches[0]
    if "PostBack" in (field.get_attribute("onchange") or ""):
        with page.expect_navigation(wait_until="domcontentloaded"):
            field.select_option(label=label)
    else:
        field.select_option(label=label)
    expect(field.locator("option:checked")).to_have_text(label)
    page.get_by_label("用" + kind.label, exact=True).check()
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.locator('input[type=image][src*="btn_log"]').click()
    remaining = meter_balance(page, label, kind)
    result = {"campus": campus, "dorm_building": building, "floor": floor, "dorm_room": label,
              "source": entry, kind.key + "_unit": kind.unit, "observed_at": datetime.now(SHANGHAI).isoformat(timespec="seconds")}
    if dates:
        return [dict(result, **dates, readings=meter_history(page, label, dates, kind))]
    return [{**result, "remaining_" + kind.key: remaining}]


def meter_balance(page, label, kind=POWER):
    heading = page.locator(".crumb h6")
    text = heading.inner_text().strip() if heading.count() == 1 else ""
    match = re.fullmatch(re.escape(label) + kind.label + r"表剩余电量[：:]\s*(-?\d+(?:\.\d+)?)\s*" + kind.unit, text)
    if not match:
        raise QueryUnavailable(f"用{kind.label}记录页未返回所选{kind.label}表的余量")
    return match[1]


def meter_history(page, label, dates, kind=POWER):
    page.locator("#txtstart").fill(dates["startDate"])
    page.locator("#txtend").fill(dates["endDate"])
    with page.expect_navigation(wait_until="domcontentloaded"):
        page.locator("#btnser").click()
    readings = []
    number = 1
    while True:
        meter_balance(page, label, kind)
        if (page.locator("#txtstart").input_value(), page.locator("#txtend").input_value()) != (
                dates["startDate"], dates["endDate"]):
            raise QueryUnavailable(f"用{kind.label}记录页的日期与查询不符")
        table = page.locator("table.dataTable tr")
        cells = table.evaluate_all("rows => rows.map(r => Array.from(r.cells, c => c.innerText.trim()))")
        if not cells or cells[0] != ["日期", kind.label + "表名称", f"用量({kind.unit})", f"单价(元/{kind.unit})"]:
            raise QueryUnavailable(f"用{kind.label}明细表头与校方格式不符")
        for row in cells[1:]:
            if len(row) != 4 or row[1] != label + kind.label + "表" or not dates["startDate"] <= row[0] <= dates["endDate"]:
                raise QueryUnavailable(f"用{kind.label}明细与所选{kind.label}表或日期不符")
            readings.append({"date": row[0], "used_" + kind.key: row[2], kind.price_key: row[3]})
        pager = page.locator(".pageer")
        position = re.search(r"第\s*(\d+)\s*页\s*/\s*共\s*(\d+)\s*页", pager.inner_text())
        if not position or int(position[1]) != number:
            raise QueryUnavailable(f"无法核对用{kind.label}明细页码")
        if number >= int(position[2]):
            break
        with page.expect_navigation(wait_until="domcontentloaded"):
            pager.get_by_text("下一页", exact=True).click()
        number += 1
    return sorted(readings, key=lambda r: r["date"])
