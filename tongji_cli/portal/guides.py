import re
from urllib.parse import urlsplit

from playwright.sync_api import Error, expect, sync_playwright

from tongji_cli.browser_session import open_session
from tongji_cli.common import QueryUnavailable


GUIDE = "https://gs.tongji.edu.cn/info/1092/4089.htm"
PRINT_GUIDE = "https://am.tongji.edu.cn/info/1538/4621.htm"
PORTAL = "https://all.tongji.edu.cn/"
DIRECTORY = "https://txd.tongji.edu.cn/newservice/fe/site/service"


def service_find(page, keyword):
    if not keyword:
        raise QueryUnavailable("请输入办事事项或关键词")
    page.goto(GUIDE, wait_until="commit")
    paragraphs = page.locator("#vsb_content p")
    paragraphs.first.wait_for(state="attached")
    sections = []
    for paragraph in paragraphs.all_inner_texts():
        text = paragraph.strip()
        heading = re.fullmatch(r"[一二三四五六七八九十]+、(.+)", text)
        if heading:
            sections.append({"title": heading[1], "audience": "研究生", "source": GUIDE, "notes": []})
        elif sections and text.startswith("操作流程"):
            sections[-1]["steps"] = re.sub(r"^操作流程[：:]\s*", "", text)
            sections[-1]["url"] = PORTAL if "all.tongji.edu.cn" in text else GUIDE
        elif sections and (text.startswith("注意事项") or re.match(r"^\d+、", text)):
            note = text.removeprefix("注意事项：").strip()
            if note:
                sections[-1]["notes"].append(note)
    if not sections or any("steps" not in section for section in sections):
        raise QueryUnavailable(f"研究生自助服务指南的事项格式待核实：{GUIDE}")
    matches = [s for s in sections if keyword in s["title"] or keyword in s["steps"]]
    paper_title = "在读证明、中英文成绩单（纸质版打印）"
    page.goto(PRINT_GUIDE, wait_until="commit")
    article = page.locator(".v_news_content").inner_text()
    paper = article.split("【纸质版打印】", 1)[-1].split("【电子版下载】", 1)[0]
    if keyword in paper_title or keyword in paper:
        materials = re.search(r"所需材料[：:]([^\n]+)", paper)
        location = re.search(r"办理地点[：:]([^\n]+)", paper)
        if not materials or not location:
            raise QueryUnavailable(f"纸质版办理指南格式待核实：{PRINT_GUIDE}")
        matches.append({"title": paper_title, "audience": "本科生、研究生", "source": PRINT_GUIDE,
                        "url": PRINT_GUIDE, "materials": materials[1].strip(), "steps": location[1].strip(),
                        "notes": [s for s in paper.partition("备注：")[2].splitlines() if s.strip()]})
    return matches + directory_services(page, keyword)


def directory_services(page, keyword):
    page.goto(DIRECTORY, wait_until="commit")
    rows = page.locator("table:visible tbody tr")
    page.get_by_text("服务事项名称", exact=True).first.wait_for()
    rows.first.locator("td:nth-child(2)").wait_for()
    number = 1
    matches = []
    while True:
        for row in rows.all():
            cells = row.locator("td").all_inner_texts()
            if keyword not in " ".join(cells[:3]):
                continue
            title, department, category = [value.strip() for value in cells[:3]]
            result = {"title": title, "department": department, "category": category, "url": DIRECTORY,
                      "steps": f"进入同心搭服务大厅，选择“{title}”", "source": DIRECTORY}
            guide = row.get_by_text("办事指南", exact=True)
            if guide.count():
                with page.expect_popup() as opened:
                    guide.click()
                detail = opened.value
                try:
                    detail.get_by_text(re.compile(r"信息更新时间[：:]\s*\d{4}")).first.wait_for()
                    result["url"] = detail.url
                    body = detail.locator("body").inner_text()
                    instructions = body.partition("申请说明")[2].partition("办事流程")[0].strip()
                    if instructions and instructions != "暂无说明":
                        result["guide"] = instructions
                finally:
                    detail.close()
            matches.append(result)
        number += 1
        next_page = page.locator(".n-pagination").get_by_text(str(number), exact=True)
        if not next_page.count():
            return matches
        first_title = rows.first.locator("td").first.inner_text()
        next_page.click()
        page.wait_for_function("""old => {
            const first = document.querySelector('table tbody tr td');
            return first && first.innerText.trim() && first.innerText.trim() !== old.trim();
        }""", arg=first_title)


