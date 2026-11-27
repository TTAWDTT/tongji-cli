import unittest
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.portal import apply as portal_apply
from tongji_cli.common import QueryUnavailable


class PortalApplyTest(unittest.TestCase):
    def setUp(self):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(channel="chrome")
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.set_default_timeout(4000)
        self.search_names = ["校园绿地使用申请表"]
        self.submissions = []
        self.form_title = self.search_names[0]
        self.cases = [{"id": 201, "app": {"id": 15}}, {"id": 202, "app": {"id": 44}}]
        self.context.route("**/*", self.route)

    def tearDown(self):
        self.browser.close()
        self.pw.stop()

    def route(self, route):
        path = urlsplit(route.request.url).path
        if path == urlsplit(portal_apply.HISTORY).path:
            route.fulfill(content_type="text/html; charset=utf-8", body="""
                <span class="matter_nav_item active">我的申请</span>
                <div class="matter_nav_tab"><button class="active">进行中</button>
                <button onclick="this.previousElementSibling.className='';this.className='active';load(1)">全部</button></div>
                <div class="n-pagination"></div><script>async function load(n){
                  const r=await fetch('/newservice/site/session/list?p='+n)
                  const {d}=await r.json()
                  const pager=document.querySelector('.n-pagination')
                  pager.replaceChildren()
                  for(let i=1;i<=d.total;i++){
                    const btn=document.createElement('button');btn.textContent=i
                    btn.onclick=()=>load(i);pager.append(btn)
                  }
                }load(1)</script>""")
            return
        if path == "/newservice/site/session/list":
            page = int(parse_qs(urlsplit(route.request.url).query)["p"][0])
            route.fulfill(json={"e": "OK", "d": {"page": str(page), "total": len(self.cases), "perpage": 1,
                                                  "list": self.cases[page-1:page]}})
            return
        if path == "/newservice/api/home-page/search":
            route.fulfill(json={"e": "OK", "d": {"apps": [{"id": 15, "name": {"zh": name}} for name in self.search_names]}})
            return
        if path == "/fixture-submit":
            self.submissions.append(True)
            self.cases.append({"id": 203, "app": {"id": 15}})
            route.fulfill(json={"ok": True})
            return
        if path == portal_apply.FORM_PATH:
            body = f'''<span class="matter_title">{self.form_title}</span>
            <div class="pc_form"><textarea></textarea></div>
            <button onclick="fetch('/fixture-submit',{{method:'POST'}})">立即提交</button>'''
        else:
            body = """<input placeholder="请输入要搜索的关键词"><div class="results"></div>
            <script>document.querySelector('input').onkeydown=async e=>{
                if(e.key!=='Enter') return
                const r=await fetch('/newservice/api/home-page/search?keyword='+encodeURIComponent(e.target.value))
                for(const app of (await r.json()).d.apps) {
                    const item=document.createElement('div')
                    item.className='item'
                    item.innerHTML='<div class="index_search_name">服务<div class="name"></div></div>'
                    item.querySelector('.name').textContent=app.name.zh
                    item.onclick=()=>location.href='/newservice/fe/taskCenter/matterApplication?app_id='+app.id
                    document.querySelector('.results').append(item)
                }
            }</script>"""
        route.fulfill(content_type="text/html; charset=utf-8", body=body)

    def test_exact_result_opens_matching_form_without_submitting(self):
        self.search_names.append("校园绿地使用申请表（新版）")
        self.assertEqual(portal_apply.open_form(self.page, "校园绿地使用申请表"), "15")
        self.assertEqual(urlsplit(self.page.url).path, portal_apply.FORM_PATH)
        self.assertEqual(self.submissions, [])

    def test_ambiguous_and_absent_exact_results(self):
        for names, expected in [(["校园绿地使用申请表"] * 2, 2), (["校园绿地使用申请表（新版）"], 0)]:
            self.search_names = names
            with self.assertRaisesRegex(QueryUnavailable, f"{expected} 项"):
                portal_apply.open_form(self.page, "校园绿地使用申请表")
        self.assertEqual(self.submissions, [])

    def test_mismatched_form_title_is_unverified(self):
        self.form_title = "另一项材料申请"
        result = portal_apply.apply_in_session(self.context, "校园绿地使用申请表", True, self.fail)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(self.submissions, [])

    def test_handoff_verifies_new_case_from_later_page(self):
        def submit_on_local_site(title):
            page, = [p for p in self.context.pages if urlsplit(p.url).path == portal_apply.FORM_PATH]
            with page.expect_response("**/fixture-submit"):
                page.get_by_role("button", name="立即提交").click()

        result = portal_apply.apply_in_session(self.context, self.form_title, False, submit_on_local_site)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["items"][0]["receipt"], "203")
        self.assertEqual(self.submissions, [True])

    def test_unrelated_new_application_does_not_verify_submission(self):
        def add_different_case(title):
            self.cases.append({"id": 203, "app": {"id": 44}})

        result = portal_apply.apply_in_session(self.context, self.form_title, False, add_different_case)
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(self.submissions, [])
