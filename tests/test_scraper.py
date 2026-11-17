import contextlib
import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from bs4 import BeautifulSoup
import scraper


class LoginDetectionTests(unittest.TestCase):
    def test_fetch_page_retries_chunked_response_then_succeeds(self):
        session = Mock()
        response = Mock(status_code=200, text="<html>ok</html>")
        session.get.side_effect = [
            requests.exceptions.ChunkedEncodingError("Response ended prematurely"),
            response,
        ]
        with patch.object(scraper.time, "sleep"):
            result = scraper.fetch_page(session, "https://forum.naixi.net/thread-16529-1-1.html")

        self.assertEqual(result, "<html>ok</html>")
        self.assertEqual(session.get.call_count, 2)

    def test_fetch_page_raises_after_chunked_response_retries_are_exhausted(self):
        session = Mock()
        error = requests.exceptions.ChunkedEncodingError("Response ended prematurely")
        session.get.side_effect = error
        with patch.object(scraper.time, "sleep") as sleep, self.assertRaises(
            requests.exceptions.ChunkedEncodingError
        ):
            scraper.fetch_page(session, "https://forum.naixi.net/thread-16529-1-1.html")

        self.assertEqual(session.get.call_count, scraper.MAX_FETCH_ATTEMPTS)
        self.assertEqual(sleep.call_count, scraper.MAX_FETCH_ATTEMPTS - 1)

    def test_navigation_login_link_does_not_mean_session_is_logged_out(self):
        html = """
        <html>
          <body>
            <a href="member.php?mod=logging&action=login">登录</a>
            <a href="/forum.php?mod=viewthread&tid=123">日记标题</a>
          </body>
        </html>
        """
        self.assertFalse(scraper.is_login_required(html))

    def test_rewritten_thread_urls_are_parsed(self):
        self.assertEqual(scraper.parse_tid("https://forum.naixi.net/thread-12345-1-1.html"), "12345")
        items = scraper.parse_thread_list(
            """
            <ul id="threadlisttableid">
              <li class="kmlist common">
                <a class="kmtit" href="thread-12345-1-1.html">测试帖子</a>
              </li>
            </ul>
            """
        )
        self.assertEqual(items[0]["tid"], "12345")

    def test_profile_listing_uses_dateline_order_and_page_number(self):
        self.assertIn("order=dateline", scraper.PROFILE_PATH)
        self.assertTrue(scraper.PROFILE_PATH.endswith("&from=space"))

    def test_initial_sync_scans_ten_pages(self):
        self.assertEqual(scraper.page_limit_for_archive([]), 10)

    def test_incremental_sync_scans_one_page(self):
        self.assertEqual(
            scraper.page_limit_for_archive([{"id": "16529"}]),
            1,
        )

    def test_thread_list_entry_date_is_extracted(self):
        html = """
          <ul id="threadlisttableid">
            <li class="kmlist common">
              <a class="kmtit" href="thread-12345-1-1.html">测试帖子</a>
              <span title="2026-11-17 22:30:45">发表于 2026-11-17 22:30:45</span>
            </li>
          </ul>
        """
        item = scraper.parse_thread_list(html)[0]
        self.assertEqual(item["published_at"], "2026-11-17T22:30:45+08:00")

    def test_thread_list_keeps_pretty_thread_url(self):
        items = scraper.parse_thread_list(
            """
            <ul id="threadlisttableid">
              <li class="kmlist common">
                <a class="kmtit" href="https://forum.naixi.net/thread-16529-1-1.html">测试帖子</a>
              </li>
            </ul>
            """
        )
        self.assertEqual(
            items[0]["href"],
            "https://forum.naixi.net/thread-16529-1-1.html",
        )

    def test_only_topics_inside_threadlisttableid_are_returned(self):
        html = """
          <a href="thread-7706-1-1.html">侧栏旧帖，不是列表文章</a>
          <ul id="threadlisttableid">
            <li class="kmlist common">
              <a href="thread-7706-1-1.html" class="showcontent">更多操作</a>
              <a href="thread-16530-1-1.html" class="kmtit">列表里的帖子</a>
              <a href="space-uid-4328.html">作者</a>
              <a href="forum-84-1.html">版块</a>
            </li>
          </ul>
        """
        items = scraper.parse_thread_list(html)
        self.assertEqual([item["tid"] for item in items], ["16530"])
        self.assertEqual(items[0]["title"], "列表里的帖子")
        self.assertEqual(items[0]["href"], "https://forum.naixi.net/thread-16530-1-1.html")

    def test_missing_threadlisttableid_returns_no_items(self):
        self.assertEqual(
            scraper.parse_thread_list('<a href="thread-7706-1-1.html">其他链接</a>'),
            [],
        )

    def test_thread_links_are_extracted_from_table_without_tr_rows(self):
        html = """
          <div id="threadlisttableid">
            <li class="kmlist common">
              <a class="kmtit" href="thread-16530-1-1.html">列表里的帖子</a>
              <span title="2026-11-17 22:30:45">刚刚</span>
            </li>
          </div>
        """
        items = scraper.parse_thread_list(html)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["tid"], "16530")
        self.assertEqual(items[0]["title"], "列表里的帖子")
        self.assertEqual(items[0]["published_at"], "2026-11-17T22:30:45+08:00")

    def test_postlist_extracts_original_post_content_and_exact_time(self):
        html = """
          <h1 id="thread_subject">示例标题</h1>
          <div class="notice">本主题由 管理团队 于 2026-5-13 20:34 移动</div>
          <div id="postlist" class="pl comiis_postlist">
            <div id="post_100" class="comiis_vpost comiis_vone">
              <div class="authi">
                <em id="authorposton100">发表于
                  <span title="2026-11-17 16:00:41">7 小时前</span>
                </em>
              </div>
              <td class="t_f">
                <div class="attach_tips">登录后下载</div>
                <i class="pstatus">最后编辑 2026-11-17 16:03</i>
                原帖正文
              </td>
              <button class="kmbtn">快速回复</button>
            </div>
            <div id="post_101" class="comiis_vpost">
              <em id="authorposton101"><span title="2026-11-17 16:06:00">稍后</span></em>
              <td class="t_f">回复内容</td>
            </div>
          </div>
        """
        title, content = scraper.parse_post_content(html)
        self.assertEqual(title, "示例标题")
        self.assertIn("原帖正文", content)
        self.assertNotIn("登录后下载", content)
        self.assertNotIn("快速回复", content)
        self.assertNotIn("本主题由", content)
        self.assertNotIn("回复内容", content)
        self.assertEqual(scraper.parse_post_date(html), "2026-11-17T16:00:41+08:00")

    def test_post_html_preserves_formatting_and_removes_unsafe_markup(self):
        html = """
          <h1 id="thread_subject">格式测试</h1>
          <div id="postlist">
            <div class="comiis_vpost" id="post_1">
              <em id="authorposton1"><span title="2026-11-17 16:00:41"></span></em>
              <div class="t_f">
                第一行<br><br><strong style="color: red; background-image: url(javascript:bad)">加粗</strong>
                <a href="javascript:alert(1)" onclick="alert(1)">危险链接</a>
                <img src="https://forum.naixi.net/image.jpg" onerror="alert(1)" alt="图片">
              </div>
            </div>
          </div>
        """
        title, text, body_html = scraper.parse_post_html(html)

        self.assertEqual(title, "格式测试")
        self.assertIn("第一行<br/><br/>", body_html)
        self.assertIn("<strong style=\"color: red\">加粗</strong>", body_html)
        self.assertNotIn("javascript:", body_html)
        self.assertNotIn("onclick", body_html)
        self.assertNotIn("onerror", body_html)
        self.assertIn("危险链接", text)

    def test_post_images_are_saved_locally_and_rewritten(self):
        response = Mock(
            status_code=200,
            headers={"Content-Type": "image/jpeg"},
            content=b"fake-image",
        )
        session = Mock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(scraper, "IMAGE_DIR", Path(temp_dir)):
                html = scraper.download_post_images(
                    '<p>图 <img src="/attachments/photo.jpg" alt="照片"></p>',
                    "16530",
                    session,
                    "https://forum.naixi.net/thread-16530-1-1.html",
                )
                image_url = BeautifulSoup(html, "html.parser").img["src"]
                saved_image = Path(temp_dir) / "16530" / Path(image_url).name

            self.assertTrue(image_url.startswith("images/16530/"))
            self.assertEqual(saved_image.read_bytes(), b"fake-image")
        session.get.assert_called_once_with(
            "https://forum.naixi.net/attachments/photo.jpg",
            timeout=30,
            allow_redirects=True,
        )

    def test_crawl_refreshes_legacy_post_html_without_changing_archive_metadata(self):
        session = Mock()
        thread_html = """
          <h1 id="thread_subject">论坛新标题</h1>
          <div id="postlist">
            <div class="comiis_vpost" id="post_1">
              <em id="authorposton1"><span title="2026-11-17 16:00:41"></span></em>
              <div class="t_f">修复后的正文<br>第二行</div>
            </div>
          </div>
        """
        legacy = {
            "id": "16529",
            "source_url": "https://forum.naixi.net/thread-16529-1-1.html",
            "title": "归档原始标题",
            "published_at": "2026-11-17T16:00:41+08:00",
            "content": "旧的纯文本",
            "content_html": "旧的整页文本",
        }
        with (
            patch.object(scraper, "build_session", return_value=session),
            patch.object(scraper, "load_existing", return_value={"posts": [legacy]}),
            patch.object(scraper, "fetch_posts_for_page", return_value=[]),
            patch.object(scraper, "fetch_page", return_value=thread_html),
        ):
            updates = scraper.crawl_forum(limit_pages=1, existing_ids={"16529"})

        merged = scraper.merge_posts([legacy], updates)[0]
        self.assertIn("修复后的正文<br/>第二行", merged["content_html"])
        self.assertEqual(merged["title"], "归档原始标题")
        self.assertEqual(merged["published_at"], legacy["published_at"])
        self.assertEqual(merged["content"], "旧的纯文本")

    def test_post_content_requires_a_real_body_instead_of_scraping_controls(self):
        html = """
          <div id="postlist">
            <div id="post_1" class="comiis_vpost">
              <button class="kmbtn">快速回复</button>
            </div>
          </div>
        """
        with self.assertRaisesRegex(RuntimeError, "original post body"):
            scraper.parse_post_content(html)

    def test_slash_and_chinese_date_formats_are_parsed(self):
        self.assertEqual(
            scraper.parse_post_date("2026/11/17 22:30"),
            "2026-11-17T22:30:00+08:00",
        )
        self.assertEqual(
            scraper.parse_post_date("2026年11月17日 22:30"),
            "2026-11-17T22:30:00+08:00",
        )

    def test_relative_post_dates_use_hong_kong_time(self):
        fixed_now = datetime(2026, 11, 18, 0, 20, tzinfo=timezone.utc)
        yesterday = """
          <div id="postlist">
            <div class="comiis_vpost" id="post_1">
              <em id="authorposton1"><span>昨天 17:48</span></em>
              <div class="t_f">正文</div>
            </div>
          </div>
        """
        minutes_ago = """
          <div id="postlist">
            <div class="comiis_vpost" id="post_1">
              <em id="authorposton1"><span>13 分钟前</span></em>
              <div class="t_f">正文</div>
            </div>
          </div>
        """

        self.assertEqual(
            scraper.parse_post_date(yesterday, now=fixed_now),
            "2026-11-17T17:48:00+08:00",
        )
        self.assertEqual(
            scraper.parse_post_date(minutes_ago, now=fixed_now),
            "2026-11-18T08:07:00+08:00",
        )

    def test_discuz_login_form_is_detected(self):
        html = """
        <form id="loginform" action="member.php?mod=logging&action=login">
          <input name="username">
          <input type="password" name="password">
        </form>
        """
        self.assertTrue(scraper.is_login_required(html))

    def test_discuz_login_required_notice_is_detected(self):
        html = """
        <html>
          <head><title>提示信息 奶昔论坛</title></head>
          <body><div>请先登录后才能继续浏览</div></body>
        </html>
        """
        self.assertTrue(scraper.is_login_required(html))

    def test_cookie_header_prefix_is_accepted(self):
        with patch.dict(os.environ, {"FORUM_COOKIE": "Cookie: auth=secret; saltkey=token"}):
            session = scraper.build_session()
        self.assertEqual(session.headers["Cookie"], "auth=secret; saltkey=token")

    def test_missing_auth_secrets_has_specific_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "FORUM_USERNAME and FORUM_PASSWORD"):
                scraper.build_session()

    def test_login_posts_credentials_with_dynamic_form_tokens(self):
        session = Mock()
        session.headers = {}
        session.get.return_value = Mock(
            url=scraper.LOGIN_URL,
            text="""
              <?xml version="1.0" encoding="utf-8"?>
              <root><![CDATA[
                <form id="loginform_ab12" action="member.php?mod=logging&amp;action=login&amp;loginsubmit=yes&amp;loginhash=ab12">
                  <input type="hidden" name="formhash" value="xyz789">
                  <input type="hidden" name="referer" value="https://forum.naixi.net/">
                  <input type="text" name="username">
                  <input type="password" name="password">
                  <select name="questionid"><option value="0">无</option></select>
                  <input type="text" name="answer">
                </form>
              ]]></root>
            """,
        )
        session.post.return_value = Mock(text="<root><![CDATA[欢迎您回来]]></root>")

        scraper.login_forum(session, "test-user", "test-password", "", "test-answer")

        args, kwargs = session.post.call_args
        self.assertIn("loginhash=ab12", args[0])
        self.assertIn("inajax=1", args[0])
        self.assertEqual(kwargs["data"]["formhash"], "xyz789")
        self.assertEqual(kwargs["data"]["questionid"], "0")
        self.assertEqual(kwargs["data"]["username"], "test-user")
        self.assertEqual(kwargs["data"]["password"], "test-password")
        self.assertEqual(kwargs["data"]["answer"], "test-answer")
        get_kwargs = session.get.call_args.kwargs
        self.assertEqual(get_kwargs["params"]["handlekey"], "login")
        self.assertEqual(get_kwargs["params"]["ajaxtarget"], "fwin_content_login")
        self.assertEqual(kwargs["headers"]["X-Requested-With"], "XMLHttpRequest")

    def test_login_uses_configured_security_question_id(self):
        session = Mock()
        session.headers = {}
        session.get.return_value = Mock(
            url=scraper.LOGIN_URL,
            text="""
              <?xml version="1.0" encoding="utf-8"?>
              <root><![CDATA[
                <form id="loginform_ab12" action="member.php?mod=logging&amp;action=login&amp;loginsubmit=yes">
                  <input type="hidden" name="formhash" value="xyz789">
                  <select name="questionid">
                    <option value="0">无</option>
                    <option value="3">安全问题</option>
                  </select>
                  <input type="text" name="answer">
                </form>
              ]]></root>
            """,
        )
        session.post.return_value = Mock(text="<root><![CDATA[欢迎您回来]]></root>")

        scraper.login_forum(session, "test-user", "test-password", "3", "answer")

        self.assertEqual(session.post.call_args.kwargs["data"]["questionid"], "3")

    def test_login_requires_forum_success_message(self):
        session = Mock()
        session.headers = {}
        session.get.return_value = Mock(
            url=scraper.LOGIN_URL,
            text="""
              <root><![CDATA[
                <form id="loginform_ab12" action="member.php?mod=logging&amp;action=login&amp;loginsubmit=yes">
                  <input type="hidden" name="formhash" value="xyz789">
                  <select name="questionid"><option value="0">无</option></select>
                </form>
              ]]></root>
            """,
        )
        session.post.return_value = Mock(text="<root><![CDATA[登录失败]]></root>")

        with self.assertRaisesRegex(RuntimeError, "rejected the login"):
            scraper.login_forum(session, "test-user", "test-password")

    def test_login_uses_cookie_fallback_when_credentials_are_absent(self):
        with patch.dict(
            os.environ,
            {"FORUM_COOKIE": "sid=sample"},
            clear=True,
        ):
            session = scraper.build_session()
        self.assertEqual(session.headers["Cookie"], "sid=sample")

    def test_crawl_skips_deleted_thread_404_and_continues(self):
        session = Mock()
        missing_response = Mock(status_code=404)
        not_found = requests.HTTPError("404 not found", response=missing_response)
        working_thread_html = """
          <h1 id="thread_subject">可访问帖子</h1>
          <div id="postlist">
            <div id="post_1" class="comiis_vpost">
              <em id="authorposton1"><span title="2026-11-17 16:00:41"></span></em>
              <td class="t_f">正文</td>
            </div>
          </div>
        """
        with (
            patch.object(scraper, "build_session", return_value=session),
            patch.object(
                scraper,
                "fetch_posts_for_page",
                return_value=[
                    {"tid": "7706", "title": "已失效帖子", "href": "https://forum.naixi.net/thread-7706-1-1.html"},
                    {"tid": "16529", "title": "可访问帖子", "href": "https://forum.naixi.net/thread-16529-1-1.html"},
                ],
            ),
            patch.object(scraper, "fetch_page", side_effect=[not_found, working_thread_html]),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            posts = scraper.crawl_forum(limit_pages=1)

        self.assertEqual([post["id"] for post in posts], ["16529"])
        self.assertIn("skipping unavailable forum thread 7706", output.getvalue())

    def test_crawl_propagates_non_404_http_errors(self):
        session = Mock()
        server_error = requests.HTTPError("500 server error", response=Mock(status_code=500))
        with (
            patch.object(scraper, "build_session", return_value=session),
            patch.object(
                scraper,
                "fetch_posts_for_page",
                return_value=[
                    {"tid": "16529", "title": "测试", "href": "https://forum.naixi.net/thread-16529-1-1.html"},
                ],
            ),
            patch.object(scraper, "fetch_page", side_effect=server_error),
            self.assertRaises(requests.HTTPError),
        ):
            scraper.crawl_forum(limit_pages=1)


if __name__ == "__main__":
    unittest.main()
