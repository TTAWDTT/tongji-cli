from datetime import timedelta

from tongji_cli.jw.competitions import LEVELS
from tongji_cli.jw.timetable import timetable, timetable_range


def configure(commands):
    jw = commands.add_parser("jw").add_subparsers(dest="operation", required=True)
    menu = jw.add_parser("menu", help="从本人的教务侧栏查入口和完整菜单路径")
    menu.add_argument("--section", help="只列出指定的一级菜单")
    menu.add_argument("--search", help="按名称或菜单路径搜索")
    announcements = jw.add_parser("notices", help="查看本人教务工作台的通知公告").add_subparsers(dest="action", required=True)
    announcements.add_parser("list").add_argument("--search", help="在全部公告标题中搜索")
    announcements.add_parser("show").add_argument("id", type=int, help="教务公告编号")
    image = announcements.add_parser("image", help="保存公告中的一张原图")
    image.add_argument("id", type=int, help="教务公告编号")
    image.add_argument("--index", type=int, required=True, help="show 返回的图片序号，从 1 开始")
    image.add_argument("--output", required=True, help="新文件路径")
    applications = jw.add_parser("applications", help="查询教务工作台“我的申请”").add_subparsers(dest="action", required=True)
    applications.add_parser("list", help="查看本人申请及当前审批状态")
    applications.add_parser("show", help="读取指定申请的详情和审批进度").add_argument("number", help="列表中的完整申请编号")
    mentors = jw.add_parser("mentors", help="查本人的导师资料和新生见面会").add_subparsers(dest="action", required=True)
    profile = mentors.add_parser("profile", help="按新生、学院或互选导师入口查看本人导师")
    profile.add_argument("kind", choices=["freshman", "college", "mutual"])
    mentors.add_parser("meetings", help="列出新生导师见面会的时间和地点")
    guides = jw.add_parser("help-center", help="查教务帮助中心的指南、常见问题和附件").add_subparsers(dest="action", required=True)
    guides.add_parser("list", help="列出教务帮助主题").add_argument("--search", help="按主题关键词筛选")
    guides.add_parser("show", help="查看正文和附件编号").add_argument("id", type=int, help="帮助条目编号")
    guide_file = guides.add_parser("download", help="保存指定帮助条目的附件原件")
    guide_file.add_argument("id", type=int, help="帮助条目编号")
    guide_file.add_argument("--attachment", type=int, required=True, help="show 返回的附件编号")
    guide_file.add_argument("--output", required=True, help="新文件路径")
    graduation = jw.add_parser("graduation", help="查看毕业设计安排").add_subparsers(dest="action", required=True)
    graduation.add_parser("defenses", help="查教务公布给本人的课题、答辩时间和地点")
    from tongji_cli.jw.graduation import TASK_STATES
    tasks = graduation.add_parser("tasks", help="查毕业设计任务书目录及状态")
    tasks.add_argument("--year", type=int, help="四位课题年份")
    tasks.add_argument("--title", help="按课题名称筛选")
    tasks.add_argument("--advisor", help="使用教务页面的导师筛选框")
    tasks.add_argument("--state", choices=list(TASK_STATES), help="任务书状态")
    tasks.add_argument("--page", type=int, default=1, help="从 1 开始的目录页码")
    forms = jw.add_parser("forms", help="查学籍表格与毕业设计文件").add_subparsers(dest="action", required=True)
    form_list = forms.add_parser("list", help="列出指定目录的表格与手册")
    form_list.add_argument("--search", help="按文件名或说明筛选")
    form_file = forms.add_parser("download", help="保存所选校方文件")
    for sub in (form_list, form_file):
        sub.add_argument("catalog", choices=["student-status", "graduation"], help="学籍管理或毕业设计")
    form_file.add_argument("id", help="所选目录返回的文件编号")
    form_file.add_argument("--output", required=True, help="新文件路径")
    schemes = jw.add_parser("schemes", help="查询教务“我的培养方案”").add_subparsers(dest="action", required=True)
    schemes.add_parser("list", help="列出可选方案和编号")
    scheme = schemes.add_parser("show", help="读取方案的章节、学分要求与各学期教学安排")
    scheme.add_argument("id", help="schemes list 返回的方案 ID")
    scheme.add_argument("--chapter", help="只读指定章节，填写完整章节名")
    figure = schemes.add_parser("image", help="保存指定章节内的原图")
    figure.add_argument("id")
    figure.add_argument("--chapter", required=True, help="show 返回的章节名")
    figure.add_argument("--index", type=int, required=True, help="本章图片序号，从 1 开始")
    figure.add_argument("--output", required=True, help="新文件路径")
    progress = jw.add_parser("progress", help="查询本人课程的教学进度").add_subparsers(dest="action", required=True)
    progress_list = progress.add_parser("list", help="查看教学班、任课教师、调课与进度状态")
    progress_list.add_argument("--search", help="按课程名称、课程编号或任课教师筛选")
    progress_show = progress.add_parser("show", help="查看指定进度记录的授课安排及答疑信息")
    progress_show.add_argument("id", help="progress list 返回的进度记录 ID")
    for sub in (progress_list, progress_show):
        sub.add_argument("--term", help="例如 2025-2026第2学期，默认使用教务当前学期")
    competitions = jw.add_parser("competitions", help="查询创新创业竞赛目录及学校列出的获奖等级")
    competitions.add_argument("keyword", nargs="?", default="", help="竞赛名称关键词")
    competitions.add_argument("--level", choices=list(LEVELS))
    competitions.add_argument("--valid", choices=["是", "否"])
    competitions.add_argument("--page", type=int, default=1)
    syllabi = jw.add_parser("syllabus", help="查教务系统发布的课程教学大纲").add_subparsers(dest="action", required=True)
    search = syllabi.add_parser("search", help="按课程编码、代码或名称搜索大纲目录")
    search.add_argument("keyword", nargs="?", default="")
    search.add_argument("--page", type=int, default=1)
    detail = syllabi.add_parser("show", help="查看指定课程大纲的正文、考核及教材")
    detail.add_argument("keyword", metavar="课程编码或代码")
    detail.add_argument("--id", help="同一课程有多份大纲时指定大纲编号")
    for sub in (search, detail):
        sub.add_argument("--term", help="完整学期名，默认使用教务页面当前学期")
    major = jw.add_parser("major-timetable", help="查本人所在专业的学期课表")
    major.add_argument("--term", help="默认教务当前学期，例如 2025-2026第2学期")
    major.add_argument("--search", help="匹配校方排课文字中的课程、教师或教室")
    tt = jw.add_parser("timetable").add_mutually_exclusive_group()
    tt.add_argument("--today", action="store_true")
    tt.add_argument("--week", choices=["this", "next"])
    plan = jw.add_parser("plan", help="查询个人培养计划的课程明细")
    export = plan.add_subparsers(dest="action").add_parser("export", help="导出校方原始培养计划压缩包")
    export.add_argument("--output", required=True, help="新建 ZIP 文件路径")
    enrollment = jw.add_parser("enrollment", help="个人选课入口状态与申请结果").add_subparsers(dest="action", required=True)
    enrollment.add_parser("status", help="核对个人选课页面当前显示的状态")
    enrollment.add_parser("requests", help="查看个人选课申请和学校回复")
    enroll = enrollment.add_parser("apply", help="在教务页由本人选课，完成后核对个人课表")
    enroll.add_argument("code", metavar="新课程序号")
    enroll.add_argument("--term", required=True, help="教务页面的完整学期名")
    enroll.add_argument("--preview", action="store_true")
    retakes = jw.add_parser("retakes", help="查询本学期重考窗口及个人课程").add_subparsers(dest="action")
    apply = retakes.add_parser("apply", help="按新课程序号申请一门重考")
    apply.add_argument("code", metavar="新课程序号")
    apply.add_argument("--preview", action="store_true", help="只核对课程与申请资格")
    withdrawal = jw.add_parser("withdrawals", help="期中退课页面中的本人课程状态")
    mode = withdrawal.add_mutually_exclusive_group()
    mode.add_argument("--verify", metavar="新课程序号", help="同时核对该课是否列于同学期的个人课表")
    mode.add_argument("--apply", metavar="新课程序号", help="在校方页面本人办理期中退课，随后核对记录和课表")
    withdrawal.add_argument("--term", help="办理时指定教务页面的完整学期名")
    withdrawal.add_argument("--preview", action="store_true")
    jw.add_parser("courses").add_argument("--term", help="完整学期名，可用 calendar terms 查询")
    for name in ("exams", "grades", "credits"):
        jw.add_parser(name)


