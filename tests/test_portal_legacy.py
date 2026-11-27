import json
from io import BytesIO
from tempfile import TemporaryDirectory
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portal_legacy
import portal_certificate_download as proof
from queries import QueryUnavailable


class LegacyPortalTest(unittest.TestCase):
    def setUp(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(channel="chrome")
        self.context = self.browser.new_context()
        self.rows = [[["学生班车查询", "https://jiading.tongji.edu.cn/shuttle"]]]
        self.destination_title = "学生班车时刻表"
        self.context.route("**/*", self.serve)

    def tearDown(self):
        self.browser.close()
        self.pw.stop()

    def serve(self, route):
        url = urlsplit(route.request.url)
        if url.hostname != "all.tongji.edu.cn":
            html = f"<title>{self.destination_title}</title><p>{self.destination_title}</p>"
        elif url.path == "/":
            html = '<iframe style="width:900px;height:500px" src="/CUS_TEMPLATE_TONGJI"></iframe>'
        else:
            html = """<div id="stepThree"><input placeholder="搜索事项" onclick="box.hidden=false"></div>
              <div class="tj-hide-box-wrap" id="box" hidden><input placeholder="搜索事项"
                onkeydown="if(event.key==='Enter'){parent.location.hash='/search';show(0)}"></div>
              <div class="cus-ser-wrap"><div id="cards"></div><div class="we-pagination">
                <span class="we-pager"><span class="active" id="currentPage"></span></span>
                <button class="btn-next" onclick="show(index+1)">下一页</button></div></div>
              <div class="detail-dialog" id="guide" hidden><div class="itemdetails"><span id="guideTitle"></span>
                <div class="tb_list"><span class="tb_label">服务对象</span><span class="tb_text">学生</span></div>
                </div><button class="we-dialog__headerbtn" onclick="guide.hidden=true">关闭</button></div>
              <script>const rows=ROWS;let index=0;
              function show(n){ index=n; currentPage.textContent=n+1;cards.replaceChildren();
                for(const [name,url] of rows[n]){
                  const card=document.createElement('div');card.className='matter-item'
                  const title=document.createElement('span');title.className='item-name';title.textContent=name;
                  const link=document.createElement('a');link.textContent=url?'在线办理':'办事指南';
                  if(url){link.href=url;link.target='_blank'}
                  else {link.onclick=()=>{guideTitle.textContent=name;guide.hidden=false}}
                  card.append(title,link);cards.append(card)
                }
                if(!rows[n].length)cards.textContent='未找到相关数据'
                document.querySelector('.btn-next').disabled=(n+1===rows.length)
              }</script>""".replace("ROWS", json.dumps(self.rows))
        route.fulfill(content_type="text/html; charset=utf-8", body=html)

    def run_preview(self, title):
        return portal_legacy.apply_in_session(self.context, title, True)

    def test_exact_name_on_first_of_two_pages_opens_public_schedule(self):
        self.rows.append([["教师班车查询", "https://jiading.tongji.edu.cn/faculty"]])
        result = self.run_preview("学生班车查询")
        self.assertEqual(result["items"][0]["state"], "public_schedule")
        self.assertEqual(len(self.context.pages), 0)

    def test_duplicate_title_across_pages_and_partial_name(self):
        self.rows.append([self.rows[0][0]])
        with self.assertRaisesRegex(QueryUnavailable, "2 项"):
            self.run_preview("学生班车查询")
        with self.assertRaisesRegex(QueryUnavailable, "0 项"):
            self.run_preview("学生班车")

    def test_guide_only_on_later_page(self):
        self.rows.append([["本科生学生证补办", ""]])
        result = self.run_preview("本科生学生证补办")
        self.assertEqual(result["items"][0]["state"], "guide_only")
        self.assertEqual(result["items"][0]["audience"], "学生")

    def test_unknown_destination_gives_no_receipt(self):
        self.rows = [[["学生电子证明文件", "https://example.test/"]]]
        result = self.run_preview("学生电子证明文件")
        self.assertEqual(result["status"], "unverified")
        self.assertNotIn("receipt", result["items"][0])

    def test_employment_login_requires_authentication(self):
        self.rows = [[["毕业生“升学”去向鉴证", "https://tj91.tongji.edu.cn/login_tzdl.jsp"]]]
        self.destination_title = "同济大学学生就业信息网"
        self.assertEqual(self.run_preview("毕业生“升学”去向鉴证")["status"], "login_required")

class CertificateTest(unittest.TestCase):
    template = "本科生在读证明电子档下载"
    base = "https://zzfw.tongji.edu.cn/wec-self-print-app-console/"

    def setUp(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(channel="chrome")
        self.context = self.browser.new_context()
        self.context.set_default_timeout(3000)
        self.names = [self.template, "本科生中文成绩单电子档下载"]
        self.orders = {"已完成文件": [self.order(100)], "未完成文件": [self.order(101)]}
        self.issued = []
        self.downloads = 0
        self.download_body = b""
        self.context.route("**/*", self.serve)
        self.page = self.context.new_page()
        self.page.goto(self.base)

    def tearDown(self):
        self.browser.close()
        self.pw.stop()

    def order(self, number, name=None):
        return {"orderId": number, "itemId": self.names.index(name or self.template)+1, "itemName": name or self.template, "title": "学籍证明.pdf",
                "completeTime": "2026-11-26 16:20:00"}

    def serve(self, route):
        from urllib.parse import parse_qs
        url = urlsplit(route.request.url)
        query = parse_qs(url.query)
        page_number = int(query.get("p", ["1"])[0])
        if url.path == portal_legacy.ORDER_LIST:
            data = self.orders[query["tab"][0]]
            route.fulfill(json={"rows": data[page_number-1:page_number], "total": len(data),
                                "pageNumber": page_number, "lastPageNumber": len(data)})
        elif url.path == portal_legacy.TEMPLATE_LIST:
            data = self.names[page_number-1:page_number]
            route.fulfill(json={"code": "0000", "data": {"pages": len(self.names), "current": page_number,
                                "total": len(self.names), "records": [{"name": n, "id": self.names.index(n)+1} for n in data]}})
        elif url.path == "/local-download":
            self.downloads += 1
            route.fulfill(body=self.download_body, content_type="application/pdf",
                          headers={"Content-Disposition": 'attachment; filename="proof.pdf"'})
        elif url.path.endswith("/local-issue"):
            self.issued.append(True)
            self.orders["已完成文件"].append(self.order(102))
            route.fulfill(json={})
        else:
            route.fulfill(content_type="text/html; charset=utf-8", body="""<title>自助打印PC端</title>
            <div>电子证明中心</div><a class="header-menu">证明文件</a><a class="header-menu">未完成文件</a>
            <a class="header-menu">已完成文件</a><div id="content"></div>
            <div class="ivu-page"><span class="ivu-page-total"></span><button class="ivu-page-prev">上一页</button><button class="ivu-page-next">下一页</button></div>
            <script>let current;function issue(){fetch('/local-issue')}
            function details(id){
               history.pushState({},'', '#/detail?orderId='+id)
               content.innerHTML='<span>学籍证明.pdf</span><button id="fetchProof">再次下载</button>';
               fetchProof.onclick=async()=>{
                 const file=await (await fetch('/local-download')).blob()
                 const a=document.createElement('a');a.href=URL.createObjectURL(file);a.download='proof.pdf';a.click()
               }
            }
            async function load(tab,p){
              current=tab;
              for(const n of document.querySelectorAll('a'))n.classList.toggle('ivu-menu-item-active',n.textContent===tab);
              let total,html;
              if(tab==='证明文件'){
                const {data}=await (await fetch('TEMPLATES?p='+p)).json();
                total=data.total; html=data.records.map(r=>'<button class="itemNameClass" onclick="issue()">'+r.name+'</button>').join('')
              }else{
                const d=await(await fetch('ORDERS?p='+p+'&tab='+encodeURIComponent(tab))).json();
                total=d.total; html='<table><thead><tr><th>文件名称</th><th>取件方式</th><th>打印完成时间</th><th>操作</th></tr></thead><tbody>';
                for(const r of d.rows)html+='<tr><td>'+r.title+'</td><td>电子档</td><td>'+r.completeTime+'</td><td><a data-order="'+r.orderId+'" onclick="details(this.dataset.order)">查看详情</a></td></tr>';
                html+='</tbody></table>'+(total?'':'<span>暂无数据</span>')
              }
              content.innerHTML=html;
              document.querySelector('.ivu-page-total').textContent='共 '+total+' 条';
              document.querySelector('.ivu-page-next').onclick=()=>load(tab,p+1);
              document.querySelector('.ivu-page-prev').onclick=()=>load(tab,p-1)
            }
            document.querySelectorAll('a').forEach(n=>n.onclick=()=>load(n.textContent,1));load('证明文件',1)
            </script>""".replace("ORDERS", portal_legacy.ORDER_LIST).replace("TEMPLATES", portal_legacy.TEMPLATE_LIST))

    def result(self, preview=True, template=None, confirm=None, history_only=False):
        return portal_legacy.certificate_center(self.page, {"title": portal_legacy.CERTIFICATES}, preview,
                                                template, portal_legacy.certificate_history if history_only else None, confirm)

    def test_preview_second_page_template_never_issues(self):
        result = self.result(template=self.names[1])
        self.assertEqual(result["items"][0]["template"], self.names[1])
        self.assertEqual(result["items"][0]["completed_count"], 1)
        self.assertEqual(self.issued, [])

    def test_history_filters_by_template_and_displays_official_filename(self):
        result = self.result(history_only=True, template=self.template)
        self.assertEqual(result["items"][0]["文件名称"], "学籍证明.pdf")
        self.assertNotIn("操作", result["items"][0])
        self.assertEqual(result["items"][0]["receipt"], "100")
        self.assertEqual(result["items"][0]["template"], self.template)
        self.assertEqual(self.result(history_only=True, template=self.names[1])["items"], [])

    def test_user_issued_order_distinguished_from_old_one(self):
        def issue_on_local_site(name):
            with self.page.expect_response("**/local-issue"):
                self.page.get_by_role("button", name=name, exact=True).click()
        result = self.result(False, self.template, issue_on_local_site)
        self.assertEqual(result["items"][0]["receipt"], "102")
        self.assertEqual(self.issued, [True])

    def test_old_pending_order_cannot_be_claimed_as_new(self):
        def finish_old_order(name):
            self.orders["已完成文件"].append(self.orders["未完成文件"].pop())
            self.orders["已完成文件"].append(self.order(104, self.names[1]))
            self.orders["已完成文件"].append(dict(self.order(105), itemId=999))
        self.assertEqual(self.result(False, self.template, finish_old_order)["status"], "unverified")

    def test_duplicate_or_missing_template_does_not_open_issuance(self):
        self.names.append(self.template)
        with self.assertRaisesRegex(QueryUnavailable, "2 个同名模板"):
            self.result(template=self.template)
        with self.assertRaisesRegex(QueryUnavailable, "0 个同名模板"):
            self.result(template="在读证明")
        self.assertEqual(self.issued, [])

    def test_no_new_record_and_multiple_new_records(self):
        self.assertEqual(self.result(False, self.template, lambda _: None)["status"], "unverified")
        def create_two(name):
            self.orders["已完成文件"].extend([self.order(104), self.order(105)])
        self.assertEqual(self.result(False, self.template, create_two)["status"], "unverified")

    def test_download_preview_finds_earlier_page_and_avoids_download(self):
        self.orders["已完成文件"].append(self.order(110))
        result = proof.download_page(self.page, "100", None)
        self.assertEqual(result["items"][0]["state"], "download_preview")
        self.assertEqual(self.downloads, 0)

    def test_save_actual_pdf_and_reject_existing_file(self):
        from pypdf import PdfWriter
        out = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(36, 36)
        writer.write(out)
        self.download_body = out.getvalue()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "证明.pdf"
            result = proof.download_page(self.page, "100", path)
            self.assertEqual(result["items"][0]["bytes"], len(self.download_body))
            self.assertEqual(path.read_bytes(), self.download_body)
            with self.assertRaisesRegex(QueryUnavailable, "新文件名"):
                proof.download(Path(tmp), "100", path)
            self.assertEqual(path.read_bytes(), self.download_body)
        self.assertEqual(self.downloads, 1)

    def test_invalid_and_truncated_files_leave_no_output(self):
        with TemporaryDirectory() as tmp:
            dest = Path(tmp) / "proof.pdf"
            for body in [b"<html>login required</html>", b"%PDF-1.4\nbroken"]:
                self.download_body = body
                self.page.goto(self.base)
                with self.assertRaisesRegex(QueryUnavailable, "PDF"):
                    proof.download_page(self.page, "100", dest)
                self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(self.downloads, 2)

    def test_missing_order_and_duplicate_order_rejected(self):
        with self.assertRaisesRegex(QueryUnavailable, "未找到"):
            proof.download_page(self.page, "10", None)
        self.orders["已完成文件"].append(self.order(100))
        with self.assertRaisesRegex(QueryUnavailable, "重复订单号"):
            proof.download_page(self.page, "100", None)
        self.assertEqual(self.downloads, 0)
