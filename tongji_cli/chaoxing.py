"""学习通网页版查询；仅复用浏览器会话，不提交作业。"""
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit, parse_qs, unquote, urljoin
from playwright.sync_api import Error
from tongji_cli.common import QueryUnavailable, SHANGHAI

COURSES = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
MIDDLE = "https://mooc1.chaoxing.com/visit/stucoursemiddle"
WORKS = "https://mooc1.chaoxing.com/mooc2/work/list"


def safe_url(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not (parts.hostname or "").endswith(".chaoxing.com") or parts.username or parts.password:
        raise QueryUnavailable("学习通返回了非官方链接，已停止读取")
    return parts._replace(scheme="https").geturl()


def document(page, html, kind):
    return page.evaluate("""([html, kind]) => {
      const d = new DOMParser().parseFromString(html, 'text/html');
      if (kind === 'courses') return [...d.querySelectorAll('[href], [onclick]')].map(a => ({
        link: a.getAttribute('href') || a.getAttribute('onclick'),
        title: (a.closest('.course') || a.closest('li') || a).querySelector('[class*=course-name]')?.getAttribute('title') || a.getAttribute('title') || a.textContent.trim()
      }));
      if (kind === 'hidden') return Object.fromEntries([...d.querySelectorAll('input[id]')].map(x => [x.id, x.value]));
      return [...d.querySelectorAll('li[data]')].map(x => ({
        url: x.getAttribute('data'), title: x.querySelector('p.overHidden2')?.textContent.trim(),
        state: x.querySelector('p.status')?.textContent.trim(), text: x.textContent.trim()
      }));
    }""", [html, kind])


def read(context, url, params=None):
    target = safe_url(url)
    for redirect in range(6):
        response = context.request.get(target, params=params, timeout=30000, max_redirects=0)
        if response.status not in {301, 302, 303, 307, 308}:
            break
        target = safe_url(urljoin(target, response.headers.get("location", "")))
        if "passport" in urlsplit(target).hostname:
            raise QueryUnavailable("学习通登录已失效，请运行 login --site chaoxing")
        params = None
    else:
        raise QueryUnavailable("学习通跳转次数过多，请核对官方入口")
    safe_url(response.url)
    if not response.ok:
        raise QueryUnavailable("学习通请求失败，请稍后核对官方页面")
    body = response.text()
    if 'passport' in urlsplit(response.url).hostname or '用户登录' in body:
        raise QueryUnavailable("学习通登录已失效，请运行 login --site chaoxing")
    if '验证码' in body and ('antispider' in body or '9010' in body):
        raise QueryUnavailable("学习通要求验证码，请在官方网页完成验证")
    return body


def courses(context, page):
    base = read(context, 'https://i.chaoxing.com/base')
    match = re.search(r'"fid"\s*:\s*"?(\d+)', base) or re.search(r"var fid\s*=\s*'(\d+)'", base)
    if not match:
        raise QueryUnavailable("未能识别本人学习通机构，不能确定课程范围")
    html = read(context, COURSES, {'courseType': 1, 'courseFid': match[1], 'courseTeacherid': 0, 'courseOrderBy': 0})
    rows = []
    seen = set()
    for item in document(page, html, 'courses'):
        found = re.search(r'stucoursemiddle\?([^\"\'<> ]+)', item['link'] or '')
        if not found:
            continue
        query = parse_qs(found[1])
        if not all(query.get(k) for k in ('courseid', 'clazzid', 'cpi')):
            continue
        cid, clazz, cpi = (query[k][0] for k in ('courseid', 'clazzid', 'cpi'))
        key = (cid, clazz, cpi)
        if key in seen:
            continue
        if not item['title']:
            continue
        seen.add(key)
        rows.append({'id': cid + ':' + clazz, 'course_id': cid, 'class_id': clazz, 'cpi': cpi,
                     'title': item['title'] or cid, 'source': 'chaoxing'})
    if not rows and not re.search('暂无课程|没有课程|还没有课程', html):
        raise QueryUnavailable("课程列表结构未识别，不能判定没有课程")
    return rows


def deadline(text):
    match = re.search(r'(?:截止时间|截止日期|结束时间|截止)\s*[:：]?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', text)
    if not match:
        match = re.search(r'作答时间\s*[:：][^\n\r]*?至\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)', text)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match[1].replace('/', '-')).replace(tzinfo=SHANGHAI).isoformat()
    except ValueError:
        return None


