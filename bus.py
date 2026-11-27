import argparse
import hashlib
import re
from datetime import date, datetime, time, timedelta
from html import unescape
from urllib.parse import urljoin
from urllib.request import urlopen

from queries import QueryUnavailable, SHANGHAI
from school_calendar import open_data

BASE = "https://jiading.tongji.edu.cn"
INDEX = BASE + "/rctz/list.htm"
SERVICES = BASE + "/5916/list.htm"
CALENDAR_PATH = "/v1/rt/onetongji/calendar"
# The student timetable is a poster, signed May 2026. Only use this transcription
# while the student-services listing still points to the verified poster.
POSTER_SHA = "006c28d5c0e931340669e43af6cd5d62e9087e3afafd768e71dce5935dd46ce5"
REGULAR = {
    "平日": {"嘉定": ["06:30", "12:15", "16:30"], "四平": ["08:45", "14:00", "20:30"]},
    "周六": {"嘉定": ["06:30", "12:15"], "四平": ["11:00", "15:30", "17:30"]},
    "周日": {"嘉定": ["06:30", "12:15"], "四平": ["11:00", "17:30"]},
}
STOPS = {"嘉定": "广楼南侧", "四平": "四平校区西南门停车场"}
SHUTTLE_STOPS = {"嘉定": "嘉三路近七号楼入口处", "上海汽车城": "曹安公路安谐路822路公交站点（靠地铁站一侧）"}
DZ1_STOPS = {"嘉定": SHUTTLE_STOPS["嘉定"], "封浜": "封浜公交站（位于出轨交14号线封浜站5号口后的翔封路对面）"}
DZ1_TIMES = [
    ("06:50", "07:25"), ("08:10", "08:45"), ("09:50", "10:25"),
    ("16:10", "16:45"), ("17:35", "18:10"), ("19:10", "19:45"),
]
SHUTTLE_TIMES = [
    ("06:25", "06:40"), ("06:40", "06:55"), ("06:55", "07:10"), ("07:10", "07:25"),
    ("07:30", "07:45"), ("07:50", "08:05"), ("08:20", "08:35"), ("08:55", "09:10"),
    ("09:30", "09:45"), ("10:10", "10:25"), ("10:45", "11:00"), ("11:45", "12:00"),
    ("12:20", "12:35"), ("12:55", "13:10"), ("13:30", "13:45"), ("14:05", "14:20"),
    ("14:40", "14:55"), ("15:15", "15:30"), ("16:00", "16:15"), ("16:40", "16:55"),
    ("17:35", "17:50"), ("18:15", "18:30"), ("18:45", "19:00"), ("19:15", "19:30"),
    ("19:45", "20:00"), ("20:15", "20:30"), ("20:45", "21:00"), ("21:15", "21:30"),
    ("21:45", "22:20"),
]
WEEKDAY_ONLY = {"06:25", "07:10", "12:55", "15:15"}
MD = r"(\d{1,2})月(\d{1,2})日"
WEEKDAY = r"(?:[（(](?:星期|周)[一二三四五六日天][）)])?"
SPAN = re.compile(MD + WEEKDAY + r"[至到—－-](?:(\d{1,2})月)?(\d{1,2})日")


def configure(commands):
    parser = commands.add_parser("bus", help="校区定班车与地铁短驳车")
    operations = parser.add_subparsers(dest="operation", required=True)
    sub = operations.add_parser("next", help="嘉定与四平校区之间的下一班学生定班车")
    sub.add_argument("--from", dest="origin", required=True, choices=STOPS)
    sub.add_argument("--to", dest="destination", required=True, choices=STOPS)
    sub.add_argument("--at", type=parse_time, help="上海出发时间，如 2026-11-27T12:00")
    shuttle = operations.add_parser("shuttle", help="嘉定校区往返11号线上海汽车城站、14号线封浜站的时刻与候车点")
    shuttle.add_argument("--line", choices=("11", "14"), default="11", help="地铁线路，默认 11")
    shuttle.add_argument("--date", type=date.fromisoformat, metavar="YYYY-MM-DD", help="默认上海今天")
    shuttle.add_argument("--from", dest="origin", choices=("嘉定", "上海汽车城", "封浜"), help="默认查询双向")


def parse_time(value):
    try:
        instant = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("请输入 ISO 日期或日期时间") from None
    return instant.astimezone(SHANGHAI) if instant.tzinfo else instant.replace(tzinfo=SHANGHAI)


