import re
import sys
from urllib.parse import urlsplit

from playwright.sync_api import Error, expect, sync_playwright

from tongji_cli.browser_session import open_session
from tongji_cli.portal.guides import PORTAL, next_portal_page, portal_guide, search_portal
from tongji_cli.common import QueryUnavailable


LOGIN = {"status": "login_required", "detail": "请运行 ./tongji login --site service 完成学校统一身份认证。"}


CERTIFICATES = "学生电子证明文件"
CENTER = "zzfw.tongji.edu.cn"
ORDER_LIST = "/wec-self-print-app-console/order/listByPage"
TEMPLATE_LIST = "/wec-self-print-app-console/item/sp-print-item/list/terminal"


def apply(profile, title, preview=False, template=None):
    return run(profile, title, preview, template, certificate_query=None)


def certificates(profile, template=None):
    return run(profile, CERTIFICATES, True, template, certificate_query=certificate_history)


def run(profile, title, preview, template, certificate_query):
    title = title.strip()
    if not title:
        raise QueryUnavailable("请输入 service find 返回的完整事项名称")
    if template is not None:
        template = template.strip()
        if not template or title != CERTIFICATES:
            raise QueryUnavailable("--template 适用于学生电子证明文件，请输入完整模板名")
    if not profile.exists():
        return LOGIN
    if not preview and not sys.stdin.isatty():
        raise QueryUnavailable("请在交互终端使用办理页，或加 --preview 查看事项")
    with sync_playwright() as pw:
        context = open_session(pw, profile, interactive=not preview)
        try:
            return apply_in_session(context, title, preview, template, certificate_query)
        finally:
            context.close()


def exact_card(page, search, title):
    frame, results, cards = search
    label = frame.locator(".item-name").filter(has_text=re.compile(rf"^\s*{re.escape(title)}\s*$"))
    position = 1
    found = []
    while cards.count():
        found.extend([position] * cards.filter(has=label).count())
        if not next_portal_page(results, cards):
            break
        position += 1
    if len(found) != 1:
        raise QueryUnavailable(f"旧门户搜索结果中有 {len(found)} 项与完整名称相同，请用 service find 核对")
    if found[0] != position:
        search = search_portal(page, title)
        if search is None:
            return None
        frame, results, cards = search
        for _ in range(1, found[0]):
            if not next_portal_page(results, cards):
                raise QueryUnavailable("门户检索结果已变化，请重新检索")
    selected = cards.filter(has=label)
    expect(selected).to_have_count(1)
    return selected


def apply_in_session(context, title, preview=True, template=None, certificate_query=None, confirm=None):
    page = context.new_page()
    page.set_default_timeout(16000)
    try:
        search = search_portal(page, title)
        if search is None:
            return LOGIN
        card = exact_card(page, search, title)
        if card is None:
            return LOGIN
        item = {"title": title, "source": PORTAL}
        action = card.get_by_text("在线办理", exact=True)
        if not action.is_visible():
            if certificate_query:
                raise QueryUnavailable("旧门户未列出电子证明中心的在线入口，无法读取已完成文件")
            has_guide = card.get_by_text("办事指南", exact=True).is_visible()
            item["state"] = "guide_only" if has_guide else "no_online_entry"
            if has_guide:
                item.update(portal_guide(search[0], card, title))
            return {"status": "ok", "items": [item], "detail": "该事项卡片未列出在线办理入口。"
                    + ("已读取该事项的办事指南。" if has_guide else "")}
        with page.expect_popup() as opened:
            action.click()
        dest = opened.value
        try:
            dest.set_default_timeout(16000)
            dest.wait_for_load_state("domcontentloaded")
            return destination_result(dest, item, preview, template, certificate_query, confirm)
        finally:
            dest.close()
    except (Error, AssertionError, ValueError, KeyError, TypeError):
        return {"status": "unverified", "detail": "已检索旧门户，未能核实唯一的办理入口及目标页面。"}
    finally:
        page.close()


