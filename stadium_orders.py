import re
from urllib.parse import urlsplit

from playwright.sync_api import expect

from queries import QueryUnavailable
from stadium import DIRECTORY, slots


ORDER_URL = "https://stadium.tongji.edu.cn/pc/#/Order"


def orders(page):
    def is_listing(response):
        return urlsplit(response.url).path == "/venue/personal/personalOrderlist"

    with page.expect_response(is_listing) as result:
        if page.url == ORDER_URL:
            page.reload(wait_until="domcontentloaded")
        else:
            page.get_by_text("我的订单", exact=True).filter(visible=True).click()
    items = []
    number = 1
    while True:
        response = result.value
        body = response.json() if response.ok else {}
        if body.get("current") != number or not isinstance(body.get("records"), list) or not isinstance(body.get("total"), int):
            raise QueryUnavailable("体育平台未返回个人订单列表")
        cards = page.locator(".el-tab-pane:visible .card")
        records = body["records"]
        expect(cards).to_have_count(len(records))
        for row, card in zip(records, cards.all()):
            expect(card.locator(".pStyle")).to_contain_text(row["spaceInfo"])
            state = card.locator(".noSelect span").inner_text().strip()
            items.append({"id": str(row["pOrderid"]), "venue": row["venuename"], "sport": row["venname"],
                          "date": row["scDate"], "booking": row["spaceInfo"], "status": state,
                          "amount": row["countprice"], "url": ORDER_URL})
        if len(items) == body["total"]:
            if len({item["id"] for item in items}) != len(items):
                raise QueryUnavailable("体育平台翻页时重复返回订单，请重新查询")
            return items
        if not records or len(items) > body["total"]:
            raise QueryUnavailable("体育平台个人订单与页面总数不符")
        with page.expect_response(is_listing) as result:
            page.locator(".el-pagination:visible .btn-next").click()
        number += 1


def reserve(page, args, checkout):
    previous = set() if args.preview else {r["id"] for r in orders(page)}
    items = slots(page, args.venue, args.date, args.sport)
    matches = [(i, row) for i, row in enumerate(items)
               if row["field"] == args.field and row["time_slot"] == args.time_slot]
    if len(matches) != 1 or matches[0][1]["available"] is not True:
        raise QueryUnavailable("指定场地和时段当前不可选，请查询 sports slots")
    index, row = matches[0]
    table = page.locator(".tables:visible .inner-seat-wrapper > div.clearfix .seat")
    cell = table.nth(index).locator(".inner-seat.unselected-seat")
    cell.click(timeout=5000)
    selected = page.locator(".drawerText:visible")
    expect(selected.locator(".textrow .el-col-15")).to_have_text([f"{args.field} {args.time_slot}"])
    expect(selected.locator("h2")).to_contain_text(row["date"])
    price = selected.locator(".textrow").filter(has=page.get_by_text("合计", exact=True)).locator(".el-col-12").last.inner_text()
    if not re.fullmatch(r"[￥¥]\s*\d+(?:\.\d+)?\s*元", price):
        raise QueryUnavailable("预约页未显示可核对的合计金额")
    place = page.get_by_text("立即下单", exact=True).filter(visible=True)
    expect(place).to_have_count(1)
    if args.preview:
        return [dict(row, action="preview", amount=price)]

    checkout(row, price)
    if page.is_closed():
        page = page.context.new_page()
    page.goto(DIRECTORY, wait_until="domcontentloaded")
    booking = re.compile(r"(?:^|\s)" + re.escape(args.field) + r"\s*[（(]\s*" + re.escape(args.time_slot) + r"\s*[）)](?:\s|$)")
    receipts = [r for r in orders(page) if r["id"] not in previous and r["venue"] == row["venue"]
                and r["date"] == row["date"] and booking.search(r["booking"])]
    if len(receipts) != 1:
        raise QueryUnavailable("未核实到对应的新订单，请用 sports orders 查询后再决定是否办理")
    return [dict(receipts[0], action="order_recorded")]
