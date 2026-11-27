import os
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from datetime import date
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import Error, sync_playwright

from tongji_cli.common import QueryUnavailable


SOURCES = {
    "jiading": ("嘉定校区管委办", "https://jiading.tongji.edu.cn/rctz/list.htm"),
    "sports": ("体育部", "https://sports.tongji.edu.cn/tztg.htm"),
    "graduate": ("研究生院", "https://gs.tongji.edu.cn/tzgg.htm"),
    "undergraduate": ("本科生院", "https://bksy.tongji.edu.cn/30359/list.htm"),
    "library": ("图书馆", "https://www.lib.tongji.edu.cn/index.php?classid=11979"),
}
DIRECTORIES = {**SOURCES, "graduate-forms": ("研究生院常用下载", "https://gs.tongji.edu.cn/ggfw/cyxz.htm")}
ROWS = {
    "jiading": (".wp_article_list_table li", "a[title]", "span"),
    "sports": (".list_style_1 li", "a", "span"),
    "graduate": (".list_list li", "a[title]", ".listriqi"),
    "undergraduate": (".wcts-a0018 li", "a", ".li-data"),
    "library": ("#content .news dl", ".title a", ".input_time"),
}


ROWS["graduate-forms"] = ROWS["graduate"]

ARTICLE_URLS = {
    "jiading": r"https://jiading\.tongji\.edu\.cn/[0-9a-f]{2}/[0-9a-f]{2}/c5453a[0-9]+/page\.htm",
    "graduate-forms": r"https://gs\.tongji\.edu\.cn/info/1096/[0-9]+\.htm",
    "sports": r"https://sports\.tongji\.edu\.cn/info/1049/[0-9]+\.htm",
    "graduate": r"https://gs\.tongji\.edu\.cn/info/1092/[0-9]+\.htm",
    "undergraduate": r"https://bksy\.tongji\.edu\.cn/[0-9a-f]{2}/[0-9a-f]{2}/c30359a[0-9]+/page\.(?:htm|psp)",
    "library": r"https://www\.lib\.tongji\.edu\.cn/index\.php\?classid=11979&newsid=[0-9]+&t=show",
}
ARTICLE_PARTS = {
    "jiading": ('[frag="窗口603"] .title', ".info .release_time", ".wp_articlecontent"),
    "sports": ("h2.title_3", ".date_1", ".v_news_content"),
    "graduate": ('form[name="_newscontent_fromname"] h1', "h1 + div", ".v_news_content"),
    "undergraduate": (".view-title", ".view-info", ".wp_articlecontent"),
    "library": (".news_title", ".news_info", ".news_content"),
}
ARTICLE_PARTS["graduate-forms"] = ARTICLE_PARTS["graduate"]


def configure(commands):
    notices = commands.add_parser("notices", help="校园部门和嘉定校区的公开通知")
    operations = notices.add_subparsers(dest="operation", required=True)
    listing = operations.add_parser("list", help="按来源页码列出公开通知")
    search = operations.add_parser("search", help="按标题关键词检索指定范围的通知")
    show = operations.add_parser("show", help="按列表中的校方原文链接读取正文与附件地址")
    show.add_argument("url", help="通知列表返回的校方原文 URL")
    search.add_argument("keyword", help="标题关键词")
    search.add_argument("--pages", type=int, default=3, help="每个来源连续检索的页数（默认 3）")
    for parser in (listing, search):
        parser.add_argument("--source", choices=["all", *SOURCES], default="all", help="通知来源（默认全部）")
        parser.add_argument("--page", type=int, default=1, help="各来源的起始页码（默认 1）")


def run(args):
    entry = result(args)
    if entry["status"] != "ok":
        raise QueryUnavailable(entry["detail"])
    return entry["items"]


def result(args):
    if args.operation == "show":
        return {"status": "ok", "items": [show_notice(args.url)]}
    count = getattr(args, "pages", 1)
    keyword = getattr(args, "keyword", "").strip().casefold()
    if args.page < 1 or count < 1:
        raise QueryUnavailable("页码和检索页数必须大于零")
    if args.operation == "search" and not keyword:
        raise QueryUnavailable("请输入通知标题关键词")
    sources = SOURCES if args.source == "all" else [args.source]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        context = browser.new_context()
        context.set_default_timeout(12000)
        return read_sources(context, sources, args.page, count, keyword)


def read_sources(context, sources, start, count, keyword):
    items = []
    states = {}
    for source in sources:
        state, rows = read_source(context, source, start, count, keyword)
        states[source] = state
        items.extend(rows)
    entry = {"status": "ok", "items": sorted(items, key=lambda r: r["date"], reverse=True), "sources": states}
    errors = [f"{DIRECTORIES[key][0]}：{state['detail']}" for key, state in states.items() if "detail" in state]
    if errors:
        entry["status"] = "partial" if any(s["status"] != "unverified" for s in states.values()) else "unverified"
        entry["detail"] = "；".join(errors)
    return entry


