import unittest

from playwright.sync_api import sync_playwright

from tongji_cli.library.loans import loan_pages
from tongji_cli.common import QueryUnavailable


class LoanPagesTest(unittest.TestCase):
    def test_failure_on_second_page_keeps_first(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""
                    <main><table><thead><tr><th>题名</th><th>应还日期</th></tr></thead>
                    <tbody><tr><td>样例书</td><td>2026-12-10</td></tr></tbody></table>
                    <span class="ant-pagination-item-active">1</span>
                    <button class="ant-pagination-next" onclick="
                    document.querySelector('span').textContent='2';
                    document.querySelector('th').textContent='未识别的列'">下一页</button></main>
                """)
                items = []
                with self.assertRaises(QueryUnavailable):
                    loan_pages(page, page.locator("main"), "图书", items)
                self.assertEqual(items, [{"kind": "图书", "title": "样例书", "due_date": "2026-12-10"}])
            finally:
                browser.close()

    def test_history_uses_the_return_date_table_and_keeps_repeated_loans(self):
        from tongji_cli.library.loans import history_pages

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""
                    <main><table><thead><tr><th>题名</th><th>条码号</th><th>借阅日期</th><th>实还日期</th><th>应还日期</th></tr></thead>
                    <tbody><tr><td>样例书</td><td>001</td><td>2026-09-02</td><td>2026-09-07</td><td>2026-10-02</td></tr>
                    <tr><td>样例书</td><td>001</td><td>2026-10-03</td><td>2026-10-06</td><td>2026-11-02</td></tr></tbody></table>
                    <table><thead><tr><th>操作</th></tr></thead><tbody><tr><td>详情</td></tr><tr><td>详情</td></tr></tbody></table></main>""")
                records = [
                    {"title": "样例书", "barcode": "001", "loanDate": "2026-09-02", "returnDate": "2026-09-07", "normReturnDate": "2026-10-02"},
                    {"title": "样例书", "barcode": "001", "loanDate": "2026-10-03", "returnDate": "2026-10-06", "normReturnDate": "2026-11-02"},
                ]
                items = []
                history_pages(page, page.locator("main"), "图书", "loanHistoryList",
                              {"searchResult": records, "numFound": 2}, items)
                self.assertEqual([row["returned_date"] for row in items], ["2026-09-07", "2026-10-06"])
                self.assertEqual([row["barcode"] for row in items], ["001", "001"])
            finally:
                browser.close()

    def test_renewal_requires_one_barcode_and_a_later_due_date(self):
        from datetime import date
        from types import SimpleNamespace
        from tongji_cli.library.loans import renew_book

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                context = browser.new_context()
                page = context.new_page()
                stored = {"barcode": "001", "title": "样例书", "loanDate": "2026-11-01", "normReturnDate": "2026-12-01"}
                books = [dict(stored, barcode="01"), stored, dict(stored, barcode="0001")]
                submissions = []
                html = """
                    <div role="tabpanel"><label class="ant-radio-button-wrapper-checked">图书</label>
                    <div class="ant-table-body"><table><thead><tr><th></th><th>题名</th><th>条码号</th>
                    <th>借阅日期</th><th>应还日期</th></tr></thead><tbody></tbody></table></div>
                    <button id="renew" onclick="document.querySelector('[role=dialog]').hidden=false">批量续借</button>
                    <div role="dialog" hidden>确认续借
                    <button onclick="fetch('/renew',{method:'POST',body:JSON.stringify([...document.querySelectorAll('tbody input:checked')].map(input=>input.value))});this.parentNode.hidden=true">确定</button></div></div>
                    <script>
                    fetch('/loanList').then(r=>r.json()).then(body=>{
                      for(const loan of body.data.searchResult) {
                        const row=document.querySelector('tbody').insertRow()
                        const select=document.createElement('input')
                        select.type='checkbox'
                        select.value=loan.barcode
                        row.insertCell().append(select)
                        for(const key of ['title','barcode','loanDate','normReturnDate'])row.insertCell().textContent=loan[key]
                      }
                    })
                    </script>"""
                context.route("**/reader", lambda r: r.fulfill(content_type="text/html; charset=utf-8", body=html))
                context.route("**/loanList", lambda r: r.fulfill(json={
                    "success": True, "data": {"searchResult": books, "numFound": len(books)}}))
                def save(route):
                    from json import loads
                    selected = loads(route.request.post_data)
                    submissions.append(selected)
                    for book in books:
                        if book["barcode"] in selected:
                            book["normReturnDate"] = "2026-12-16"
                    route.fulfill(status=200, body="ok")

                context.route("**/renew", save)
                args = SimpleNamespace(barcode="001", due=date(2026, 12, 1), preview=True)
                url = "http://fixture.local/reader"
                preview, = renew_book(page, url, args)
                self.assertEqual((preview["action"], preview["barcode"], submissions), ("preview", "001", []))
                args.preview = False
                receipt, = renew_book(page, url, args)
                self.assertEqual((receipt["previous_due_date"], receipt["due_date"]), ("2026-12-01", "2026-12-16"))
                with self.assertRaisesRegex(QueryUnavailable, "应还日期"):
                    renew_book(page, url, args)
                args.barcode = "not-held"
                with self.assertRaisesRegex(QueryUnavailable, "没有这个条码号"):
                    renew_book(page, url, args)
                self.assertEqual(submissions, [["001"]])
                self.assertEqual([book["normReturnDate"] for book in books], ["2026-12-01", "2026-12-16", "2026-12-01"])
            finally:
                browser.close()
