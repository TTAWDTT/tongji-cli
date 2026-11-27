import hashlib
import re
import webbrowser
from urllib.parse import quote

from playwright.sync_api import Error, sync_playwright

from tongji_cli.common import QueryUnavailable


LIB_HOURS = "https://www.lib.tongji.edu.cn/index.php?classid=11974"
CATALOG = "https://findtongji.libsp.cn/#/searchListExternal/01/{}/01"
SEATS = "https://space.tongji.edu.cn/"


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
                from tongji_cli.library.holdings import holdings
                return holdings(page, args.id)
            return catalog_search(page, args.book.strip(), args.page)
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