def destination_result(page, item, preview, template, certificate_query, confirm):
    host = urlsplit(page.url).hostname
    if item["title"] == CERTIFICATES and host == CENTER:
        return certificate_center(page, item, preview, template, certificate_query, confirm)
    if host == "iam.tongji.edu.cn":
        return LOGIN
    if host == "tj91.tongji.edu.cn" and urlsplit(page.url).path == "/login_tzdl.jsp":
        expect(page).to_have_title("同济大学学生就业信息网")
        return {"status": "login_required", "items": [dict(item, state="destination_login", destination=host)],
                "detail": "就业信息网打开了本系统的登录页。"}
    if item["title"] == "学生班车查询" and host == "jiading.tongji.edu.cn":
        expect(page).to_have_title("学生班车时刻表")
        return {"status": "ok", "items": [dict(item, state="public_schedule", destination=host)],
                "detail": "已打开嘉定校区管委办的学生班车时刻表。可用 bus 命令查询。"}
    return {"status": "unverified", "items": [dict(item, state="destination_unverified", destination=host)],
            "detail": "已从门户进入事项链接，目标页面上的同名表单及办件回执尚未核实。"}


def certificate_center(page, item, preview, template, certificate_query, confirm):
    expect(page).to_have_title("自助打印PC端")
    page.get_by_text("电子证明中心", exact=True).filter(visible=True).first.wait_for()
    if certificate_query:
        return certificate_query(page, template)
    landing = page.url
    completed = order_rows(page, "已完成文件")
    templates, selected_page, template_id = template_names(page, template)
    if template and templates.count(template) != 1:
        raise QueryUnavailable(f"电子证明中心有 {templates.count(template)} 个同名模板，请核对完整名称")
    item = dict(item, state="template_list", templates=templates, completed_count=len(completed), destination=CENTER)
    if template:
        item.update(template=template, state="template_preview")
    if preview or not template:
        return {"status": "ok", "items": [item], "detail": "已核对校方可选证明模板和本人已完成文件数量。"}
    pending = order_rows(page, "未完成文件")
    existing = {key for key, _, _, _ in completed + pending}
    history = page.context.new_page()
    try:
        history.goto(landing, wait_until="domcontentloaded")
        with page.expect_response(source_path(TEMPLATE_LIST)):
            page.locator(".header-menu").filter(has_text=re.compile(r"^\s*证明文件\s*$")).click()
        for _ in range(1, selected_page):
            with page.expect_response(source_path(TEMPLATE_LIST)):
                page.locator(".ivu-page-next:visible").click()
        page.locator(".itemNameClass:visible").filter(
            has_text=re.compile(rf"^\s*{re.escape(template)}\s*$")).scroll_into_view_if_needed()
        page.bring_to_front()
        (confirm or confirm_certificate)(template)
        # 独立页保留本人办理前的校方会话，核对时重新进入已完成文件。
        rows = order_rows(history, "已完成文件")
        new = [key for key, name, identifier, _ in rows
               if key not in existing and name == template and identifier == template_id]
        if len(new) != 1:
            return {"status": "unverified", "detail": "已完成文件中未找到唯一新增的同名证明。可用 service certificates 核对。"}
        return {"status": "ok", "items": [dict(item, state="completed", receipt=new[0])],
                "detail": "已在校方已完成文件中核对同名证明的新订单号。"}
    finally:
        history.close()


def certificate_history(page, template):
    rows = order_rows(page, "已完成文件")
    return {"status": "ok", "items": [dict(fields, receipt=key, template=name)
                                      for key, name, _, fields in rows if not template or name == template],
            "source": CENTER}


def confirm_certificate(template):
    print(f"请在电子证明中心选择《{template}》，核对领取方式并自行办理。结束后回到终端按回车核对结果。",
          file=sys.stderr, flush=True)
    try:
        input()
    except EOFError:
        raise QueryUnavailable("终端输入已结束，请用 service certificates 查看已完成文件。") from None


def source_path(path):
    return lambda response: urlsplit(response.url).hostname == CENTER and urlsplit(response.url).path == path


