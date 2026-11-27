import base64
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urljoin

from playwright.sync_api import expect

from tongji_cli.jw.records import query_data, record_pages, watch_query
from tongji_cli.common import QueryUnavailable


VIEW = "/myAnnouncement"
LIST = "/api/commonservice/commonMsgPublish/findMyCommonMsgPublish"
DETAIL = "/api/commonservice/commonMsgPublish/findCommonMsgPublishById"


def announcements(page, args):
    url = urljoin(page.url, VIEW)
    items = []
    for rows in record_pages(page, url, LIST, "通知公告"):
        for index, row in enumerate(rows):
            item = {"id": row["id"], "title": row["title"].strip(), "date": (row.get("publishTime") or "").strip().partition(" ")[0] or None, "url": url}
            if args.action == "list":
                if not args.search or args.search.casefold() in item["title"].casefold():
                    items.append(item)
            elif row["id"] == args.id:
                return [open_announcement(page, index, item, args)]
    if args.action != "list":
        raise QueryUnavailable("本人教务公告目录中未找到该编号")
    return items


def open_announcement(page, index, item, args):
    table = page.locator(".el-table:visible").filter(has=page.get_by_text("信息标题", exact=True))
    button = table.locator(".el-table__body-wrapper tr:visible").nth(index).get_by_role("button")
    expect(button).to_have_text(item["title"])
    with watch_query(page, DETAIL) as opened:
        button.click()
    detail = query_data(opened.value)
    if detail["id"] != item["id"] or detail["title"].strip() != item["title"]:
        raise QueryUnavailable("教务打开的公告与所选编号不一致")
    dialog = page.locator(".el-dialog:visible")
    expect(dialog.locator(".title-span")).to_have_text(item["title"])
    content = dialog.locator(".info-content")
    content.wait_for(state="attached")
    images = content.locator("img")
    if args.action == "image":
        return {**item, **save_image(images, args.index, args.output)}
    links = dialog.locator(".info a[href]").evaluate_all("""links => links
        .filter(a => ['https:', 'http:'].includes(a.protocol))
        .map(a => ({title: a.innerText.trim(), url: a.href}))""")
    media = images.evaluate_all("""images => images.map((img, i) => ({
        index: i + 1, alt: img.alt, url: /^https?:/.test(img.src) ? img.src : null
    }))""")
    attachments = [line.strip() for block in dialog.locator(".info-attach").all_inner_texts()
                   for line in block.splitlines() if line.strip()]
    return {**item, "body": content.inner_text().strip(), "links": links, "images": media,
            "attachments": attachments}


def save_image(images, index, output):
    if not 1 <= index <= images.count():
        raise QueryUnavailable("所选图片序号不在正文中，请用 show 查看配图序号")
    dest = Path(output).expanduser().absolute()
    if dest.exists() or not dest.parent.is_dir():
        raise QueryUnavailable("请在已有目录中指定一个新文件名")
    result = images.nth(index - 1).evaluate("""async img => {
        try {
            const url = new URL(img.currentSrc || img.src);
            if (!['data:', 'https:', 'http:'].includes(url.protocol)) return null;
            const response = await fetch(url);
            if (!response.ok) return null;
            const blob = await response.blob();
            if (!blob.size || !blob.type.startsWith('image/')) return null;
            return await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve({data: reader.result.split(',')[1], type: blob.type});
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            });
        } catch { return null; }
    }""")
    if not result:
        raise QueryUnavailable("浏览器未取得此配图的原始文件，请在学校原页面查看")
    payload = base64.b64decode(result["data"], validate=True)
    with TemporaryDirectory(dir=dest.parent) as tmp:
        staged = Path(tmp) / "image"
        staged.write_bytes(payload)
        os.link(staged, dest)
    return {"index": index, "path": str(dest), "bytes": len(payload), "content_type": result["type"]}