def read_source(context, source, start, count, keyword):
    first_url = DIRECTORIES[source][1]
    state = {"status": "ok", "pages": []}
    items = []
    errors = []
    total = 1
    with context.new_page() as page:
        try:
            open_list(page, first_url)
            if count is None or start + count - 1 > 1:
                try:
                    total = page_count(page, source)
                except (Error, QueryUnavailable):
                    errors.append(f"后续页码待核实：{first_url}")
            if start == 1:
                items.extend(notice_rows(page, source, keyword))
                state["pages"].append(1)
        except (QueryUnavailable, Error) as exc:
            errors.append(page_error(1, first_url, exc))
    for number in range(max(start, 2), (total if count is None else min(start + count - 1, total)) + 1):
        if source in {"graduate", "graduate-forms"}:
            archive = first_url.rsplit("/", 1)[-1].removesuffix(".htm")
            url = urljoin(first_url, f"{archive}/{total - number + 1}.htm")
        elif source in {"undergraduate", "jiading"}:
            url = urljoin(first_url, f"list{number}.htm")
        else:
            url = f"{first_url}&page_11979={number}"
        with context.new_page() as page:
            try:
                open_list(page, url)
                items.extend(notice_rows(page, source, keyword))
                state["pages"].append(number)
            except (QueryUnavailable, Error) as exc:
                errors.append(page_error(number, url, exc))
    if errors:
        state.update(status="partial" if state["pages"] else "unverified", detail="；".join(errors))
    return state, items


def page_error(number, url, exc):
    detail = str(exc) if isinstance(exc, QueryUnavailable) else f"未能读取 {url}"
    return f"第 {number} 页：{detail}"


def notice_rows(page, source, keyword):
    label = DIRECTORIES[source][0]
    items = []
    row, link, published = ROWS[source]
    data = page.locator(row).evaluate_all("""(rows, [link, published]) => rows.map(row => {
        const a = row.querySelector(link);
        const text = selector => row.querySelector(selector)?.textContent.trim();
        const month = text('.li-data span');
        const date = month ? month.replace('.', '-') + '-' + text('.li-data p') : text(published);
        return [a?.title.trim() || text('.li-tt-title') || a?.textContent.trim(), date, a?.href];
    })""", [link, published])
    if not data:
        raise QueryUnavailable(f"{label}通知列表格式待核实：{page.url}")
    for title, published_on, url in data:
        if not title or not published_on or not url:
            raise QueryUnavailable(f"{label}通知缺少标题、日期或链接：{page.url}")
        try:
            day = date.fromisoformat(published_on)
        except ValueError:
            raise QueryUnavailable(f"{label}通知日期格式待核实：{page.url}") from None
        if source == "sports":
            title = title.removeprefix("·").strip()
        if keyword in title.casefold():
            items.append(dict(title=title, date=day.isoformat(), url=url, source=label, source_url=page.url))
    return items


def open_list(page, url):
    response = page.goto(url, wait_until="domcontentloaded")
    if not response or not response.ok:
        raise QueryUnavailable(f"校方通知列表加载失败：{url}")


def page_count(page, source):
    if source == "sports":
        return 1
    if source in {"undergraduate", "jiading"}:
        pager = ".wp_paging" if source == "jiading" else "#wp_pager"
        last = page.locator(pager).get_by_text("尾页", exact=True).locator("xpath=ancestor-or-self::a[1]").get_attribute("href")
        match = re.search(r"list(\d+)\.htm$", last or "")
    else:
        selector = '[id^="fanye"]' if source in {"graduate", "graduate-forms"} else ".pager"
        match = re.search(r"\b1\s*/\s*(\d+)", page.locator(selector).first.text_content())
    if not match:
        raise QueryUnavailable(f"通知总页数待核实：{page.url}")
    return int(match[1])


def article_source(url):
    for source, pattern in ARTICLE_URLS.items():
        if re.fullmatch(pattern, url):
            return source
    raise QueryUnavailable("请使用列表中的校方通知原文 URL。校外转载可通过列表所给链接直接阅读")


def show_notice(url):
    source = article_source(url)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page(java_script_enabled=False)
        # PDF 和图片有时构成整篇正文。仅读取通知 HTML，从其中提取文件地址。
        page.route("**/*", lambda route: route.abort())
        try:
            response = page.request.get(url, max_redirects=0, timeout=12000)
            if response.status in (301, 302, 307, 308):
                url = urljoin(url, response.headers.get("location", ""))
                if article_source(url) != source:
                    raise QueryUnavailable("校方通知原文的跳转地址待核实")
                response = page.request.get(url, max_redirects=0, timeout=12000)
            if not response.ok:
                raise QueryUnavailable(f"校方通知原文返回 HTTP {response.status}：{url}")
            page.set_content(response.text(), wait_until="domcontentloaded")
            return article_record(page, source, url)
        except Error as error:
            raise QueryUnavailable(f"未能读取校方通知：{url}") from error


