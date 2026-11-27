from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dorm_energy
from queries import QueryUnavailable


class MeterLocationsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel="chrome")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page=self.browser.new_page()
        self.addCleanup(self.page.close)
        self.page.route("http://school.test/**",self.serve)
        source=patch.object(dorm_energy,"SERVICES","http://school.test/services")
        source.start()
        self.addCleanup(source.stop)
        self.posts=[]
        self.failing=False

    def serve(self,route):
        if urlsplit(route.request.url).path=="/services":
            return route.fulfill(content_type="text/html; charset=utf-8",body='<a href="/meter">水电查询</a>')
        form=parse_qs(route.request.post_data or "")
        campus=form.get("campus",[""])[0]
        building=form.get("building",[""])[0]
        if route.request.method=="POST":
            self.posts.append((campus,building))
            if self.failing:
                return route.fulfill(status=503,body="busy")
        html='<form action="/meter" method="post">'
        for field,name,options,selected in [
            ("drlouming","campus",["校区","东校区","西校区"],campus),
            ("drceng","building",["楼栋"]+(["一舍"] if campus=="东校区" else []),building),
            ("dr_ceng","floor",["楼层"]+(["1F","公用"] if building=="一舍" else []),"")]:
            html+=f'<select id="{field}" name="{name}" onchange="this.form.submit()">'
            for index,option in enumerate(options):
                value=option if index else ""
                html+=f'<option value="{value}" {"selected" if value==selected else ""}>{option}</option>'
            html+='</select>'
        route.fulfill(content_type="text/html; charset=utf-8",body=html+'</form>')

    def test_exact_cascade_preserves_school_labels(self):
        rows=dorm_energy.meter_locations(self.page,"东校区","一舍")
        self.assertEqual([r["floor"] for r in rows],["1F","公用"])
        self.assertEqual(self.posts,[("东校区",""),("东校区","一舍")])
        self.assertEqual(dorm_energy.meter_locations(self.page,"西校区",None),[])
        with self.assertRaisesRegex(QueryUnavailable,"楼栋"):
            dorm_energy.meter_locations(self.page,"西校区","一舍")

    def test_failed_selection_never_becomes_empty_directory(self):
        self.failing=True
        with self.assertRaisesRegex(QueryUnavailable,"未能加载"):
            dorm_energy.meter_locations(self.page,"东校区",None)
