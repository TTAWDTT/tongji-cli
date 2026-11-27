import hashlib
import re
import webbrowser
from datetime import date
from urllib.parse import quote, urlsplit

from playwright.sync_api import Error, expect, sync_playwright

from browser_session import open_session
from queries import QueryUnavailable

LIB_HOURS = "https://www.lib.tongji.edu.cn/index.php?classid=11974"
CATALOG = "https://findtongji.libsp.cn/#/searchListExternal/01/{}/01"
SEATS = "https://space.tongji.edu.cn/"
GUIDE = "https://gs.tongji.edu.cn/info/1092/4089.htm"
PRINT_GUIDE = "https://am.tongji.edu.cn/info/1538/4621.htm"
PORTAL = "https://all.tongji.edu.cn/"
DIRECTORY = "https://txd.tongji.edu.cn/newservice/fe/site/service"


def configure(commands):
    library = commands.add_parser("library", help="图书馆开放时间、馆藏目录和空间预约")
    subs = library.add_subparsers(dest="operation", required=True)
    loans = subs.add_parser("loans", help="本人当前在借或历史借阅的图书和现刊")
    loans.add_argument("--history", action="store_true", help="查询馆方借阅历史和实还日期")
    renew = subs.add_parser("renew", help="按条码续借一本当前在借图书")
    renew.add_argument("barcode", help="本人当前在借图书的条码号，保留前导零")
    renew.add_argument("--due", type=date.fromisoformat, required=True, help="续借前的应还日期 YYYY-MM-DD")
    renew.add_argument("--preview", action="store_true", help="核对在借图书和原应还日期，不提交")
    records = subs.add_parser("reservations", help="查看本人图书馆空间预约记录")
    records.add_argument("--kind", choices=["seat", "room", "research"], default="seat")
    records.add_argument("--limit", type=int, default=10, help="从最新一条起最多读取的记录数")
    hours = subs.add_parser("hours", help="按馆区查看公布的常规开放时间")
    hours.add_argument("campus", nargs="?", default="", help="例如四平、嘉定、沪北")
    search = subs.add_parser("search", help="在官方馆藏目录中分页检索")
    search.add_argument("book", help="书名或检索词")
    search.add_argument("--page", type=int, default=1, help="馆藏目录页码")
    holdings = subs.add_parser("holdings", help="按书目 ID 查询逐册馆藏和各馆藏地的可借复本")
    holdings.add_argument("id", type=int, help="library search 返回的纸本书目 ID")
    seats = subs.add_parser("seats", help="打开官方空间预约")
    seat_actions = seats.add_subparsers(dest="action", required=True)
    seat_actions.add_parser("open", help="在浏览器打开预约入口")
    for name, help_text in (("availability", "查询馆舍、楼层或区域的余座"), ("list", "查看指定区域的座位列表"),
                            ("reserve", "预约指定日期、时段和座位，或仅预览")):
        action = seat_actions.add_parser(name, help=help_text)
        action.add_argument("--date", type=date.fromisoformat, required=name == "reserve", help="馆方可选日期 YYYY-MM-DD")
        action.add_argument("--branch", required=name != "availability", help="馆舍全名")
        action.add_argument("--floor", required=name != "availability", help="馆方显示的楼层名")
        if name != "availability":
            action.add_argument("--area", required=True, help="馆方显示的区域名")
            action.add_argument("--time", dest="time_slot", required=name == "reserve", help="馆方显示的时段，如 08:00-22:00")
        if name == "reserve":
            action.add_argument("--seat", required=True, help="列表中的完整座位号，保留前导零")
            action.add_argument("--preview", action="store_true", help="只选中并核对目标座位")
    rooms = subs.add_parser("rooms", help="查图书馆研习室、研讨室和其他预约空间的目录")
    room_actions = rooms.add_subparsers(dest="action", required=True)
    room_actions.add_parser("dates", help="查馆方当前列出的预约日期")
    spaces = room_actions.add_parser("list", help="列出所选日期的预约空间，可按馆舍、楼层和空间类型筛选")
    spaces.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD，默认馆方当前选中日期")
    spaces.add_argument("--branch", help="馆舍全名")
    spaces.add_argument("--floor", help="楼层全名")
    spaces.add_argument("--type", dest="room_type", help="馆方目录中的空间类型")
    receipts = room_actions.add_parser("receipts", help="查本人研习空间的回执编号、申请主题和办理状态")
    select = receipts.add_mutually_exclusive_group()
    select.add_argument("--id", dest="receipt_id", help="在全部本人记录中按完整回执编号查一件")
    select.add_argument("--limit", type=int, default=10, help="从最新一件起最多显示的记录数，默认 10")
    slots = room_actions.add_parser("slots", help="查看指定空间的开放时间、已占和空档")
    reserve = room_actions.add_parser("reserve", help="选择空间和时段，预览申请或由本人办理")
    for action in (slots, reserve):
        action.add_argument("room_id", metavar="空间编号", help="library rooms list 返回的房间编号")
        action.add_argument("--date", type=date.fromisoformat, required=action is reserve,
                            help="YYYY-MM-DD，查询省略时列出这个房间时段页提供的全部日期")
    reserve.add_argument("--time", dest="time_slot", required=True, help="起止时刻，例如 12:00-13:00")
    reserve.add_argument("--topic", help="馆方列出的申请主题全名，预览可查看选项")
    reserve.add_argument("--purpose", help="填入研习室的申请内容")
    reserve.add_argument("--preview", action="store_true", help="打开并核对所选房间的申请表")
    study = subs.add_parser("study", help="按馆方周期查询或预约研修座位、考研座位")
    actions = study.add_subparsers(dest="action", required=True)
    for name in ("availability", "list", "reserve"):
        sub = actions.add_parser(name)
        sub.add_argument("--type", dest="study_type", choices=["research", "exam"], default="research",
                         help="research 为研修座位，exam 为考研座位")
        sub.add_argument("--branch", required=name != "availability", help="馆舍全名")
        sub.add_argument("--floor", required=name != "availability", help="馆方显示的楼层名")
        if name != "availability":
            sub.add_argument("--area", required=True, help="馆方显示的区域名")
            sub.add_argument("--period", choices=["current", "next"], required=name == "reserve", default="current",
                             help="current 为本期，next 为下期，具体起止日期见馆方")
        if name == "reserve":
            sub.add_argument("--seat", required=True, help="该期列表中的完整座位号")
            sub.add_argument("--preview", action="store_true", help="只选中目标座位，查看期限、权限和预约按钮")
    service = commands.add_parser("service", help="查找一网通办和学校公开的办事指南")
    operations = service.add_subparsers(dest="operation", required=True)
    apply = operations.add_parser("apply", help="按事项全名进入校方办理页面，办理后核对新增办件")
    apply.add_argument("title", metavar="完整事项名称")
    apply.add_argument("--source", choices=["txd", "portal"], default="txd", help="txd 为同心搭，portal 为旧版一网通办")
    apply.add_argument("--template", metavar="模板全名", help="旧门户学生电子证明中的指定模板")
    apply.add_argument("--preview", action="store_true", help="核对事项及表单入口")
    applications = operations.add_parser("applications", help="一网通办中我发起的办件与进度")
    certificates = operations.add_parser("certificates", help="查看电子证明中心的本人已完成文件记录")
    certificates.add_argument("--template", metavar="模板全名", help="只看由该模板签发的已完成文件记录")
    certificate = operations.add_parser("certificate", help="读取已完成的电子证明").add_subparsers(dest="action", required=True)
    download = certificate.add_parser("download", help="从订单详情再次下载已签发的 PDF")
    download.add_argument("receipt", metavar="订单号", help="service certificates 返回的 receipt")
    download.add_argument("--output", help="保存到新的本地 PDF 文件路径")
    download.add_argument("--preview", action="store_true", help="仅核对订单和再次下载入口")
    applications.add_argument("--with-flow", action="store_true", help="同时查看每件申请的流转记录")
    tasks = operations.add_parser("tasks", help="本人待办、已办任务")
    tasks.add_argument("--state", choices=["pending", "processed"], help="只查待办或已办")
    forms = operations.add_parser("forms", help="按标题搜索研究生院常用下载的表格和指南")
    forms.add_argument("keyword", nargs="?", default="", help="省略关键词列出全部")
    form = operations.add_parser("form", help="读一项研究生院材料的说明和附件链接")
    form.add_argument("url", help="service forms 返回的原文链接")
    form.add_argument("--attachment", help="需下载的完整附件名称，与 --output 一起使用")
    form.add_argument("--output", help="另存到新的文件路径")
    find = operations.add_parser("find")
    find.add_argument("query", help="事项名或关键词，例如在读证明")


