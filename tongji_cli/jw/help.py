from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

from playwright.sync_api import expect

from tongji_cli.jw.records import course_rows, query_data, record_pages, watch_query
from tongji_cli.campus.notices import save_school_attachment
from tongji_cli.common import QueryUnavailable


VIEW = "/helpCenter"
LIST = "/api/commonservice/helpCenter/listAllHelp"
DETAIL = "/api/commonservice/helpCenter/detailHelp"


def help_center(page, args):
    url = urljoin(page.url, VIEW)
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("主题", exact=True))
    items = []
    for records in record_pages(page, url, LIST, "帮助中心"):
        rows = course_rows(page, table)
        if [r["主题"] for r in rows] != [r["theme"].strip() for r in records]:
            raise QueryUnavailable("帮助中心的主题与教务列表不一致")
        for index, (record, row) in enumerate(zip(records, rows)):
            item = {"id": record["id"], "title": row.pop("主题"), **row, "url": url}
            if args.action == "list":
                if not args.search or args.search.casefold() in item["title"].casefold():
                    items.append(item)
            elif args.id == item["id"]:
                selected = table.locator(".el-table__body-wrapper tr:visible").nth(index)
                with watch_query(page, DETAIL) as opened:
                    selected.get_by_role("button", name="详情", exact=True).click()
                return [help_detail(page, item, query_data(opened.value), args)]
    if args.action != "list":
        raise QueryUnavailable("教务帮助中心未找到该条目编号")
    return items


def help_detail(page, item, detail, args):
    if detail["id"] != item["id"] or detail["theme"].strip() != item["title"]:
        raise QueryUnavailable("打开的帮助详情与所选条目不一致")
    dialog = page.locator(".el-dialog:visible")
    expect(dialog.locator(".info-title")).to_have_text(item["title"])
    attachments = detail["attachmentList"] or []
    links = dialog.locator(".info-attach .attach-item a")
    expect(links).to_have_count(len(attachments))
    names = [a["fileName"] for a in attachments]
    if [name.strip() for name in links.all_inner_texts()] != names:
        raise QueryUnavailable("帮助详情的附件名称与学校清单不一致")
    if args.action == "download":
        matches = [(i, a) for i, a in enumerate(attachments) if a["id"] == args.attachment]
        if len(matches) != 1:
            raise QueryUnavailable("此帮助条目中没有唯一匹配的附件编号")
        index, attachment = matches[0]
        dest = Path(args.output).expanduser().absolute()
        if dest.exists() or not dest.parent.is_dir():
            raise QueryUnavailable("请在已有目录中指定一个新文件名")
        with page.expect_download(timeout=30000) as result:
            links.nth(index).click()
        server_name = unquote(urlsplit(attachment["fileUrl"]).path.rsplit("/", 1)[-1])
        saved = save_school_attachment(result.value, server_name, dest)
        return {**item, "attachment_id": attachment["id"], "filename": attachment["fileName"], **saved}
    body = dialog.locator(".info-content")
    references = body.locator("a[href]").evaluate_all("""links => links.filter(a =>
        ['https:', 'http:'].includes(a.protocol)).map(a => ({title:a.innerText.trim(), url:a.href}))""")
    return {**item, "body": body.inner_text().strip(), "links": references,
            "attachments": [{"id": a["id"], "title": a["fileName"]} for a in attachments]}