def run(args):
    if args.operation == "shuttle":
        return shuttle_timetable(args.date or datetime.now(SHANGHAI).date(), args.origin, args.line)
    if args.origin == args.destination:
        raise QueryUnavailable("嘉定与四平之间的定班车需要不同的起终点")
    now = args.at or datetime.now(SHANGHAI)
    if now.date() < date(2026, 6, 1):
        raise QueryUnavailable("目前核对的时刻表署于 2026 年 5 月，更早班次未核实")
    regular_source = regular_timetable_url()
    tomorrow = now.date() + timedelta(days=1)
    calendar = None
    notices = [(published, url, title, article(url))
               for published, url, title in student_notices(tomorrow)]
    for day in (now.date(), tomorrow):
        schedule = None
        for published, url, title, body in notices:
            if day < published:
                continue
            schedule = notice_schedule(body, title, published, day, args.origin, url)
            if schedule is not None:
                departures, label = schedule
                source = url
                break
        if schedule is None:
            if calendar is None:
                calendar = open_data(CALENDAR_PATH, {"fromDate": now.date(), "endDate": tomorrow})
            kind = str(calendar.get(day.isoformat()))
            label = {"2": "平日", "3": "周六" if day.weekday() == 5 else "周日"}.get(kind)
            if not label or (kind == "3" and day.weekday() < 5):
                raise QueryUnavailable(f"{day} 校历或假期班车安排待核实。{INDEX}")
            departures, source = REGULAR[label][args.origin], regular_source
        for clock in departures:
            departure = datetime.combine(day, time.fromisoformat(clock), SHANGHAI)
            if departure >= now:
                return [{"from": args.origin, "to": args.destination, "line": "学生定班车",
                         "departure": departure.isoformat(), "stop": STOPS[args.origin],
                         "schedule": label, "source": source, "regular_source": regular_source}]
    raise QueryUnavailable(f"今日和次日均无可确认的后续班次。{INDEX}")


def fetch(url):
    try:
        with urlopen(url, timeout=12) as response:
            return response.read()
    except OSError:
        raise QueryUnavailable(f"未能读取校方班车来源。{url}") from None


def article(url):
    html = fetch(url).decode()
    body = re.search(r"""<div\s+class=["']wp_articlecontent["']>(.*?)</div>""", html, re.S)
    if not body:
        raise QueryUnavailable(f"校方公告格式待核对。{url}")
    return body[1]


def regular_timetable_url():
    html = fetch(SERVICES).decode()
    link = re.search(r"""<a href=['"]([^'"]+)['"][^>]*title=['"]学生班车时刻表['"]""", html)
    if not link:
        raise QueryUnavailable(f"未找到学生班车时刻表。{SERVICES}")
    url = urljoin(BASE, link[1])
    poster = re.search(r"""<img\b[^>]*?\ssrc=["']([^"']+)""", article(url))
    if not poster or hashlib.sha256(fetch(urljoin(url, poster[1]))).hexdigest() != POSTER_SHA:
        raise QueryUnavailable(f"学生班车时刻表图片已变动，原文时刻待重新核对。{url}")
    return url


def student_notices(until, title_pattern="班车|定班车", since=date(2026, 5, 1)):
    result = []
    url = INDEX
    while url:
        html = fetch(url).decode()
        links = re.findall(r"""<span>([\d-]{10})</span>\s*<a[^>]*>\s*<a href=['"]([^'"]+)['"][^>]*title=['"]([^'"]+)""", html)
        if not links:
            raise QueryUnavailable(f"班车通知目录格式待核对。{url}")
        for stamp, href, title in links:
            published = date.fromisoformat(stamp)
            if published < since:
                return result
            if published > until or not re.search(title_pattern, title):
                continue
            if "教师班车" in title and not re.search("学生班车|定班车", title):
                continue
            if "三门路同济北苑" in title and "嘉定" not in title:
                continue
            result.append((published, urljoin(BASE, href), title))
        next_page = re.search(r'<a class="next" href="([^"]+)"', html)
        url = urljoin(url, next_page[1]) if next_page else None
    return result


def plain(fragment):
    return re.sub(r"\s+", "", unescape(re.sub(r"<[^>]+>", "", fragment)))


