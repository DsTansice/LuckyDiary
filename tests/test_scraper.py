import os
import unittest
from unittest.mock import Mock, patch

import scraper


class LoginDetectionTests(unittest.TestCase):
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
            '<a href="thread-12345-1-1.html">测试帖子</a>'
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
          <div class="thread">
            <a href="forum.php?mod=viewthread&tid=12345">测试帖子</a>
            <span>发表于 2026-11-17 22:30:45</span>
          </div>
        """
        item = scraper.parse_thread_list(html)[0]
        self.assertEqual(item["published_at"], "2026-11-17T22:30:45+08:00")

    def test_thread_list_keeps_pretty_thread_url(self):
        items = scraper.parse_thread_list(
            '<a href="https://forum.naixi.net/thread-16529-1-1.html">测试帖子</a>'
        )
        self.assertEqual(
            items[0]["href"],
            "https://forum.naixi.net/thread-16529-1-1.html",
        )

    def test_postlist_extracts_original_post_content_and_exact_time(self):
        html = """
          <h1 id="thread_subject">示例标题</h1>
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
        self.assertNotIn("回复内容", content)
        self.assertEqual(scraper.parse_post_date(html), "2026-11-17T16:00:41+08:00")

    def test_slash_and_chinese_date_formats_are_parsed(self):
        self.assertEqual(
            scraper.parse_post_date("2026/11/17 22:30"),
            "2026-11-17T22:30:00+08:00",
        )
        self.assertEqual(
            scraper.parse_post_date("2026年11月17日 22:30"),
            "2026-11-17T22:30:00+08:00",
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


if __name__ == "__main__":
    unittest.main()