def article_record(page, source, url):
    title, stamp, body = (page.locator(selector).first for selector in ARTICLE_PARTS[source])
    if not all(part.count() for part in (title, stamp, body)):
        raise QueryUnavailable(f"校方通知正文格式待核实：{url}")
    match = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})", stamp.inner_text())
    if not match:
        raise QueryUnavailable(f"校方通知发布日期待核实：{url}")
    published = date(*map(int, match.groups())).isoformat()
    text = "\n".join(line.strip() for line in body.inner_text().splitlines() if line.strip())
    resources = article_resources(page, body, url)
    if not text and not any(resources.values()):
        raise QueryUnavailable(f"校方通知正文为空：{url}")
    return dict(title=title.inner_text().strip(), date=published, body=text, url=url,
                source=DIRECTORIES[source][0], source_url=DIRECTORIES[source][1], **resources)


def article_resources(page, body, base):
    resources = {"attachments": [], "images": [], "links": []}
    urls = set()
    entries = body.locator("a[href], img[src], iframe[src], embed[src], object[data]").evaluate_all("""nodes =>
        nodes.map(node => [node.tagName, node.getAttribute('href') || node.getAttribute('orisrc') ||
            node.getAttribute('src') || node.getAttribute('data'), (node.innerText || node.alt || '').trim()])""")
    entries += page.locator('form[name="_newscontent_fromname"] li a[href*="download.jsp"]').evaluate_all(
        "nodes => nodes.map(a => ['ATTACHMENT', a.getAttribute('href'), a.innerText.trim()])")
    for script in body.locator("script").all_text_contents():
        for pdf in re.findall(r"""showVsbpdfIframe\(\s*["']([^"']+\.pdf)["']""", script, re.I):
            entries.append(("ATTACHMENT", pdf, "正文 PDF"))
    for tag, href, label in entries:
        url = urljoin(base, href)
        if urlsplit(url).scheme not in {"https", "http"} or url in urls or href.startswith("#"):
            continue
        urls.add(url)
        if tag == "IMG":
            kind = "images"
        elif tag == "ATTACHMENT" or re.search(r"\.(pdf|docx?|xlsx?|pptx?|zip|rar|7z)($|[?#])|/download\.jsp", url, re.I):
            kind = "attachments"
        else:
            kind = "links"
        resources[kind].append({"title": label or urlsplit(url).path.rsplit("/", 1)[-1], "url": url})
    return resources


def graduate_forms(args):
    if args.operation == "form":
        if article_source(args.url) != "graduate-forms":
            raise QueryUnavailable("请使用 service forms 列出的研究生院材料页链接")
        if bool(args.attachment) != bool(args.output):
            raise QueryUnavailable("请同时指定 --attachment 的完整附件名和 --output 的新文件路径")
        item = show_notice(args.url)
        if args.attachment:
            files = [entry for entry in item["attachments"] if entry["title"] == args.attachment]
            if len(files) != 1:
                raise QueryUnavailable("未匹配到唯一附件，请核对材料页列出的完整附件名")
            destination = Path(args.output).expanduser().absolute()
            if destination.exists() or not destination.parent.is_dir():
                raise QueryUnavailable("请选择已有目录中的新文件路径")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel="chrome", headless=False)
                try:
                    context = browser.new_context()
                    item = download_form(context, args.url, files[0], destination)
                finally:
                    browser.close()
        return {"status": "ok", "items": [item]}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        try:
            context = browser.new_context()
            context.set_default_timeout(12000)
            return read_sources(context, ["graduate-forms"], 1, None, args.keyword.strip().casefold())
        finally:
            browser.close()

def download_form(context, source, attachment, destination):
    downloads = []
    context.on("page", lambda page: page.on("download", lambda download: downloads.append(download)))
    page = context.new_page()
    page.goto(source, wait_until="domcontentloaded")
    link = page.get_by_role("link", name=attachment["title"], exact=True)
    if link.count() != 1 or link.evaluate("a => a.href") != attachment["url"]:
        raise QueryUnavailable("材料页的附件已变动，请重新读取材料页")
    link.click()
    print("已打开校方附件，请在下载页按提示完成验证。", file=sys.stderr, flush=True)
    deadline = monotonic() + 180
    while not downloads and context.pages and monotonic() < deadline:
        context.pages[-1].wait_for_timeout(250)
    if not downloads:
        raise QueryUnavailable("未收到校方附件，请在材料页核对下载要求")
    download = downloads[0]
    saved = save_school_attachment(download, attachment["title"], destination)
    return {"title": attachment["title"], "url": source, **saved}


def save_school_attachment(download, title, destination):
    if download.suggested_filename != title:
        raise QueryUnavailable("下载文件名与所选附件不一致，请核对材料页")
    with TemporaryDirectory(dir=destination.parent) as temp:
        staged = Path(temp) / "attachment"
        download.save_as(staged)
        size = staged.stat().st_size
        if not size:
            raise QueryUnavailable("校方返回空文件")
        os.link(staged, destination)
    return {"path": str(destination), "bytes": size}
