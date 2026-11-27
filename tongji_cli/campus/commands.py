import sys
from datetime import date, timedelta

from tongji_cli.campus import bus
from tongji_cli.campus import guides as campus_guides
from tongji_cli.campus import dorm_energy
from tongji_cli.campus import notices
from tongji_cli.campus import school_calendar
from tongji_cli.common import QueryUnavailable


def configure(commands):
    calendar = commands.add_parser("calendar").add_subparsers(dest="operation", required=True)
    terms = calendar.add_parser("terms", help="公开学期目录、起止日期及教学周与考试周范围")
    terms.add_argument("--year", type=int, help="学年的起始年份，如 2026")
    span = calendar.add_parser("range", help="逐日查看一段日期内学校公布的校历标记")
    span.add_argument("start", type=date.fromisoformat, metavar="开始日期")
    span.add_argument("end", type=date.fromisoformat, metavar="结束日期")
    calendar.add_parser("week").add_argument("date", type=date.fromisoformat, nargs="?")
    calendar.add_parser("day").add_argument("date", type=date.fromisoformat)
    rooms = commands.add_parser("rooms").add_subparsers(dest="operation", required=True)
    rooms.add_parser("search", help="在公开教室信息系统按名称查找教室").add_argument("keyword", metavar="关键词")
    rooms.add_parser("status", help="按完整教室名读取公开状态").add_argument("name", metavar="完整教室名")
    buildings = rooms.add_parser("buildings", help="查教学楼名称和教务编号")
    buildings.add_argument("--campus", choices=list(school_calendar.CAMPUSES))
    directory = rooms.add_parser("list", help="查询教学楼内的教室及课表查询 ID")
    directory.add_argument("--building", required=True, help="rooms buildings 给出的教学楼编号")
    schedule = rooms.add_parser("schedule")
    schedule.add_argument("--room", required=True, help="教室编号")
    schedule.add_argument("--term", help="校方学期编号，默认当前学期")
    campus_guides.configure(commands)
    dorm_energy.configure(commands)
    notices.configure(commands)
    bus.configure(commands)


def run(args, day):
    if args.command == "calendar" and args.operation == "range":
        return school_calendar.calendar_range(args.start, args.end)
    if args.command == "notices":
        return notices.result(args)
    return {"status": "ok", "items": public_query(args, day)}


def public_query(args, day):
    if args.command == "dorm":
        return dorm_energy.energy(args, day)
    if args.command in {"sports", "clinic", "card"}:
        return campus_guides.read(args)
    if args.command == "calendar":
        if args.operation == "terms":
            return school_calendar.calendar_terms(args.year)
        return school_calendar.calendar_info(args.date or day, args.operation == "day")
    if args.command == "rooms":
        if args.operation == "search":
            from tongji_cli.campus.rooms_public import search_rooms
            return [search_rooms(args.keyword)]
        if args.operation == "status":
            from tongji_cli.campus.rooms_public import room_status
            return [room_status(args.name)]
        if args.operation == "schedule":
            return school_calendar.room_schedule(args.room, args.term)
        return school_calendar.room_directory(getattr(args, "building", None), getattr(args, "campus", None))
    return bus.run(args)


def sports_items(args, page):
    if args.operation == "orders":
        from tongji_cli.campus.stadium_orders import orders
        return orders(page)
    if args.operation == "reserve":
        from tongji_cli.campus.stadium_orders import reserve
        return reserve(page, args, confirm_sports_checkout)
    from tongji_cli.campus.stadium import slots
    return slots(page, args.venue, args.date, args.sport)


def card_items(args, page, day):
    if args.operation == "transactions":
        from tongji_cli.campus.card_transactions import transactions
        end = args.end_date or day
        return transactions(page, args.start_date or (end - timedelta(days=6)), end)
    return campus_guides.card_balance(page)


def confirm_sports_checkout(row, price):
    print(f"{row['date']} {row['venue']} {row['field']} {row['time_slot']}，合计 {price}。"
          "请在体育平台完成本次下单，再回到终端按回车核对个人订单。", file=sys.stderr, flush=True)
    try:
        input()
    except EOFError:
        raise QueryUnavailable("核对订单需要交互终端，请查询 sports orders") from None
