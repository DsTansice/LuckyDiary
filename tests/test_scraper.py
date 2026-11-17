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
                <form id="loginform_ab12" action="member.php?mod=logging&amp;action=login&amp;loginsubmit=yes&amp;loginhash=ab12">
                  <input type="hidden" name="formhash" value="xyz789">
                  <input type="hidden" name="referer" value="https://forum.naixi.net/">
                  <input type="text" name="username">
                  <input type="password" name="password">
                  <select name="questionid"><option value="0">无</option></select>
                  <input type="text" name="answer">
                </form>
            """,
        )
        session.post.return_value = Mock()

        scraper.login_forum(session, "test-user", "test-password", "", "test-answer")

        args, kwargs = session.post.call_args
        self.assertIn("loginhash=ab12", args[0])
        self.assertEqual(kwargs["data"]["formhash"], "xyz789")
        self.assertEqual(kwargs["data"]["questionid"], "0")
        self.assertEqual(kwargs["data"]["username"], "test-user")
        self.assertEqual(kwargs["data"]["password"], "test-password")
        self.assertEqual(kwargs["data"]["answer"], "test-answer")

    def test_login_uses_configured_security_question_id(self):
        session = Mock()
        session.headers = {}
        session.get.return_value = Mock(
            url=scraper.LOGIN_URL,
            text="""
                <form id="loginform_ab12" action="member.php?mod=logging&amp;action=login&amp;loginsubmit=yes">
                  <input type="hidden" name="formhash" value="xyz789">
                  <select name="questionid">
                    <option value="0">无</option>
                    <option value="3">安全问题</option>
                  </select>
                  <input type="text" name="answer">
                </form>
            """,
        )
        session.post.return_value = Mock()

        scraper.login_forum(session, "test-user", "test-password", "3", "answer")

        self.assertEqual(session.post.call_args.kwargs["data"]["questionid"], "3")

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
