#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://forum.naixi.net"
PROFILE_PATH = "/home.php?mod=space&uid=4328&do=thread&view=me&from=space"
LOGIN_URL = f"{BASE_URL}/member.php"
DATA_PATH = Path(__file__).resolve().parent / "data" / "posts.json"


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
    response = session.get(url, timeout=30, allow_redirects=True)
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
    items: list[dict[str, str]] = []
    for a in soup.select("a[href*='tid='], a[href*='mod=viewthread'], a[href*='thread-']"):
        href = a.get("href", "")
        if not href:
            continue
        text = " ".join(a.get_text(" ", strip=True).split())
        if not text:
            continue
        tid = parse_tid(href)
        if not tid:
            continue
        items.append({"tid": tid, "title": text, "href": normalize_url(href)})
    unique: dict[str, dict[str, str]] = {}
    for item in items:
        if item["tid"] not in unique:
            unique[item["tid"]] = item
    return list(unique.values())


def parse_post_date(html: str) -> str | None:
    patterns = [
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
        r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})",
        r"(\d{4}年\d{1,2}月\d{1,2}日\s*\d{1,2}:\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            value = match.group(1)
            normalized = value.replace("年", "-").replace("月", "-").replace("日", " ")
            normalized = re.sub(r"\s+", " ", normalized)
            try:
                return datetime.strptime(normalized, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%S+08:00")
            except ValueError:
                try:
                    return datetime.strptime(normalized, "%Y-%m-%d %H:%M").strftime("%Y-%m-%dT%H:%M:00+08:00")
                except ValueError:
                    continue
    return None


def parse_post_content(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one("title")
    if title_tag:
        title = " ".join(title_tag.get_text(" ", strip=True).split())
    else:
        title = ""

    containers = soup.select("div.t_fsz, div.t_f, div.postcontent, div.pcb, div.t_msgfont")
    if not containers:
        containers = soup.select("td.t_f, div#postlist div")
    content_html = ""
    for container in containers:
        cleaned = container.decode_contents() if hasattr(container, "decode_contents") else str(container)
        if cleaned.strip():
            content_html = cleaned
            break

    text = BeautifulSoup(content_html or html, "html.parser").get_text("\n", strip=True)
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
        raise RuntimeError(
            "no thread links were found on the first profile page "
            f"(response title: {page_title!r}); authentication may have failed or the forum's thread-link "
            "format may have changed"
        )
    return items


def crawl_forum(limit_pages: int = 10, existing_ids: set[str] | None = None) -> list[dict[str, Any]]:
    session = build_session()
    existing_ids = existing_ids or set()
    posts_by_tid: dict[str, dict[str, Any]] = {}
    for page in range(1, limit_pages + 1):
        items = fetch_posts_for_page(session, page)
        if not items:
            break
        for item in items:
            tid = item["tid"]
            if tid in posts_by_tid or tid in existing_ids:
                continue
            thread_url = f"{BASE_URL}/forum.php?mod=viewthread&tid={tid}&extra=page%3D1"
            thread_html = fetch_page(session, thread_url)
            title, text = parse_post_content(thread_html)
            if not title:
                title = item["title"]
            date_value = parse_post_date(thread_html)
            if not date_value:
                raise RuntimeError(f"could not find the original forum post time for thread {tid}")
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
    return list(posts_by_tid.values())


def merge_posts(existing: list[dict[str, Any]], new_posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {str(post["id"]): post for post in existing}
    for post in new_posts:
        merged.setdefault(str(post["id"]), post)
    return sorted(merged.values(), key=lambda x: x.get("published_at", "1970-01-01T00:00:00+00:00"), reverse=True)


def main() -> None:
    current = load_existing()
    existing_posts = current.get("posts", [])
    existing_ids = {str(post["id"]) for post in existing_posts}
    new_posts = crawl_forum(limit_pages=10, existing_ids=existing_ids)
    posts = merge_posts(existing_posts, new_posts)
    save_posts(posts)
    print(f"saved {len(posts)} posts")


if __name__ == "__main__":
    main()
