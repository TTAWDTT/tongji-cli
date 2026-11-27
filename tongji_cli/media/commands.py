from tongji_cli.media import courses as media_courses


def configure(commands):
    media = commands.add_parser("media", help="智慧教学媒体资源管理平台").add_subparsers(dest="operation", required=True)
    media.add_parser("courses", help="列出本人在媒体平台的全部课程").add_argument("--search", default="", help="课程名或教师名")
    sessions = media.add_parser("sessions", help="读取课程目录列出的各节课、校方状态及回放入口")
    sessions.add_argument("--course", required=True, help="media courses 列出的课程 ID 或完整课程名")
    sessions.add_argument("--status", help="只列指定的校方状态，例如回放或未开始")
    export = media.add_parser("export", help="导出指定智播回放的课件或语音识别文档")
    export.add_argument("id", type=int, help="media sessions 返回的课次 ID")
    export.add_argument("--course", required=True, help="媒体课程 ID 或完整课程名")
    export.add_argument("--include", choices=["slides", "transcript", "translation"], action="append",
                        help="可重复选择课件、语音原文、译文。默认仅课件")
    export.add_argument("--output", required=True, help="保存到新文件")
    media.add_parser("terms", help="列出媒体平台任务页可选的学期")
    media_tasks = media.add_parser("tasks", help="查本人必做或选做任务，自动读取全部结果页")
    media_tasks.add_argument("--term", default="全部", help="media terms 返回的学期，默认查全部")
    media_tasks.add_argument("--kind", choices=["required", "optional"], default="required")
    media_tasks.add_argument("--status", choices=["已完成", "未完成"], help="筛选必做任务")
    media_tasks.add_argument("--type", dest="task_type", help="校方任务类型名称，例如智播或教学视频")
    media_tasks.add_argument("--search", help="按课程名或任务名搜索")


def run(args, page):
    if args.operation == "courses":
        return media_courses.courses(page, args.search)
    if args.operation == "sessions":
        from tongji_cli.media.sessions import sessions
        return sessions(page, args.course, args.status)
    if args.operation == "export":
        from tongji_cli.media.export import export_courseware
        return export_courseware(page, args)
    from tongji_cli.media.tasks import tasks
    return tasks(page, args)
