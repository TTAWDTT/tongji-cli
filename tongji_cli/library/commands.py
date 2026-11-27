from datetime import date

from tongji_cli.browser_session import PROFILE
from tongji_cli.library.loans import loans
from tongji_cli.library import services as library_services


def configure(commands):
    library = commands.add_parser("library", help="图书馆开放时间、馆藏目录和空间预约")
    subs = library.add_subparsers(dest="operation", required=True)
    loans = subs.add_parser("loans", help="本人当前在借或历史借阅的图书和现刊")
    loans.add_argument("--history", action="store_true", help="查询馆方借阅历史和实还日期")
    renew = subs.add_parser("renew", help="按条码续借一本当前在借图书")
    renew.add_argument("barcode", help="本人当前在借图书的条码号，保留前导零")
    renew.add_argument("--due", type=date.fromisoformat, required=True, help="续借前的应还日期 YYYY-MM-DD")
    renew.add_argument("--preview", action="store_true", help="核对在借图书和原应还日期，不提交")
    records = subs.add_parser("reservations", help="查看本人图书馆空间预约记录")
    records.add_argument("--kind", choices=["seat", "room", "research"], default="seat")
    records.add_argument("--limit", type=int, default=10, help="从最新一条起最多读取的记录数")
    hours = subs.add_parser("hours", help="按馆区查看公布的常规开放时间")
    hours.add_argument("campus", nargs="?", default="", help="例如四平、嘉定、沪北")
    search = subs.add_parser("search", help="在官方馆藏目录中分页检索")
    search.add_argument("book", help="书名或检索词")
    search.add_argument("--page", type=int, default=1, help="馆藏目录页码")
    holdings = subs.add_parser("holdings", help="按书目 ID 查询逐册馆藏和各馆藏地的可借复本")
    holdings.add_argument("id", type=int, help="library search 返回的纸本书目 ID")
    seats = subs.add_parser("seats", help="打开官方空间预约")
    seat_actions = seats.add_subparsers(dest="action", required=True)
    seat_actions.add_parser("open", help="在浏览器打开预约入口")
    for name, help_text in (("availability", "查询馆舍、楼层或区域的余座"), ("list", "查看指定区域的座位列表"),
                            ("reserve", "预约指定日期、时段和座位，或仅预览")):
        action = seat_actions.add_parser(name, help=help_text)
        action.add_argument("--date", type=date.fromisoformat, required=name == "reserve", help="馆方可选日期 YYYY-MM-DD")
        action.add_argument("--branch", required=name != "availability", help="馆舍全名")
        action.add_argument("--floor", required=name != "availability", help="馆方显示的楼层名")
        if name != "availability":
            action.add_argument("--area", required=True, help="馆方显示的区域名")
            action.add_argument("--time", dest="time_slot", required=name == "reserve", help="馆方显示的时段，如 08:00-22:00")
        if name == "reserve":
            action.add_argument("--seat", required=True, help="列表中的完整座位号，保留前导零")
            action.add_argument("--preview", action="store_true", help="只选中并核对目标座位")
    rooms = subs.add_parser("rooms", help="查图书馆研习室、研讨室和其他预约空间的目录")
    room_actions = rooms.add_subparsers(dest="action", required=True)
    room_actions.add_parser("dates", help="查馆方当前列出的预约日期")
    spaces = room_actions.add_parser("list", help="列出所选日期的预约空间，可按馆舍、楼层和空间类型筛选")
    spaces.add_argument("--date", type=date.fromisoformat, help="YYYY-MM-DD，默认馆方当前选中日期")
    spaces.add_argument("--branch", help="馆舍全名")
    spaces.add_argument("--floor", help="楼层全名")
    spaces.add_argument("--type", dest="room_type", help="馆方目录中的空间类型")
    receipts = room_actions.add_parser("receipts", help="查本人研习空间的回执编号、申请主题和办理状态")
    select = receipts.add_mutually_exclusive_group()
    select.add_argument("--id", dest="receipt_id", help="在全部本人记录中按完整回执编号查一件")
    select.add_argument("--limit", type=int, default=10, help="从最新一件起最多显示的记录数，默认 10")
    slots = room_actions.add_parser("slots", help="查看指定空间的开放时间、已占和空档")
    reserve = room_actions.add_parser("reserve", help="选择空间和时段，预览申请或由本人办理")
    for action in (slots, reserve):
        action.add_argument("room_id", metavar="空间编号", help="library rooms list 返回的房间编号")
        action.add_argument("--date", type=date.fromisoformat, required=action is reserve,
                            help="YYYY-MM-DD，查询省略时列出这个房间时段页提供的全部日期")
    reserve.add_argument("--time", dest="time_slot", required=True, help="起止时刻，例如 12:00-13:00")
    reserve.add_argument("--topic", help="馆方列出的申请主题全名，预览可查看选项")
    reserve.add_argument("--purpose", help="填入研习室的申请内容")
    reserve.add_argument("--preview", action="store_true", help="打开并核对所选房间的申请表")
    study = subs.add_parser("study", help="按馆方周期查询或预约研修座位、考研座位")
    actions = study.add_subparsers(dest="action", required=True)
    for name in ("availability", "list", "reserve"):
        sub = actions.add_parser(name)
        sub.add_argument("--type", dest="study_type", choices=["research", "exam"], default="research",
                         help="research 为研修座位，exam 为考研座位")
        sub.add_argument("--branch", required=name != "availability", help="馆舍全名")
        sub.add_argument("--floor", required=name != "availability", help="馆方显示的楼层名")
        if name != "availability":
            sub.add_argument("--area", required=True, help="馆方显示的区域名")
            sub.add_argument("--period", choices=["current", "next"], required=name == "reserve", default="current",
                             help="current 为本期，next 为下期，具体起止日期见馆方")
        if name == "reserve":
            sub.add_argument("--seat", required=True, help="该期列表中的完整座位号")
            sub.add_argument("--preview", action="store_true", help="只选中目标座位，查看期限、权限和预约按钮")


def run(args):
    if args.operation in {"loans", "renew"}:
        return loans(PROFILE, history=getattr(args, "history", False),
                     renewal=args if args.operation == "renew" else None)
    return {"status": "ok", "items": library_services.run(args)}


def space_items(args, page):
    from tongji_cli.library.space import availability, reservation_history, reserve_seat
    if args.operation == "rooms":
        if args.action == "receipts":
            from tongji_cli.library.room_booking import lookup_room_receipts
            return lookup_room_receipts(page, args)
        if args.action in {"slots", "reserve"}:
            from tongji_cli.library.room_booking import room_booking
            return room_booking(page, args)
        from tongji_cli.library.rooms import room_directory
        return room_directory(page, args)
    if args.operation == "study":
        if args.action == "reserve":
            from tongji_cli.library.study import reserve_study
            return reserve_study(page, args)
        return availability(page, branch=args.branch, floor=args.floor, area=getattr(args, "area", None),
                            study_type=args.study_type, period=getattr(args, "period", "current"))
    if args.operation == "seats":
        if args.action == "reserve":
            return reserve_seat(page, args)
        return availability(page, args.date, args.branch, args.floor, getattr(args, "area", None),
                            getattr(args, "time_slot", None))
    return reservation_history(page, args.kind, args.limit)
