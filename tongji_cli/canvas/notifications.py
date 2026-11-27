import re
from time import monotonic

from tongji_cli.canvas import api as canvas_api
from tongji_cli.common import QueryUnavailable


FREQUENCIES = {
    "immediately": ("立即通知", "Notify immediately"),
    "daily": ("每日摘要", "Daily summary"),
    "weekly": ("每周摘要", "Weekly summary"),
    "never": ("关闭通知", "Notifications off"),
}


def notification_settings(context, page, args):
    channels = list(canvas_api.listing(context, "users/self/communication_channels"))
    if args.channel is not None:
        channels = [channel for channel in channels if channel["id"] == args.channel]
        if not channels:
            raise QueryUnavailable("本人 Canvas 账户中没有此通知渠道")
    if args.operation == "notifications":
        return [row for channel in channels for row in preferences(context, channel, args.category)]
    return change_frequency(context, page, channels[0], args.category, args.frequency, args.preview)


def category_key(value):
    return "_".join(value.strip().lower().split())


def preferences(context, channel, category):
    path = f"users/self/communication_channels/{channel['id']}/notification_preferences"
    settings, _ = canvas_api.request(context, canvas_api.endpoint(path, {}))
    return [{"channel_id": channel["id"], "channel_type": channel["type"],
             "channel_state": channel["workflow_state"], "category": row["category"],
             "notification": row["notification"], "frequency": row["frequency"]}
            for row in settings["notification_preferences"]
            if category is None or category_key(category) == category_key(row["category"])]


def change_frequency(context, page, channel, category, frequency, preview):
    current = preferences(context, channel, category)
    if not current:
        raise QueryUnavailable("该渠道没有此通知类别；可通过 canvas notifications 查询类别")
    page.set_viewport_size({"width": 1600, "height": 900})
    page.goto(canvas_api.CANVAS + "/profile/communication", wait_until="domcontentloaded")
    row = page.get_by_test_id(category_key(current[0]["category"]))
    row.wait_for(timeout=12000)
    table = row.locator("xpath=ancestor::table[1]")
    headers = table.locator('thead th')
    cells = [i for i, text in enumerate(headers.all_inner_texts())
             if channel['address'] in [part.strip() for part in text.splitlines()]
             and channel['type'].casefold() in [part.strip().casefold() for part in text.splitlines()]]
    if len(cells) != 1:
        raise QueryUnavailable("无法在 Canvas 通知表中确定该渠道")
    button = row.locator(":scope > *").nth(cells[0]).get_by_role("button")
    if not button.is_enabled():
        raise QueryUnavailable("Canvas 未开放此渠道的提醒设置")
    button.click()
    names = "|".join(map(re.escape, FREQUENCIES[frequency]))
    choice = page.get_by_role("menuitem", name=re.compile(rf"^({names})$", re.I))
    choice.wait_for()
    result = {"channel_id": channel["id"], "category": current[0]["category"], "frequency": frequency,
              "notifications": len(current)}
    if preview:
        return [{**result, "action": "preview"}]
    if all(row["frequency"] == frequency for row in current):
        return [{**result, "action": "unchanged"}]
    choice.click()
    expected = {row["notification"] for row in current}
    deadline = monotonic() + 10
    while monotonic() < deadline:
        updated = preferences(context, channel, category)
        if {row["notification"] for row in updated if row["frequency"] == frequency} == expected and len(updated) == len(current):
            return [{**result, "action": "updated"}]
        page.wait_for_timeout(300)
    raise QueryUnavailable("已操作 Canvas 通知菜单，重新读取时尚未确认该类别各项的频率")