def run(args, page, day):
    if args.operation == "mentors":
        from tongji_cli.jw.mentors import mentor_meetings, mentor_profile
        return mentor_meetings(page) if args.action == "meetings" else mentor_profile(page, args.kind)
    if args.operation == "help-center":
        from tongji_cli.jw.help import help_center
        return help_center(page, args)
    if args.operation == "graduation":
        from tongji_cli.jw.graduation import defenses, task_books
        return defenses(page) if args.action == "defenses" else task_books(page, args)
    if args.operation == "major-timetable":
        from tongji_cli.jw.major_timetable import major_timetable
        return major_timetable(page, args.term, args.search)
    if args.operation == "forms":
        from tongji_cli.jw.forms import forms
        return forms(page, args)
    if args.operation == "schemes":
        from tongji_cli.jw.schemes import schemes
        return schemes(page, args)
    if args.operation == "progress":
        from tongji_cli.jw.progress import progress
        return progress(page, args)
    if args.operation == "competitions":
        from tongji_cli.jw.competitions import competitions
        return competitions(page, args)
    if args.operation == "applications":
        from tongji_cli.jw.applications import applications
        return applications(page, args)
    if args.operation == "notices":
        from tongji_cli.jw.announcements import announcements
        return announcements(page, args)
    if args.operation == "syllabus":
        from tongji_cli.jw.syllabus import syllabus
        return syllabus(page, args)
    if args.operation == "menu":
        from tongji_cli.jw.menu import student_menu
        return student_menu(page, args.section, args.search)
    if personal_change_command(args):
        from tongji_cli.jw.personal_changes import personal_change
        enrolling = args.operation == "enrollment"
        return personal_change(page, "enroll" if enrolling else "withdraw", args.term,
                               args.code if enrolling else args.apply, preview=args.preview)
    if args.operation == "retakes":
        from tongji_cli.jw.retake import retakes
        return retakes(page, getattr(args, "code", None), getattr(args, "preview", False))
    if args.operation == "withdrawals" and args.verify:
        from tongji_cli.jw.records import check_withdrawal
        return check_withdrawal(page, args.verify)
    if args.operation == "plan":
        from tongji_cli.jw.records import personal_plan
        return personal_plan(page, getattr(args, "output", None))
    if args.operation != "timetable":
        from tongji_cli.jw.records import enrollment_status, records
        if args.operation == "enrollment" and args.action == "status":
            return enrollment_status(page)
        return records(page, args.action if args.operation == "enrollment" else args.operation,
                       requested_term=getattr(args, "term", None))
    if not args.week:
        return timetable(page, day)
    monday = day - timedelta(days=day.weekday()) + timedelta(weeks=int(args.week == "next"))
    return timetable_range(page, [monday + timedelta(days=i) for i in range(7)])


def personal_change_command(args):
    return args.command == "jw" and ((args.operation == "enrollment" and args.action == "apply")
                                     or (args.operation == "withdrawals" and args.apply))