def run(args):
    if args.operation == "seats":
        if not webbrowser.open(SEATS, new=2):
            raise QueryUnavailable(f"未能打开默认浏览器，请访问 {SEATS}")
        return [{"title": "同济大学图书馆空间预约", "url": SEATS, "action": "opened"}]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            page = browser.new_page()
            page.set_default_timeout(16000)
            if args.operation == "hours":
                return library_hours(page, args.campus.strip())
            if args.operation == "holdings":
                from catalog_holdings import holdings
                return holdings(page, args.id)
            if args.operation == "search":
                return catalog_search(page, args.book.strip(), args.page)
            return service_find(page, args.query.strip())
    except (Error, AssertionError) as exc:
        raise QueryUnavailable("官方页面未能加载可核实的结果，请稍后重试") from exc


def library_hours(page, campus):
    page.goto(LIB_HOURS, wait_until="commit")
    links = page.locator("#content li a")
    links.first.wait_for()
    branches = links.evaluate_all("ls => ls.map(a => [a.innerText.trim(), a.href])")
    results = []
    for branch, url in branches:
        if campus not in branch:
            continue
        page.goto(url, wait_until="commit")
        content = page.locator(".inner-main div#content")
        lines = content.inner_text().splitlines()
        hours = [cell.strip() for line in lines for cell in line.split("\t")
                 if re.search(r"\d{1,2}[:：]\d{2}|24\s*小时开放", cell)]
        row = {"branch": branch, "hours": list(dict.fromkeys(hours)), "url": url}
        schedule = content.locator("table").evaluate_all("""tables => tables.flatMap(table => {
            const [header, ...rows] = table.rows;
            const labels = Array.from(header.cells, cell => cell.innerText.trim());
            if (!labels.includes("开放时间")) return [];
            return rows.map(tr => Object.fromEntries(Array.from(tr.cells,
                (cell, i) => [labels[i], cell.innerText.trim()])));
        })""")
        if schedule:
            row["areas"] = schedule
            row["hours"] = [area["开放时间"] for area in schedule]
        if not row["hours"]:
            poster = content.locator("img[alt*='开放时间']").first
            if not poster.count():
                raise QueryUnavailable(f"{branch}的开放时间格式待核实：{url}")
            image_url = poster.evaluate("img => img.src")
            image = page.request.get(image_url, timeout=10000)
            # 嘉定馆只发布图片。图片变化后，此处核对的时刻随之失效。
            if not image.ok or hashlib.sha256(image.body()).hexdigest() != "1e70a3ea6b22b9be864a6163f424f2029047b1a1b38b1a373cac3435a9edcd31":
                raise QueryUnavailable(f"{branch}的官方时刻图待核实：{image_url}")
            row.update(hours=["周一至周日 7:30–22:30", "一楼学术交流区和休闲交流区 24 小时开放"], poster=image_url)
        results.append(row)
    return results


