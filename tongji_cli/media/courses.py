from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from playwright.sync_api import expect

from tongji_cli.common import QueryUnavailable


ENTRY = "https://look.tongji.edu.cn/education/"
COURSE_LIST = "/personal/courseapi/vlabpassportapi/v1/account-profile/course"


def courses(page, search):
    page.get_by_text("我的课程", exact=True).filter(visible=True).first.click()
    frame = page.frame_locator("#inlineFrameExample")
    frame.get_by_placeholder("课程名称/教师名称").fill(search)
    button = frame.get_by_role("button", name="搜索", exact=True)
    items = []
    number = 1
    while True:
        result = course_page(page, button, search, number)
        cards = frame.locator(".my-course-list .courseInfo")
        expect(cards.locator(".course-label")).to_have_text([r["Title"] for r in result["data"]])
        details = cards.evaluate_all("""cards => cards.map(card => Array.from(
            card.querySelectorAll('.course-desc-p'), p => p.innerText.trim()
        ))""")
        for row, labels in zip(result["data"], details):
            fields = dict(label.split("：", 1) for label in labels if "：" in label)
            detail = urlencode({"course_id": row["Id"], "tenant_code": row["TenantCode"]})
            items.append({"id": row["Id"], "title": row["Title"], "term": row.get("TermName") or None,
                          "teacher": fields["主讲教师"] or None, "last_studied": fields["上次学习"] or None,
                          "task_count": int(fields["任务数"]), "source": ENTRY,
                          "url": urljoin(ENTRY, "/coursedetail") + "?" + detail})
        if len(items) == result["total"]:
            return items
        if not result["data"] or len(items) > result["total"]:
            raise QueryUnavailable("媒体平台课程页数与目录总数不符")
        button = frame.locator(".el-pagination .btn-next")
        if not button.is_enabled():
            raise QueryUnavailable("媒体平台尚有课程，但目录没有开放下一页")
        number += 1


def course_page(page, button, search, number):
    def requested_page(response):
        url = urlsplit(response.url)
        params = parse_qs(url.query)
        return (url.path == COURSE_LIST and response.request.method == "GET"
                and params.get("nowpage") == [str(number)] and params.get("search", [""]) == [search])

    with page.expect_response(requested_page) as fetched:
        button.click()
    response = fetched.value
    if not response.ok:
        raise QueryUnavailable(f"媒体平台未返回课程目录（HTTP {response.status}）")
    payload = response.json()
    if payload["code"] != 1000 or payload["status"] != 200:
        raise QueryUnavailable("媒体平台未确认课程查询成功")
    result = payload["params"]["result"]
    if int(result["page"]) != number:
        raise QueryUnavailable("媒体平台返回的页码与所选页不符")
    if result["data"] is None and result["total"] == 0:
        result["data"] = []
    if not isinstance(result["data"], list):
        raise QueryUnavailable("媒体平台未返回可核对的课程列表")
    return result
