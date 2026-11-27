from datetime import date
from playwright.sync_api import expect

from tongji_cli.library.services import SEATS
from tongji_cli.library.space import load_choices
from tongji_cli.common import QueryUnavailable


def room_directory(page, args):
    entry = page.get_by_text("研习室预约", exact=True).filter(visible=True).first
    choices = load_choices(page, entry)
    available_dates = choices.get("date")
    if available_dates == [] and not choices["area"]:
        if args.action != "dates" and args.date:
            raise QueryUnavailable("馆方尚未列出该日期，可用 library rooms dates 查看")
        return []
    dates = page.locator(".section:visible").filter(has=page.get_by_text("日期", exact=True))
    active = dates.locator(".dayList .active .day")
    selected_day = date.fromisoformat(active.inner_text().strip()).isoformat()
    if not isinstance(available_dates, list) or selected_day not in available_dates:
        raise QueryUnavailable("馆方可选日期与当前选中的日期不符")
    if args.action == "dates":
        return [{"date": day, "selected": day == selected_day, "url": SEATS} for day in available_dates]
    requested = args.date.isoformat() if args.date else selected_day
    if args.action == "list" and requested not in available_dates:
        raise QueryUnavailable("馆方尚未列出该日期，可用 library rooms dates 查看")
    if requested != selected_day and requested in available_dates:
        selected_day = requested
        target = dates.get_by_text(selected_day, exact=True)
        if not target.is_visible():
            dates.get_by_text("全部展开", exact=False).filter(visible=True).click()
        choices = load_choices(page, target)
        expect(active).to_have_text(selected_day)
    branches = {str(r["id"]): r["name"] for r in choices["premises"]}
    floors = {str(r["id"]): r for r in choices["storey"]}
    rooms = []
    for room in choices["area"]:
        floor = floors[str(room["parentId"])]
        branch = branches[str(floor["parentId"])]
        if args.action == "list" and ((args.branch and args.branch != branch) or (args.floor and args.floor != floor["name"])
                                      or (args.room_type and args.room_type != room["type_name"])):
            continue
        rooms.append({"date": selected_day, "branch": branch, "floor": floor["name"], "room_id": room["id"],
                      "room_name": room["name"], "room_type": room["type_name"], "url": SEATS})
    return rooms
