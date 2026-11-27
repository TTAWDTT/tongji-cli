import json
import os
from datetime import timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from queries import QueryUnavailable, SEMESTERS, semester_list, term_and_week


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


API = "https://api.tongji.edu.cn"
DAY_TYPES = {"1": "节假日", "2": "工作日", "3": "周末", "4": "寒假", "5": "暑期"}


def open_data(path, params=None, *, token=None):
    url = API + path + ("?" + urlencode(params) if params else "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    opener = build_opener(NoRedirect()).open if token else urlopen
    try:
        with opener(Request(url, headers=headers), timeout=15) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise QueryUnavailable(f"学校开放平台返回 HTTP {error.code}，请核对接口授权或稍后重试") from None
    except (OSError, ValueError):
        raise QueryUnavailable("未能取得学校开放平台响应") from None
    if payload.get("code") != "A00000":
        raise QueryUnavailable(f"学校开放平台未返回有效数据（{payload.get('code')}）")
    return payload["data"]


def calendar_terms(year=None):
    return [{"semester": row["semesterName"], "semester_id": row["ID"], "year": row["year"],
             "start_date": row["beginDay"], "end_date": row["endDay"],
             "teaching_week_start": row.get("teachingWeekStart"), "teaching_week_end": row.get("teachingWeekEnd"),
             "exam_week_start": row.get("examWeekStart"), "exam_week_end": row.get("examWeekEnd"), "source": SEMESTERS}
            for row in semester_list() if year is None or str(row["year"]) == str(year)]


def date_types(start, end):
    if end < start:
        raise QueryUnavailable("校历结束日期须等于或晚于开始日期")
    params = {"fromDate": start.isoformat(), "endDate": end.isoformat()}
    path = "/v1/rt/onetongji/calendar"
    data = open_data(path, params)
    if not isinstance(data, dict):
        raise QueryUnavailable("校方校历未返回按日期列出的标记")
    return data, API + path + "?" + urlencode(params)


def calendar_range(start, end):
    data, source = date_types(start, end)
    rows = []
    for offset in range((end - start).days + 1):
        day = (start + timedelta(days=offset)).isoformat()
        rows.append({"date": day, "day_type": DAY_TYPES.get(str(data.get(day))), "source": source})
    missing = sum(row["day_type"] is None for row in rows)
    if not missing:
        return {"status": "ok", "items": rows}
    return {"status": "unverified" if missing == len(rows) else "partial", "items": rows,
            "detail": f"校方尚未提供可识别的日期标记，共 {missing} 天"}


def calendar_info(day, include_day):
    term, week = term_and_week(day, semester_list())
    result = {"date": day.isoformat(), "semester": term, "week": week, "source": SEMESTERS}
    monday = day - timedelta(days=day.weekday())
    result.update(week_start=monday.isoformat(), week_end=(monday + timedelta(days=6)).isoformat())
    if include_day:
        data, source = date_types(day, day)
        kind = str(data.get(day.isoformat()))
        if kind not in DAY_TYPES:
            raise QueryUnavailable("校方校历未提供该日的日期类型")
        result.update(day_type=DAY_TYPES[kind], calendar_source=source)
    return [result]


CAMPUSES = {"四平": "1", "沪北": "2", "嘉定": "3", "沪西": "4", "其他": "5"}


def room_token():
    token = os.environ.get("TONGJI_OPEN_TOKEN")
    if not token:
        raise QueryUnavailable("教室查询需要校方客户端模式授权。请通过 TONGJI_OPEN_TOKEN 提供获准访问此接口的令牌")
    return token


def room_directory(building=None, campus=None):
    if building is None:
        path = "all_classroom_list"
        params = {"campus": CAMPUSES[campus]} if campus else {}
    else:
        path = "get_classroom_by_tower"
        params = {"towerCode": building}
    data = open_data("/v1/rt/onetongji/classroom/" + path, params, token=room_token())
    rows = data["list"]
    if not isinstance(rows, list) or len(rows) != int(data["total_"]):
        raise QueryUnavailable("教务目录的记录数与总数不符")
    if building is None:
        return [{"building": r["name"], "code": r["code"], "campus": r["campusI18n"]} for r in rows]
    return [{"room": r["name"], "id": r["id"], "building": r["towerName"], "campus": r["campusI18n"],
             "floor": r.get("floor"), "type": r.get("typeI18n")} for r in rows]


def room_schedule(room, term):
    token = room_token()
    params = {"classroomIds": room}
    if term:
        params["calendarId"] = term
    data = open_data("/v1/rt/onetongji/classroom/get_timetable_by_classroom", params, token=token)
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise QueryUnavailable("教室课表返回结构待核实")
    return [{"room": row["classroomName"], "semester": row["calendarName"], "campus": row.get("campusI18n"),
             "schedule": row["classroomOccupationList"]} for row in data["data"]]
