"""学习通网页版查询；仅复用浏览器会话，不提交作业。"""
import re
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.sync_api import Error

from tongji_cli.common import QueryUnavailable, SHANGHAI

BASE = "https://i.chaoxing.com/base"
COURSES = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
MIDDLE = "https://mooc1.chaoxing.com/visit/stucoursemiddle"
WORKS = "https://mooc1.chaoxing.com/mooc2/work/list"
TASK_PATH = "/mooc2/work/task"
READ_PATHS = {
    "/base": {"/base"},
    "/mooc2-ans/visit/courselistdata": {"/mooc2-ans/visit/courselistdata"},
    "/visit/stucoursemiddle": {"/visit/stucoursemiddle", "/mooc2-ans/mycourse/stu"},
    "/mooc2/work/list": {"/mooc2/work/list"},
    TASK_PATH: {TASK_PATH, "/mooc2/work/preview", "/mooc2/work/view"},
}


def safe_url(url, base=None):
    try:
        parts = urlsplit(urljoin(base, url) if base else url)
        port = parts.port
    except (ValueError, TypeError):
        raise QueryUnavailable("学习通链接格式异常") from None
    if port not in {None, 443}:
        raise QueryUnavailable("学习通链接端口异常")
    if (parts.scheme not in {"http", "https"} or not (parts.hostname or "").endswith(".chaoxing.com")
            or parts.username is not None or parts.password is not None):
        raise QueryUnavailable("学习通返回了非官方链接，已停止读取")
    return parts._replace(scheme="https").geturl()


def check_ids(query, expected):
    for key, values in query.items():
        name = key.lower()
        if name == "clazzid":
            name = "classid"
        if name in expected and values != [expected[name]]:
            raise QueryUnavailable("学习通链接与所选作业、课程或班级不符")


def read(context, url, params=None, *, expected_ids=None):
    """Return HTML and its final URL. Relative links belong to that document."""
    target = safe_url(url)
    allowed = READ_PATHS.get(urlsplit(target).path.removeprefix("/mooc-ans"), set())
    for _ in range(6):
        parts = urlsplit(target)
        if parts.hostname.startswith("passport"):
            raise QueryUnavailable("学习通登录已失效，请运行 login --site chaoxing")
        if parts.path.removeprefix("/mooc-ans") not in allowed:
            raise QueryUnavailable("未识别为此查询的只读页面，已停止读取")
        if expected_ids:
            check_ids(parse_qs(parts.query, keep_blank_values=True), expected_ids)
        try:
            response = context.request.get(target, params=params, timeout=20000, max_redirects=0)
            try:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise QueryUnavailable("学习通跳转缺少目标地址")
                    target = safe_url(location, response.url)
                    params = None
                    continue
                if not response.ok:
                    raise QueryUnavailable(f"学习通未能读取此资源（HTTP {response.status}）")
                mime = response.headers.get("content-type", "").partition(";")[0].strip().lower()
                if mime not in {"text/html", "application/xhtml+xml"}:
                    raise QueryUnavailable("学习通未返回 HTML 页面，数据格式待核实")
                return response.text(), safe_url(response.url)
            finally:
                response.dispose()
        except Error:
            raise QueryUnavailable("学习通请求超时或连接失败，请稍后核对官方页面") from None
    raise QueryUnavailable("学习通跳转次数过多，请核对官方入口")


