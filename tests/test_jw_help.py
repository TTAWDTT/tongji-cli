import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from playwright.sync_api import sync_playwright

from tongji_cli.jw.help import help_detail
from tongji_cli.common import QueryUnavailable


class HelpDetailTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.route("http://school.test/**", lambda r: r.fulfill(body="home"))
        self.page.goto("http://school.test/")
        self.page.set_content("""
          <div class="el-dialog"><h1 class="info-title">同名指南</h1>
          <div class="info-content">正文<a href="/guide">原文链接</a></div>
          <div class="info-attach"><div class="attach-item"><a href="/archive-a.pdf">申请表.pdf</a></div>
          <div class="attach-item"><a href="/archive-b.pdf">申请表.pdf</a></div></div></div>""")
        self.page.route("**/archive-*.pdf", lambda r: r.fulfill(
            headers={"Content-Disposition":'attachment; filename="'+r.request.url.rsplit("/",1)[1]+'"'},
            content_type="application/pdf",body=r.request.url.rsplit("/",1)[1].encode()))
        self.item = {"id":7,"title":"同名指南"}
        self.detail = {"id":7,"theme":"同名指南","attachmentList":[
            {"id":21,"fileName":"申请表.pdf","fileUrl":"/archive-a.pdf"},
            {"id":22,"fileName":"申请表.pdf","fileUrl":"/archive-b.pdf"}]}

    def test_same_filenames_remain_bound_to_attachment_id(self):
        row=help_detail(self.page,self.item,self.detail,SimpleNamespace(action="show"))
        self.assertEqual([a["id"] for a in row["attachments"]],[21,22])
        self.assertEqual(row["links"][0]["url"],"http://school.test/guide")
        with TemporaryDirectory() as folder:
            target=Path(folder)/"second.pdf"
            args=SimpleNamespace(action="download",attachment=22,output=str(target))
            help_detail(self.page,self.item,self.detail,args)
            self.assertEqual(target.read_bytes(),b"archive-b.pdf")
            with self.assertRaisesRegex(QueryUnavailable,"新文件名"):
                help_detail(self.page,self.item,self.detail,args)

    def test_wrong_guide_and_wrong_file_are_rejected(self):
        self.detail["id"]=8
        with self.assertRaisesRegex(QueryUnavailable,"所选条目"):
            help_detail(self.page,self.item,self.detail,SimpleNamespace(action="show"))
        self.detail["id"]=7
        self.detail["attachmentList"][1]["fileUrl"]="/archive-a.pdf"
        with TemporaryDirectory() as folder:
            target=Path(folder)/"other.pdf"
            with self.assertRaisesRegex(QueryUnavailable,"文件名"):
                help_detail(self.page,self.item,self.detail,SimpleNamespace(action="download",attachment=22,output=str(target)))
            self.assertFalse(target.exists())