def shuttle_timetable(day, origin, line="11"):
    stops = DZ1_STOPS if line == "14" else SHUTTLE_STOPS
    if origin and origin not in stops:
        raise QueryUnavailable(f"{line}号线接驳的出发站可选{'、'.join(stops)}。")
    if day < date(2026, 6, 1):
        raise QueryUnavailable(f"目前核对的短驳车时刻表署于 2026 年 5 月，更早班次未核实。{SERVICES}")
    poster = regular_timetable_url()
    schedule, changes = shuttle_overrides(day, line)
    if schedule is None:
        params = {"fromDate": day.isoformat(), "endDate": day.isoformat()}
        kind = str(open_data(CALENDAR_PATH, params).get(day.isoformat()))
        day_types = {"2": "工作日", "3": "双休日"} if line == "14" else {"1": "双休日", "2": "工作日", "3": "双休日"}
        label = day_types.get(kind)
        if not label:
            raise QueryUnavailable(f"{day} 短驳车校历或假期安排待核实。{INDEX}")
        schedule = label, None, poster
    label, pairs, source = schedule
    if pairs is None and line == "14":
        pairs = DZ1_TIMES
    elif pairs is None:
        weekend = label == "双休日" or (label == "公告指定正常运行" and day.weekday() >= 5)
        pairs = [pair for pair in SHUTTLE_TIMES if not (weekend and pair[0] in WEEKDAY_ONLY)
                 and (pair[0] != "16:00" or (not weekend and day.weekday() == 4))]
    result = []
    stations = list(stops)
    for column, (station, stop) in enumerate(stops.items()):
        if origin and station != origin:
            continue
        departures = {}
        for pair in pairs:
            pickup = changes.get((station, pair[column]), (stop, source))
            departures.setdefault(pickup, []).append(pair[column])
        for (pickup_stop, pickup_source), times in departures.items():
            row = {"date": day.isoformat(), "line": "14号线嘉定DZ1线" if line == "14" else "11号线短驳车", "from": station,
                   "to": stations[1 - column], "stop": pickup_stop,
                   "departures": times, "schedule": label, "source": source, "regular_source": poster}
            if station == "封浜":
                row["notes"] = "封浜站具体发车时间以公交车到站时间为准"
            if pickup_source != source:
                row["stop_source"] = pickup_source
            result.append(row)
    return result


def shuttle_overrides(day, line):
    schedule = None
    changes = {}
    # The verified poster image was published May 26, after the May 21 DZ1 adjustment.
    if line == "14":
        notices = student_notices(day, "学生班车|短驳车|14号线|DZ1|封浜|定制公交", since=date(2026, 5, 27))
    else:
        notices = student_notices(day, "学生班车|短驳车|上海汽车城")
    other = "11" if line == "14" else "14"
    for published, url, title in notices:
        if other + "号线" in title and line + "号线" not in title:
            continue
        body = article(url)
        if re.fullmatch(r"关于\d{1,2}月\d{1,2}日短驳车发车点临时调整的通知", title):
            month, number = map(int, re.search(MD, title).groups())
            if day == date(published.year, month, number):
                changes.update(shuttle_stop_changes(body, url))
        else:
            override = shuttle_notice(body, published, day, url, line)
            if schedule is None and override:
                schedule = override
    return schedule, changes


def table_rows(table):
    return [[plain(cell) for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)]
            for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, re.S)]


def shuttle_stop_changes(body, url):
    rows = table_rows(body)
    if not rows or rows[0] != ["涉及出发时刻", "原发车点", "临时调整发车点"] or len(rows) < 2:
        raise QueryUnavailable(f"短驳车临时发车点待核实。{url}")
    changes = {}
    for row in rows[1:]:
        if len(row) != 3 or row[1] != SHUTTLE_STOPS["嘉定"] or not row[2]:
            raise QueryUnavailable(f"短驳车临时发车点待核实。{url}")
        clocks = re.findall(r"\d{1,2}:\d{2}", row[0])
        if not clocks or "".join(clocks) != row[0]:
            raise QueryUnavailable(f"临时调整发车点的班次待核实。{url}")
        changes.update({("嘉定", clock.zfill(5)): (row[2], url) for clock in clocks})
    return changes


def notice_period(text, published):
    intro = text.split("学生班车安排如下")[0]
    stated_year = re.search(r"(20\d{2})年", intro)
    year = int(stated_year[1]) if stated_year else published.year
    return year, SPAN.search(intro)


def is_makeup_day(text, year, day):
    makeup = re.search(r"((?:" + MD + WEEKDAY + r"[、，,]?)+)(?:上课、上班|上班、上课)[，,]学生班车按工作日", text)
    return makeup and any(day == date(year, int(m), int(d)) for m, d in re.findall(MD, makeup[1]))


