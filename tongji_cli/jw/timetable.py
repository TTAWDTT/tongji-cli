import json
import re
from datetime import date
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen

from playwright.sync_api import Error

from tongji_cli.common import QueryUnavailable


SEMESTERS = "https://api.tongji.edu.cn/v1/rt/teaching_info/semester"


def timetable(page, day):
    return timetable_range(page, [day])[0]["items"]


def dated_timetable(page, day):
    for menu in ("我的课表", "我的课程", "我的课表"):
        link = page.get_by_text(menu, exact=True).first
        if link.is_visible():
            try:
                link.click(timeout=3000)
            except Error:
                raise QueryUnavailable("教务课表菜单暂不可用") from None
            if menu == "我的课表":
                break
    # 只接受带实际日期的列。周几相同不能说明当前页面属于本周。
    formats = (day.isoformat(), f"{day.year}年{day.month}月{day.day}日", f"{day.year}/{day.month}/{day.day}")
    for frame in page.frames:
        for table in frame.locator("table:visible").all():
            rows = table.get_by_role("row").all()
            for offset, row in enumerate(rows):
                headers = row.locator(":scope > th, :scope > td").all_inner_texts()
                if not headers or not re.search(r"节次|时间|节数", headers[0]):
                    continue
                column = next((i for i, value in enumerate(headers)
                               if any(re.search(r"(?<!\d)" + re.escape(date) + r"(?!\d)", value)
                                      for date in formats)), None)
                if column is None:
                    continue
                courses = []
                for body_row in rows[offset + 1:]:
                    cells = body_row.locator(":scope > th, :scope > td")
                    if cells.count() != len(headers) or body_row.locator("[rowspan]:not([rowspan='1']), [colspan]:not([colspan='1'])").count():
                        raise QueryUnavailable("教务课表含合并单元格，需核对页面格式")
                    value = cells.nth(column).inner_text().strip()
                    if value:
                        courses.append({"period": cells.first.inner_text().strip(), "detail": value})
                if len(rows) > offset + 1:
                    return courses
    raise QueryUnavailable("尚未识别当天课表，请核对 1 系统的当前教学周和页面布局")


def graduate_timetable(page, day):
    return graduate_days(page, [day])[0]["items"]


def timetable_range(page, days):
    path = urlsplit(page.url).path
    if path != "/GraduateStudentTimeTable" and page.get_by_text("个人课表", exact=True).filter(visible=True).count():
        page.goto(urljoin(page.url, "/GraduateStudentTimeTable"), wait_until="commit")
        path = urlsplit(page.url).path
    if path == "/GraduateStudentTimeTable":
        result = graduate_days(page, days)
    else:
        result = [{"date": day.isoformat(), "items": dated_timetable(page, day)} for day in days]
    source = urlsplit(page.url)._replace(query="", fragment="").geturl()
    for row in result:
        row["source"] = source
    return result


def graduate_days(page, days):
    header = page.locator("table.el-table__header").filter(has_text="上课时间").first
    header.wait_for(timeout=12000)
    table = header.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' el-table ')][1]")
    rows = table.locator("table.el-table__body tr")
    empty = table.locator(".el-table__empty-text:visible")
    rows.first.or_(empty.first).first.wait_for(timeout=12000)
    if empty.count() and not rows.count():
        page.wait_for_load_state("networkidle", timeout=12000)
    labels = [s.strip() for s in header.locator("th").all_inner_texts()]
    fields = [labels.index(name) for name in ("课程名称", "上课时间", "上课地点")]
    campus_field = labels.index("校区") if "校区" in labels else None
    terms = page.locator("input:visible").evaluate_all("inputs => inputs.map(input => input.value)")
    calendar = semester_list()
    schedules = []
    for row in rows.all():
        cells = row.locator(":scope > td").all_inner_texts()
        if len(cells) <= max(*fields, campus_field or 0):
            raise QueryUnavailable("教务课程列表列数与表头不一致")
        title, schedule, locations = (cells[i].strip() for i in fields)
        campus = cells[campus_field].strip() if campus_field is not None else None
        schedules.append((title, schedule, locations, campus))
    result = []
    for day in days:
        _, week = term_and_week(day, calendar, terms)
        weekday = "一二三四五六日"[day.weekday()]
        courses = [{"period": period, "detail": title, "locations_as_listed": location, "campus": campus}
                   for title, schedule, location, campus in schedules
                   for period in matching_periods(schedule, weekday, week)]
        courses.sort(key=lambda item: int(item["period"].split("-")[0]))
        result.append({"date": day.isoformat(), "teaching_week": week, "items": courses})
    return result


def semester_list():
    try:
        with urlopen(SEMESTERS, timeout=10) as response:
            result = json.load(response)
    except OSError:
        raise QueryUnavailable("校方学期接口暂不可用") from None
    if result["code"] != "A00000" or not isinstance(result["data"], list):
        raise QueryUnavailable("校方学期接口未返回学期列表")
    return result["data"]


def term_and_week(day, calendar, selected_terms=None):
    terms = {term.replace("学年", "") for term in selected_terms} if selected_terms is not None else None
    for term in calendar:
        if terms is not None and term["semesterName"] not in terms:
            continue
        start = date.fromisoformat(term["beginDay"])
        if start <= day <= date.fromisoformat(term["endDay"]):
            return term["semesterName"], ((day - start).days + start.weekday()) // 7 + 1
    raise QueryUnavailable("所选课表学期与校方当前学期未能对应")


def matching_periods(schedule, weekday, week):
    slots = re.split(r"[,，;；\s]+(?=星期)", schedule)
    for slot in slots:
        match = re.fullmatch(r"星期([一二三四五六日天])\s*(\d+(?:-\d+)?)节\s*\[([^\]]+)\]", slot.strip())
        if not match:
            raise QueryUnavailable("教务上课时间格式待核对")
        day_name, period, weeks = match.groups()
        if day_name.replace("天", "日") != weekday:
            continue
        for span in re.split(r"[,，、]\s*", weeks):
            bounds = re.fullmatch(r"(\d+)(?:-(\d+))?([单双])?", span.strip())
            if not bounds:
                raise QueryUnavailable("教务上课周次格式待核对")
            start, end, parity = bounds.groups()
            if int(start) <= week <= int(end or start) and (parity is None or week % 2 == int(parity == "单")):
                yield period
                break
