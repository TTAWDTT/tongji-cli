import unittest

from playwright.sync_api import sync_playwright

from tongji_cli.portal.records import personal_records, tab_records


class PortalRecordsTest(unittest.TestCase):
    def test_empty_hint_behind_loading_mask(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""
                    <section class="task-wrap"><div class="todoList-table">
                      <div class="table-header">
                        <div>流程标题</div><div>状态</div><div>系统来源 </div><p>最近处理时间</p><p>操作</p>
                      </div>
                      <p id="empty">暂无相关数据</p><div class="we-loading-mask">加载中</div>
                    </div></section>
                """)
                page.wait_for_load_state("networkidle")
                page.evaluate("""() => setTimeout(() => {
                    document.querySelector('.we-loading-mask').remove();
                    document.querySelector('#empty').outerHTML =
                      '<div class="task-items"><div>示例</div><div>完成</div><div></div><div>周五</div><div>详情</div></div>';
                }, 400)""")
                items = []
                tab_records(page, page, page.locator(".task-wrap"), "我发起的", items)
                self.assertEqual(items, [{"分类": "我发起的", "流程标题": "示例", "状态": "完成",
                                          "系统来源": None, "最近处理时间": "周五"}])
            finally:
                browser.close()

    def test_switch_to_cached_tab_without_loading_mask(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.route("**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=(
                    """<button>个人中心</button><section class="task-wrap"><h3>我的办件</h3>
                    <div class="task-nav"><button class="active">待办任务</button>
                    <button onclick="this.previousElementSibling.className='';this.className='active'">已办任务</button></div>
                    <div class="todoList-table"><div class="table-header"><b>流程标题</b><b>发起人</b><b>系统来源</b>
                    <b>最近处理时间</b><b>操作</b></div><span>暂无相关数据</span></div>
                    <span class="we-pagination__total">共 0 条</span></section>"""
                    if "CUS_TEMPLATE_TONGJI" in route.request.url else '<iframe src="/CUS_TEMPLATE_TONGJI"></iframe>')))
                result = personal_records(page, ["已办任务"])
                self.assertEqual(result["sources"], {"已办任务": "ok"})
                self.assertEqual(result["items"], [])
            finally:
                browser.close()

    def test_flow_history_distinguishes_empty_error_and_visible_steps(self):
        from tongji_cli.portal.records import flow_history

        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.set_content("""
                    <div class="task-items"><div><button onclick="load()">流程</button></div></div>
                    <div class="we-dialog" hidden><span>流转记录</span><ul class="step"></ul>
                    <button class="we-dialog__headerbtn" onclick="this.parentNode.hidden=true">关闭</button></div>
                    <script>
                    async function load(){
                      document.querySelector('.we-dialog').hidden=false
                      const res=await fetch('http://fixture.local/process_list')
                      const {data}=await res.json()
                      await new Promise(resolve => setTimeout(resolve, 350))
                      document.querySelector('ul').replaceChildren()
                      for(const step of data||[]) {
                        const li=document.createElement('li')
                        li.innerText=[step.visible,step.note].filter(Boolean).join('\\n')
                        document.querySelector('ul').appendChild(li)
                      }
                    }</script>""")
                row = page.locator(".task-items")
                payload = {"code": "A00000", "data": [{"visible": "申请已提交"}]}
                page.route("**/process_list", lambda route: route.fulfill(
                    json=payload, headers={"Access-Control-Allow-Origin": "*"}))
                self.assertEqual(flow_history(page, page, row), {"流转记录读取状态": "ok", "流转记录": ["申请已提交"]})
                payload["data"] = [{"visible": "审批已完成"}]
                self.assertEqual(flow_history(page, page, row), {"流转记录读取状态": "ok", "流转记录": ["审批已完成"]})
                payload["data"] = [{"visible": "审批已完成", "note": "请补材料"}]
                self.assertEqual(flow_history(page, page, row), {"流转记录读取状态": "ok", "流转记录": ["审批已完成\n请补材料"]})
                payload["data"] = [{"visible": "审批已完成", "metadata": "页面未显示的字段"}]
                self.assertEqual(flow_history(page, page, row), {"流转记录读取状态": "unverified"})
                payload["data"] = []
                self.assertEqual(flow_history(page, page, row), {"流转记录读取状态": "ok", "流转记录": []})
                payload.update(code="A04002", data=None)
                self.assertEqual(flow_history(page, page, row), {"流转记录读取状态": "unverified"})
                payload = []
                self.assertEqual(flow_history(page, page, row), {"流转记录读取状态": "unverified"})
                self.assertFalse(page.locator(".we-dialog").is_visible())
            finally:
                browser.close()
