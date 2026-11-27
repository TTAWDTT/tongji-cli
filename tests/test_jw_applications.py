import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jw_applications import DETAIL, LIST, VIEW, applications
from queries import QueryUnavailable


def table(labels, body=""):
    return ('<div class="el-table"><div class="el-table__header-wrapper"><table><tr>'
            + ''.join(f'<th>{label}</th>' for label in labels) + '</tr></table></div>'
            + '<div class="el-table__body-wrapper"><table><tbody>' + body + '</tbody></table></div></div>')


PAGE = table(["申请编号","申请类型","申请时间","审批状态","当前处理人","操作"]) + """
<div class="el-pagination"><div class="el-pagination__jump"><input onkeydown="if(event.key==='Enter') load(+this.value)"></div></div>
<script>
async function get(path,params) {
    return (await (await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(params)})).json()).data;
}
function openDetail(id) { location.href="/StudentRollDetail?id="+id; }
async function load(n) {
    const d=await get('LIST',{page:n});
    document.querySelector('.el-table__body-wrapper tbody').innerHTML=d.list.map(r=>'<tr><td>'+r.no+'</td><td>通用申请</td><td>日期</td><td>'
        +r.display+'</td><td>无</td><td><button onclick="openDetail('+r.id+')">查看明细</button></td></tr>').join('');
    if (!d.list.length) document.querySelector('.el-table').insertAdjacentHTML('beforeend','<span class="el-table__empty-text">暂无数据</span>');
}
load(1);
</script>""".replace("'LIST'",repr(LIST))
DETAIL_PAGE = table(["序号","时间","审批人","角色","审批结果","审批说明","审批材料"]) + """
<div class="edu-info-list"><div class="item-group"><label class="label">学号：</label>样例身份</div>
<div class="item-group"><label class="label">详细修改：</label><div>修改内容</div></div>
<div class="item-group"><label class="label">审批材料：</label></div></div>
<script>fetch('DETAIL',{method:'POST',body:new URLSearchParams(location.search).get('id')})
.then(r=>r.json()).then(r=>{
    const d=r.data;
    document.querySelector('.el-table__body-wrapper tbody').innerHTML=d.listApproveHistory.map(s=>'<tr><td>1</td><td>日期</td><td>经办人</td><td>审核</td><td>同意</td><td>说明</td><td></td></tr>').join('');
    if(!d.listApproveHistory.length) document.querySelector('.el-table').insertAdjacentHTML('beforeend','<span class="el-table__empty-text">暂无数据</span>');
});
</script>""".replace("'DETAIL'",repr(DETAIL))


class ApplicationsTest(unittest.TestCase):
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
        self.rows = [{"id": 1, "no": "A-01", "applyNo": "different", "display": "办理中"},
                     {"id": 2, "no": "B-02", "applyNo": "other", "display": "已结束"}]
        self.wrong = False
        self.page.route("http://school.test/**", self.serve)
        self.page.goto("http://school.test/")

    def serve(self, route):
        path = urlsplit(route.request.url).path
        if path in (VIEW, "/StudentRollDetail"):
            html = PAGE if path == VIEW else DETAIL_PAGE
            return route.fulfill(content_type="text/html; charset=utf-8", body=html)
        if path == LIST:
            n = route.request.post_data_json["page"]
            data = {"list": self.rows[n-1:n], "pageNum_": n, "pageSize_": 1, "total_": len(self.rows)}
        elif path == DETAIL:
            index = next(i for i,r in enumerate(self.rows) if r["no"]==route.request.post_data)
            data = dict(self.rows[index], listApproveHistory=[{}] if index else [])
            if self.wrong:
                data["no"] = "C-03"
        else:
            return route.fulfill(body="home")
        route.fulfill(json={"code":200, "data":data})

    def test_two_pages_and_exact_application_history(self):
        rows = applications(self.page, SimpleNamespace(action="list"))
        self.assertEqual([(r["申请编号"],r["审批状态"]) for r in rows], [("A-01","办理中"),("B-02","已结束")])
        row, = applications(self.page, SimpleNamespace(action="show",number="B-02"))
        self.assertEqual(row["详细修改"], "修改内容")
        self.assertIsNone(row["审批材料"])
        self.assertNotIn("学号",row)
        self.assertEqual(row["审批进度"][0]["审批结果"], "同意")
        empty, = applications(self.page, SimpleNamespace(action="show",number="A-01"))
        self.assertEqual(empty["审批进度"], [])

    def test_empty_list_unknown_id_and_mismatched_detail(self):
        self.wrong = True
        with self.assertRaisesRegex(QueryUnavailable,"不一致"):
            applications(self.page, SimpleNamespace(action="show",number="A-01"))
        with self.assertRaisesRegex(QueryUnavailable,"未找到"):
            applications(self.page, SimpleNamespace(action="show",number="different"))
        self.rows[1]["no"] = self.rows[0]["no"]
        with self.assertRaisesRegex(QueryUnavailable,"多个"):
            applications(self.page, SimpleNamespace(action="show",number="A-01"))
        self.rows.clear()
        self.assertEqual(applications(self.page, SimpleNamespace(action="list")), [])