def catalog_search(page, keyword, number):
    if not keyword:
        raise QueryUnavailable("请输入馆藏检索词")
    if number < 1:
        raise QueryUnavailable("页码必须大于零")
    url = CATALOG.format(quote(keyword, safe=""))
    page.goto(url, wait_until="commit")
    titles = page.locator("a[class*='infotit'][href]")
    empty = page.get_by_text("未找到匹配的结果", exact=True)
    titles.first.or_(empty).first.wait_for()
    if empty.is_visible():
        return []
    if number > 1:
        jump = page.locator(".ant-pagination-options-quick-jumper input").first
        if not jump.count():
            return []
        total = page.get_by_text(re.compile(r"^共\s*\d+\s*条$")).first.inner_text()
        count = int(re.search(r"\d+", total)[0])
        if (number - 1) * titles.count() >= count:
            return []
        first_url = titles.first.get_attribute("href")
        jump.fill(str(number))
        jump.press("Enter")
        page.wait_for_function("""previous =>
            document.querySelector("a[class*='infotit'][href]")?.getAttribute('href') !== previous
            && !!document.querySelector("a[class*='infotit'][href]")""", arg=first_url)
    return titles.evaluate_all(r"""links => links.map(link => {
        const card = link.closest("div[class*='content___']");
        const fields = card.querySelectorAll("[class*='modeInfo'] > span[title]");
        const book = link.hash.match(/^#\/searchList\/bookDetails\/(\d+)$/);
        return {
            ...(book ? {id: Number(book[1])} : {}),
            title: link.innerText.replace(/^\d+\.\s*/, '').trim(),
            bibliography: Array.from(fields, field => field.title),
            url: link.href,
            search_url: location.href
        };
    })""")


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
        items.extend(run(args))
        sources["public"] = "ok"
    except QueryUnavailable:
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
