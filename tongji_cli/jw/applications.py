from urllib.parse import urlencode, urljoin

from playwright.sync_api import expect

from tongji_cli.jw.records import course_rows, query_data, record_pages, watch_query
from tongji_cli.common import QueryUnavailable


VIEW = "/StudentRollCheck"
LIST = "/api/workflow/approval/selectApproFlowList"
DETAIL = "/api/workflow/approval/selectApproFlow"


def applications(page, args):
    url = urljoin(page.url, VIEW)
    items = []
    for batch in record_pages(page, url, LIST, "我的申请"):
        table = page.locator(".el-table:visible").filter(has=page.get_by_text("申请编号", exact=True))
        rows = course_rows(page, table)
        if [r["申请编号"] for r in rows] != [r["no"] for r in batch]:
            raise QueryUnavailable("教务申请表中的编号与当前查询页不一致")
        items.extend((record["id"], row) for record, row in zip(batch, rows))
    if args.action == "list":
        return [{**row, "url": url} for _, row in items]
    matches = [(record_id, row) for record_id, row in items if row["申请编号"] == args.number]
    if not matches:
        raise QueryUnavailable("本人教务申请列表中未找到该编号")
    if len(matches) != 1:
        raise QueryUnavailable("教务目录中有多个相同的申请编号，无法唯一确认明细")
    record_id, row = matches[0]
    target = urljoin(url, "/StudentRollDetail") + "?" + urlencode({"id": row["申请编号"]})
    with watch_query(page, DETAIL) as opened:
        page.goto(target, wait_until="domcontentloaded")
    detail = query_data(opened.value)
    if detail["id"] != record_id or detail["no"] != row["申请编号"]:
        raise QueryUnavailable("教务打开的明细与申请编号不一致")
    return [{**row, **application_detail(page, detail)}]


def application_detail(page, detail):
    history = page.locator(".el-table:visible").filter(has=page.get_by_text("审批结果", exact=True))
    expect(history.locator(".el-table__body-wrapper tr:visible")).to_have_count(len(detail["listApproveHistory"]))
    steps = course_rows(page, history)
    fields = {}
    for group in page.locator(".edu-info-list .item-group:visible").all():
        caption = group.locator(".label").inner_text().strip()
        label = caption.rstrip("：:")
        if label in {"详细修改", "审批材料", "修改说明"}:
            fields[label] = group.inner_text().strip().removeprefix(caption).strip() or None
    return {**fields, "审批进度": steps, "url": page.url}