def template_names(page, selected):
    with page.expect_response(source_path(TEMPLATE_LIST)) as response:
        page.locator(".header-menu").filter(has_text=re.compile(r"^\s*证明文件\s*$")).click()
    expect(page.locator(".header-menu.ivu-menu-item-active")).to_have_text(re.compile(r"^\s*证明文件\s*$"))
    names = []
    selected_page = template_id = None
    page_number = 1
    pager = page.locator(".ivu-page:visible")
    cards = page.locator(".itemNameClass:visible")
    while True:
        reply = response.value
        payload = reply.json()
        data = payload.get("data", {})
        if (not reply.ok or payload.get("code") != "0000" or int(data["current"]) != page_number
                or not isinstance(data.get("records"), list)):
            raise QueryUnavailable("电子证明模板列表未核实")
        total = int(data["total"])
        expect(pager.locator(".ivu-page-total")).to_have_text(re.compile(rf"共\s*{total}\s*条"))
        visible = [record["name"] for record in data["records"]]
        expect(cards).to_have_text(visible, use_inner_text=True)
        names.extend(visible)
        if selected in visible:
            selected_page = page_number
            template_id = str(data["records"][visible.index(selected)]["id"])
        if page_number >= int(data["pages"]):
            if len(names) != total or any(not name for name in names):
                raise QueryUnavailable("可见模板数量与校方总数不符")
            return names, selected_page, template_id
        with page.expect_response(source_path(TEMPLATE_LIST)) as response:
            pager.locator(".ivu-page-next").click()
        page_number += 1


def order_rows(page, tab):
    results = []
    for total, rows in order_pages(page, tab):
        results.extend(rows)
    if len({key for key, _, _, _ in results}) != total or len(results) != total:
        raise QueryUnavailable("电子证明订单数量与校方总数不符")
    return results


def order_pages(page, tab):
    selector = page.locator(".header-menu").filter(has_text=re.compile(rf"^\s*{tab}\s*$"))
    with page.expect_response(source_path(ORDER_LIST)) as response:
        selector.click()
    expect(page.locator(".header-menu.ivu-menu-item-active")).to_have_text(re.compile(rf"^\s*{tab}\s*$"))
    page_number = 1
    while True:
        reply = response.value
        data = reply.json()
        if not reply.ok or data.get("pageNumber") != page_number or not isinstance(data.get("rows"), list):
            raise QueryUnavailable("电子证明订单页码或记录未核实")
        total = int(data["total"])
        expect(page.locator(".ivu-page-total:visible")).to_have_text(re.compile(rf"共\s*{total}\s*条"))
        yield total, visible_orders(page, data["rows"], tab)
        if page_number >= int(data["lastPageNumber"]):
            return
        with page.expect_response(source_path(ORDER_LIST)) as response:
            page.locator(".ivu-page-next:visible").click()
        page_number += 1


def visible_orders(page, rows, tab):
    if not rows:
        page.get_by_text("暂无数据", exact=True).filter(visible=True).first.wait_for()
        return []
    titles = [text.strip() for text in page.locator("table:visible th").all_inner_texts()]
    if "文件名称" not in titles or (tab == "已完成文件" and "打印完成时间" not in titles):
        raise QueryUnavailable("电子证明记录缺少文件名称或完成时间")
    visible = page.locator("table:visible tbody tr:visible")
    expect(visible).to_have_count(len(rows))
    results = []
    for index, record in enumerate(rows):
        number, name = record.get("orderId"), record.get("itemName")
        if not number or not name or not record.get("itemId") or (tab == "已完成文件" and not record.get("completeTime")):
            raise QueryUnavailable("电子证明记录缺少可核对的编号、模板或完成时间")
        cells = visible.nth(index).locator("td")
        expect(cells.nth(titles.index("文件名称"))).to_have_text(record["title"], use_inner_text=True)
        values = [text.strip() for text in cells.all_inner_texts()]
        if len(values) != len(titles):
            raise QueryUnavailable("电子证明表头和记录列数不一致")
        fields = {k: v for k, v in zip(titles, values) if k and k != "操作"}
        results.append((str(number), name, str(record["itemId"]), fields))
    return results
