from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.sync_api import TimeoutError as BrowserTimeout, expect

from jw_announcements import save_image
from jw_records import query_data, table_grid, watch_query
from queries import QueryUnavailable


VIEW = "/myBclCultureScheme"
LIST = "/api/cultureservice/bclStudentCultureRel/queryStudentCultureScheme"
DETAIL = "/api/cultureservice/bclCultureSchemeDetail/findCultScheDetailOrTemplateList"


def schemes(page, args):
    url = urljoin(page.url, VIEW)
    responses = {}

    def on_response(response):
        url = urlsplit(response.url)
        if url.path == DETAIL:
            for identifier in parse_qs(url.query).get("cultureId", []):
                responses[identifier] = response

    page.on("response", on_response)
    try:
        with watch_query(page, LIST) as opened:
            page.goto(url, wait_until="networkidle")
        options = [{"id": str(row["id"]), "名称": row["name"], "年级": row.get("grade"), "url": url}
                   for row in query_data(opened.value)]
        if args.action == "list":
            return options
        item = next((row for row in options if row["id"] == args.id), None)
        if item is None:
            raise QueryUnavailable("本人的培养方案目录中未找到该编号")
        field = page.get_by_placeholder("请选择培养方案")
        expect(field).not_to_have_value("")
        if field.input_value() != item["名称"]:
            field.click()
            option = page.locator(".el-select-dropdown:visible .el-select-dropdown__item").get_by_text(item["名称"], exact=True)
            option.first.wait_for()
            if option.count() != 1:
                raise QueryUnavailable("学校下拉框有多个同名方案，无法确认所选项")
            with watch_query(page, DETAIL):
                option.click()
        expect(page.locator(".scrollBar h2:visible")).to_have_text(item["名称"])
        page.wait_for_load_state("networkidle")
        if args.id not in responses:
            raise QueryUnavailable("学校页面未返回所选编号的培养方案章节")
        chapters = query_data(responses[args.id])
        wait_for_scheme_text(page, chapters)
        return [scheme_content(page, item, chapters, args)]
    finally:
        page.remove_listener("response", on_response)


def wait_for_scheme_text(page, chapters):
    contents = [ch["content"] if ch["contentType"] == 1 else None for ch in chapters]
    try:
        page.wait_for_function("""contents => {
            const headings = document.querySelectorAll('.scrollBar h3');
            if (headings.length !== contents.length) return false;
            return contents.every((html, i) => {
                if (html === null) return true;
                const body = headings[i].parentElement.querySelector(':scope > p');
                const template = document.createElement('template');
                template.innerHTML = html;
                const images = e => Array.from(e.querySelectorAll('img'), img => img.getAttribute('src'));
                return body && body.textContent.trim() === template.content.textContent.trim()
                    && JSON.stringify(images(body)) === JSON.stringify(images(template.content));
            });
        }""", arg=contents, timeout=8000, polling=200)
    except BrowserTimeout:
        raise QueryUnavailable("学校页面显示的章节正文与所选培养方案不一致，请重新查询") from None


def scheme_content(page, item, chapters, args):
    headings = page.locator(".scrollBar h3:visible")
    expect(headings).to_have_count(len(chapters))
    sections = []
    for heading, chapter in zip(headings.all(), chapters):
        name = chapter["name"].strip()
        title = heading.inner_text().strip()
        if title != name and title.partition("、")[2] != name:
            raise QueryUnavailable("培养方案的章节标题与所选方案不一致")
        if args.chapter and args.chapter not in (name, title):
            continue
        block = heading.locator("..")
        images = block.locator("img")
        if args.action == "image":
            return {**item, "章节": name, **save_image(images, args.index, args.output)}
        body = block.locator(":scope > p").all_inner_texts()
        tables = [scheme_table(table) for table in block.locator(".el-table:visible").all()]
        media = images.evaluate_all("""images => images.map((img,i)=>({
            index:i+1, alt:img.alt, url:/^https?:/.test(img.src) ? img.src : null
        }))""")
        sections.append({"标题": name, "正文": "\n".join(body).strip(), "表格": tables, "配图": media})
    if args.chapter and not sections:
        raise QueryUnavailable("培养方案中没有这个章节，请用 schemes show 查看标题")
    return {**item, "章节": sections}


def scheme_table(table):
    header = table.locator(":scope > .el-table__header-wrapper table")
    grid = table_grid(header, ".el-table__fixed-header-wrapper table")
    body = table.locator(":scope > .el-table__body-wrapper table")
    if not body.count() or not body.locator("tr").count():
        # 学分表把内容和表头一起放在 thead 中。
        columns, *rows = grid
    else:
        columns = [" / ".join(dict.fromkeys(v for v in col if v)) for col in zip(*grid, strict=True)]
        rows = table_grid(body, ".el-table__fixed-body-wrapper table")
    if not all(columns) or len(set(columns)) != len(columns) or any(len(row) != len(columns) for row in rows):
        raise QueryUnavailable("培养方案表格的字段与表头不一致")
    result = []
    for row in rows:
        if columns[:3] == ["课程编码", "课程代码", "课程名称"] and row[0] and row[0] == row[1] == row[2]:
            result.append({"分类": row[0], "说明": row[-1] or None})
        else:
            result.append(dict(zip(columns, (v or None for v in row))))
    return {"列": columns, "行": result}
