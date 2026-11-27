"""学习通网页版查询；仅复用浏览器会话，不提交作业。"""
import re
from datetime import datetime, timedelta
from urllib.parse import urlsplit, parse_qs, urljoin
from playwright.sync_api import Error
from tongji_cli.common import QueryUnavailable, SHANGHAI

COURSES = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
MIDDLE = "https://mooc1.chaoxing.com/visit/stucoursemiddle"
WORKS = "https://mooc1.chaoxing.com/mooc2/work/list"


def safe_url(url):
    try:
        parts = urlsplit(url)
        port = parts.port
    except (ValueError, TypeError):
        raise QueryUnavailable("学习通链接格式异常") from None
    if port not in {None, 443}:
        raise QueryUnavailable("学习通链接端口异常")
    if parts.scheme not in {"http", "https"} or not (parts.hostname or "").endswith(".chaoxing.com") or parts.username or parts.password:
        raise QueryUnavailable("学习通返回了非官方链接，已停止读取")
    return parts._replace(scheme="https").geturl()


def document(page, html, kind):
    return page.evaluate(r"""([html, kind]) => {
      const d = new DOMParser().parseFromString(html, 'text/html');
      const timeField = root => {
        const pattern = /^(作答时间|截止时间|截止日期|结束时间|截止)\s*[:：]\s*((?:(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)(?:\s*至\s*(?:(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)?)?)/;
        const elements = [...root.querySelectorAll('p,div,span,li,td')];
        if (!root.children.length) elements.push(root);
        const fields = elements.filter(e => ![...e.children].some(c => pattern.test(c.textContent.trim())))
          .map(e => e.textContent.trim().match(pattern)).filter(Boolean);
        const field = fields.find(m => m[1] === '作答时间') || fields[0];
        return field ? {field: field[1] + ':' + field[2], value: field[2].trim()} : null;
      };
      if (kind === 'time') return timeField(d.body);
      if (kind === 'has_next') return [...d.querySelectorAll('[rel=next], .pagination a, .paging a')].some(a => (a.rel === 'next' || /下一页|下页/.test(a.textContent)) && !a.closest('.disabled, [aria-disabled=true]') && !a.hasAttribute('disabled') && (a.getAttribute('onclick') || (a.getAttribute('href') && !['#', 'javascript:void(0)', 'javascript:;'].includes(a.getAttribute('href')))));
      if (kind === 'courses') return [...d.querySelectorAll('[href], [onclick]')].map(a => ({
        link: a.getAttribute('href') || a.getAttribute('onclick'),
        title: (a.closest('.course') || a.closest('li') || a).querySelector('[class*=course-name]')?.getAttribute('title') || a.getAttribute('title') || a.textContent.trim()
      }));
      if (kind === 'hidden') return Object.fromEntries([...d.querySelectorAll('input[id]')].map(x => [x.id, x.value]));
      return [...d.querySelectorAll('li[data]')].map(x => ({
        url: x.getAttribute('data'), title: x.querySelector('p.overHidden2')?.textContent.trim(),
        state: x.querySelector('p.status')?.textContent.trim(), text: x.textContent.trim(), time: timeField(x)
      }));
    }""", [html, kind])


def read(context, url, params=None):
    target = safe_url(url)
    for redirect in range(6):
        try:
            response = context.request.get(target, params=params, timeout=20000, max_redirects=0)
        except Error:
            raise QueryUnavailable("学习通请求超时或连接失败，请稍后核对官方页面") from None
        if response.status not in {301, 302, 303, 307, 308}:
            break
        location = response.headers.get("location")
        if not location:
            raise QueryUnavailable("学习通跳转缺少目标地址")
        target = safe_url(urljoin(target, location))
        if "passport" in urlsplit(target).hostname:
            raise QueryUnavailable("学习通登录已失效，请运行 login --site chaoxing")
        params = None
    else:
        raise QueryUnavailable("学习通跳转次数过多，请核对官方入口")
    safe_url(response.url)
    if not response.ok:
        raise QueryUnavailable(f"学习通未能读取此资源（HTTP {response.status}）")
    if "html" not in response.headers.get("content-type", "").lower():
        raise QueryUnavailable("学习通未返回 HTML 页面，数据格式待核实")
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
    if document(page, html, 'has_next'):
        raise QueryUnavailable('课程目录还有下一页，当前无法确认完整范围')
    rows = []
    seen = set()
    for item in document(page, html, 'courses'):
        found = re.search(r'stucoursemiddle\?([^\"\'<> ]+)', item['link'] or '')
        if not found:
            continue
        query = parse_qs(found[1])
        if not all(len(query.get(k, [])) == 1 and query[k][0].isdigit() for k in ('courseid', 'clazzid', 'cpi')):
            raise QueryUnavailable('学习通课程标识缺失或格式异常')
        cid, clazz, cpi = (query[k][0] for k in ('courseid', 'clazzid', 'cpi'))
        key = (cid, clazz, cpi)
        if key in seen:
            continue
        if not item['title']:
            raise QueryUnavailable('学习通课程名称缺失')
        seen.add(key)
        rows.append({'id': cid + ':' + clazz, 'course_id': cid, 'class_id': clazz, 'cpi': cpi,
                     'title': item['title'] or cid, 'source': 'chaoxing'})
    if not rows and not re.search('暂无课程|没有课程|还没有课程', html):
        raise QueryUnavailable("课程列表结构未识别，不能判定没有课程")
    return rows


