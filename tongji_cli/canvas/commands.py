import argparse
import re
from datetime import date

from tongji_cli.canvas import api as canvas_api
from tongji_cli.canvas.assignments import assignments


def duration(raw):
    match = re.fullmatch(r"([1-9][0-9]{0,2})d", raw)
    if not match:
        raise argparse.ArgumentTypeError("请使用 1d 至 999d，例如 7d")
    return int(match[1])


def configure(commands):
    canvas = commands.add_parser("canvas").add_subparsers(dest="operation", required=True)
    course_list = canvas.add_parser("courses", help="查询本人的 Canvas 课程")
    groups = canvas.add_parser("groups", help="查看本人当前或往期小组、课程、学期及可进入的链接")
    navigation = canvas.add_parser("navigation", help="查看本人在该课程或小组页面能使用的导航入口")
    totals = canvas.add_parser("grades", help="查询本人课程的 Canvas 总评")
    totals.add_argument("--course")
    grading = canvas.add_parser("grading", help="查看教师设置的作业分组、权重和舍分规则")
    grading.add_argument("--course", required=True)
    syllabus = canvas.add_parser("syllabus", help="查看课程大纲正文、链接和图片地址")
    syllabus.add_argument("--course", required=True)
    inbox = canvas.add_parser("inbox", help="读取本人 Canvas 收件箱，可按文件夹或课程筛选")
    inbox.add_argument("--scope", choices=["inbox", "unread", "starred", "sent", "archived"], default="inbox")
    inbox.add_argument("--course", help="课程名称、代码或 ID")
    recipients = canvas.add_parser("recipients", help="按姓名搜索本人可以发消息的用户")
    recipients.add_argument("keyword", help="姓名或部分姓名")
    recipients.add_argument("--course", help="限指定在读课程")
    conversation = canvas.add_parser("conversation", help="查看本人会话或发消息").add_subparsers(dest="action", required=True)
    thread = conversation.add_parser("show", help="读取会话及消息，保留未读状态")
    thread.add_argument("id", type=int, help="canvas inbox 返回的会话 ID")
    compose = conversation.add_parser("send", help="给指定课程中的一位收件人发消息")
    compose.add_argument("--course", required=True)
    compose.add_argument("--to", required=True, type=int, help="canvas recipients 返回的用户 ID")
    compose.add_argument("--subject", required=True)
    compose.add_argument("--message", required=True)
    compose.add_argument("--preview", action="store_true", help="只填写编辑框并核对收件人")
    reply = conversation.add_parser("reply", help="回复会话的全部直接收件人")
    reply.add_argument("id", type=int)
    reply.add_argument("--message", required=True)
    reply.add_argument("--preview", action="store_true", help="只读核对原会话及收件人")
    update = conversation.add_parser("set", help="修改会话的已读、归档或星标状态")
    update.add_argument("id", type=int)
    field = update.add_mutually_exclusive_group(required=True)
    field.add_argument("--state", choices=["read", "unread", "archived"])
    field.add_argument("--star", choices=["on", "off"])
    update.add_argument("--preview", action="store_true", help="只读比较当前和目标状态")
    quiz = canvas.add_parser("quiz", help="查询课程测验及本人的作答记录").add_subparsers(dest="action", required=True)
    quiz_commands = []
    for name in ("list", "show", "submission"):
        command = quiz.add_parser(name)
        quiz_commands.append(command)
        command.add_argument("--course", required=True)
        if name != "list":
            command.add_argument("id", type=int, help="quiz list 返回的 ID")
            command.add_argument("--engine", choices=["classic", "new"], default="classic", help="quiz list 返回的测验类型")
    preferences = canvas.add_parser("notifications", help="本人 Canvas 账户各渠道的通知频率")
    preferences.add_argument("--channel", type=int, help="只看指定渠道 ID")
    preferences.add_argument("--category", help="只看指定类别，例如 announcement")
    setting = canvas.add_parser("notification").add_subparsers(dest="action", required=True).add_parser("set")
    setting.add_argument("--channel", type=int, required=True, help="canvas notifications 输出的渠道 ID")
    setting.add_argument("--category", required=True, help="要调整的通知类别")
    setting.add_argument("--frequency", choices=["immediately", "daily", "weekly", "never"], required=True)
    setting.add_argument("--preview", action="store_true", help="在账户通知设置中核对目标菜单，不保存")
    files = canvas.add_parser("files", help="列出课程或小组文件及下载所需 ID")
    download = canvas.add_parser("file").add_subparsers(dest="action", required=True).add_parser("download")
    download.add_argument("id", type=int)
    download.add_argument("--output", required=True, help="新建的本地文件路径")
    topics = canvas.add_parser("discussions", help="课程或小组的讨论主题")
    discussion = canvas.add_parser("discussion").add_subparsers(dest="action", required=True)
    create_topic = discussion.add_parser("create", help="在课程或小组中保存新的普通讨论主题")
    create_topic.add_argument("--title", required=True)
    create_topic.add_argument("--message", required=True, help="纯文本正文")
    create_topic.add_argument("--preview", action="store_true", help="核对新讨论表单和保存按钮")
    reply = discussion.add_parser("reply", help="回复讨论主题或指定发言")
    reply.add_argument("id", type=int)
    reply.add_argument("--parent", type=int, help="所回复发言的 ID")
    reply.add_argument("--message", required=True, help="纯文本正文")
    reply.add_argument("--preview", action="store_true", help="核对回复目标及编辑框")
    topic = discussion.add_parser("show")
    topic.add_argument("id", type=int)
    topic.add_argument("--replies", action="store_true", help="同时读取对本人可见的讨论回复")
    events = canvas.add_parser("calendar", help="查询个人日历，可指定课程日历")
    events.add_argument("--course")
    events.add_argument("--from", dest="start_day", type=date.fromisoformat, metavar="YYYY-MM-DD")
    events.add_argument("--next", type=duration, default=7, metavar="7d")
    plan = canvas.add_parser("planner", help="按日期查询 Canvas 学习计划，含测验、讨论等事项")
    plan.add_argument("--from", dest="start_day", type=date.fromisoformat, metavar="YYYY-MM-DD")
    plan.add_argument("--next", type=duration, default=7, metavar="7d")
    pages = canvas.add_parser("pages", help="列出课程或小组 Wiki 页面及其 slug")
    detail = canvas.add_parser("page").add_subparsers(dest="action", required=True).add_parser("show")
    detail.add_argument("slug")
    for command in (navigation, files, download, topics, topic, reply, create_topic, pages, detail):
        target = command.add_mutually_exclusive_group(required=True)
        target.add_argument("--course", help="课程名称、代码或 ID")
        target.add_argument("--group", type=int, help="canvas groups 列出的可进入小组 ID")
    receipt = canvas.add_parser("submission", help="本人作业提交回执与反馈")
    receipt.add_argument("id", type=int)
    receipt.add_argument("--course", required=True)
    receipt.add_argument("--history", action="store_true", help="按尝试次数列出本人各次交件的时间、内容与附件编号")
    tasks = canvas.add_parser("assignments")
    tasks.add_argument("--course")
    window = tasks.add_mutually_exclusive_group()
    window.add_argument("--due", choices=["today"])
    window.add_argument("--next", type=duration, metavar="7d")
    window.add_argument("--overdue", action="store_true")
    actions = canvas.add_parser("assignment").add_subparsers(dest="action", required=True)
    send = actions.add_parser("submit", help="按作业允许的方式提交并核对本人回执")
    send.add_argument("id", type=int)
    send.add_argument("--course", required=True)
    payload = send.add_mutually_exclusive_group(required=True)
    payload.add_argument("--file", action="append", help="本地文件，可重复指定")
    payload.add_argument("--text", help="要提交的纯文本，可含换行")
    payload.add_argument("--url", help="要提交的网页完整地址")
    send.add_argument("--preview", action="store_true", help="按该作业允许的类型核对交件内容")
    show = actions.add_parser("show")
    show.add_argument("id", type=int)
    show.add_argument("--course", required=True)
    attachment = actions.add_parser("download", help="下载本人这份作业的提交或反馈附件")
    attachment.add_argument("id", type=int, help="作业 ID")
    attachment.add_argument("--course", required=True)
    attachment.add_argument("--attachment", required=True, type=int, help="canvas submission 列出的附件 ID")
    attachment.add_argument("--attempt", type=int, help="下载指定尝试的本人提交附件")
    attachment.add_argument("--output", required=True, help="保存到新文件")
    rubric = actions.add_parser("rubric", help="查看作业评分量规的标准、等级和分值")
    rubric.add_argument("id", type=int)
    rubric.add_argument("--course", required=True)
    materials = canvas.add_parser("materials", help="查课程模块和讲义目录")
    materials.add_argument("--course", required=True)
    canvas_notices = canvas.add_parser("announcements", help="最近的课程公告，或指定小组的公告")
    canvas_notices.add_argument("--since", type=duration, default=7, metavar="7d")
    audience = canvas_notices.add_mutually_exclusive_group()
    audience.add_argument("--course", help="课程名称、代码或 ID")
    audience.add_argument("--group", type=int, help="canvas groups 返回的小组 ID")
    for course_query in (course_list, groups, navigation, totals, grading, syllabus, rubric, materials, files, download, pages, detail, tasks, show, receipt, attachment, topics, topic, canvas_notices, *quiz_commands):
        course_query.add_argument("--state", choices=["active", "completed"], default="active",
                                  help="active 查在读，completed 查已结课")


