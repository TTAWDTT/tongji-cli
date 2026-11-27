import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit

from playwright.sync_api import Error, TimeoutError as BrowserTimeout, sync_playwright

from tongji_cli.media import courses as media_courses
from tongji_cli.browser_session import PROFILE, open_session
from tongji_cli.common import QueryUnavailable, failure
from tongji_cli.jw.commands import personal_change_command


SITES = {
    "canvas": "https://canvas.tongji.edu.cn/courses",
    "jw": "https://1.tongji.edu.cn/workbench",
    "service": "https://all.tongji.edu.cn/",
    "library": "https://www.lib.tongji.edu.cn/my/home/dashboard",
    "space": "https://space.tongji.edu.cn/",
    "card": "https://yikatong.tongji.edu.cn/",
    "stadium": "https://stadium.tongji.edu.cn/pc/#/Venue/1",
    "media": media_courses.ENTRY,
}


def observe(page, site):
    host = urlsplit(page.url).hostname
    if host == "iam.tongji.edu.cn":
        return "login_required"
    if host != urlsplit(SITES[site]).hostname:
        return "unverified"
    if site == "media":
        return "authenticated" if page.get_by_text("我的课程", exact=True).first.is_visible() else "unverified"
    if site == "service":
        portal = page.frame_locator('iframe[src*="CUS_TEMPLATE_TONGJI"]')
        return "authenticated" if portal.locator('#stepThree input[placeholder*="事项"]').is_visible() else "unverified"
    if site == "stadium":
        if page.get_by_text("退出", exact=True).filter(visible=True).count():
            return "authenticated"
        return "login_required" if page.get_by_text(re.compile(r"^\s*登\s*录\s*$")).filter(visible=True).count() else "unverified"
    if site == "card":
        if page.get_by_role("link", name="个人中心", exact=True).is_visible():
            return "authenticated"
        return "login_required" if page.get_by_role("link", name="统一认证登陆").is_visible() else "unverified"
    if site == "space":
        return "authenticated" if page.get_by_text("我的中心", exact=True).first.is_visible() else "unverified"
    if site == "library":
        if page.get_by_text("登录统一身份认证", exact=True).first.is_visible():
            return "login_required"
        return "authenticated" if page.get_by_role("link", name="图书借阅", exact=True).is_visible() else "unverified"
    if site == "canvas":
        if page.locator("#global_nav_profile_link").is_visible() and page.locator("#content").is_visible():
            return "authenticated"
    else:
        if page.get_by_text(re.compile(r"^(退出登录|安全退出|个人课表|我的课表|我的选课)$")).filter(visible=True).count():
            return "authenticated"
        if page.get_by_text(re.compile(r"^(统一身份认证登录|统一身份认证|登录)$")).first.is_visible():
            return "login_required"
    return "unverified"


def visit(page, site, interactive):
    if site == "space" and not interactive:
        page.set_viewport_size({"width": 1280, "height": 720})
    try:
        page.goto(SITES[site], wait_until="commit", timeout=30000)
    except Error:
        if observe(page, site) != "login_required":
            return "unreachable"
    deadline = time.monotonic() + (600 if interactive else 12)
    login_seen = None
    opened_sso = False
    stadium_menu_open = False
    while time.monotonic() < deadline:
        state = observe(page, site)
        if state == "login_required":
            if (interactive and site == "library" and not opened_sso
                    and urlsplit(page.url).hostname == urlsplit(SITES["library"]).hostname):
                page.get_by_text("登录统一身份认证", exact=True).first.click()
                opened_sso = True
            elif site == "stadium" and not opened_sso and urlsplit(page.url).hostname == urlsplit(SITES[site]).hostname:
                login = re.compile(r"^\s*登\s*录\s*$")
                dialog = page.locator('[role=dialog]:visible').get_by_text(login)
                if dialog.filter(visible=True).count():
                    dialog.filter(visible=True).last.click()
                    opened_sso = True
                    login_seen = None
                    continue
                if not stadium_menu_open:
                    try:
                        page.get_by_text(login).filter(visible=True).first.click(timeout=1200)
                    except BrowserTimeout:
                        if observe(page, site) == "login_required":
                            raise
                        continue
                    stadium_menu_open = True
                    continue
            elif site == "card" and not opened_sso and urlsplit(page.url).hostname == urlsplit(SITES["card"]).hostname:
                page.get_by_role("link", name="统一认证登陆").click()
                opened_sso = True
                login_seen = None
                continue
            if login_seen is None:
                login_seen = time.monotonic()
        else:
            login_seen = None
        if state == "authenticated" or (not interactive and login_seen is not None and time.monotonic() - login_seen >= 3):
            return state
        page.wait_for_timeout(500)
    return observe(page, site)


def signed_in_queries(args, now, site_items):
    interactive = args.command == "login"
    site_filter = getattr(args, "site", args.command)
    if args.command in {"login", "status"} and site_filter == "all":
        sites = list(SITES)
    elif site_filter in SITES:
        sites = [site_filter]
    else:
        sites = ["canvas", "jw"]
    os.umask(0o077)
    PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = {}
    with sync_playwright() as engine:
        checkout_window = args.command == "sports" and args.operation == "reserve" and not args.preview
        library_window = args.command == "library" and args.operation in {"study", "rooms"} and args.action == "reserve" and not args.preview
        handoff = checkout_window or library_window or (personal_change_command(args) and not args.preview)
        context = open_session(engine, PROFILE, interactive=interactive or bool(handoff), no_viewport=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            if interactive:
                page.bring_to_front()
            for site in sites:
                if interactive:
                    print(f"正在打开 {site} 的学校页面，请在浏览器内完成认证。", file=sys.stderr, flush=True)
                try:
                    state = visit(page, site, interactive)
                    entry = {"status": state}
                    if state == "authenticated" and args.command not in {"login", "status"}:
                        output = site_items(args, site, context, page, now)
                        if isinstance(output, dict):
                            entry.update(output)
                        else:
                            entry["items"] = output
                    results[site] = entry
                except (Error, AssertionError, QueryUnavailable, OSError, ValueError, KeyError, TypeError) as error:
                    if page.is_closed():
                        raise
                    results[site] = failure(error)
        finally:
            context.close()
    if interactive and any(entry["status"] == "authenticated" for entry in results.values()):
        check = subprocess.run(
            [sys.executable, "-m", "tongji_cli", "status", *(["--site", site_filter] if site_filter else []), "--json"],
            capture_output=True, text=True,
        )
        if check.stdout.strip():
            restarted = json.loads(check.stdout)
        else:
            restarted = {}
        for site, entry in results.items():
            entry["after_restart"] = restarted.get(site, {}).get("status", "unverified")
    return results
