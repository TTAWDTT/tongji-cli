from urllib.parse import urljoin

from playwright.sync_api import expect

from tongji_cli.jw.records import query_data, watch_query
from tongji_cli.common import QueryUnavailable


VIEW = "/competitionAwards"
LIST = "/api/innovativeservice/race/getList"
LEVELS = {"国际": "INTERNATIONAL", "国家": "COUNTRY", "省级": "PROVINCIAL", "校级": "SCHOOL"}


def competitions(page, args):
    if args.page < 1:
        raise QueryUnavailable("竞赛目录页码从 1 开始")
    url = urljoin(page.url, VIEW)
    with watch_query(page, LIST) as initial:
        page.goto(url, wait_until="domcontentloaded")
    response = initial.value
    keyword = args.keyword.strip()
    if keyword or args.level or args.valid:
        form = page.locator(".el-form-item:visible")
        if keyword:
            form.filter(has_text="竞赛名称").locator("input").fill(keyword)
        for label, value in (("竞赛等级", args.level), ("是否有效", args.valid)):
            if value:
                field = form.filter(has_text=label).locator("input")
                field.click()
                page.locator(".el-select-dropdown:visible").get_by_text(value, exact=True).click()
                expect(field).to_have_value(value)
        with watch_query(page, LIST) as filtered:
            page.get_by_role("button", name="筛选", exact=True).click()
        response = filtered.value
    condition = response.request.post_data_json["condition"]
    if ((condition.get("raceName") or "") != keyword or (condition.get("raceLevel") or "") != LEVELS.get(args.level, "")
            or str(condition["enable"]) != {None: "", "是": "1", "否": "0"}[args.valid]):
        raise QueryUnavailable("教务竞赛目录与筛选条件不一致")
    data = query_data(response)
    total, size = data["total_"], data["pageSize_"]
    if size <= 0 or total < 0:
        raise QueryUnavailable("竞赛目录分页信息无效")
    pages = (total + size - 1) // size
    if args.page > max(pages, 1):
        raise QueryUnavailable(f"竞赛目录共 {pages} 页，请核对页码")
    if args.page > 1:
        jump = page.locator(".el-pagination:visible .el-pagination__jump input")
        jump.fill(str(args.page))
        with watch_query(page, LIST) as turn:
            jump.press("Enter")
        if turn.value.request.post_data_json["condition"] != condition:
            raise QueryUnavailable("竞赛目录翻页时筛选条件发生变化")
        data = query_data(turn.value)
    rows = data["list"]
    if (data["pageNum_"] != args.page or data["total_"] != total or data["pageSize_"] != size
            or len(rows) != min(size, total - (args.page - 1) * size)):
        raise QueryUnavailable("教务返回的竞赛目录与所选页不一致")
    items = []
    for row in rows:
        valid = {"1": "是", "0": "否"}.get(str(row["enable"]))
        if (args.level and row["raceLevelName"] != args.level) or (args.valid and valid != args.valid):
            raise QueryUnavailable("教务返回的竞赛与所选等级或有效状态不符")
        items.append({"id": row["raceId"], "竞赛名称": row["raceName"], "竞赛等级": row["raceLevelName"],
                      "获奖等级": row["priceNames"], "是否有效": valid, "备注": row.get("remark") or None, "url": url})
    return {"items": items, "page": args.page, "pages": pages, "total": total,
            "detail": f"共 {total} 项，第 {args.page} 页" if total else "未找到匹配竞赛"}
