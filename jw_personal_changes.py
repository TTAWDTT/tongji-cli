import re
import sys
from datetime import datetime
from urllib.parse import urljoin

from playwright.sync_api import Error as BrowserError

from jw_records import VIEWS, enrollment_status, records, selected_term
from queries import QueryUnavailable, SHANGHAI


WITHDRAWAL_NOTICE = "https://bksy.tongji.edu.cn/63/17/c30359a418583/page.htm"


def personal_change(page, operation, term, class_id, *, preview=False, handoff=None, now=None):
    term, class_id = term.strip(), class_id.strip()
    if not term or not class_id:
        raise QueryUnavailable("请同时指定学期和新课程序号")
    home = page.url
    enrolling = operation == "enroll"
    source, path, _ = VIEWS["requests" if enrolling else "withdrawals"]
    result = {"学期": term, "新课程序号": class_id, "source": source, "url": urljoin(home, path)}
    before = course_state(page, operation, term, class_id)
    result["办理前"] = before
    if completed(before, enrolling):
        return [dict(result, state="already", detail="办理前已核实该课状态")]

    if enrolling:
        window, = enrollment_status(page)
    else:
        if before["退课记录状态"] != "未退课" or not before["个人课表列有该课"]:
            raise QueryUnavailable(f"退课办理前状态不一致：{state_text(before)}")
        window = withdrawal_window(page, term, now or datetime.now(SHANGHAI))
    result.update(window)
    if window["state"] == "closed":
        if preview:
            return [result]
        raise QueryUnavailable(window["detail"] + " " + window.get("通知链接", result["url"]))
    if preview:
        return [dict(result, state="preview")]

    page.bring_to_front()
    (handoff or wait_for_student)(result, enrolling)
    checker = page.context.new_page()
    try:
        checker.goto(home, wait_until="domcontentloaded")
        after = course_state(checker, operation, term, class_id)
    except (BrowserError, QueryUnavailable) as exc:
        reason = str(exc) if isinstance(exc, QueryUnavailable) else "未能读取教务页面"
        raise QueryUnavailable(f"{term} {class_id} 办理后未能核实：{reason}。请先查询最新记录。") from None
    finally:
        checker.close()
    if not completed(after, enrolling):
        raise QueryUnavailable(f"{term} {class_id} 办理结果未核实。办理前：{state_text(before)}。"
                               f"办理后：{state_text(after)}。请查看学校页面的办理结果。")
    return [dict(result, state="verified", detail="已回读学校记录", 办理后=after)]


def course_state(page, operation, term, class_id):
    courses = records(page, "courses")
    require_term(page, term)
    timetable = page.url
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("上课时间", exact=True))
    for item in table.all():
        if "新课程序号" not in [s.strip() for s in item.locator(".el-table__header-wrapper th").all_inner_texts()]:
            raise QueryUnavailable("个人课表缺少新课程序号，无法核对教学班")
    present = any(row["新课程序号"] == class_id for row in courses)
    state = {"个人课表列有该课": present, "个人课表链接": timetable}
    if operation == "withdraw":
        rows = records(page, "withdrawals")
        require_term(page, term)
        matches = [row for row in rows if row.get("新课程序号") == class_id]
        if len(matches) != 1 or not matches[0].get("状态"):
            raise QueryUnavailable(f"{term} 的期中退课记录未显示唯一的 {class_id} 及其状态")
        state.update(退课记录状态=matches[0]["状态"], 课程名称=matches[0].get("课程名称"), 退课记录链接=page.url)
    return state


def require_term(page, term):
    actual = selected_term(page)
    if not actual or term != actual:
        raise QueryUnavailable(f"指定学期与教务页面不一致。指定为「{term}」，页面显示「{actual}」")
    error = page.locator(".el-message--error:visible, .el-notification:visible .el-icon-error")
    if error.count():
        raise QueryUnavailable("学校查询页显示错误，无法核实课程状态")


def completed(state, enrolling):
    return (state["个人课表列有该课"] if enrolling
            else state["退课记录状态"] == "已退课" and not state["个人课表列有该课"])


def state_text(state):
    presence = "个人课表有该课" if state["个人课表列有该课"] else "个人课表无该课"
    return presence + ("，退课记录为" + state["退课记录状态"] if "退课记录状态" in state else "")


def withdrawal_window(page, term, now):
    closed = re.compile(r"^(?:.{0,12}(?:不在|未到|已过|未开放|没有开放).{0,8}退课.{0,15}|"
                        r".{0,12}退课(?:时间|窗口|申请|办理|功能)?.{0,5}(?:已结束|已截止|尚未开放|未开放|尚未开始))[！!。]?$")
    message = page.get_by_text(closed).filter(visible=True)
    if message.count():
        return {"state": "closed", "detail": message.first.inner_text().strip()}
    if re.fullmatch(r"2026\s*[-－–]\s*2027(?:学年)?第[一1]学期", term):
        start = datetime(2026, 10, 26, 9, tzinfo=SHANGHAI)
        end = datetime(2026, 10, 30, 16, tzinfo=SHANGHAI)
        detail = "本科生院公布的本学期期中退课办理时间为 2026-10-26 09:00 至 2026-10-30 16:00（北京时间）"
        return {"state": "published_window" if start <= now < end else "closed",
                "detail": detail, "通知链接": WITHDRAWAL_NOTICE}
    return {"state": "window_unverified", "detail": "请在校方页面核对该学期的退课安排"}


def wait_for_student(result, enrolling):
    instruction = "选课并保存课表" if enrolling else "办理期中退课"
    print(f"{result['学期']}，新课程序号 {result['新课程序号']}。{state_text(result['办理前'])}。"
          f"{result['detail']}。请本人在教务页面核对教学班、{instruction}，完成后回终端按回车核对结果。",
          file=sys.stderr, flush=True)
    try:
        input()
    except EOFError:
        raise QueryUnavailable("等待本人网页办理需要交互终端。请先查询该课的当前状态。") from None