def deadline(text):
    stamp = r'\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?'
    match = re.fullmatch(r'(?:截止时间|截止日期|结束时间|截止)\s*[:：]\s*(' + stamp + r')\s*', text)
    if not match:
        match = re.fullmatch(r'作答时间\s*[:：]\s*(?:' + stamp + r'|\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2})\s*至\s*(' + stamp + r')\s*', text)
    if not match:
        return None
    try:
        values = [int(x) for x in re.findall(r'\d+', match[1])]
        return datetime(*values, tzinfo=SHANGHAI).isoformat()
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
    if selector is not None:
        selector = selector.strip()
        if not selector:
            raise QueryUnavailable('课程筛选条件不能为空')
        exact = [c for c in selected if selector in (c['id'], c['course_id'], c['title'])]
        selected = exact or [c for c in selected if selector in c['title']]
        if len(selected) != 1:
            raise QueryUnavailable("课程匹配不唯一或未找到，请使用 courses 返回的 id")
    items, errors = [], []
    seen = set()
    for course in selected:
        try:
            html = read(context, MIDDLE, {'courseid': course['course_id'], 'clazzid': course['class_id'], 'cpi': course['cpi'], 'ismooc2': 1, 'v': 2})
            fields = document(page, html, 'hidden')
            if not fields.get('workEnc'):
                raise QueryUnavailable("课程未提供作业入口或签名")
            html = read(context, WORKS, {'courseId': course['course_id'], 'classId': course['class_id'], 'cpi': course['cpi'], 'ut': 's', 'enc': fields['workEnc'], 'openc': fields.get('openc', ''), 'stuenc': fields.get('enc', ''), 'isdisplaytable': 2})
            if document(page, html, 'has_next'):
                raise QueryUnavailable('作业目录还有下一页，当前无法确认完整范围')
            if re.search('没有权限|权限不足|无权访问|禁止访问', html):
                raise QueryUnavailable('学习通未授权查看此课程作业')
            rows = document(page, html, 'works')
            if not rows and not re.search('暂无作业|没有作业|未发布作业', html):
                raise QueryUnavailable("作业页面结构未识别，不能判定没有作业")
            for row in rows:
                if not row['title'] or not row['state']:
                    raise QueryUnavailable("作业字段缺失")
                target = safe_url(urljoin(WORKS, row['url']))
                if not urlsplit(target).path.endswith('/work/task'):
                    raise QueryUnavailable('未识别为只读作业详情入口，已停止读取')
                query = parse_qs(urlsplit(target).query)
                if len(query.get('workId', [])) != 1 or not query['workId'][0].isdigit():
                    raise QueryUnavailable('学习通作业标识缺失或格式异常')
                for key, expected in (('courseId', course['course_id']), ('classId', course['class_id'])):
                    if key in query and query[key] != [expected]:
                        raise QueryUnavailable('作业链接与所选课程或班级不符')
                identity = course['id'] + ':' + query['workId'][0]
                if identity in seen:
                    raise QueryUnavailable('学习通作业标识重复，列表完整性待核实')
                seen.add(identity)
                item = {'id': identity, 'course': course['title'], 'course_id': course['course_id'],
                        'class_id': course['class_id'], 'title': row['title'],
                        'submission_state': row['state'], 'submitted': submitted(row['state']),
                        'due': deadline(row['time']['field']) if row['time'] else None,
                        'due_as_listed': row['time']['value'] if row['time'] else None,
                        'detail': row['text'], 'url': target, 'source': 'chaoxing'}
                items.append(item)
                try:
                    detail = read(context, target)
                    time = document(page, detail, 'time')
                    if time:
                        item['due_as_listed'] = time['value']
                        item['due'] = deadline(time['field'])
                except (QueryUnavailable, Error) as error:
                    item['detail_status'] = 'unverified'
                    errors.append({'course': course['title'], 'id': identity,
                                   'detail': str(error) if isinstance(error, QueryUnavailable) else '作业详情读取失败'})
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
