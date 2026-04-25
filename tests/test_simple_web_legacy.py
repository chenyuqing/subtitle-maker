from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from subtitle_maker import simple_web
from subtitle_maker.app import legacy_simple_app


class SimpleWebLegacyTests(unittest.TestCase):
    """冻结 legacy simple web wrapper 的最小兼容行为。"""

    def setUp(self):
        self.client = TestClient(simple_web.app)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="simple_web_legacy_"))
        self.tmpdir.mkdir(parents=True, exist_ok=True)

        self.patchers = [
            patch.object(legacy_simple_app, "OUTPUT_DIR", str(self.tmpdir)),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def test_index_keeps_legacy_upload_page(self):
        """旧 simple app 入口应继续返回上传页。"""

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))
        self.assertIn("本地 SRT 字幕翻译", response.text)

    def test_translate_generates_downloadable_srt(self):
        """上传 SRT 后应继续生成可下载的 legacy 结果。"""

        with patch(
            "subtitle_maker.app.legacy_simple_app.Translator.translate_batch",
            return_value=["你好"],
        ):
            response = self.client.post(
                "/translate",
                files={
                    "file": (
                        "demo.srt",
                        b"1\n00:00:00,000 --> 00:00:01,000\nhello\n",
                        "application/x-subrip",
                    )
                },
                data={"target_lang": "Chinese", "system_prompt": "保持原意"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("/download/simple_", response.text)

        generated_files = sorted(self.tmpdir.glob("simple_*_Chinese.srt"))
        self.assertEqual(len(generated_files), 1)

        downloaded = self.client.get(f"/download/{generated_files[0].name}")
        self.assertEqual(downloaded.status_code, 200)
        self.assertIn("你好", downloaded.text)

    def test_download_missing_file_redirects_home(self):
        """缺失文件时仍应回到 legacy simple 首页。"""

        response = self.client.get("/download/missing.srt", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/")


if __name__ == "__main__":
    unittest.main()