def service_results(args, profile):
    keyword = args.query.strip()
    if not keyword:
        raise QueryUnavailable("请输入办事事项或关键词")
    items = []
    sources = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            page = browser.new_page()
            page.set_default_timeout(16000)
            items.extend(service_find(page, keyword))
        sources["public"] = "ok"
    except (QueryUnavailable, Error, AssertionError):
        sources["public"] = "unverified"

    sources["portal"] = "login_required"
    if profile.exists():
        try:
            with sync_playwright() as pw:
                context = open_session(pw, profile)
                try:
                    page = context.new_page()
                    try:
                        page.set_default_timeout(16000)
                        sources["portal"] = portal_services(page, keyword, items)
                    finally:
                        page.close()
                finally:
                    context.close()
        except Error:
            sources["portal"] = "unverified"
    if all(status == "ok" for status in sources.values()):
        return {"status": "ok", "items": items, "sources": sources}
    missing = "、".join(f"{source}={state}" for source, state in sources.items() if state != "ok")
    return {"status": "partial" if "ok" in sources.values() or items else "unverified",
            "items": items, "sources": sources, "detail": f"部分来源无法核实：{missing}"}


def search_portal(page, keyword):
    page.goto(PORTAL, wait_until="commit")
    frame = page.frame_locator('iframe[src*="CUS_TEMPLATE_TONGJI"]')
    search = frame.locator('#stepThree input[placeholder*="事项"]')
    try:
        search.wait_for()
    except Error:
        if urlsplit(page.url).hostname == "iam.tongji.edu.cn":
            return None
        raise

    search.click()
    # 首页点击搜索框后，门户用另一个输入框接收检索词。
    active = frame.locator('.tj-hide-box-wrap input[placeholder*="事项"]:visible')
    active.fill(keyword)
    active.press("Enter")
    page.wait_for_url(re.compile(r"#/search(?:[?/]|$)"))
    results = frame.locator(".cus-ser-wrap")
    cards = results.locator(".matter-item:visible")
    empty = results.get_by_text("未找到相关数据", exact=True).filter(visible=True)
    cards.first.or_(empty).first.wait_for()
    return frame, results, cards


def portal_services(page, keyword, items):
    search = search_portal(page, keyword)
    if search is None:
        return "login_required"
    frame, results, cards = search
    if not cards.count():
        return "ok"

    while True:
        for card in cards.all():
            title = card.locator(".item-name").inner_text()
            record = {"title": title, "source": PORTAL, "url": PORTAL,
                      "steps": f"登录一网通办，搜索“{keyword}”，选择“{title}”"}
            items.append(record)
            record.update(portal_guide(frame, card, title))
        if not next_portal_page(results, cards):
            return "ok"


def portal_guide(frame, card, title):
    guide = card.get_by_text("办事指南", exact=True)
    if not guide.is_visible():
        return {}
    record = {}
    guide.click()
    dialog = frame.locator(".detail-dialog:visible")
    detail = dialog.locator(".itemdetails")
    detail.get_by_text(title, exact=True).filter(visible=True).first.wait_for()
    values = detail.locator(".tb_list:visible").evaluate_all("""rows =>
        Object.fromEntries(rows.map(row => [row.querySelector('.tb_label').innerText.trim(),
            row.querySelector('.tb_text').innerText.trim()]))""")
    for label, field in (("责任部门", "department"), ("服务对象", "audience"), ("办理方式", "method"),
                         ("办理时限", "processing_time")):
        if values.get(label):
            record[field] = values[label]
    sections = detail.locator(".title1:visible").evaluate_all("""headers =>
        Object.fromEntries(headers.filter(h => h.innerText.trim() !== '基本信息').map(h =>
            [h.innerText.trim(), h.nextElementSibling?.innerText.trim() || '']))""")
    if sections:
        record["guide"] = {heading: body for heading, body in sections.items() if body}
    dialog.locator(".we-dialog__headerbtn:visible").first.click()
    dialog.wait_for(state="hidden")
    return record


def next_portal_page(results, cards):
    next_button = results.locator(".we-pagination .btn-next:visible")
    if not next_button.count() or next_button.is_disabled():
        return False
    active = results.locator(".we-pager .active:visible")
    previous = active.inner_text()
    next_button.click()
    expect(active).not_to_have_text(previous)
    # 相邻页可能完全同名，门户切换页码后仍有后台统计请求。
    results.locator(".we-loading-mask:visible").first.wait_for(state="hidden")
    cards.first.locator(".item-name").filter(has_text=re.compile(r"\S")).wait_for()
    return True
