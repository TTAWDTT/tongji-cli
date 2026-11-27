import unittest
from datetime import date
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from playwright.sync_api import sync_playwright, Error
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

    def test_http_errors_and_content_type_are_checked(self):
        for status, kind in [(503, 'text/html'), (200, 'application/json')]:
            context = Mock()
            context.request.get.return_value = Mock(status=status, ok=status == 200,
                url='https://i.chaoxing.com/base', headers={'content-type': kind})
            with self.assertRaises(QueryUnavailable):
                chaoxing.read(context, 'https://i.chaoxing.com/base')

    def test_transport_error_is_sanitized(self):
        context = Mock()
        context.request.get.side_effect = Error('request failed secret-cookie-value')
        with self.assertRaisesRegex(QueryUnavailable, '连接失败') as error:
            chaoxing.read(context, 'https://i.chaoxing.com/base')
        self.assertNotIn('secret', str(error.exception))

    def test_external_redirect_is_not_requested(self):
        context = Mock()
        context.request.get.return_value = Mock(status=302, headers={'location': 'https://evil.org/path'})
        with self.assertRaises(QueryUnavailable):
            chaoxing.read(context, 'https://i.chaoxing.com/base')
        self.assertEqual(context.request.get.call_count, 1)

    def test_single_digit_calendar_fields(self):
        self.assertEqual(chaoxing.deadline('截止时间:2026/2/3 9:05'), '2026-02-03T09:05:00+08:00')

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

    def test_malformed_course_identity_is_not_silently_skipped(self):
        html = '<a href="stucoursemiddle?courseid=1&amp;clazzid=2" title="课程甲">课程甲</a>'
        with patch.object(chaoxing, 'read', side_effect=["var fid = '123';", html]):
            with self.assertRaisesRegex(QueryUnavailable, '标识'):
                chaoxing.courses(None, self.page)

    def test_failed_details_keep_listed_assignment(self):
        course={'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'课程甲'}
        work='<li data="https://mooc1.chaoxing.com/mooc2/work/task?workId=9"><p class="overHidden2">报告</p><p class="status">未完成</p></li>'
        with patch.object(chaoxing,'courses',return_value=[course]), patch.object(chaoxing,'read',side_effect=['<input id="workEnc" value="fixture">',work,QueryUnavailable('详情暂不可用')]):
            result=chaoxing.assignments(None,self.page)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['items'][0]['title'],'报告')
        self.assertFalse(result['items'][0]['submitted'])
        self.assertEqual(result['items'][0]['detail_status'],'unverified')
        self.assertEqual(result['errors'][0]['id'],'1:2:9')

    def test_blank_selector_does_not_query_all_courses(self):
        with patch.object(chaoxing,'courses',return_value=[]):
            with self.assertRaisesRegex(QueryUnavailable, '不能为空'):
                chaoxing.assignments(None,self.page,' ')

    def test_pagination_is_not_reported_as_complete(self):
        with patch.object(chaoxing,'read',side_effect=["var fid = '123';",'<a rel="next" href="?page=2">下一页</a>']):
            with self.assertRaisesRegex(QueryUnavailable, '下一页'):
                chaoxing.courses(None,self.page)

    def test_wrong_course_link_is_rejected(self):
        course={'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'课程甲'}
        work='<li data="https://mooc1.chaoxing.com/mooc2/work/task?workId=9&amp;courseId=99"><p class="overHidden2">报告</p><p class="status">未完成</p></li>'
        with patch.object(chaoxing,'courses',return_value=[course]), patch.object(chaoxing,'read',side_effect=['<input id="workEnc" value="fixture">',work]) as read:
            result=chaoxing.assignments(None,self.page)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['items'],[])
        self.assertEqual(read.call_count,2)

    def test_permission_page_is_partial_and_other_courses_survive(self):
        rows=[{'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'甲'},
              {'id':'4:5','course_id':'4','class_id':'5','cpi':'3','title':'乙'}]
        work='<li data="/mooc2/work/task?workId=9"><p class="overHidden2">报告</p><p class="status">未完成</p></li>'
        with patch.object(chaoxing,'courses',return_value=rows), patch.object(chaoxing,'read',side_effect=[
            '<input id="workEnc" value="x">','<p>你暂时没有权限查看此课程</p>',
            '<input id="workEnc" value="x">',work,'<p>作答时间：11-01 08:00 至 12-03 20:00</p>']):
            result=chaoxing.assignments(None,self.page)
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['errors'][0]['course'],'甲')
        self.assertEqual(result['items'][0]['course'],'乙')

    def test_explicit_empty_work_list_is_ok(self):
        course={'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'甲'}
        with patch.object(chaoxing,'courses',return_value=[course]), patch.object(chaoxing,'read',side_effect=[
            '<input id="workEnc" value="x">','<p class="empty">暂无作业</p>']):
            result=chaoxing.assignments(None,self.page)
        self.assertEqual(result['status'],'ok');self.assertEqual(result['items'],[])

    def test_unrelated_date_does_not_replace_unknown_deadline(self):
        course={'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'甲'}
        work='<li data="/mooc2/work/task?workId=9"><p class="overHidden2">报告</p><p class="status">未完成</p></li>'
        detail='<p>作答时间：11-01 08:00 至 12-03 20:00</p><p>参考上一轮活动，报名截止时间：2025-06-01 12:00</p>'
        with patch.object(chaoxing,'courses',return_value=[course]), patch.object(chaoxing,'read',side_effect=[
            '<input id="workEnc" value="x">',work,detail]):
            result=chaoxing.assignments(None,self.page)
        item=result['items'][0]
        self.assertIsNone(item['due'])
        self.assertEqual(item['due_as_listed'],'11-01 08:00 至 12-03 20:00')
        week=week_view({'jw':{'status':'ok','items':[]},'canvas':{'status':'ok','items':[]},'chaoxing':result},date(2026,11,28))['week']
        self.assertEqual(week['undated_assignments'],[item])

    def test_enabled_script_next_and_disabled_last_page(self):
        for control, expected in [
            ('<a rel="next" href="#" onclick="loadPage(2);return false">下一页</a>',True),
            ('<a rel="next" href="#" onclick="loadPage(2)" class="disabled">下一页</a>',False),
            ('<a rel="next" href="#" onclick="loadPage(2)" aria-disabled="true">下一页</a>',False)]:
            with self.subTest(control=control):
                self.assertEqual(chaoxing.document(self.page,'<div class="pagination">'+control+'</div>','has_next'),expected)

    def test_script_next_marks_work_list_partial(self):
        course={'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'甲'}
        control='<div class="pagination"><a rel="next" href="#" onclick="loadPage(2);return false">下一页</a></div>'
        with patch.object(chaoxing,'courses',return_value=[course]), patch.object(chaoxing,'read',side_effect=[
            '<input id="workEnc" value="x">',control]):
            result=chaoxing.assignments(None,self.page)
        self.assertEqual(result['status'],'partial');self.assertIn('下一页',result['errors'][0]['detail'])

    def test_encoded_query_value_is_preserved_for_request_and_output(self):
        course={'id':'1:2','course_id':'1','class_id':'2','cpi':'3','title':'甲'}
        work='<li data="/mooc2/work/task?workId=9&amp;label=A%26B"><p class="overHidden2">报告</p><p class="status">未完成</p></li>'
        with patch.object(chaoxing,'courses',return_value=[course]), patch.object(chaoxing,'read',side_effect=[
            '<input id="workEnc" value="x">',work,'<p>作答时间：11-01 08:00 至 12-03 20:00</p>']) as read:
            result=chaoxing.assignments(None,self.page)
        target='https://mooc1.chaoxing.com/mooc2/work/task?workId=9&label=A%26B'
        self.assertEqual(read.call_args.args[1],target)
        self.assertEqual(result['items'][0]['url'],target)

class DefaultSitesTest(unittest.TestCase):
    def test_default_login_status_today_week_use_same_sites(self):
        import io, json
        from contextlib import redirect_stdout
        from unittest.mock import MagicMock
        from tongji_cli import cli, auth
        states={'canvas':'authenticated','jw':'authenticated','chaoxing':'login_required'}
        with TemporaryDirectory() as temp:
            for command, extra, expected_code in [('login',[],0),('status',[],0),('today',[],0),('week',[],0),
                ('today',['--include-chaoxing'],1),('week',['--include-chaoxing'],1)]:
                with self.subTest(command=command,extra=extra):
                    context=MagicMock();context.pages=[MagicMock()]
                    with patch('sys.argv',['tongji',command,*extra,'--json']), patch.object(auth,'PROFILE',__import__('pathlib').Path(temp)), \
                         patch.object(auth,'sync_playwright'),patch.object(auth,'open_session',return_value=context), \
                         patch.object(auth,'visit',side_effect=lambda page,site,interactive:states[site]) as visit, \
                         patch.object(auth.subprocess,'run',return_value=Mock(stdout=json.dumps({s:{'status':states[s]} for s in ('canvas','jw')}))), \
                         patch.object(cli,'site_items',return_value=[]),redirect_stdout(io.StringIO()) as output:
                        code=cli.run(cli.arguments())
                    self.assertEqual(code,expected_code)
                    self.assertEqual([c.args[1] for c in visit.call_args_list],['canvas','jw']+(['chaoxing'] if extra else []))
                    if command=='week':
                        self.assertEqual(json.loads(output.getvalue())['week']['status'],'partial' if extra else 'ok')

if __name__=='__main__':unittest.main()
