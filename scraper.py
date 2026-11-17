#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://forum.naixi.net"
PROFILE_PATH = "/home.php?mod=space&uid=4328&do=thread&view=me&order=dateline&from=space"
LOGIN_URL = f"{BASE_URL}/member.php"
DATA_PATH = Path(__file__).resolve().parent / "data" / "posts.json"
MAX_FETCH_ATTEMPTS = 3
HONG_KONG_TZ = timezone(timedelta(hours=8))


def load_existing() -> dict[str, Any]:
    if not DATA_PATH.exists():
        return {"posts": []}
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"could not read existing archive at {DATA_PATH}") from error


def save_posts(posts: list[dict[str, Any]]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps({"posts": posts}, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_url(raw_url: str) -> str:
    return raw_url if raw_url.startswith("http") else urljoin(BASE_URL + "/", raw_url)


def parse_tid(raw_url: str) -> str | None:
    parsed = urlparse(raw_url)
    query = parse_qs(parsed.query)
    if "tid" in query:
        return query["tid"][0]
    match = re.search(r"(?:^|/)thread-(\d+)(?:-\d+-\d+)?\.html(?:$|[?#])", parsed.path)
    if match:
        return match.group(1)
    return None


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
    username = os.getenv("FORUM_USERNAME", "").strip()
    password = os.getenv("FORUM_PASSWORD", "")
    question_id = os.getenv("FORUM_QUESTION_ID", "")
    answer = os.getenv("FORUM_ANSWER", "")
    if username or password:
        if not username or not password:
            raise RuntimeError("set both FORUM_USERNAME and FORUM_PASSWORD GitHub secrets")
        login_forum(session, username, password, question_id, answer)
        return session

    cookie_value = os.getenv("FORUM_COOKIE", "").strip()
    if not cookie_value:
        raise RuntimeError(
            "forum credentials are missing; set FORUM_USERNAME and FORUM_PASSWORD GitHub secrets "
            "(or provide FORUM_COOKIE as a fallback)"
        )
    if cookie_value.lower().startswith("cookie:"):
        cookie_value = cookie_value.split(":", 1)[1].strip()
    session.headers["Cookie"] = cookie_value
    return session


def login_forum(
    session: requests.Session,
    username: str,
    password: str,
    question_id: str = "",
    answer: str = "",
) -> None:
    login_page = session.get(
        LOGIN_URL,
        params={
            "mod": "logging",
            "action": "login",
            "infloat": "yes",
            "handlekey": "login",
            "inajax": "1",
            "ajaxtarget": "fwin_content_login",
        },
        headers={
            "Referer": f"{BASE_URL}/",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
        allow_redirects=True,
    )
    login_page.raise_for_status()
    form_html_match = re.search(r"<!\[CDATA\[(.*?)\]\]>", login_page.text, re.DOTALL)
    form_html = form_html_match.group(1) if form_html_match else login_page.text
    soup = BeautifulSoup(form_html, "html.parser")
    form = soup.select_one("form[id^='loginform']")
    if form is None:
        raise RuntimeError("the forum AJAX login response did not contain a login form")

    action = form.get("action")
    if not action:
        raise RuntimeError("the forum login form has no action URL")
    post_url = urljoin(login_page.url, action)
    parsed_url = urlsplit(post_url)
    query = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    query.setdefault("loginsubmit", "yes")
    query.setdefault("handlekey", "login")
    query["inajax"] = "1"
    post_url = urlunsplit(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, urlencode(query), parsed_url.fragment)
    )

    form_data: dict[str, str] = {}
    for field in form.select("input[type='hidden'][name]"):
        form_data[field["name"]] = field.get("value", "")
    question_select = form.select_one("select[name='questionid']")
    if question_select is not None:
        selected_option = question_select.select_one("option[selected]") or question_select.select_one("option")
        form_data["questionid"] = question_id or (
            selected_option.get("value", "") if selected_option is not None else ""
        )
    elif question_id:
        form_data["questionid"] = question_id
    form_data["username"] = username
    form_data["password"] = password
    if form.select_one("input[name='answer']") is not None:
        form_data["answer"] = answer

    response = session.post(
        post_url,
        data=form_data,
        headers={
            "Referer": login_page.url,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=30,
        allow_redirects=True,
    )
    response.raise_for_status()
    if "登录失败" in response.text:
        raise RuntimeError("the forum rejected the login; check the GitHub username/password/security-answer secrets")
    if "欢迎您回来" not in response.text:
        raise RuntimeError(
            "the forum login response did not confirm success. Check the credentials and optional "
            "FORUM_QUESTION_ID/FORUM_ANSWER secrets against the login form"
        )


def fetch_page(session: requests.Session, url: str) -> str:
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=30, allow_redirects=True)
            break
        except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError):
            if attempt == MAX_FETCH_ATTEMPTS:
                raise
            delay = attempt
            print(
                f"warning: temporary connection error fetching {url}; "
                f"retrying in {delay}s ({attempt + 1}/{MAX_FETCH_ATTEMPTS})"
            )
            time.sleep(delay)
    if response.status_code in (403, 401):
        raise RuntimeError(f"forum access forbidden for {url}; set FORUM_COOKIE with a valid auth cookie")
    response.raise_for_status()
    return response.text


def is_login_required(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    visible_text = "".join(soup.stripped_strings)
    if "请先登录后才能继续浏览" in visible_text:
        return True
    for form in soup.find_all("form"):
        action = form.get("action", "").lower()
        has_password_field = form.select_one('input[type="password"]') is not None
        is_discuz_login = "member.php" in action and "mod=logging" in action
        is_login_form = form.get("id", "").lower() == "loginform"
        if has_password_field and (is_discuz_login or is_login_form):
            return True
    return False


def parse_thread_list(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    thread_table = soup.select_one("#threadlisttableid")
    if thread_table is None:
        return []

    items: list[dict[str, str]] = []
    thread_rows = [
        row
        for row in thread_table.find_all("li", class_="kmlist", recursive=False)
        if "common" in row.get("class", [])
    ]
    for row in thread_rows:
        topic_link = row.select_one("a.kmtit[href]")
        if topic_link is None:
            continue
        href = topic_link.get("href", "")
        tid = parse_tid(href)
        title = " ".join(topic_link.get_text(" ", strip=True).split())
        if not tid or not title:
            continue

        published_at = parse_post_date(str(row))
        item = {"tid": tid, "title": title, "href": normalize_url(href)}
        if published_at:
            item["published_at"] = published_at
        items.append(item)
    unique: dict[str, dict[str, str]] = {}
    for item in items:
        if item["tid"] not in unique:
            unique[item["tid"]] = item
    return list(unique.values())


def parse_post_date(html: str, now: datetime | None = None) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    postlist = soup.select_one("#postlist, .postlist")
    first_post = None
    if postlist is not None:
        first_post = postlist.select_one("div.comiis_vpost[id^='post_'], div[id^='post_']")

    date_scope = first_post or postlist or soup
    for date_node in date_scope.select("em[id^='authorposton'] span[title], time[datetime]"):
        value = date_node.get("title") or date_node.get("datetime")
        if value:
            parsed = parse_absolute_date(value)
            if parsed:
                return parsed
    for date_node in date_scope.select("em[id^='authorposton'] span, time"):
        parsed = parse_relative_date(date_node.get_text(" ", strip=True), now=now)
        if parsed:
            return parsed

    patterns = [
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?[ T]\d{1,2}:\d{2}:\d{2})",
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?[ T]\d{1,2}:\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            value = match.group(1).replace("T", " ")
            normalized = value.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", " ")
            normalized = re.sub(r"\s+", " ", normalized)
            parsed = parse_absolute_date(normalized)
            if parsed:
                return parsed
    return None


def parse_absolute_date(value: str) -> str | None:
    normalized = value.strip().replace("/", "-").replace("年", "-").replace("月", "-").replace("日", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            date_value = datetime.strptime(normalized, date_format)
            return date_value.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        except ValueError:
            continue
    return None


def parse_relative_date(value: str, now: datetime | None = None) -> str | None:
    value = " ".join(value.strip().split())
    current = now or datetime.now(HONG_KONG_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=HONG_KONG_TZ)
    else:
        current = current.astimezone(HONG_KONG_TZ)

    relative_match = re.fullmatch(r"(\d+)\s*(秒|分钟|分|小时|天)前", value)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        delta = {
            "秒": timedelta(seconds=amount),
            "分钟": timedelta(minutes=amount),
            "分": timedelta(minutes=amount),
            "小时": timedelta(hours=amount),
            "天": timedelta(days=amount),
        }[unit]
        return (current - delta).strftime("%Y-%m-%dT%H:%M:%S+08:00")
    if value == "刚刚":
        return current.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%S+08:00")

    day_match = re.fullmatch(r"(今天|昨天|前天)\s+(\d{1,2}):(\d{2})(?::(\d{2}))?", value)
    if day_match:
        days_ago = {"今天": 0, "昨天": 1, "前天": 2}[day_match.group(1)]
        date_value = (current - timedelta(days=days_ago)).date()
        try:
            parsed = datetime(
                date_value.year,
                date_value.month,
                date_value.day,
                int(day_match.group(2)),
                int(day_match.group(3)),
                int(day_match.group(4) or "0"),
                tzinfo=HONG_KONG_TZ,
            )
        except ValueError:
            return None
        return parsed.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    return None


def parse_post_content(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.select_one("#thread_subject")
    if title_node is None:
        title_node = soup.select_one("h1.ts, title")
    title = " ".join(title_node.get_text(" ", strip=True).split()) if title_node else ""

    postlist = soup.select_one("#postlist, .postlist")
    first_post = None
    if postlist is not None:
        first_post = postlist.select_one("div.comiis_vpost[id^='post_'], div[id^='post_']")

    if first_post is None:
        raise RuntimeError("could not find the original post container in #postlist")
    scope = first_post
    content = scope.select_one(".t_f, .t_fsz, .postcontent, .t_msgfont")
    if content is None:
        content = scope.select_one(".pcb")
    if content is None:
        raise RuntimeError("could not find the original post body in #postlist")

    body = BeautifulSoup(str(content), "html.parser")
    for unwanted in body.select(
        ".attach_tips, .pstatus, .kmbtn, .pob, .po, .fastre, .replysubmit, "
        "button, input, textarea, select, script, style"
    ):
        unwanted.decompose()
    body_node = body.find()
    if body_node is None:
        raise RuntimeError("could not parse the original post body")
    for line_break in body_node.select("br"):
        line_break.replace_with("\n")
    for block in body_node.select("p, div, li, blockquote, pre"):
        block.insert_before("\n")
        block.insert_after("\n")
    text = body_node.get_text(" ", strip=True)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^\s*本主题由.*?移动\s*$", "", text).strip()
    if not text:
        raise RuntimeError("the original post body is empty after removing forum controls")
    return title, text


def fetch_posts_for_page(session: requests.Session, page_num: int) -> list[dict[str, str]]:
    target_url = f"{BASE_URL}{PROFILE_PATH}&page={page_num}"
    page_html = fetch_page(session, target_url)
    if is_login_required(page_html):
        raise RuntimeError(
            "the forum returned a login-required page after authentication. Check FORUM_USERNAME and "
            "FORUM_PASSWORD, and set FORUM_ANSWER if the account requires a security-question answer. "
            "If using FORUM_COOKIE instead, refresh it from a currently logged-in forum request."
        )
    items = parse_thread_list(page_html)
    if not items and page_num == 1:
        soup = BeautifulSoup(page_html, "html.parser")
        page_title = soup.title.get_text(" ", strip=True) if soup.title else "(no page title)"
        has_thread_table = soup.select_one("#threadlisttableid") is not None
        thread_link_count = (
            len(soup.select("#threadlisttableid a[href]")) if has_thread_table else 0
        )
        raise RuntimeError(
            "could not extract topic links from the first profile page "
            f"(response title: {page_title!r}, #threadlisttableid present: {has_thread_table}, "
            f"links inside it: {thread_link_count}); the table markup may differ from the expected format"
        )
    return items


def crawl_forum(limit_pages: int = 10, existing_ids: set[str] | None = None) -> list[dict[str, Any]]:
    session = build_session()
    existing_ids = existing_ids or set()
    posts_by_tid: dict[str, dict[str, Any]] = {}
    skipped_not_found = 0
    for page in range(1, limit_pages + 1):
        items = fetch_posts_for_page(session, page)
        if not items:
            break
        for item in items:
            tid = item["tid"]
            if tid in posts_by_tid or tid in existing_ids:
                continue
            thread_url = item["href"]
            try:
                thread_html = fetch_page(session, thread_url)
            except requests.HTTPError as error:
                if error.response is None or error.response.status_code != 404:
                    raise
                skipped_not_found += 1
                print(f"warning: skipping unavailable forum thread {tid} (HTTP 404): {thread_url}")
                continue
            if is_login_required(thread_html):
                raise RuntimeError(
                    f"forum thread {tid} returned a login-required/permission page; "
                    "the logged-in account cannot access its original post"
                )
            thread_title, text = parse_post_content(thread_html)
            title = item["title"] or thread_title
            if not title:
                title = thread_title
            date_value = parse_post_date(thread_html) or item.get("published_at")
            if not date_value:
                page_title = BeautifulSoup(thread_html, "html.parser").title
                title_text = page_title.get_text(" ", strip=True) if page_title else "(no page title)"
                raise RuntimeError(
                    f"could not find the original forum post time for thread {tid} "
                    f"(response title: {title_text!r}); neither the thread nor its list entry included "
                    "a recognized timestamp"
                )
            source_url = thread_url
            posts_by_tid[tid] = {
                "id": tid,
                "source_url": source_url,
                "title": title,
                "published_at": date_value,
                "excerpt": text[:240],
                "content": text,
                "content_html": BeautifulSoup(thread_html, "html.parser").get_text("\n", strip=True),
            }
    if skipped_not_found:
        print(f"skipped {skipped_not_found} unavailable thread(s) that returned HTTP 404")
    return list(posts_by_tid.values())


def merge_posts(existing: list[dict[str, Any]], new_posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {str(post["id"]): post for post in existing}
    for post in new_posts:
        merged.setdefault(str(post["id"]), post)
    return sorted(merged.values(), key=lambda x: x.get("published_at", "1970-01-01T00:00:00+00:00"), reverse=True)


def page_limit_for_archive(existing_posts: list[dict[str, Any]]) -> int:
    return 1 if existing_posts else 10


def main() -> None:
    current = load_existing()
    existing_posts = current.get("posts", [])
    existing_ids = {str(post["id"]) for post in existing_posts}
    page_limit = page_limit_for_archive(existing_posts)
    new_posts = crawl_forum(limit_pages=page_limit, existing_ids=existing_ids)
    posts = merge_posts(existing_posts, new_posts)
    save_posts(posts)
    print(f"saved {len(posts)} posts (scanned {page_limit} page(s))")


if __name__ == "__main__":
    main()