def shuttle_notice(body, published, day, url, line):
    text = plain(body)
    year, period = notice_period(text, published)
    if not period:
        raise QueryUnavailable(f"短驳车变更公告适用日期待核实。{url}")
    if is_makeup_day(text, year, day):
        return "工作日", None, url
    if not in_span(period, year, day):
        return None
    if line == "14":
        section = re.search(r"(?:三|3)[、.．]轨道交通14号线(?:短驳车|定制公交(?:嘉定)?DZ1线)[（(][^）)]+[）)](.*?)(?:注[：:]|特此通知|$)", text)
        if section and re.fullmatch(r"(?:端午节|暑假|中秋节|国庆节)期间(?:按时刻表)?正常运行[。.]?", section[1]):
            return "公告指定正常运行", None, url
        raise QueryUnavailable(f"14号线嘉定DZ1线临时安排待核实。{url}")
    section = re.search(r"(?:二|2)[、.．]轨道交通11号线短驳车[（(][^）)]+[）)](.*?)(?:三|3)[、.．]", text)
    if section:
        arrangement = section[1]
        if re.fullmatch(r"[^。]*期间按双休日时刻表运行[。.]?", arrangement):
            return "双休日", None, url
        if re.search("停开|停运|取消|调整发车点", arrangement):
            raise QueryUnavailable(f"短驳车临时安排请见校方原文。{url}")
        normal = re.search(r"正常运行至" + MD, arrangement)
        if normal and day <= date(year, *map(int, normal.groups())):
            return "公告指定正常运行", None, url
        bounds = SPAN.search(arrangement)
        if not bounds or in_span(bounds, year, day):
            for table in re.findall(r"<table\b[^>]*>.*?</table>", body, re.S):
                rows = table_rows(table)
                if rows and rows[0] == ["嘉定校区发车时间", "上海汽车城站返回时间"]:
                    if len(rows) > 1 and all(len(row) == 2 and all(re.fullmatch(r"\d{1,2}:\d{2}", t)
                                               for t in row) for row in rows[1:]):
                        return "校方临时时刻表", [(a.zfill(5), b.zfill(5)) for a, b in rows[1:]], url
    raise QueryUnavailable(f"短驳车临时安排请见校方原文。{url}")


def in_span(match, year, day):
    month1, day1, month2, day2 = (int(v) if v else None for v in match.groups())
    end_month = month2 or month1
    return date(year, month1, day1) <= day <= date(year + int(end_month < month1), end_month, day2)


def notice_schedule(body, title, published, day, origin, url):
    text = plain(body)
    year, period = notice_period(text, published)
    if is_makeup_day(text, year, day):
        return REGULAR["平日"][origin], "公告指定工作日"
    if not period:
        dates = re.findall(MD, title)
        if len(dates) == 1 and not re.search("起|开始|恢复", title) and ("当天" in text or "当日" in text):
            month, day_of_month = map(int, dates[0])
            if day != date(year, month, day_of_month):
                return None
        raise QueryUnavailable(f"班车变更公告的适用日期或新安排待核实。{url}")
    if not in_span(period, year, day):
        return None
    section = re.search(r"一[、.．]定班车(.*?)(?:二[、.．]|$)", text)
    if not section:
        raise QueryUnavailable(f"假期定班车安排待核实。{url}")
    if re.search(r"发车点.{0,8}(?:调整|改为|迁)|(?:调整|变更).{0,5}发车点", section[1]):
        raise QueryUnavailable(f"定班车发车地点变更待核实。{url}")
    tables = re.findall(r"<table\b[^>]*>.*?</table>", body, re.S)
    cursor = 0
    for table in tables:
        position = body.index(table, cursor)
        preceding = plain(body[cursor:position])
        cursor = position + len(table)
        rows = table_rows(table)
        if not rows or rows[0][-2:] != ["嘉定校区", "四平路校区"]:
            continue
        bounds = list(SPAN.finditer(preceding))
        if bounds and not in_span(bounds[-1], year, day):
            continue
        clocks = []
        applies = True
        for row in rows[1:]:
            if "双休日" in row:
                applies = day.weekday() >= 5
            elif "周一至周五" in row:
                applies = day.weekday() < 5
            if applies:
                if len(row) < 2 or not all(re.fullmatch(r"\d{1,2}:\d{2}", t) for t in row[-2:]):
                    raise QueryUnavailable(f"临时班车时刻待核实。{url}")
                clocks.append(row[-2 if origin == "嘉定" else -1].zfill(5))
        if clocks:
            return sorted(clocks), "校方临时安排"
    raise QueryUnavailable(f"公告未列出可确认的定班车时刻。{url}")
