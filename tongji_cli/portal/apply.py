import math
import re
import sys
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.sync_api import Error, expect, sync_playwright

from tongji_cli.browser_session import open_session
from tongji_cli.portal.guides import DIRECTORY
from tongji_cli.common import QueryUnavailable


LOGIN = {"status": "login_required", "detail": "请运行 ./tongji login --site service 完成学校统一身份认证。"}
FORM_PATH = "/newservice/fe/taskCenter/matterApplication"
HISTORY = urljoin(DIRECTORY, "/newservice/fe/taskCenter/matter/application")


def apply(profile, title, preview=False):
    title = title.strip()
    if not title:
        raise QueryUnavailable("请输入 service find 返回的完整表单名称")
    if not profile.exists():
        return LOGIN
    if not preview and not sys.stdin.isatty():
        raise QueryUnavailable("请在交互终端办理，或加 --preview 核对表单")
    with sync_playwright() as pw:
        context = open_session(pw, profile, interactive=not preview)
        try:
            return apply_in_session(context, title, preview, confirm_in_browser)
        finally:
            context.close()


def confirm_in_browser(title):
    print(f"请在学校网页填写《{title}》并亲自确认提交。网页处理完毕后回到终端按回车核对办件。",
          file=sys.stderr, flush=True)
    try:
        input()
    except EOFError:
        raise QueryUnavailable("终端输入已结束，本次提交未核实。请在学校网页查看我的申请。") from None


def open_form(page, title):
    page.goto(DIRECTORY, wait_until="commit")
    search = page.get_by_placeholder("请输入要搜索的关键词", exact=True)
    search.fill(title)
    with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/home-page/search")
                              and parse_qs(urlsplit(r.url).query).get("keyword") == [title]) as reply:
        search.press("Enter")
    payload = reply.value.json()
    apps = (payload.get("d") or {}).get("apps") if reply.value.ok and payload.get("e") == "OK" else None
    if not isinstance(apps, list):
        raise QueryUnavailable("同心搭未返回可核对的服务搜索结果")
    matches = [app for app in apps if app["name"].get("zh") == title]
    if len(matches) != 1:
        raise QueryUnavailable(f"同心搭搜索结果中有 {len(matches)} 项与完整名称相同，请用 service find 核对")
    label = page.locator(".item .index_search_name .name:visible").filter(has_text=re.compile(rf"^{re.escape(title)}$"))
    expect(label).to_have_count(1)
    label.click()
    page.wait_for_url(lambda url: urlsplit(url).hostname == "iam.tongji.edu.cn"
                      or (urlsplit(url).hostname == "txd.tongji.edu.cn" and urlsplit(url).path == FORM_PATH))
    if urlsplit(page.url).hostname == "iam.tongji.edu.cn":
        return None
    expect(page.locator(".matter_title:visible")).to_have_text(title)
    page.locator(".pc_form:visible").wait_for()
    page.get_by_role("button", name="立即提交", exact=True).wait_for()
    app_id = str(matches[0]["id"])
    if parse_qs(urlsplit(page.url).query).get("app_id") != [app_id]:
        raise QueryUnavailable("表单事项编号与搜索结果不一致")
    return app_id


def apply_in_session(context, title, preview, confirm):
    page = context.new_page()
    page.set_default_timeout(16000)
    try:
        app_id = open_form(page, title)
        if app_id is None:
            return LOGIN
        if preview:
            return {"status": "ok", "items": [{"title": title, "action": "preview", "source": DIRECTORY}],
                    "detail": "已核对学校办理表单及提交入口。"}
        history = context.new_page()
        history.set_default_timeout(16000)
        try:
            before = application_ids(history, app_id)
            page.bring_to_front()
            confirm(title)
            new = application_ids(history, app_id) - before
            if len(new) != 1:
                return {"status": "unverified", "detail": "我的申请中未能核对到唯一新增的同名办件，请在校方页面查看。"}
            return {"status": "ok", "items": [{"title": title, "action": "submitted", "receipt": new.pop(), "source": HISTORY}],
                    "detail": "已在我的申请核对到一件新增的同名办件。"}
        finally:
            history.close()
    except (Error, AssertionError):
        if urlsplit(page.url).hostname == "iam.tongji.edu.cn":
            return LOGIN
        return {"status": "unverified", "detail": "未能核实校方的同名办理表单或新增办件，请查看同心搭的我的申请。"}
    finally:
        page.close()


def application_ids(page, app_id):
    def is_list(response):
        return urlsplit(response.url).path == "/newservice/site/session/list"

    with page.expect_response(is_list):
        page.goto(HISTORY, wait_until="commit")
    expect(page.locator(".matter_nav_item.active")).to_have_text(re.compile(r"^我的申请\s*$"))
    tabs = page.locator(".matter_nav_tab")
    with page.expect_response(is_list) as listing:
        tabs.get_by_text("全部", exact=True).click()
    expect(tabs.locator(".active")).to_have_text(re.compile(r"^全部"))
    seen, matches = set(), set()
    number = 1
    while True:
        response = listing.value
        payload = response.json()
        if not response.ok or payload.get("e") != "OK":
            raise QueryUnavailable("学校未返回完整的个人申请清单")
        data = payload["d"]
        if int(data["page"]) != number or not isinstance(data["list"], list):
            raise QueryUnavailable("个人申请清单的页码或记录未能核实")
        for row in data["list"]:
            case_id = row.get("id")
            if not case_id or not isinstance(row.get("app"), dict) or not row["app"].get("id"):
                raise QueryUnavailable("个人申请缺少可核对的事项或办件编号")
            seen.add(str(case_id))
            if str(row["app"]["id"]) == app_id:
                matches.add(str(case_id))
        total = int(data["total"])
        if number >= math.ceil(total / int(data["perpage"])):
            if len(seen) != total:
                raise QueryUnavailable("个人申请条数与校方总数不符")
            return matches
        number += 1
        with page.expect_response(is_list) as listing:
            page.locator(".n-pagination").get_by_text(str(number), exact=True).click()