def document(page, html, kind):
    result = page.evaluate(r"""([html, kind]) => {
      const d = new DOMParser().parseFromString(html, 'text/html');
      // A hidden input is intentional. Read only the fields used by the work list.
      const inputs = kind === 'hidden' ? Object.fromEntries(['workEnc','openc','enc']
        .map(id => [id, d.querySelector('input[id="' + id + '"]')?.value || ''])) : null;
      d.querySelectorAll('script, style, template, noscript, [hidden], [aria-hidden="true"], .hidden, .hide')
        .forEach(e => e.remove());
      for (const e of d.querySelectorAll('[style]')) {
        if (e.style.display === 'none' || e.style.visibility === 'hidden') e.remove();
      }

      const messages = [d.title.trim()];
      const walker = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (!node.parentElement.closest('li[data], .overHidden2, .course, .infoHead, article, .question, a[href], aside, nav, header, footer')) {
          const message = node.textContent.trim();
          if (message) messages.push(message);
        }
      }
      const denied = /(?:没有|无)(?:查看|访问)?权限|权限不足|无权(?:访问|查看)|禁止访问/;
      if (messages.some(s => denied.test(s)))
        return {error: '学习通权限不足，未能核实此页面'};
      if (messages.includes('用户登录') && (d.title.includes('登录') || d.querySelector('input[type=password]')))
        return {error: '学习通登录已失效，请运行 login --site chaoxing'};
      if (messages.some(s => s.includes('验证码')) && /antispider|9010/i.test(html))
        return {error: '学习通要求验证码，请在官方网页完成验证'};
      if (kind === 'hidden') return inputs;
      if (kind === 'institution') {
        const ids = new Set();
        for (const match of html.matchAll(/"fid"\s*:\s*(?:"([0-9]+)"|([0-9]+)(?=\s*[,}]))|\bvar\s+fid\s*=\s*['"]([0-9]+)['"]/g))
          ids.add(match[1] || match[2] || match[3]);
        return ids.size === 1 ? [...ids][0] : null;
      }

      const timeField = root => {
        const pattern = /^(作答时间|截止时间|截止日期|结束时间|截止)\s*[:：]\s*(\S[\s\S]*)$/;
        const elements = [root, ...root.querySelectorAll('p,div,span,li,td')];
        const matches = elements.filter(e => !e.closest('.overHidden2,.status') && !e.querySelector('.overHidden2,.status'))
          .filter(e => ![...e.children].some(c => pattern.test(c.textContent.trim())))
          .map(e => e.textContent.trim().match(pattern)).filter(Boolean);
        const field = matches.find(m => m[1] === '作答时间') || matches[0];
        return field ? {fields: matches.map(m => m[1] + ':' + m[2]), value: field[2]} : null;
      };
      if (kind === 'time') {
        const head = d.querySelector('.detailsHead .infoHead');
        if (head) return timeField(head);
        // Also accept a standalone field fragment. A full document needs its work header.
        const fragment = !/<(?:html|body)\b|<!doctype/i.test(html) &&
          [...d.body.children].every(e => e.matches('p, span'));
        return (fragment && timeField(d.body)) || {error: '作业详情结构未识别'};
      }

      const list = (kind === 'works' && d.querySelector('.task-list')) || d.body;
      const controls = [...list.querySelectorAll('[rel~="next" i], .pagination :is(a,button), .paging :is(a,button)'),
                        ...d.head.querySelectorAll('link[rel~="next" i]')];
      const next = controls.some(e => {
        if (e.closest('.disabled, [disabled], [aria-disabled="true"]')) return false;
        const label = [e.textContent, e.title, e.getAttribute('aria-label')].join(' ');
        if (!e.matches('[rel~="next" i]') && !/下一页|下页/.test(label)) return false;
        const href = (e.getAttribute('href') || '').trim();
        return e.matches('button') || !!e.getAttribute('onclick')?.trim() ||
          (!!href && !/^(?:#|javascript:\s*(?:void\s*\(\s*0\s*\))?\s*;?)$/i.test(href));
      });
      if (kind === 'has_next') return next;
      const emptyList = (root, pattern) => (pattern.test(root.textContent.trim()) && messages.some(s => pattern.test(s))) ||
        [...root.querySelectorAll('.null-data, .empty')].some(e =>
          !e.closest('aside, nav, header, footer, .course, li[data]') && pattern.test(e.textContent.trim()));
      if (kind === 'courses') {
        const cards = new Set(d.querySelectorAll('.course'));
        const rows = [];
        for (const a of d.querySelectorAll('[href*="stucoursemiddle"], [onclick*="stucoursemiddle"]')) {
          const card = a.closest('.course') || a.closest('li') || a;
          cards.delete(card);
          const name = card.querySelector('[class*=course-name]');
          const title = name?.getAttribute('title')?.trim() || name?.textContent.trim() ||
            a.getAttribute('title')?.trim() || a.textContent.trim();
          const link = [a.getAttribute('href'), a.getAttribute('onclick')].find(v => v?.includes('stucoursemiddle?'));
          rows.push({link, title});
        }
        return {rows, next, missing: cards.size > 0,
                empty: emptyList(d.body, /^(?:暂无课程|(?:还)?没有课程)[。！!]?$/u)};
      }
      const workRows = new Set([...list.querySelectorAll('li[data], li p.overHidden2')].map(e => e.closest('li')));
      const rows = [...workRows].map(e => ({
        url: e.getAttribute('data'), title: e.querySelector('p.overHidden2')?.textContent.trim(),
        state: e.querySelector('p.status')?.textContent.trim(), text: e.textContent.trim(), time: timeField(e)
      }));
      return {rows, next, empty: emptyList(list, /^(?:暂无作业|没有作业|未发布作业)[。！!]?$/u)};
    }""", [html, kind])
    if isinstance(result, dict) and "error" in result:
        raise QueryUnavailable(result["error"])
    return result


