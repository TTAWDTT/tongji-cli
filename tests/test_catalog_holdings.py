import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from tongji_cli.library.holdings import holdings, table_rows, COPIES
from tongji_cli.common import QueryUnavailable


class CatalogHoldingsTest(unittest.TestCase):
    def test_reads_two_separate_tables_and_the_sibling_pager(self):
        with sync_playwright() as pw, patch("tongji_cli.library.holdings.BOOK", "http://fixture.local/book/{}"):
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                body = """
                    <section><div class="ant-table-wrapper"><table><thead><tr><th>条码号</th><th>书刊状态</th><th>馆藏地</th></tr></thead>
                    <tbody><tr><td>001</td><td>在架</td><td>书库</td></tr></tbody></table></div>
                    <ul class="ant-pagination"><li class="ant-pagination-item-active">1</li>
                    <li class="ant-pagination-next"><button onclick="nextPage()">下一页</button></li></ul></section>
                    <section><table><thead><tr><th>馆藏地</th><th>可借复本</th><th>当前请求数</th></tr></thead>
                    <tbody><tr><td>书库</td><td>1</td><td>0</td></tr></tbody></table></section>
                    <script>
                    for (const name of ['getDetail', 'groupitems', 'getRequestAndEnreustList']) fetch('/'+name)
                    async function nextPage(){
                        await fetch('/groupitems?page=2')
                        document.querySelector('.ant-pagination-item-active').innerText='2'
                        setTimeout(()=>{
                            const cells=document.querySelector('tbody tr').cells
                            cells[0].innerText='002'
                            cells[1].innerText='借出'
                        },350)
                    }
                    </script>"""

                def reply(route):
                    url = route.request.url
                    if "/book/" in url:
                        route.fulfill(content_type="text/html; charset=utf-8", body=body)
                        return
                    if url.endswith("getDetail"):
                        data = {"clearTitle": "样例书"}
                    elif url.endswith("getRequestAndEnreustList"):
                        data = {"totalCount": 1, "list": [{"locationName": "书库", "onShelfNum": 1, "requestNum": 0}]}
                    else:
                        second = url.endswith("page=2")
                        data = {"totalCount": 2, "list": [{"barcode": "002" if second else "001",
                                                          "processType": "借出" if second else "在架"}]}
                    route.fulfill(json={"success": True, "data": data})

                page.route("**/*", reply)
                row, = holdings(page, 1)
                self.assertEqual([(copy["条码号"], copy["书刊状态"]) for copy in row["copies"]],
                                 [("001", "在架"), ("002", "借出")])
                self.assertEqual(row["locations"], [{"馆藏地": "书库", "可借复本": "1", "当前请求数": "0"}])
            finally:
                browser.close()

    def test_empty_and_repeated_barcodes(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                keys = {"条码号": "barcode"}
                self.assertEqual(table_rows(page, COPIES, {"totalCount": 0, "list": []}, keys), [])
                page.set_content("<table><thead><tr><th>条码号</th></tr></thead><tbody>"
                                 "<tr><td>001</td></tr><tr><td>001</td></tr></tbody></table>")
                with self.assertRaisesRegex(QueryUnavailable, "重复条码"):
                    table_rows(page, COPIES, {"totalCount": 2, "list": [{"barcode": "001"}] * 2}, keys)
            finally:
                browser.close()
