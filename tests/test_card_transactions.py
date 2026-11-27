import unittest
from pathlib import Path
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from card_transactions import read_pages, report_response
from queries import QueryUnavailable


class CardTransactionsTest(unittest.TestCase):
    def test_displayed_columns_and_incomplete_page(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.route("http://card.test/", lambda r: r.fulfill(content_type="text/html", body='<iframe name="comepage" src="/report"></iframe>'))
                page.route("**/report", lambda r: r.fulfill(content_type="text/html; charset=utf-8", body="""
                    <div class="datagrid-view2"><div class="datagrid-header"><table><tr>
                    <td field="OCCTIME">交易时间</td><td field="TRANAMT">交易金额</td><td field="TRANNAME">交易类型</td>
                    </tr></table></div><div class="datagrid-body"><table><tbody></tbody></table></div></div>
                    <input class="pagination-num" value="1"><button id="run">查询</button>
                    <a href="#" id="next" class="l-btn"><span class="pagination-next">下一页</span></a>
                    <script>async function show(n){
                      document.querySelector('input').value=n;
                      const {rows,total}=await (await fetch('/Report/GetPersonTrjn?page='+n)).json();
                      await new Promise(resolve=>setTimeout(resolve,300));
                      document.querySelector('.datagrid-body tbody').innerHTML=rows.map(r=>'<tr class="datagrid-row"><td field="OCCTIME">'+r.OCCTIME+
                        '</td><td field="TRANAMT">'+r.TRANAMT.toFixed(2)+'</td><td field="TRANNAME">消费</td></tr>').join('');
                      if(total===0)document.querySelector('input').value=0;
                      next.classList.toggle('l-btn-disabled',n===2)
                    }run.onclick=()=>show(1);next.onclick=e=>{e.preventDefault();show(2)}</script>"""))
                total = 2
                page.route("**/Report/GetPersonTrjn?*", lambda r: r.fulfill(json={"total": total,
                    "rows": [] if not total else [{"OCCTIME": "2026-11-01 08:00:00", "TRANAMT": -int(r.request.url[-1]), "TRANNAME": "消费", "internal_id": 123}]}))
                page.goto("http://card.test/")
                frame = page.frame_locator('iframe')
                with report_response(page) as first:
                    frame.locator("#run").click()
                items = read_pages(page, frame, first.value)
                self.assertEqual([i["交易金额"] for i in items], ["-1.00", "-2.00"])
                self.assertEqual(set(items[0]), {"交易时间", "交易金额", "交易类型"})
                total = 3
                with report_response(page) as first:
                    frame.locator("#run").click()
                with self.assertRaisesRegex(QueryUnavailable, "总数不一致"):
                    read_pages(page, frame, first.value)
                total = 0
                with report_response(page) as first:
                    frame.locator("#run").click()
                self.assertEqual(read_pages(page, frame, first.value), [])
            finally:
                browser.close()
