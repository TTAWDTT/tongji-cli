import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from tongji_cli.jw.competitions import LIST, VIEW, competitions
from tongji_cli.common import QueryUnavailable


HTML = """<div class="el-form-item">竞赛名称<input id="keyword"></div>
<div class="el-form-item">竞赛等级<input readonly id="level" onclick="levels.hidden=false"></div>
<div class="el-select-dropdown" id="levels" hidden><button onclick="level.value='省级';levels.hidden=true">省级</button></div>
<div class="el-form-item">是否有效<input readonly id="valid" onclick="document.getElementById('validity').hidden=false"></div>
<div class="el-select-dropdown" id="validity" hidden><button onclick="valid.value='否';document.getElementById('validity').hidden=true">否</button></div>
<button onclick="load(1)">筛选</button>
<div class="el-pagination"><span class="el-pagination__jump"><input onkeydown="if(event.key==='Enter')load(+this.value)"></span></div>
<script>
function load(n){
    const condition={raceName:keyword.value,raceLevel:level.value?'PROVINCIAL':'',enable:valid.value?0:''};
    fetch('LIST',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pageNum_:n,condition})});
}
load(1)
</script>""".replace("'LIST'",repr(LIST))


class CompetitionsTest(unittest.TestCase):
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
        self.mismatch = False
        self.html = HTML
        self.page.route("http://school.test/**",self.serve)
        self.page.goto("http://school.test/")

    def serve(self, route):
        path = urlsplit(route.request.url).path
        if path == VIEW:
            return route.fulfill(content_type="text/html; charset=utf-8",body=self.html)
        if path != LIST:
            return route.fulfill(body="home")
        q = route.request.post_data_json
        condition = q["condition"]
        rows = ([] if condition["raceName"]=="无匹配" else [
            {"raceId":str(i),"raceName":"竞赛"+str(i),"raceLevelName":"省级","enable":"0","priceNames":"一等奖,二等奖","remark":""}
            for i in range(3)])
        n = q["pageNum_"]
        if self.mismatch and n==2:
            n=1
        route.fulfill(json={"code":200,"data":{"list":rows[n-1:n],"total_":len(rows),"pageSize_":1,"pageNum_":n}})

    def call(self, page=1, keyword="",level=None,valid=None):
        return competitions(self.page,SimpleNamespace(keyword=keyword,level=level,valid=valid,page=page))

    def test_filtered_page_preserves_invalid_status_and_awards(self):
        result=self.call(2,"竞赛","省级","否")
        item,=result["items"]
        self.assertEqual((item["id"],item["是否有效"],item["获奖等级"],result["pages"]),("1","否","一等奖,二等奖",3))
        zero=self.call(keyword="无匹配")
        self.assertEqual((zero["total"],zero["items"]),(0,[]))

    def test_empty_result_with_wrong_level_is_not_an_empty_match(self):
        self.html = HTML.replace("'PROVINCIAL'", "'COUNTRY'")
        with self.assertRaisesRegex(QueryUnavailable, "筛选条件"):
            self.call(keyword="无匹配", level="省级")

    def test_page_bounds_and_response_page_mismatch(self):
        with self.assertRaisesRegex(QueryUnavailable,"页码"):
            self.call(0)
        with self.assertRaisesRegex(QueryUnavailable,"共 3 页"):
            self.call(4)
        self.mismatch=True
        with self.assertRaisesRegex(QueryUnavailable,"所选页"):
            self.call(2)
