from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import expect

from tongji_cli.jw.records import query_data, record_batches, watch_query
from tongji_cli.campus.notices import save_school_attachment
from tongji_cli.common import QueryUnavailable


CATALOGS = {
    "student-status": ("/modelFilesManage", "/api/studentservice/templateFile/listTemplate", "模板文件", "fileName", "点此下载"),
    "graduation": ("/graduationDesignPrint", "/api/designservice/docRelatedPrint/queryByPage", "毕业设计（论文）相关表格", "attachName", "下载"),
}


def forms(page, args):
    view, path, heading, filename, download_label = CATALOGS[args.catalog]
    url = urljoin(page.url, view)
    if args.action == "download":
        destination = Path(args.output).expanduser().absolute()
        if destination.exists() or not destination.parent.is_dir():
            raise QueryUnavailable("请在已有目录中指定一个新文件名")
    with watch_query(page, path) as opened:
        page.goto(url, wait_until="domcontentloaded")
    table = page.locator(".el-table:visible").filter(has=page.get_by_text(heading, exact=True))
    items = []
    unpack = graduation_page if args.catalog == "graduation" else query_data
    for batch in record_batches(page, path, heading, opened.value, unpack):
        rows = table.locator(".el-table__body-wrapper tr:visible")
        expect(rows).to_have_count(len(batch))
        for index, record in enumerate(batch):
            title = record[filename]
            item = {"id": str(record["id"]), "title": title, "catalog": args.catalog, "url": url}
            if args.catalog == "student-status":
                item.update(说明=record.get("remark"), 上传时间=record.get("uploadTime"))
            if args.action == "list":
                if not args.search or args.search.casefold() in (title + " " + (item.get("说明") or "")).casefold():
                    items.append(item)
            elif item["id"] == args.id:
                row = rows.nth(index)
                expect(row.get_by_role("button", name=title, exact=True)).to_be_visible()
                with page.expect_download(timeout=30000) as download:
                    row.get_by_role("button", name=download_label, exact=True).click()
                return [{**item, **save_school_attachment(download.value, title, destination)}]
    if args.action == "download":
        raise QueryUnavailable("所选教务文件目录中未找到该编号")
    return items


def graduation_page(response):
    data = query_data(response)
    return {"pageNum_": data["pageNum"], "pageSize_": data["pageSize"], "total_": data["total"], "list": data["list"]}
