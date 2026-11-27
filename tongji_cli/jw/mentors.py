from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.sync_api import expect

from tongji_cli.jw.records import query_data, record_pages, table_grid, watch_query
from tongji_cli.common import QueryUnavailable


MY_TUTOR = "/api/welcomeservice/tutorStudent/myTutor"
PROFILES = {
    "freshman": ("新生导师", "/mySchoolTutor", MY_TUTOR, "1"),
    "college": ("学院导师", "/myCollegeTutor", MY_TUTOR, "2"),
    "mutual": ("互选导师", "/myMutualTutor", "/api/welcomeservice/selection/myTutor", None),
}
MEETING_VIEW = "/schoolTutorMeeting"
MEETING_LIST = "/api/welcomeservice/tutorMeeting/queryByPage"


def mentor_profile(page, kind):
    name, view, path, mentor_type = PROFILES[kind]
    url = urljoin(page.url, view)
    with watch_query(page, path) as opened:
        page.goto(url, wait_until="domcontentloaded")
    response = opened.value
    if mentor_type and parse_qs(urlsplit(response.url).query).get("type") != [mentor_type]:
        raise QueryUnavailable("学校返回的导师类别与所选入口不一致")
    record = query_data(response)
    fields = page.locator(".el-form-item:visible")
    if not record or not record.get("teacherName"):
        message = page.get_by_text("您目前没有导师", exact=True).filter(visible=True)
        expect(message).to_be_visible()
        return {"detail": f"{name}页面显示“您目前没有导师”", "items": []}
    identity = fields.filter(has=page.get_by_text("姓名:", exact=True)).locator(".el-form-item__content")
    expect(identity).to_have_text(record["teacherName"].strip())
    values = fields.evaluate_all("""groups => Object.fromEntries(groups.map(group=>{
        const name=group.querySelector('label').innerText.trim().replace(/[：:]$/, '');
        return [name,group.querySelector('.el-form-item__content').innerText.trim() || null];
    }))""")
    return [{"导师类别": name, **values, "url": url}]


def mentor_meetings(page):
    url = urljoin(page.url, MEETING_VIEW)
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("见面时间", exact=True))
    result = []
    for batch in record_pages(page, url, MEETING_LIST, "新生见面会"):
        body = table.locator(":scope > .el-table__body-wrapper table")
        expect(body.locator("tr:visible")).to_have_count(len(batch))
        header = table.locator(":scope > .el-table__header-wrapper table")
        labels, = table_grid(header, ".el-table__fixed-header-wrapper table")
        rows = table_grid(body, ".el-table__fixed-body-wrapper table")
        for cells, record in zip(rows, batch, strict=True):
            row = dict(zip(labels, cells, strict=True))
            if (row["见面时间"] != (record["meetingTime"] or "")
                    or row["见面地点"] != (record["meetingLocation"] or "")):
                raise QueryUnavailable("新生见面会的时间或地点与教务记录不一致")
            result.append({**{k: row[k] or None for k in ("学期","导师","导师所属学院","见面时间","见面地点","备注","发布时间")}, "url": url})
    return result
