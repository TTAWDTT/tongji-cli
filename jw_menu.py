from urllib.parse import parse_qsl, urljoin, urlsplit

from playwright.sync_api import expect

from jw_records import VIEWS


def student_menu(page, section=None, keyword=None):
    groups = page.locator("aside.left-side .el-collapse:visible > .el-collapse-item:visible")
    dashboard = page.get_by_text("切换旧版", exact=True).filter(visible=True)
    groups.first.or_(dashboard).first.wait_for()
    if not groups.count():
        page.goto(urljoin(page.url, VIEWS["courses"][1]), wait_until="domcontentloaded")
        groups.first.wait_for()
    rows = []
    for group in groups.all():
        header = group.locator(":scope > [role=tab] > .el-collapse-item__header")
        title = header.inner_text().strip()
        if section is not None and title != section:
            continue
        menu = group.locator(".el-collapse-item__content > ul.el-menu").first
        if not menu.is_visible():
            header.click()
        expect(menu).to_be_visible()
        rows.extend(menu_items(page, menu, [title]))
    if keyword:
        return [r for r in rows if any(keyword.casefold() in name.casefold() for name in r["menu_path"])]
    return rows


def menu_items(page, menu, parents):
    rows = []
    for item in menu.locator(":scope > li:visible, :scope > div > li:visible").all():
        submenu = item.locator(":scope > .el-submenu__title")
        if submenu.count():
            child = item.locator(":scope > ul.el-menu")
            if not child.is_visible():
                submenu.click()
            expect(child).to_be_visible()
            rows.extend(menu_items(page, child, [*parents, submenu.inner_text().strip()]))
        else:
            link = item.locator(":scope > a[href]:visible")
            if link.count():
                title = link.inner_text().strip()
                rows.append({"title": title, "menu_path": [*parents, title],
                             "url": menu_url(page.url, link.get_attribute("href"))})
    return rows


def menu_url(base, href):
    target = urlsplit(urljoin(base, href))
    if target.scheme not in {"http", "https"}:
        return None
    if target.query:
        if target.netloc != urlsplit(base).netloc or any(k != "t" for k, _ in parse_qsl(target.query, keep_blank_values=True)):
            return None
        target = target._replace(query="")
    return target.geturl()
