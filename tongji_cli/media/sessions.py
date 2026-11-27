from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from playwright.sync_api import expect

from tongji_cli.media.courses import courses
from tongji_cli.common import QueryUnavailable


def sessions(page, selector, status):
    available = courses(page, "" if selector.isdecimal() else selector)
    matches = [c for c in available if selector == str(c["id"]) or selector == c["title"]]
    if len(matches) != 1:
        raise QueryUnavailable("未匹配到唯一的媒体课程，请用 media courses 的课程 ID 查询")
    course = matches[0]
    def student_detail(response):
        url = urlsplit(response.url)
        query = parse_qs(url.query)
        return (response.request.method == "GET" and url.path == "/courseapi/v3/multi-search/get-course-detail"
                and query.get("course_id") == [str(course["id"])] and "student" in query)

    with (page.expect_response(student_detail) as fetch,
          page.expect_response(lambda r: urlsplit(r.url).path == "/courseapi/v3/multi-search/get-tenant-sub-type") as types):
        page.goto(course["url"], wait_until="domcontentloaded")
    if not fetch.value.ok:
        raise QueryUnavailable("媒体平台未返回课程详情")
    payload = fetch.value.json()
    if payload["code"] != 0 or str(payload["data"]["id"]) != str(course["id"]):
        raise QueryUnavailable("媒体平台未确认所选课程")
    dictionary = types.value.json()
    if not types.value.ok or dictionary["code"] != 0:
        raise QueryUnavailable("媒体平台未返回课次类型名称")
    expect(page.locator(".info-title p").first).to_have_text(course["title"])
    return session_rows(page, course, payload["data"]["sub_list"], status, dictionary["data"])


def lessons(section):
    if isinstance(section, dict) and "sub_title" in section:
        yield section
    elif isinstance(section, (list, dict)):
        for child in (section.values() if isinstance(section, dict) else section):
            yield from lessons(child)
    else:
        raise QueryUnavailable("媒体课程目录结构待核实")


def session_rows(page, course, sections, status, type_names):
    records = list(lessons(sections))
    lines = page.locator(".content-list .content-inner-one > p")
    expect(lines.locator(":scope > span:nth-child(2)")).to_have_text([r["sub_title"] for r in records])
    details = lines.evaluate_all("""lines => lines.map(p => ({
        type: p.children[0].innerText.trim(),
        teacher: p.children[2].innerText.trim(),
        status: p.children[4]?.innerText.trim() || null,
        week: p.closest('.content-inner-one').parentElement.querySelector('.cap-title-info')?.innerText.trim() || null
    }))""")
    tenant = parse_qs(urlsplit(course["url"]).query)["tenant_code"][0]
    items = []
    for info, r in zip(details, records, strict=True):
        if status and info["status"] != status:
            continue
        if r["type"] in type_names:
            info["type"] = type_names[r["type"]]["name"]
        item = dict(info, id=r["id"], title=r["sub_title"], course=course["title"],
                    course_id=course["id"], source=course["url"])
        if info["status"] == "回放" and r["type"] == "course_live":
            query = urlencode({"course_id": course["id"], "sub_id": r["id"], "tenant_code": tenant})
            item["url"] = urljoin(course["url"], "/livingroom") + "?" + query
        items.append(item)
    return items
