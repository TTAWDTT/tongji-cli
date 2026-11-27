import argparse
import sys
from datetime import datetime

from playwright.sync_api import Error

from tongji_cli.auth import SITES, signed_in_queries
from tongji_cli.campus import commands as campus
from tongji_cli.canvas import commands as canvas
from tongji_cli.common import QueryUnavailable, SHANGHAI, failure
from tongji_cli.display import display
from tongji_cli.jw import commands as jw
from tongji_cli.library import commands as library
from tongji_cli.media import commands as media
from tongji_cli.portal import commands as portal
from tongji_cli.schedule import schedule_items, week_view


def arguments():
    shared = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    shared.add_argument("--json", action="store_true")
    options, argv = shared.parse_known_args()
    parser = argparse.ArgumentParser(description="同济校园查询；所有命令均支持 --json")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("login", "status"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--site", choices=["all", *SITES], help="默认检查教务和 Canvas；all 包括一网通办、图书馆、空间预约、一卡通、体育场馆、教学媒体平台和学习通")
    for name, help_text in (("today", "今日课表、今日截止作业"), ("week", "未来七个上海日期的课表和作业")):
        cmd = commands.add_parser(name, help=help_text)
        cmd.add_argument("--include-chaoxing", action="store_true", help="同时查询学习通；须先 login --site chaoxing")
    cx = commands.add_parser("chaoxing", help="学习通课程与作业查询")
    cx_ops = cx.add_subparsers(dest="operation", required=True)
    cx_ops.add_parser("courses")
    cx_work = cx_ops.add_parser("assignments")
    cx_work.add_argument("--course")
    cx_work.add_argument("--next", type=int, choices=range(1, 367), metavar="DAYS")
    jw.configure(commands)
    media.configure(commands)
    canvas.configure(commands)
    campus.configure(commands)
    library.configure(commands)
    portal.configure(commands)
    args = parser.parse_args(argv)
    if args.command == "jw" and args.operation == "withdrawals":
        if args.apply and not args.term:
            parser.error("withdrawals --apply 需要指定 --term")
        if (args.term or args.preview) and not args.apply:
            parser.error("withdrawals 的 --term 与 --preview 需要搭配 --apply")
    args.json = options.json
    return args


def site_items(args, site, context, page, now):
    day = now.date()
    if site == "chaoxing":
        from tongji_cli import chaoxing
        if args.command in {"today", "week"}:
            result = chaoxing.assignments(context, page)
            if args.command == "today":
                result["undated_assignments"] = [x for x in result["items"] if not x.get("due")]
                result["items"] = [x for x in result["items"] if x.get("due") and x["due"][:10] == day.isoformat()]
            return result
        return chaoxing.run(args, context, page, now)
    if args.command in {"today", "week"}:
        return schedule_items(args, site, context, page, day)
    if site == "stadium":
        return campus.sports_items(args, page)
    if site == "card":
        return campus.card_items(args, page, day)
    if site == "space":
        return library.space_items(args, page)
    if site == "jw":
        return jw.run(args, page, day)
    if site == "media":
        return media.run(args, page)
    return canvas.run(args, context, page, now)


def run(args):
    now = datetime.now(SHANGHAI)
    if (args.command == "library" and args.operation in {"study", "rooms"} and args.action == "reserve"
            and not args.preview and not sys.stdin.isatty()):
        return display({"library": {"status": "unverified", "detail": "请在交互终端运行，或加 --preview 核对所选预约"}}, args.json)
    if args.command == "sports" and args.operation == "reserve" and not args.preview and not sys.stdin.isatty():
        return display({"sports": {"status": "unverified", "detail": "请在交互终端运行以完成场馆下单，或加 --preview 查看金额"}}, args.json)
    if args.command == "sports" and args.operation in {"slots", "orders", "reserve"}:
        args.site = "stadium"
        return display({"sports": signed_in_queries(args, now, site_items)["stadium"]}, args.json)
    if args.command == "card" and args.operation in {"balance", "transactions"}:
        return display(signed_in_queries(args, now, site_items), args.json)
    if args.command == "library" and (args.operation in {"reservations", "study", "rooms"} or
                                      (args.operation == "seats" and args.action in {"availability", "list", "reserve"})):
        args.site = "space"
        return display({"library": signed_in_queries(args, now, site_items)["space"]}, args.json)
    if args.command in {"calendar", "rooms", "bus", "library", "service", "notices", "sports", "clinic", "card", "dorm"}:
        try:
            if args.command == "service":
                entry = portal.run(args)
            elif args.command == "library":
                entry = library.run(args)
            else:
                entry = campus.run(args, now.date())
        except (QueryUnavailable, OSError, Error, ValueError, KeyError, TypeError) as error:
            entry = failure(error)
        return display({args.command: entry}, args.json)
    results = signed_in_queries(args, now, site_items)
    if args.command == "week":
        results = week_view(results, now.date())
    return display(results, args.json)


def main():
    try:
        return run(arguments())
    except Error as error:
        if "SingletonLock" in str(error) or "ProcessSingleton" in str(error):
            sys.exit("专用 Chrome 正被另一条 tongji 命令使用，请在它结束后重试。")
        sys.exit("Chrome 未完成操作。请确认已安装 Chrome，并保持专用窗口打开。")
