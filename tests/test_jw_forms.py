import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.jw.forms import CATALOGS, forms
from tongji_cli.common import QueryUnavailable


class AcademicFormsTest(unittest.TestCase):
    def setUp(self):
        self.pw=sync_playwright().start()
        self.browser=self.pw.chromium.launch(channel="chrome")
        self.addCleanup(self.pw.stop)
        self.addCleanup(self.browser.close)
        self.page=self.browser.new_page()
        self.page.route("http://school.test/**",self.serve)
        self.page.goto("http://school.test/")
        self.filename="form-2.doc"

    def serve(self,route):
        path=urlsplit(route.request.url).path
        view,api,heading,_,button=CATALOGS["graduation"]
        if path==api:
            n=int(route.request.post_data)
            return route.fulfill(json={"code":200,"data":{"pageNum":n,"pageSize":1,"total":2,
                                          "list":[{"id":n,"attachName":f"form-{n}.doc"}]}})
        if path=="/download":
            return route.fulfill(headers={"Content-Disposition":f'attachment; filename="{self.filename}"'},
                                 content_type="application/msword",body=b"school attachment")
        if path!=view:
            return route.fulfill(body="home")
        html=r"""
          <div class="el-table"><span>HEADING</span><div class="el-table__body-wrapper"><table><tbody></tbody></table></div></div>
          <div class="el-pagination"><div class="el-pagination__jump"><input onkeydown="if(event.key==='Enter') load(+this.value)"></div></div>
          <script>
          async function load(n) {
            const {data}=await (await fetch('API',{method:'POST',body:String(n)})).json();
            document.querySelector('tbody').innerHTML='<tr><td><button>'+data.list[0].attachName+'</button>'
              +'<button onclick="location.href=\'/download\'">BUTTON</button></td></tr>';
          }
          load(1);
          </script>""".replace("API",api).replace("HEADING",heading).replace("BUTTON",button)
        route.fulfill(content_type="text/html; charset=utf-8",body=html)

    def test_filter_and_download_from_second_page(self):
        args=SimpleNamespace(catalog="graduation",action="list",search="form-2")
        self.assertEqual([r["id"] for r in forms(self.page,args)],["2"])
        with TemporaryDirectory() as folder:
            dest=Path(folder)/"saved.doc"
            args=SimpleNamespace(catalog="graduation",action="download",id="2",output=str(dest))
            saved,=forms(self.page,args)
            self.assertEqual(dest.read_bytes(),b"school attachment")
            self.assertEqual(saved["bytes"],len(dest.read_bytes()))
            with self.assertRaisesRegex(QueryUnavailable,"新文件名"):
                forms(self.page,args)

    def test_mismatched_filename_leaves_no_file(self):
        self.filename="other.doc"
        with TemporaryDirectory() as folder:
            dest=Path(folder)/"saved.doc"
            args=SimpleNamespace(catalog="graduation",action="download",id="2",output=str(dest))
            with self.assertRaisesRegex(QueryUnavailable,"文件名"):
                forms(self.page,args)
            self.assertFalse(dest.exists())
