import os
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, unquote, urlsplit

from playwright.sync_api import Error, expect

from portal_legacy import CENTER, CERTIFICATES, ORDER_LIST, order_pages, run, source_path, visible_orders
from queries import QueryUnavailable


def download(profile, receipt, output, preview=False):
    receipt = receipt.strip()
    if not receipt:
        raise QueryUnavailable("请输入 service certificates 返回的完整订单号")
    destination = None
    if not preview:
        if not output:
            raise QueryUnavailable("请用 --output 指定新的 PDF 文件路径")
        destination = Path(output).expanduser().absolute()
        if destination.exists() or not destination.parent.is_dir():
            raise QueryUnavailable("请在已有目录中指定一个新文件名")
    return run(profile, CERTIFICATES, True, None, lambda page, _: download_page(page, receipt, destination))


def download_page(page, receipt, destination):
    selected = completed_row(page, receipt)
    fields, row = selected
    row.get_by_text("查看详情", exact=True).click()
    button = page.get_by_role("button", name="再次下载", exact=True)
    expect(button).to_be_enabled()
    if not detail_matches(page.url, receipt):
        raise QueryUnavailable("电子证明详情地址与已完成订单号不一致")
    page.get_by_text(fields["文件名称"], exact=True).filter(visible=True).first.wait_for()
    item = {"receipt": receipt, "title": fields["文件名称"], "source": CENTER}
    if destination is None:
        return {"status": "ok", "items": [dict(item, state="download_preview")],
                "detail": "已核对本人订单详情及再次下载入口。"}
    with TemporaryDirectory(dir=destination.parent) as directory:
        staged = Path(directory) / "certificate.pdf"
        try:
            with page.expect_download(timeout=30000) as pending:
                button.click()
            pending.value.save_as(staged)
        except Error:
            raise QueryUnavailable("未收到该校方订单的完整下载文件，请在已完成文件中查看领取方式。") from None
        check_pdf(staged)
        os.link(staged, destination)
    return {"status": "ok", "items": [dict(item, state="downloaded", path=str(destination),
                                            bytes=destination.stat().st_size)]}


def detail_matches(url, receipt):
    address = urlsplit(url)
    if address.hostname != CENTER:
        return False
    for part in [address, urlsplit(address.fragment)]:
        if receipt in [unquote(segment) for segment in part.path.split("/")]:
            return True
        if any(value == receipt for _, value in parse_qsl(part.query)):
            return True
    return False


def completed_row(page, receipt):
    matches = []
    keys = set()
    for page_number, (total, rows) in enumerate(order_pages(page, "已完成文件"), 1):
        for key, _, _, fields in rows:
            if key in keys:
                raise QueryUnavailable("已完成文件存在重复订单号，无法唯一定位文件")
            keys.add(key)
            if key == receipt:
                matches.append((page_number, fields))
    if len(keys) != total:
        raise QueryUnavailable("电子证明订单数量与校方总数不符")
    if len(matches) != 1:
        raise QueryUnavailable("本人已完成文件中未找到该订单号")
    target, fields = matches[0]
    while page_number > target:
        with page.expect_response(source_path(ORDER_LIST)) as response:
            page.locator(".ivu-page-prev:visible").click()
        data = response.value.json()
        page_number -= 1
        if not response.value.ok or data.get("pageNumber") != page_number or data.get("total") != total:
            raise QueryUnavailable("返回目标页时，已完成文件清单发生变化")
        rows = visible_orders(page, data["rows"], "已完成文件")
    positions = [index for index, row in enumerate(rows) if row[0] == receipt and row[3] == fields]
    if len(positions) != 1:
        raise QueryUnavailable("无法在可见列表中复核该订单")
    return fields, page.locator("table:visible tbody tr:visible").nth(positions[0])


def check_pdf(path):
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise QueryUnavailable("学校返回的文件不是 PDF")
            stream.seek(0)
            reader = PdfReader(stream, strict=True)
            if not len(reader.pages):
                raise QueryUnavailable("学校返回的 PDF 未含可读页面")
    except (PyPdfError, ValueError, IndexError, KeyError, OSError):
        raise QueryUnavailable("学校返回的 PDF 无法完整读取，文件未保存。") from None