def submitted(state):
    if not state:
        return None
    if any(word in state for word in ('未交', '未提交', '待完成', '未完成')):
        return False
    if any(word in state for word in ('已交', '已提交', '已完成', '待批阅', '已批阅')):
        return True
    return None


def assignments(context, page, selector=None):
    selected = courses(context, page)
    if selector:
        exact = [c for c in selected if selector in (c['id'], c['course_id'], c['title'])]
        selected = exact or [c for c in selected if selector in c['title']]
        if len(selected) != 1:
            raise QueryUnavailable("课程匹配不唯一或未找到，请使用 courses 返回的 id")
    items, errors = [], []
    for course in selected:
        try:
            html = read(context, MIDDLE, {'courseid': course['course_id'], 'clazzid': course['class_id'], 'cpi': course['cpi'], 'ismooc2': 1, 'v': 2})
            fields = document(page, html, 'hidden')
            if not fields.get('workEnc'):
                raise QueryUnavailable("课程未提供作业入口或签名")
            html = read(context, WORKS, {'courseId': course['course_id'], 'classId': course['class_id'], 'cpi': course['cpi'], 'ut': 's', 'enc': fields['workEnc'], 'openc': fields.get('openc', ''), 'stuenc': fields.get('enc', ''), 'isdisplaytable': 2})
            rows = document(page, html, 'works')
            if not rows and not re.search('暂无作业|没有作业|暂时没有|未发布作业', html):
                raise QueryUnavailable("作业页面结构未识别，不能判定没有作业")
            for row in rows:
                if not row['title'] or not row['state']:
                    raise QueryUnavailable("作业字段缺失")
                target = safe_url(urljoin(WORKS, unquote(row['url'])))
                if not urlsplit(target).path.endswith('/work/task'):
                    raise QueryUnavailable('未识别为只读作业详情入口，已停止读取')
                detail = read(context, target)
                detail_text = page.evaluate("s => { const d = new DOMParser().parseFromString(s, 'text/html'); d.querySelectorAll('script,style').forEach(x => x.remove()); return d.body.textContent; }", detail)
                times = re.search(r'作答时间\s*[:：]\s*([^\n\r]+)', detail_text)
                due_text = times[1].strip() if times else None
                work_id = parse_qs(urlsplit(target).query).get('workId', [row['title']])[0]
                items.append({'id': course['id'] + ':' + work_id, 'course': course['title'], 'course_id': course['course_id'], 'class_id': course['class_id'], 'title': row['title'], 'submission_state': row['state'], 'submitted': submitted(row['state']), 'due': deadline(row['text'] + '\n' + detail_text), 'due_as_listed': due_text, 'detail': row['text'], 'url': target, 'source': 'chaoxing'})
        except (QueryUnavailable, Error) as error:
            errors.append({'course': course['title'], 'detail': str(error) if isinstance(error, QueryUnavailable) else '页面读取失败'})
    result = {'status': 'partial' if errors else 'ok', 'items': items, 'courses_checked': len(selected), 'scope': '当前机构我学的课目录；不含归档目录和其他机构；仅普通作业，不含考试和章节测验'}
    if errors:
        result['errors'] = errors
    return result


def run(args, context, page, now):
    if args.operation == 'courses':
        return courses(context, page)
    result = assignments(context, page, args.course)
    if args.next:
        end = now.date() + timedelta(days=args.next)
        result['items'] = [x for x in result['items'] if x['due'] is None or now.date() <= datetime.fromisoformat(x['due']).date() < end]
        result['detail'] = '保留截止时间未知的作业；未推断缺少年份的日期'
    return result
