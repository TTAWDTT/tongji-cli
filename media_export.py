import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zipfile import BadZipFile, ZipFile

from playwright.sync_api import TimeoutError as BrowserTimeout, expect

from media_sessions import sessions
from notices import save_school_attachment
from queries import QueryUnavailable


PARTS = {"slides": ("PPT课件", "1"), "transcript": ("语音识别-原文", "2"),
         "translation": ("语音识别-译文", "3")}
EXPORT_PATH = "/courseapi/v2/export/"


def export_courseware(page, args):
    destination = Path(args.output).expanduser().absolute()
    if destination.exists() or not destination.parent.is_dir():
        raise QueryUnavailable("请选择现有目录中的新文件路径")
    choices = set(args.include or ["slides"])
    rows = sessions(page, args.course, "回放")
    matches = [r for r in rows if str(r["id"]) == str(args.id) and r.get("url")]
    if len(matches) != 1:
        raise QueryUnavailable("未找到该课程的智播回放，请用 media sessions --status 回放 核对课次 ID")
    session = matches[0]
    page.goto(session["url"], wait_until="domcontentloaded")
    try:
        trigger = page.get_by_text("导出课件", exact=True).filter(visible=True)
        trigger.wait_for(timeout=10000)
    except BrowserTimeout as error:
        raise QueryUnavailable("学校播放页未显示该课次的课件导出入口") from error
    expect(page.locator(".course_name")).to_contain_text(session["title"])
    trigger.click()
    confirm, extension = configure_export(page.locator(".el-dialog:visible"), choices)
    download, filename = download_export(page, confirm, choices, session["id"])
    validate_document(download, filename, extension)
    saved = save_school_attachment(download, filename, destination)
    return [{**saved, "id": session["id"], "course": session["course"], "title": session["title"],
             "filename": filename, "included": [label for key, (label, _) in PARTS.items() if key in choices],
             "source": session["url"]}]


def configure_export(dialog, choices):
    for key, (name, _) in PARTS.items():
        label = dialog.locator("label").filter(has_text=name)
        if not label.count() and key not in choices:
            continue
        if label.count() != 1:
            raise QueryUnavailable(f"学校导出面板未提供唯一的“{name}”选项")
        box = label.locator('input[type="checkbox"]')
        selected = key in choices
        if box.is_checked() != selected:
            if not box.is_enabled():
                raise QueryUnavailable(f"本次导出无法更改“{name}”")
            label.click()
            expect(box).to_be_checked(checked=selected)
    confirm = dialog.get_by_role("button", name="确认导出", exact=False)
    label = confirm.inner_text()
    if "(PPT)" in label:
        return confirm, ".pptx"
    if "(Word)" in label:
        return confirm, ".docx"
    raise QueryUnavailable("学校未显示可核对的导出格式")


def download_export(page, confirm, choices, session_id):
    generation = []
    def record_generation(response):
        if urlsplit(response.url).path == EXPORT_PATH + "export-async":
            generation.append(response)

    page.on("response", record_generation)
    try:
        with page.expect_download(timeout=180000) as downloaded:
            with page.expect_response(lambda r: urlsplit(r.url).path == EXPORT_PATH + "get-courseware-status") as checked:
                confirm.click()
            first = checked.value
            params = parse_qs(urlsplit(first.url).query)
            parts = {PARTS[key][1] for key in choices}
            if (first.request.method != "GET" or params.get("sub_id") != [str(session_id)]
                    or set(params.get("type", [""])[0].split(",")) != parts):
                raise QueryUnavailable("校方导出请求与选定课次或内容不符")
            result = export_response(first)
            if result["code"] != 0:
                result = wait_for_file(page, first.request, result, generation)
                page.evaluate("""file => {
                    const a = document.createElement('a');
                    a.href = file.path_name;
                    a.download = file.file_name;
                    document.body.append(a);
                    a.click();
                    a.remove();
                }""", result["data"])
        return downloaded.value, result["data"]["file_name"]
    finally:
        page.remove_listener("response", record_generation)


def export_response(response):
    if not response.ok:
        raise QueryUnavailable(f"校方课件导出服务返回 HTTP {response.status}")
    return response.json()


def wait_for_file(page, request, result, generation):
    deadline = time.monotonic() + 150
    while result["code"] != 0:
        if not (result["code"] == 200 or (result["code"] == 1 and result.get("msg") == "未找到下载记录")):
            raise QueryUnavailable("校方课件导出结果：" + str(result.get("msg") or result["code"]))
        if generation:
            created = export_response(generation.pop())
            if created["code"] != 0:
                raise QueryUnavailable("校方未接受课件生成请求：" + str(created.get("msg") or created["code"]))
        if time.monotonic() >= deadline:
            raise QueryUnavailable("校方尚未生成文件，可稍后用相同课次和内容再次查询")
        page.wait_for_timeout(1500)
        result = export_response(page.request.fetch(request, max_redirects=0, timeout=15000))
    return result


def validate_document(download, filename, extension):
    if Path(filename).suffix.lower() != extension:
        raise QueryUnavailable("校方文件名与导出面板显示的格式不符")
    document = "ppt/presentation.xml" if extension == ".pptx" else "word/document.xml"
    try:
        with ZipFile(download.path()) as archive:
            if document in archive.namelist():
                return
    except BadZipFile:
        pass
    raise QueryUnavailable("下载内容与校方标注的 Office 文档格式不符")
