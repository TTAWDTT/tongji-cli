import re
from datetime import date

from playwright.sync_api import sync_playwright

from tongji_cli.common import QueryUnavailable


SOURCES = {
    "sports": "https://sports.tongji.edu.cn/info/1049/3133.htm",
    "clinic": "https://shtjh.tongji.edu.cn/info/1021/4165.htm",
    "card": "https://nic.tongji.edu.cn/info/1026/1408.htm",
}


def configure(commands):
    sports = commands.add_parser("sports").add_subparsers(dest="operation", required=True)
    hours = sports.add_parser("hours", help="体育部公布的 2026-2027 第一学期场馆开放方案")
    hours.add_argument("--campus", default="", help="校区名称")
    hours.add_argument("--venue", default="", help="场馆名称关键词")
    venues = sports.add_parser("venues", help="体育场馆预约平台当前列出的场馆")
    venues.add_argument("--campus", default="", help="校区名称关键词")
    venues.add_argument("--venue", default="", help="场馆名称关键词")
    sports.add_parser("orders", help="查询本人体育场馆订单及状态")
    slots = sports.add_parser("slots", help="在预约平台查询指定日期和场馆的场地时段")
    reserve = sports.add_parser("reserve", help="选中一个场次并在校方页面确认下单")
    for command in (slots, reserve):
        command.add_argument("--venue", required=True, help="sports venues 列出的完整场馆名称")
        command.add_argument("--sport", help="场馆内的运动项目名")
        command.add_argument("--date", required=True, type=date.fromisoformat, metavar="YYYY-MM-DD")
    reserve.add_argument("--field", required=True, help="sports slots 列出的完整场地名")
    reserve.add_argument("--time", required=True, dest="time_slot", metavar="HH:MM-HH:MM")
    reserve.add_argument("--preview", action="store_true", help="只核对场次与合计金额")
    for key, help_text in [("clinic", "校医院门诊就医指南"), ("card", "信息办校园一卡通使用指南")]:
        operations = commands.add_parser(key).add_subparsers(dest="operation", required=True)
        operations.add_parser("guide", help=help_text)
        if key == "clinic":
            hours = operations.add_parser("hours", help="按门诊部或医院和科室查询校医院公布的门诊安排")
            hours.add_argument("--facility", choices=["同济大学门诊部", "同济大学医院"])
            hours.add_argument("--department", default="", help="科室名称关键词")
        if key == "card":
            operations.add_parser("balance", help="在本人一卡通个人中心查询账户余额")
            history = operations.add_parser("transactions", help="按日期查询本人一卡通流水，自动翻页")
            history.add_argument("--from", dest="start_date", type=date.fromisoformat, metavar="YYYY-MM-DD",
                                 help="含起始日，默认截止日前 6 天")
            history.add_argument("--to", dest="end_date", type=date.fromisoformat, metavar="YYYY-MM-DD",
                                 help="含截止日，默认上海日期今天")


def read(args):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page()
        try:
            if args.command == "sports" and args.operation == "venues":
                from tongji_cli.campus.stadium import venues
                return venues(page, args.campus, args.venue)
            source = SOURCES[args.command]
            response = page.goto(source, wait_until="domcontentloaded", timeout=25000)
            if not response or not response.ok:
                raise QueryUnavailable("校方暂未返回该指南")
            body = page.locator(".v_news_content")
            body.wait_for(timeout=12000)
            title = page.title().split("-同济大学")[0]
            if args.command == "sports":
                rows = body.locator("table tr").evaluate_all("""rs=>rs.map(r=>Array.from(r.cells,
                    c=>c.innerText.trim().replace(/\\s+/g,' ')).filter(Boolean))""")
                return sports_hours(rows, title, source, args.campus, args.venue)
            if args.command == "clinic" and args.operation == "hours":
                return clinic_hours(body.inner_text(), args.facility, args.department, source)
            content = body.inner_text().strip()
            if not content:
                raise QueryUnavailable("校方页面未显示指南正文")
            return [{"title": title, "body": content, "url": source}]
        finally:
            browser.close()


def sports_hours(rows, title, source, campus, venue):
    items = []
    group = nature = None
    for cells in rows:
        if len(cells) == 1 and re.match(r"^[一二三四五六七八九十]+、.*校区", cells[0]):
            group = cells[0].split("、", 1)[1]
            nature = None
        elif cells and cells[0].isdigit():
            if len(cells) == 4:
                nature = cells[2]
            if not group or not nature or len(cells) not in (3, 4):
                raise QueryUnavailable("体育部开放时间表格式待核实")
            items.append({"campus": group, "title": cells[1], "type": nature, "hours": cells[-1],
                          "source": title, "url": source})
    if not items:
        raise QueryUnavailable("体育部页面未列出可识别的场馆时段")
    return [row for row in items if campus in row["campus"] and venue in row["title"]]


def card_balance(page):
    page.get_by_role("link", name="个人中心", exact=True).click()
    frame = page.frame_locator('iframe[name="comepage"]')
    field = frame.get_by_text(re.compile(r"账户余额[：:]\s*-?\d+(?:\.\d+)?"))
    value = field.inner_text(timeout=20000)
    amount = re.search(r"-?\d+(?:\.\d+)?", value).group()
    return [{"balance": amount, "currency": "CNY", "source": "一卡通个人中心", "url": "https://yikatong.tongji.edu.cn/"}]

def clinic_hours(text, facility, department, source):
    records = []
    current = None
    for line in (s.strip() for s in text.splitlines()):
        header = re.fullmatch(r"(同济大学门诊部|同济大学医院)（(.+)）", line)
        if header:
            current = {"facility": header[1], "audience": header[2], "schedule": [], "url": source}
            records.append(current)
            continue
        if current is None:
            continue
        label, _, value = line.partition("：")
        if label.startswith("周") and label.endswith("开设"):
            current["schedule"].append({"department": value, "hours": label[:-2]})
        elif label == "普通门诊时间" and value:
            current["hours"] = value
        elif value.startswith("周") and re.fullmatch(r"[\u4e00-\u9fff]+科", label):
            current["schedule"].append({"department": label, "hours": value})
        elif line == "内科24小时值班":
            current["schedule"].append({"department": "内科值班", "hours": "24小时"})
        elif line.startswith("注：") and "开诊安排" in line:
            current["notes"] = value
    if len(records) != 2 or any(not r["schedule"] or not r.get("hours") for r in records):
        raise QueryUnavailable("校医院指南的门诊安排未能核实")
    for record in records:
        record["schedule"] = [row for row in record["schedule"] if department in row["department"]]
    return [r for r in records if (not facility or r["facility"] == facility) and r["schedule"]]