def run(args, context, page, now):
    day = now.date()
    if args.operation in {"grades", "grading"}:
        from tongji_cli.canvas.grades import grades, grading
        return (grades if args.operation == "grades" else grading)(context, args.course, args.state)
    if args.operation == "quiz":
        from tongji_cli.canvas.quizzes import quizzes, quiz_detail, quiz_submission
        if args.action == "list":
            return quizzes(context, args.course, args.state)
        read = quiz_detail if args.action == "show" else quiz_submission
        return read(context, args.course, args.id, args.engine, args.state)
    if args.operation == "inbox":
        from tongji_cli.canvas.inbox import inbox
        return inbox(context, args.scope, args.course)
    if args.operation == "recipients":
        from tongji_cli.canvas.inbox import recipients
        return recipients(context, args.keyword, args.course)
    if args.operation == "conversation":
        if args.action == "send":
            from tongji_cli.canvas.compose import send_message
            return send_message(context, page, args.course, args.to, args.subject, args.message, args.preview)
        if args.action == "reply":
            from tongji_cli.canvas.thread_actions import reply
            return reply(context, page, args.id, args.message, args.preview)
        if args.action == "set":
            from tongji_cli.canvas.thread_actions import set_state
            return set_state(context, page, args.id, args.state, args.star, args.preview)
        from tongji_cli.canvas.inbox import conversation
        return conversation(context, args.id)
    if args.operation in {"notification", "notifications"}:
        from tongji_cli.canvas.notifications import notification_settings
        return notification_settings(context, page, args)
    if args.operation in {"discussion", "discussions"}:
        from tongji_cli.canvas.navigation import select_group
        state = getattr(args, "state", "active")
        group = select_group(page, args.group, state) if args.group is not None else None
        if getattr(args, "action", None) == "create":
            from tongji_cli.canvas.discussion import create_topic
            return create_topic(context, page, args.course, args.title, args.message, args.preview, group=group)
        if getattr(args, "action", None) == "reply":
            from tongji_cli.canvas.discussion import reply
            return reply(context, page, args.course, args.id, args.parent, args.message, args.preview, group=group)
        return canvas_api.discussions(context, args.course, getattr(args, "id", None),
                                      getattr(args, "replies", False), state, group=group)
    if args.operation in {"files", "file", "pages", "page"} and args.group is not None:
        from tongji_cli.canvas.navigation import select_group
        group = select_group(page, args.group, args.state)
        if args.operation in {"pages", "page"}:
            return canvas_api.scoped_pages(context, "groups", group, getattr(args, "slug", None))
        if args.operation == "files":
            return canvas_api.scoped_files(context, "groups", group["id"])
        return canvas_api.download_scoped_file(context, "groups", group["id"], args.id, args.output)
    if args.operation == "files":
        return canvas_api.course_files(context, args.course, args.state)
    if args.operation == "syllabus":
        return canvas_api.syllabus(context, args.course, args.state)
    if args.operation == "file":
        return canvas_api.download_file(context, args.course, args.id, args.output, args.state)
    if args.operation == "calendar":
        return canvas_api.calendar_events(context, args.start_day or day, args.next, args.course)
    if args.operation == "planner":
        return canvas_api.planner(context, args.start_day or day, args.next)
    if args.operation in {"page", "pages"}:
        return canvas_api.course_pages(context, args.course, getattr(args, "slug", None), args.state)
    if args.operation == "submission":
        return canvas_api.own_submission(context, args.course, args.id, args.state, history=args.history)
    if args.operation == "groups":
        from tongji_cli.canvas.navigation import groups
        return groups(page, args.state)
    if args.operation == "navigation":
        from tongji_cli.canvas.navigation import navigation
        return navigation(context, page, args)
    if args.operation == "courses":
        return canvas_api.courses(context, args.state)
    if args.operation == "assignment":
        if args.action == "download":
            return canvas_api.download_submission_attachment(context, args.course, args.id, args.attachment,
                                                            args.output, args.state, attempt=args.attempt)
        if args.action == "rubric":
            from tongji_cli.canvas.grades import rubric
            return rubric(context, args.course, args.id, args.state)
        if args.action == "submit":
            from tongji_cli.canvas.submit import submit
            return submit(context, page, args.course, args.id, args.file, args.preview,
                          text=args.text, url=args.url)
        return canvas_api.show_assignment(context, args.course, args.id, args.state)
    if args.operation == "materials":
        return canvas_api.materials(context, args.course, args.state)
    if args.operation == "announcements":
        from tongji_cli.canvas.navigation import select_group
        group = select_group(page, args.group, args.state) if args.group is not None else None
        return canvas_api.announcements(context, args.since, now, args.course, args.state, group=group)
    if args.state == "active" and not (args.course or args.next or args.overdue):
        return assignments(context, day)
    return canvas_api.tasks(context, day, 1 if args.due else args.next, args.course, args.overdue, args.state)