def numeric_value(query, key):
    values = query.get(key, [])
    if len(values) == 1 and re.fullmatch(r"[0-9]+", values[0]):
        return values[0]
    return None


def courses(context, page, *, errors=None):
    base, _ = read(context, BASE)
    fid = document(page, base, "institution")
    if not fid:
        raise QueryUnavailable("未能识别本人学习通机构，不能确定课程范围")
    html, _ = read(context, COURSES, {"courseType": 1, "courseFid": fid, "courseTeacherid": 0, "courseOrderBy": 0})
    directory = document(page, html, "courses")
    issues = []
    if directory["next"]:
        issues.append({"detail": "课程目录还有下一页，当前无法确认完整范围"})
    if directory["missing"]:
        issues.append({"detail": "学习通课程卡片缺少可识别的入口"})
    entries, conflicts = {}, set()
    for item in directory["rows"]:
        found = re.search(r"""stucoursemiddle\?([^"'<>#\s]+)""", item.get("link") or "")
        query = parse_qs(found[1], keep_blank_values=True) if found else {}
        cid, clazz, cpi = (numeric_value(query, k) for k in ("courseid", "clazzid", "cpi"))
        if not all((cid, clazz, cpi)):
            issues.append({"detail": "学习通课程标识缺失或格式异常"})
            continue
        key = cid + ":" + clazz
        if key in conflicts:
            continue
        if key in entries:
            if entries[key]["cpi"] != cpi:
                conflicts.add(key)
                del entries[key]
                issues.append({"id": key, "detail": "同一课程和班级的入口标识不一致"})
            elif not entries[key]["title"]:
                entries[key]["title"] = item["title"]
            continue
        entries[key] = {"id": key, "course_id": cid, "class_id": clazz, "cpi": cpi,
                        "title": item["title"], "source": "chaoxing"}
    rows = [c for c in entries.values() if c["title"]]
    if len(rows) != len(entries):
        issues.append({"detail": "学习通课程名称缺失"})
    if issues and (errors is None or not rows):
        raise QueryUnavailable(issues[0]["detail"])
    if not rows and not directory["empty"]:
        raise QueryUnavailable("课程列表结构未识别，不能判定没有课程")
    if errors is not None:
        errors.extend(issues)
    return rows


STAMP = r"(?:[0-9]{4}[-/])?[0-9]{1,2}[-/][0-9]{1,2}[ T][0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?"
END_TIME = re.compile(rf"(?:(?:截止时间|截止日期|结束时间|截止)\s*[:：]\s*|作答时间\s*[:：]\s*{STAMP}\s*至\s*)({STAMP})")


def deadline(text, listed_due=None):
    match = END_TIME.fullmatch(text.strip())
    if not match:
        return None
    values = [int(x) for x in re.findall(r"[0-9]+", match[1])]
    if not re.match(r"[0-9]{4}[-/]", match[1]):
        if not listed_due:
            return None
        known = datetime.fromisoformat(listed_due)
        # A short detail can confirm a full list timestamp, including its precision.
        if values != [known.month, known.day, known.hour, known.minute, known.second][:len(values)]:
            return None
        return listed_due
    try:
        return datetime(*values, tzinfo=SHANGHAI).isoformat()
    except ValueError:
        return None


def field_deadline(time, listed_due=None):
    if not time:
        return None
    fields = time["fields"]
    dated = {due for field in fields if (due := deadline(field))}
    if len(dated) > 1:
        return None
    candidate = next(iter(dated), listed_due)
    if candidate and all(deadline(field, candidate) == candidate for field in fields):
        return candidate
    return None


def submitted(state):
    if not state:
        return None
    negative = any(word in state for word in ("未交", "未提交", "待完成", "未完成"))
    positive = any(word in state for word in ("已交", "已提交", "已完成", "待批阅", "已批阅"))
    return positive if positive != negative else None


def assignment_row(course, row, list_url):
    if not row["url"]:
        raise QueryUnavailable("学习通作业缺少详情链接")
    if not row["title"]:
        raise QueryUnavailable("作业名称缺失")
    target = safe_url(row["url"], list_url)
    parts = urlsplit(target)
    if parts.path.removeprefix("/mooc-ans") != TASK_PATH:
        raise QueryUnavailable("未识别为只读作业详情入口，已停止读取")
    query = parse_qs(parts.query, keep_blank_values=True)
    work = numeric_value(query, "workId")
    if work is None:
        raise QueryUnavailable("学习通作业标识缺失或格式异常")
    check_ids(query, {"courseid": course["course_id"], "classid": course["class_id"], "workid": work})
    time = row["time"]
    return {"id": course["id"] + ":" + work, "course": course["title"], "course_id": course["course_id"],
            "class_id": course["class_id"], "title": row["title"], "submission_state": row["state"] or None,
            "submitted": submitted(row["state"]), "due": field_deadline(time),
            "due_as_listed": time["value"] if time else None, "detail": row["text"], "url": target, "source": "chaoxing"}


