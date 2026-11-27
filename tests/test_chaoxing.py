import unittest
from datetime import date
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from playwright.sync_api import sync_playwright
from tongji_cli.browser_session import open_session
from tongji_cli import chaoxing
from tongji_cli.common import QueryUnavailable
from tongji_cli.schedule import week_view

class ValuesTest(unittest.TestCase):
    def test_deadline_requires_year_and_valid_date(self):
        self.assertEqual(chaoxing.deadline('作答时间:2026-11-01 09:00至2026-12-01 09:00'), '2026-12-01T09:00:00+08:00')
        self.assertIsNone(chaoxing.deadline('截止时间:02-01 00:00'))
        self.assertIsNone(chaoxing.deadline('截止时间:2026-02-30 00:00'))
        self.assertEqual(chaoxing.deadline('截止时间:2026-12-01 09:00'), '2026-12-01T09:00:00+08:00')

    def test_submission_unknown_is_not_invented(self):
        self.assertFalse(chaoxing.submitted('未完成'))
        self.assertTrue(chaoxing.submitted('已完成'))
        self.assertIsNone(chaoxing.submitted('待重做'))

    def test_untrusted_link_rejected(self):
        for url in ['https://chaoxing.com.evil.org/x','file:///tmp/a','https://evil.org/x','https://user:pass@i.chaoxing.com/x']:
            with self.assertRaises(QueryUnavailable):chaoxing.safe_url(url)

    def test_login_redirect_does_not_forward_request(self):
        context=Mock(); context.request.get.return_value=Mock(status=302,headers={'location':'https://passport2.chaoxing.com/login'})
        with self.assertRaisesRegex(QueryUnavailable,'登录已失效'):chaoxing.read(context,'https://i.chaoxing.com/base')
        self.assertEqual(context.request.get.call_args.kwargs['max_redirects'],0)
        self.assertEqual(context.request.get.call_count,1)

    def test_week_preserves_unknown_and_partial_results(self):
        result=week_view({'jw':{'status':'authenticated','items':[]},'canvas':{'status':'login_required'},'chaoxing':{'status':'partial','items':[{'title':'unknown','due':None},{'title':'in','due':'2026-11-28T10:00:00+08:00'},{'title':'out','due':'2026-12-20T10:00:00+08:00'}]}},date(2026,11,27))['week']
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['undated_assignments'][0]['title'],'unknown')
        self.assertEqual(result['items'][1]['chaoxing_assignments'][0]['title'],'in')
        self.assertNotIn('assignments',result['items'][0])

class BrowserParsingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=TemporaryDirectory();cls.pw=sync_playwright().start();cls.ctx=open_session(cls.pw,cls.tmp.name);cls.page=cls.ctx.pages[0];cls.page.goto("about:blank")
    @classmethod
    def tearDownClass(cls):
        cls.ctx.close();cls.pw.stop();cls.tmp.cleanup()

    def test_courses_uses_card_title_and_keeps_classes(self):
        html=''.join(f'<div class="course"><div><a href="https://mooc1.chaoxing.com/visit/stucoursemiddle?courseid=1&amp;clazzid={n}&amp;cpi=3"><img></a></div><span class="course-name" title="课程甲">课程甲</span></div>' for n in (2,4))
        with patch.object(chaoxing,'read',side_effect=['var fid = \'123\';',html]):
            rows=chaoxing.courses(None,self.page)
        self.assertEqual([x['title'] for x in rows],['课程甲','课程甲'])
        self.assertNotEqual(rows[0]['id'],rows[1]['id'])

    def test_unknown_list_does_not_mean_empty(self):
        with patch.object(chaoxing,'read',side_effect=['var fid = \'123\';','<html>页面已更改</html>']):
            with self.assertRaises(QueryUnavailable):chaoxing.courses(None,self.page)

    def test_work_list_and_missing_year(self):
        course={'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'课程甲'}
        work='<li onclick="goTask(this);" data="https://mooc1.chaoxing.com/mooc2/work/task?workId=9"><p class="overHidden2 fl">报告</p><p class="status fl">未完成</p></li>'
        with patch.object(chaoxing,'courses',return_value=[course]),patch.object(chaoxing,'read',side_effect=['<input id="workEnc" value="fixture">',work,'作答时间:01-04 16:14至02-01 00:00']):
            result=chaoxing.assignments(None,self.page)
        item=result['items'][0]
        self.assertEqual(result['status'],'ok');self.assertEqual(item['id'],'1:2:9')
        self.assertIsNone(item['due']);self.assertIn('02-01',item['due_as_listed']);self.assertFalse(item['submitted'])

    def test_course_failure_keeps_other_course(self):
        rows=[{'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'甲'},{'id':'4:5','course_id':'4','class_id':'5','cpi':'3','title':'乙'}]
        with patch.object(chaoxing,'courses',return_value=rows),patch.object(chaoxing,'read',side_effect=['no signature','<input id="workEnc" value="fixture">','暂无作业']):
            result=chaoxing.assignments(None,self.page)
        self.assertEqual(result['status'],'partial');self.assertEqual(len(result['errors']),1);self.assertEqual(result['items'],[])

    def test_ambiguous_course_stops(self):
        rows=[{'id':'1:2','course_id':'1','title':'甲'},{'id':'1:3','course_id':'1','title':'甲'}]
        with patch.object(chaoxing,'courses',return_value=rows):
            with self.assertRaisesRegex(QueryUnavailable,'不唯一'):chaoxing.assignments(None,self.page,'甲')

if __name__=='__main__':unittest.main()
