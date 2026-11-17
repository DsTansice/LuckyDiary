import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import site_generator


class SiteGeneratorTests(unittest.TestCase):
    def test_renders_rich_post_and_separate_guestbook_with_local_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data" / "images" / "16530").mkdir(parents=True)
            (root / "data" / "images" / "16530" / "photo.jpg").write_bytes(b"image")
            (root / "data" / "posts.json").write_text(
                json.dumps(
                    {
                        "posts": [
                            {
                                "id": "16530",
                                "source_url": "https://forum.naixi.net/thread-16530-1-1.html",
                                "title": "图文帖子",
                                "published_at": "2026-11-17T17:48:07+08:00",
                                "content": "图文帖子",
                                "content_html": '<p>保留格式<br><img src="images/16530/photo.jpg"></p>',
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                patch.object(site_generator, "ROOT", root),
                patch.object(site_generator, "DATA_PATH", root / "data" / "posts.json"),
                patch.object(site_generator, "OUT_DIR", root / "dist"),
            ):
                site_generator.render()

            index = (root / "dist" / "index.html").read_text(encoding="utf-8")
            guestbook = (root / "dist" / "guestbook.html").read_text(encoding="utf-8")
            self.assertIn("<p>保留格式<br><img src=\"images/16530/photo.jpg\"></p>", index)
            self.assertIn('href="./guestbook.html">留言</a>', index)
            self.assertNotIn("giscus.app/client.js", index)
            self.assertIn("giscus.app/client.js", guestbook)
            self.assertTrue((root / "dist" / "images" / "16530" / "photo.jpg").exists())


if __name__ == "__main__":
    unittest.main()
