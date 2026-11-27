from tongji_cli.browser_session import PROFILE
from tongji_cli.common import QueryUnavailable
from tongji_cli.portal.guides import service_results


def configure(commands):
    service = commands.add_parser("service", help="查找一网通办和学校公开的办事指南")
    operations = service.add_subparsers(dest="operation", required=True)
    apply = operations.add_parser("apply", help="按事项全名进入校方办理页面，办理后核对新增办件")
    apply.add_argument("title", metavar="完整事项名称")
    apply.add_argument("--source", choices=["txd", "portal"], default="txd", help="txd 为同心搭，portal 为旧版一网通办")
    apply.add_argument("--template", metavar="模板全名", help="旧门户学生电子证明中的指定模板")
    apply.add_argument("--preview", action="store_true", help="核对事项及表单入口")
    applications = operations.add_parser("applications", help="一网通办中我发起的办件与进度")
    certificates = operations.add_parser("certificates", help="查看电子证明中心的本人已完成文件记录")
    certificates.add_argument("--template", metavar="模板全名", help="只看由该模板签发的已完成文件记录")
    certificate = operations.add_parser("certificate", help="读取已完成的电子证明").add_subparsers(dest="action", required=True)
    download = certificate.add_parser("download", help="从订单详情再次下载已签发的 PDF")
    download.add_argument("receipt", metavar="订单号", help="service certificates 返回的 receipt")
    download.add_argument("--output", help="保存到新的本地 PDF 文件路径")
    download.add_argument("--preview", action="store_true", help="仅核对订单和再次下载入口")
    applications.add_argument("--with-flow", action="store_true", help="同时查看每件申请的流转记录")
    tasks = operations.add_parser("tasks", help="本人待办、已办任务")
    tasks.add_argument("--state", choices=["pending", "processed"], help="只查待办或已办")
    forms = operations.add_parser("forms", help="按标题搜索研究生院常用下载的表格和指南")
    forms.add_argument("keyword", nargs="?", default="", help="省略关键词列出全部")
    form = operations.add_parser("form", help="读一项研究生院材料的说明和附件链接")
    form.add_argument("url", help="service forms 返回的原文链接")
    form.add_argument("--attachment", help="需下载的完整附件名称，与 --output 一起使用")
    form.add_argument("--output", help="另存到新的文件路径")
    find = operations.add_parser("find")
    find.add_argument("query", help="事项名或关键词，例如在读证明")


def run(args):
    if args.operation in {"forms", "form"}:
        from tongji_cli.campus.notices import graduate_forms
        return graduate_forms(args)
    if args.operation == "certificates":
        from tongji_cli.portal.legacy import certificates
        return certificates(PROFILE, args.template)
    if args.operation == "certificate":
        from tongji_cli.portal.certificate_download import download
        if not args.preview and not args.output:
            raise QueryUnavailable("下载电子证明需要 --output 指定新文件路径")
        return download(PROFILE, args.receipt, args.output, args.preview)
    if args.operation == "apply":
        if args.source == "portal":
            from tongji_cli.portal.legacy import apply
            return apply(PROFILE, args.title, args.preview, template=args.template)
        from tongji_cli.portal.apply import apply
        if args.template is not None:
            raise QueryUnavailable("--template 适用于 --source portal 的学生电子证明文件")
        return apply(PROFILE, args.title, args.preview)
    if args.operation != "find":
        from tongji_cli.portal.records import records
        return records(PROFILE, args.operation, getattr(args, "state", None), getattr(args, "with_flow", False))
    return service_results(args, PROFILE)