def work_list(context, page, course):
    ids = {"courseid": course["course_id"], "classid": course["class_id"]}
    html, _ = read(context, MIDDLE, {"courseid": course["course_id"], "clazzid": course["class_id"],
                                     "cpi": course["cpi"], "ismooc2": 1, "v": 2}, expected_ids=ids)
    fields = document(page, html, "hidden")
    if not fields.get("workEnc"):
        raise QueryUnavailable("课程未提供作业入口或签名")
    html, url = read(context, WORKS, {"courseId": course["course_id"], "classId": course["class_id"],
                                      "cpi": course["cpi"], "ut": "s", "enc": fields["workEnc"],
                                      "openc": fields.get("openc", ""), "stuenc": fields.get("enc", ""),
                                      "isdisplaytable": 2}, expected_ids=ids)
    listing = document(page, html, "works")
    if not listing["rows"] and not listing["empty"] and not listing["next"]:
        raise QueryUnavailable("作业页面结构未识别，不能判定没有作业")
    return listing, url


def assignments(context, page, selector=None):
    if selector is not None:
        selector = selector.strip()
        if not selector:
            raise QueryUnavailable("课程筛选条件不能为空")
    items, errors = [], []
    selected = courses(context, page, errors=errors)
    if selector is not None:
        by_id = [c for c in selected if selector == c["id"]]
        if errors and not by_id:
            raise QueryUnavailable("课程目录不完整，无法确认唯一匹配，请使用已核实的复合 id")
        selected = (by_id or [c for c in selected if selector in (c["course_id"], c["title"])]
                    or [c for c in selected if selector in c["title"]])
        if len(selected) != 1:
            raise QueryUnavailable("课程匹配不唯一或未找到，请使用 courses 返回的 id")
    for course in selected:
        scope = {"course": course["title"], "course_id": course["course_id"], "class_id": course["class_id"]}
        try:
            listing, list_url = work_list(context, page, course)
        except (QueryUnavailable, Error) as error:
            errors.append({**scope, "detail": str(error) if isinstance(error, QueryUnavailable) else "页面读取失败"})
            continue
        if listing["next"]:
            errors.append({**scope, "detail": "作业目录还有下一页，当前无法确认完整范围"})
        seen = set()
        for row in listing["rows"]:
            try:
                item = assignment_row(course, row, list_url)
                if item["id"] in seen:
                    raise QueryUnavailable("学习通作业标识重复，列表完整性待核实")
            except QueryUnavailable as error:
                errors.append({**scope, "detail": str(error)})
                continue
            seen.add(item["id"])
            items.append(item)
            if item["submission_state"] is None:
                errors.append({**scope, "id": item["id"], "detail": "作业未提供提交状态"})
            try:
                detail, _ = read(context, item["url"], expected_ids={
                    "courseid": course["course_id"], "classid": course["class_id"], "workid": item["id"].rsplit(":", 1)[1]})
                time = document(page, detail, "time")
                if time:
                    item["due"] = field_deadline(time, item["due"])
                    item["due_as_listed"] = time["value"]
            except (QueryUnavailable, Error) as error:
                item["detail_status"] = "unverified"
                errors.append({**scope, "id": item["id"],
                               "detail": str(error) if isinstance(error, QueryUnavailable) else "作业详情读取失败"})
    result = {"status": "partial" if errors else "ok", "items": items, "courses_checked": len(selected),
              "scope": "当前机构我学的课目录；不含归档目录和其他机构；仅普通作业，不含考试和章节测验"}
    if errors:
        result["errors"] = errors
    return result


def run(args, context, page, now):
    if args.operation == "courses":
        errors = []
        rows = courses(context, page, errors=errors)
        return {"status": "partial", "items": rows, "errors": errors} if errors else rows
    result = assignments(context, page, args.course)
    if args.next:
        end = now.date() + timedelta(days=args.next)
        result["items"] = [x for x in result["items"] if x["due"] is None or now.date() <= datetime.fromisoformat(x["due"]).date() < end]
        result["detail"] = "保留截止时间未知的作业；未推断缺少年份的日期"
    return result
