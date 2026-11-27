import sys
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jw_menu import student_menu


class MenuTest(unittest.TestCase):
    def test_open_nested_groups_and_keep_full_paths_and_unsaved_links(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.route("http://school.test/**", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body="""
                  <aside class="left-side"><div class="el-collapse"><div class="el-collapse-item">
                    <div role="tab"><button class="el-collapse-item__header" onclick="document.getElementById('group-menu').hidden=false">学生服务</button></div>
                    <div class="el-collapse-item__content"><ul class="el-menu" id="group-menu" hidden>
                      <li class="el-menu-item"><a href="/advisor?t=42">我的导师</a></li>
                      <div><li class="el-submenu"><div class="el-submenu__title" onclick="document.getElementById('inner').hidden=false">学院导师</div>
                        <ul class="el-menu" id="inner" hidden><li><a href="/college">我的导师</a></li></ul>
                      </li></div><li><a href="https://external.test/auth?state=example">外部平台</a></li>
                      <li hidden><a href="/hidden">隐藏</a></li>
                    </ul></div></div></div></aside>"""))
                page.goto("http://school.test/")
                rows = student_menu(page)
                self.assertEqual([r["menu_path"] for r in rows], [
                    ["学生服务", "我的导师"], ["学生服务", "学院导师", "我的导师"], ["学生服务", "外部平台"]])
                self.assertEqual([r["url"] for r in rows], ["http://school.test/advisor", "http://school.test/college", None])
                self.assertEqual(student_menu(page, section="学生服务", keyword="学院"), [rows[1]])
                self.assertEqual(student_menu(page, section="另一个菜单"), [])
            finally:
                browser.close()

    def test_new_workbench_has_navigation_inside_student_app(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome")
            try:
                page = browser.new_page()
                page.route("http://school.test/workbench", lambda route: route.fulfill(
                    content_type="text/html; charset=utf-8", body="<div>切换旧版</div>"))
                page.route("http://school.test/GraduateStudentTimeTable", lambda route: route.fulfill(
                    content_type="text/html; charset=utf-8", body="""
                    <aside class="left-side"><div class="el-collapse"><div class="el-collapse-item">
                    <div role="tab"><span class="el-collapse-item__header">我的选课</span></div>
                    <div class="el-collapse-item__content"><ul class="el-menu"><li><a href="/courses">个人课表</a>
                    </li></ul></div></div></div></aside>"""))
                page.goto("http://school.test/workbench")
                result = student_menu(page)
                self.assertEqual(result, [{"title":"个人课表","menu_path":["我的选课","个人课表"],
                                           "url":"http://school.test/courses"}])
            finally:
                browser.close()
