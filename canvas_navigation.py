from urllib.parse import urlsplit

import queries
from canvas_api import courses, select_course
from queries import QueryUnavailable


def groups(page, state):
    response = page.goto(queries.CANVAS + "/groups", wait_until="domcontentloaded")
    if not response or not response.ok or urlsplit(page.url).path != "/groups":
        raise QueryUnavailable("Canvas 未打开本人的小组目录")
    content = page.locator("#content")
    table_id, headings = (("current_groups_table", {"当前小组", "Current Groups"}) if state == "active"
                          else ("previous_groups_table", {"以前的组群", "Previous Groups"}))
    table = content.locator(f"#{table_id}")
    if not table.count() and not headings.intersection(content.locator("h1, h2").all_inner_texts()):
        raise QueryUnavailable("Canvas 未返回可核对的小组目录")
    rows = table.locator("tr:has(td)").evaluate_all("""rows => rows.map(row => ({
        values: Array.from(row.cells, cell => cell.textContent.trim()),
        url: row.cells[0].querySelector('a')?.href || null
    }))""")
    items = []
    for row in rows:
        name, course, term = row["values"]
        url = row["url"]
        items.append({"id": int(urlsplit(url).path.rsplit("/", 1)[1]) if url else None,
                      "title": name, "course": course, "term": term or None, "url": url})
    return items


def select_group(page, group_id, state):
    target = next((g for g in groups(page, state) if g["id"] == group_id), None)
    if target is None:
        raise QueryUnavailable("该小组未出现在所选范围的可进入小组中，请用 canvas groups 查看")
    return target


def navigation(context, page, args):
    if args.group is None:
        target = select_course(courses(context, args.state), args.course, args.state)
    else:
        target = select_group(page, args.group, args.state)
    response = page.goto(target["url"], wait_until="domcontentloaded")
    path = urlsplit(target["url"]).path.rstrip("/")
    current = urlsplit(page.url)
    if (not response or not response.ok or current[:2] != urlsplit(target["url"])[:2]
            or not (current.path == path or current.path.startswith(path + "/"))):
        raise QueryUnavailable("Canvas 未打开所选课程或小组")
    menu = page.locator("#section-tabs")
    if menu.count() != 1:
        raise QueryUnavailable("Canvas 未显示该课程或小组的导航栏")
    return menu.locator("a[href]:visible").evaluate_all("""links => links.map(link => {
        const label = link.cloneNode(true);
        label.querySelector('.nav-badge')?.remove();
        return {title: label.textContent.trim(), url: link.href};
    })""")
