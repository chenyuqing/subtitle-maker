from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf
from fastapi import HTTPException
from fastapi.testclient import TestClient

API_TEST_SKIP_REASON = ""
try:
    from subtitle_maker import dubbing_cli_api
    from subtitle_maker import omnivoice_dub_api
    from subtitle_maker import voxcpm_dub_api
    from subtitle_maker import translator as translator_module
    from subtitle_maker import web
    from subtitle_maker.domains.dubbing import pipeline as dubbing_pipeline
    from subtitle_maker.domains.media import compose as media_compose
except ModuleNotFoundError as exc:  # pragma: no cover - 仅在缺三方依赖的本地环境触发
    dubbing_cli_api = None
    omnivoice_dub_api = None
    voxcpm_dub_api = None
    translator_module = None
    dubbing_pipeline = None
    web = None
    media_compose = None
    API_TEST_SKIP_REASON = f"missing dependency {exc.name}"


class FakeThread:
    """替代后台线程，避免测试中真正启动 CLI。"""

    instances = []

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        self.started = False
        FakeThread.instances.append(self)

    def start(self):
        self.started = True

@unittest.skipIf(bool(API_TEST_SKIP_REASON), API_TEST_SKIP_REASON or "")
class DubbingCliApiTests(unittest.TestCase):
    """覆盖当前 auto dubbing API 主合同。"""

    def setUp(self):
        self.client = TestClient(web.app)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="dub_api_test_"))
        self.upload_root = self.tmpdir / "uploads"
        self.output_root = self.tmpdir / "outputs"
        self.tool_path = self.tmpdir / "dub_long_video.py"
        self.tool_path.write_text("# fake tool\n", encoding="utf-8")
        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.omnivoice_output_root = self.output_root / "omnivoice"
        self.omnivoice_output_root.mkdir(parents=True, exist_ok=True)
        self.voxcpm_output_root = self.output_root / "voxcpm"
        self.voxcpm_output_root.mkdir(parents=True, exist_ok=True)

        dubbing_cli_api._tasks.clear()
        dubbing_cli_api.legacy_runtime.tasks.clear()
        omnivoice_dub_api._task_store.clear()
        voxcpm_dub_api._task_store.clear()
        FakeThread.instances = []

        self.patchers = [
            patch.object(dubbing_cli_api, "UPLOAD_ROOT", self.upload_root),
            patch.object(dubbing_cli_api, "OUTPUT_ROOT", self.output_root),
            patch.object(dubbing_cli_api, "TOOL_PATH", self.tool_path),
            patch.object(dubbing_cli_api.legacy_runtime, "UPLOAD_DIR", str(self.upload_root)),
            patch.object(omnivoice_dub_api, "OUTPUT_ROOT", self.omnivoice_output_root),
            patch.object(voxcpm_dub_api, "OUTPUT_ROOT", self.voxcpm_output_root),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(dubbing_cli_api._tasks.clear)
        self.addCleanup(dubbing_cli_api.legacy_runtime.tasks.clear)
        self.addCleanup(omnivoice_dub_api._task_store.clear)
        self.addCleanup(voxcpm_dub_api._task_store.clear)
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _patch_start_runtime(self):
        """统一屏蔽启动阶段的外部服务检查。"""

        return patch.object(dubbing_cli_api, "_switch_tts_runtime_on_demand", return_value=None)

    def test_start_auto_dubbing_creates_single_mode_task(self):
        """默认启动应走 single 模式，并生成当前主命令。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task_id = payload["task_id"]
        task = self.client.get(f"/dubbing/auto/status/{task_id}").json()
        self.assertEqual(task["status"], "queued")
        self.assertEqual(task["target_lang"], "Chinese")
        self.assertEqual(task["dubbing_mode"], "single")
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["speaker_ref_map"], [])
        self.assertIn("--dubbing-mode", task["command"])
        self.assertIn("single", task["command"])
        self.assertIn("--tts-backend", task["command"])
        self.assertIn("index-tts", task["command"])
        self.assertTrue(FakeThread.instances)
        self.assertTrue(FakeThread.instances[0].started)
        self.assertEqual(FakeThread.instances[0].args[0], task_id)
        self.assertEqual(FakeThread.instances[0].args[2]["TRANSLATE_API_KEY"], "secret-key")
        runtime_brief = task.get("runtime_brief") or {}
        self.assertIn("index-tts(api=", runtime_brief.get("tts_base", ""))
        self.assertEqual(runtime_brief.get("dubbing_mode"), "single")
        self.assertIn("sentence(", runtime_brief.get("grouping", ""))
        self.assertEqual(runtime_brief.get("translation"), "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)")
        self.assertIn("source=off(", runtime_brief.get("merge", ""))
        self.assertIn("translated=off(", runtime_brief.get("merge", ""))
        self.assertEqual(runtime_brief.get("range"), "all(ranges=0)")
        self.assertEqual(runtime_brief.get("segment"), "8.0m/4.0m")
        self.assertEqual(task.get("translate_request_count"), 0)

    def test_start_auto_dubbing_requires_subtitle_file(self):
        """Auto dubbing 不再允许无字幕启动。"""

        with self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files={"video": ("demo.mp4", b"video-data", "video/mp4")},
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("requires subtitle_file", response.json()["detail"])

    def test_omnivoice_final_srt_rebalance_limits_line_width_and_keeps_monotonic_timing(self):
        """OmniVoice 结果字幕重排应满足 25 字上限，且时间轴严格递增。"""

        input_rows = [
            {
                "start": 0.0,
                "end": 8.0,
                "text": "他正是在这间办公室参与创立了 Open AI，也是当年让特斯拉的自动驾驶系统成功运作的人，他有一种罕见的天赋，能让最复杂的技术变革显得既亲切又理所当然。",
                "speaker_id": "Speaker 1",
            },
            {
                "start": 8.0,
                "end": 13.0,
                "text": "如果这个框架是对的，哪些工作将比人们意识到的更快发生变革，而哪些我们以为安全的职业实际上是高度可验证的呢？",
                "speaker_id": "Speaker 1",
            },
        ]

        output_rows = omnivoice_dub_api._rebalance_omnivoice_final_srt_rows(input_rows)
        self.assertGreaterEqual(len(output_rows), len(input_rows))
        self.assertTrue(output_rows)

        last_end = -1.0
        for row in output_rows:
            text = str(row.get("text") or "")
            self.assertTrue(text)
            self.assertLessEqual(len(text), 25)
            start = float(row["start"])
            end = float(row["end"])
            self.assertGreater(end, start)
            self.assertGreaterEqual(start, last_end)
            last_end = end

        rendered = dubbing_cli_api.format_srt(output_rows)
        self.assertIn("-->", rendered)

    def test_omnivoice_synthesis_rebalance_fixes_extreme_adjacent_timing_pairs(self):
        """OmniVoice 合成前应修复相邻的极端时长错配，避免短字长时窗/长字短时窗。"""

        input_rows = [
            {"start": 1632.8, "end": 1648.16, "text": "你", "speaker_id": "Speaker 1"},
            {
                "start": 1648.16,
                "end": 1648.4,
                "text": "你既可以有AI来做很多人的工作，但当你有一个人类团队时，AI不只是为一个个人做很多人的工作，而是在一个人类组织中运作，它多次完成很多人的工作。",
                "speaker_id": "Speaker 1",
            },
        ]

        output_rows, adjusted_pairs = omnivoice_dub_api._rebalance_omnivoice_synthesis_rows(input_rows)

        self.assertEqual(adjusted_pairs, 1)
        self.assertEqual(len(output_rows), 2)
        first = output_rows[0]
        second = output_rows[1]
        self.assertLess(first["end"] - first["start"], 3.0)
        self.assertGreater(second["end"] - second["start"], 10.0)
        self.assertAlmostEqual(first["end"], second["start"], places=3)
        self.assertAlmostEqual(first["start"], 1632.8, places=3)
        self.assertAlmostEqual(second["end"], 1648.4, places=3)

    def test_omnivoice_selected_rows_guard_splits_overlong_without_affecting_other_paths(self):
        """5 号 OmniVoice 选中字链路应限制长时窗，且只在该链路启用。"""

        input_rows = [
            {"start": 888.160, "end": 891.200, "text": "their ability to write or their ability to kind of do do", "speaker_id": "Speaker 3"},
            {"start": 891.280, "end": 894.800, "text": "do do you know to to do uh you know less less", "speaker_id": "Speaker 3"},
            {"start": 894.800, "end": 896.640, "text": "objective scientific tasks.", "speaker_id": "Speaker 3"},
            {"start": 896.640, "end": 899.440, "text": "So I think it's gonna have benefits in many in many other", "speaker_id": "Speaker 3"},
            {"start": 899.440, "end": 903.120, "text": "areas, but you know I think we find even within software engineering", "speaker_id": "Speaker 3"},
            {"start": 903.280, "end": 907.040, "text": "this uh you know this these these kind of um uh uh", "speaker_id": "Speaker 3"},
            {"start": 907.280, "end": 912.800, "text": "soft or somewhat subjective um uh skills and abilities are become surprisingly", "speaker_id": "Speaker 3"},
        ]

        output_rows = omnivoice_dub_api._optimize_omnivoice_selected_rows(input_rows)
        self.assertGreater(len(output_rows), 1)
        max_duration = max(float(item["end"]) - float(item["start"]) for item in output_rows)
        self.assertLessEqual(max_duration, 12.0)
        self.assertTrue(all((item.get("speaker_id") == "Speaker 3") for item in output_rows))

    def test_omnivoice_selected_rows_guard_splits_single_overlong_row_by_punctuation(self):
        """5 号 OmniVoice 对单条超长字幕也应先按标点内切，避免 20s+ 长时窗。"""

        input_rows = [
            {
                "start": 888.159,
                "end": 914.159,
                "text": "他们写作的能力，或者做那些不那么客观的科学任务的能力。所以我认为这会在许多其他领域带来好处，但即使在软件工程内部，我们也会发现那些软性的或有点主观的技能和能力由于 Amdel 定律而变得出奇地重要。",
                "speaker_id": "Speaker 3",
            }
        ]

        output_rows = omnivoice_dub_api._optimize_omnivoice_selected_rows(input_rows)
        self.assertGreater(len(output_rows), 1)
        max_duration = max(float(item["end"]) - float(item["start"]) for item in output_rows)
        self.assertLessEqual(max_duration, 12.0)

    def test_omnivoice_selected_subtitles_with_speaker_copy_prefixes_speaker_id(self):
        """selected_subtitles 副本应在每条文本前带 speaker 标识，便于人工校对。"""

        input_rows = [
            {"start": 0.0, "end": 1.0, "text": "你好", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "世界", "speaker_id": "Speaker 2"},
        ]

        output_rows = omnivoice_dub_api._build_selected_subtitles_with_speaker_rows(input_rows)
        self.assertEqual(len(output_rows), 2)
        self.assertEqual(output_rows[0]["text"], "[Speaker 1] 你好")
        self.assertEqual(output_rows[1]["text"], "[Speaker 2] 世界")

    def test_voxcpm_backend_status_proxies_health_payload(self):
        """6 号面板后端状态接口应把 VoxCPM health 转成 ready 标识。"""

        with patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}):
            response = self.client.get("/voxcpm/auto/backend-status")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["device"], "mps")

    def test_reset_voxcpm_output_for_fresh_run_preserves_uploaded_refs(self):
        """新任务清场时应删除旧 segment/final，但保留用户上传参考音。"""

        out_root = self.voxcpm_output_root / "voxcpm_reset_case"
        (out_root / "segments" / "segment_0001").mkdir(parents=True, exist_ok=True)
        (out_root / "segments" / "segment_0001" / "manifest.json").write_text("{}", encoding="utf-8")
        (out_root / "final").mkdir(parents=True, exist_ok=True)
        (out_root / "final" / "dubbed_final_full.srt").write_text("old", encoding="utf-8")
        (out_root / "uploaded_speaker_refs").mkdir(parents=True, exist_ok=True)
        (out_root / "uploaded_speaker_refs" / "speaker.wav").write_text("ref", encoding="utf-8")
        (out_root / "selected_subtitles.srt").write_text("old srt", encoding="utf-8")

        voxcpm_dub_api._reset_voxcpm_output_for_fresh_run(out_root=out_root)

        self.assertFalse((out_root / "segments").exists())
        self.assertFalse((out_root / "final").exists())
        self.assertFalse((out_root / "selected_subtitles.srt").exists())
        self.assertTrue((out_root / "uploaded_speaker_refs").exists())
        self.assertTrue((out_root / "uploaded_speaker_refs" / "speaker.wav").exists())

    def test_prune_voxcpm_resume_segments_removes_stale_dirs(self):
        """resume 前应删掉不可复用 segment，只保留当前字幕仍匹配的完成段。"""

        segment_root = self.voxcpm_output_root / "voxcpm_prune_case" / "segments"
        for index in [1, 2, 3]:
            seg_dir = segment_root / f"segment_{index:04d}"
            seg_dir.mkdir(parents=True, exist_ok=True)
            (seg_dir / "manifest.json").write_text("{}", encoding="utf-8")

        voxcpm_dub_api._prune_voxcpm_resume_segments(
            segment_root=segment_root,
            completed_indices={1, 3},
        )

        self.assertTrue((segment_root / "segment_0001").exists())
        self.assertFalse((segment_root / "segment_0002").exists())
        self.assertTrue((segment_root / "segment_0003").exists())

    def test_normalize_voxcpm_internal_rows_strips_markdown_emphasis_and_drops_empty_marker_rows(self):
        """6 号面板内部字幕归一化应剥离 Markdown 样式标记，并丢掉纯标记空行。"""

        rows = [
            {"start": 0.0, "end": 1.0, "text": "」呢系一個**循環**嘅敘事。", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "**世界唔系線性，世界系周期嘅。", "speaker_id": "Speaker 1"},
            {"start": 2.0, "end": 2.5, "text": "**", "speaker_id": "Speaker 1"},
        ]

        normalized = voxcpm_dub_api._normalize_voxcpm_internal_rows(rows)

        self.assertEqual(
            [str(item.get("text") or "") for item in normalized],
            ["」呢系一個循環嘅敘事。", "世界唔系線性，世界系周期嘅。"],
        )

    def test_voxcpm_http_json_bypasses_proxy_for_local_backend(self):
        """6 号面板访问本机 VoxCPM 服务时，必须绕过系统代理。"""

        class _FakeResponse:
            """最小本地响应对象。"""

            def __init__(self, body: bytes):
                self.body = body

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        opener_mock = MagicMock()
        opener_mock.open.return_value = _FakeResponse(b'{"status":"ok","device":"mps"}')

        with (
            patch.object(voxcpm_dub_api.urllib.request, "build_opener", return_value=opener_mock) as build_opener_mock,
            patch.object(voxcpm_dub_api.urllib.request, "urlopen") as urlopen_mock,
        ):
            payload = voxcpm_dub_api._http_json(
                method="GET",
                url="http://127.0.0.1:7860/api/health",
                timeout_sec=1.0,
            )

        self.assertEqual(payload["status"], "ok")
        build_opener_mock.assert_called_once()
        opener_mock.open.assert_called_once()
        urlopen_mock.assert_not_called()

    def test_omnivoice_health_checks_bypass_proxy_for_local_backend(self):
        """5 号面板访问本机 OmniVoice 服务时，health/model status 检查必须绕过系统代理。"""

        class _FakeResponse:
            """最小本地响应对象。"""

            def __init__(self, body: bytes, status: int = 200):
                self.body = body
                self.status = status

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        opener_mock = MagicMock()
        opener_mock.open.side_effect = [
            _FakeResponse(b"", status=200),
            _FakeResponse(b'{"status":"ready","loading":false}'),
        ]

        with (
            patch.object(omnivoice_dub_api.urllib.request, "build_opener", return_value=opener_mock) as build_opener_mock,
            patch.object(omnivoice_dub_api.urllib.request, "urlopen") as urlopen_mock,
        ):
            omnivoice_dub_api._check_omnivoice_health("http://127.0.0.1:3900")
            payload = omnivoice_dub_api._fetch_omnivoice_model_status("http://127.0.0.1:3900")

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(build_opener_mock.call_count, 2)
        self.assertEqual(opener_mock.open.call_count, 2)
        urlopen_mock.assert_not_called()

    def test_omnivoice_generate_bypasses_proxy_for_local_backend(self):
        """5 号面板访问本机 OmniVoice /generate 时，正式请求也必须绕过系统代理。"""

        class _FakeResponse:
            """最小 requests 响应对象。"""

            def __init__(self, content: bytes):
                self.status_code = 200
                self.content = content
                self.text = ""

        class _FakeSession:
            """记录 trust_env/proxies 和 post 调用的最小 session。"""

            def __init__(self):
                self.trust_env = True
                self.proxies = {"http": "http://127.0.0.1:1082"}
                self.post_calls = []

            def post(self, url, **kwargs):
                self.post_calls.append((url, kwargs))
                return _FakeResponse(b"fake-wav")

            def close(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        ref_audio = self.tmpdir / "ref.wav"
        ref_audio.write_bytes(b"RIFFfake")
        fake_session = _FakeSession()

        with patch("requests.Session", return_value=fake_session) as session_ctor:
            payload = omnivoice_dub_api._call_remote_generate(
                api_url="http://127.0.0.1:3900",
                text="你好",
                language="zh",
                ref_audio_path=ref_audio,
                ref_text="你好，这是我的声音音色，很高兴为你提供配音服务。",
                instruct="",
                duration=2.0,
            )

        self.assertEqual(payload, b"fake-wav")
        session_ctor.assert_called_once()
        self.assertFalse(fake_session.trust_env)
        self.assertEqual(fake_session.proxies, {})
        self.assertEqual(len(fake_session.post_calls), 1)
        self.assertEqual(fake_session.post_calls[0][0], "http://127.0.0.1:3900/generate")

    def test_ensure_voxcpm_backend_ready_auto_starts_local_service(self):
        """6 号面板指向本机 7860 时，应先尝试自动拉起 VoxCPM 服务。"""

        with (
            patch.object(voxcpm_dub_api, "_start_local_voxcpm_backend", return_value={"started": True, "pid": 123}),
            patch.object(voxcpm_dub_api, "_check_voxcpm_backend", return_value={"status": "ok", "device": "mps"}) as check_mock,
        ):
            payload = voxcpm_dub_api._ensure_voxcpm_backend_ready("http://127.0.0.1:7860")

        self.assertEqual(payload["status"], "ok")
        check_mock.assert_called_once_with("http://127.0.0.1:7860")

    def test_voxcpm_translation_uses_shared_system_prompt_contract(self):
        """6 号面板翻译 system prompt 应与 5 号面板保持一致。"""

        prompt = translator_module.build_translation_system_prompt("保留技术术语英文原文。")

        self.assertIn("用户附加要求", prompt)
        self.assertIn("保留技术术语英文原文。", prompt)

    def test_convert_chinese_script_rows_supports_cantonese_traditional_and_simplified(self):
        """6 号面板粤语脚本转换应默认繁体，切到简体才转换。"""

        rows = [{"start": 0.0, "end": 1.0, "text": "你好，呢個系我嘅聲音音色，很高興為你提供配音服務。", "speaker_id": "Speaker 1"}]
        traditional_rows = voxcpm_dub_api._apply_voxcpm_final_script_variant(rows, "traditional", target_lang="Cantonese")
        simplified_rows = voxcpm_dub_api._apply_voxcpm_final_script_variant(rows, "simplified", target_lang="Cantonese")
        chinese_rows = voxcpm_dub_api._apply_voxcpm_final_script_variant(rows, "simplified", target_lang="Chinese")
        self.assertEqual(traditional_rows[0]["text"], rows[0]["text"])
        self.assertIn("呢个", simplified_rows[0]["text"])
        self.assertIn("声音", simplified_rows[0]["text"])
        self.assertEqual(chinese_rows[0]["text"], rows[0]["text"])

    def test_voxcpm_soft_align_segment_keeps_natural_duration_without_fit(self):
        """6 号面板应保留自然时长，不再强制 fit 到原字幕窗。"""

        raw_path = self.tmpdir / "voxcpm_raw.wav"
        out_path = self.tmpdir / "voxcpm_fit.wav"
        sf.write(raw_path, np.zeros(32000, dtype=np.float32), 16000)

        with patch.object(voxcpm_dub_api, "audio_duration", side_effect=[2.0, 2.0]):
            meta = voxcpm_dub_api._soft_align_segment(
                input_path=raw_path,
                output_path=out_path,
                target_duration_sec=1.25,
            )

        self.assertEqual(meta["mode"], "natural_passthrough")
        self.assertEqual(meta["aligned_duration_sec"], 2.0)
        self.assertEqual(meta["target_duration_sec"], 1.25)
        self.assertTrue(out_path.exists())

    def test_voxcpm_soft_align_segment_trims_leading_silence_without_fit(self):
        """6 号面板逐句整理时应先保守裁掉句首前导静音，但不再强制 fit。"""

        raw_path = self.tmpdir / "voxcpm_raw_trim.wav"
        out_path = self.tmpdir / "voxcpm_trim_fit.wav"
        trimmed_probe = self.tmpdir / "voxcpm_raw_trim_trim.wav"
        sf.write(raw_path, np.zeros(32000, dtype=np.float32), 16000)
        trimmed_probe.write_bytes(b"trimmed")

        with (
            patch.object(voxcpm_dub_api, "audio_duration", side_effect=[2.0, 1.5, 1.0]),
            patch.object(voxcpm_dub_api, "trim_silence_edges", return_value=(2.0, 1.5)),
        ):
            meta = voxcpm_dub_api._soft_align_segment(
                input_path=raw_path,
                output_path=out_path,
                target_duration_sec=1.0,
            )

        self.assertTrue(meta["trimmed_input"])
        self.assertEqual(meta["mode"], "natural_trimmed")
        self.assertEqual(meta["trimmed_raw_duration_sec"], 2.0)
        self.assertEqual(meta["trimmed_output_duration_sec"], 1.5)

    def test_list_voxcpm_batches_reads_manifest(self):
        """6 号面板结果列表应从 voxcpm_* manifest 读取。"""

        out_root = self.voxcpm_output_root / "voxcpm_20260518_000001"
        out_root.mkdir(parents=True, exist_ok=True)
        (out_root / "manifest.json").write_text(
            json.dumps(
                {
                    "batch_id": "20260518_000001",
                    "task_id": "20260518_000001",
                    "project_filename": "demo.mp4",
                    "status": "completed",
                    "created_at": "2026-05-18T00:00:00Z",
                    "target_lang": "Cantonese",
                    "subtitle_mode": "translated",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        response = self.client.get("/voxcpm/auto/batches")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["batch_id"], "20260518_000001")
        self.assertEqual(items[0]["target_lang"], "Cantonese")

    def test_load_voxcpm_batch_restores_task_view(self):
        """6 号面板加载批次应恢复结果视图和产物列表。"""

        out_root = self.voxcpm_output_root / "voxcpm_20260518_000002"
        out_root.mkdir(parents=True, exist_ok=True)
        final_dir = out_root / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        final_srt = final_dir / "dubbed_final_full.srt"
        final_mix = final_dir / "dubbed_mix_full.wav"
        final_video = final_dir / "dubbed_video_full.mp4"
        final_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        sf.write(final_mix, np.zeros(16000, dtype=np.float32), 16000)
        final_video.write_text("video", encoding="utf-8")
        manifest_path = out_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "20260518_000002",
                    "task_id": "20260518_000002",
                    "project_filename": "demo.mp4",
                    "input_media_path": str((self.upload_root / "demo.mp4").resolve()),
                    "status": "completed",
                    "stage": "completed",
                    "progress": 100.0,
                    "subtitle_mode": "translated",
                    "selected_subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "voxcpm_api_url": "http://127.0.0.1:7860",
                    "subtitle_video_preset": "1080x1920",
                    "source_subtitles_count": 0,
                    "translated_subtitles_count": 1,
                    "processed_segments": 1,
                    "segment_count": 1,
                    "generated_subtitle_video_presets": ["1080x1920"],
                    "subtitle_video_variants": [
                        {
                            "preset": "1080x1920",
                            "ass_artifact_key": "ass_1080x1920",
                            "video_artifact_key": "video_1080x1920",
                            "ass_url": "/voxcpm/auto/artifact/20260518_000002/ass_1080x1920",
                            "video_url": "/voxcpm/auto/artifact/20260518_000002/video_1080x1920",
                            "ass_path": str((final_dir / "dubbed_final_full-styled-1080x1920.ass").resolve()),
                            "video_path": str(final_video.resolve()),
                        }
                    ],
                    "preferred_video_artifact_key": "video_1080x1920",
                    "artifacts": [
                        {"key": "srt", "label": "Dubbed Final SRT", "url": "/voxcpm/auto/artifact/20260518_000002/srt"},
                        {"key": "mix", "label": "Dubbed Mix WAV", "url": "/voxcpm/auto/artifact/20260518_000002/mix"},
                        {"key": "video", "label": "Dubbed Video MP4", "url": "/voxcpm/auto/artifact/20260518_000002/video"},
                    ],
                    "paths": {
                        "dubbed_final_srt": str(final_srt.resolve()),
                        "dubbed_mix": str(final_mix.resolve()),
                        "dubbed_video_full": str(final_video.resolve()),
                        "manifest": str(manifest_path.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        response = self.client.post("/voxcpm/auto/load-batch", data={"batch_id": "20260518_000002"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_subtitle_mode"], "translated")
        self.assertEqual(payload["result_video"], str(final_video.resolve()))
        self.assertEqual(payload["subtitle_video_preset"], "1080x1920")
        self.assertEqual(len(payload["artifacts"]), 3)
        self.assertEqual(payload["generated_subtitle_video_presets"], ["1080x1920"])
        self.assertEqual(payload["preferred_video_artifact_key"], "video_1080x1920")
        self.assertEqual(payload["subtitle_video_variants"][0]["preset"], "1080x1920")

    def test_render_voxcpm_video_variant_generates_new_preset_without_rerunning_tts(self):
        """6 号面板已完成批次应可单独补生成其他视频规格，不重跑配音。"""

        out_root = self.voxcpm_output_root / "voxcpm_20260519_000001"
        out_root.mkdir(parents=True, exist_ok=True)
        final_dir = out_root / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        final_srt = final_dir / "dubbed_final_full.srt"
        final_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好，世界。\n", encoding="utf-8")
        final_mix = final_dir / "dubbed_mix_full.wav"
        sf.write(final_mix, np.zeros(16000, dtype=np.float32), 16000)
        final_ass = final_dir / "dubbed_final_full-styled.ass"
        final_ass.write_text("ass", encoding="utf-8")
        final_video = final_dir / "dubbed_video_full.mp4"
        final_video.write_text("video", encoding="utf-8")
        manifest_path = out_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "20260519_000001",
                    "task_id": "20260519_000001",
                    "project_filename": "demo.mp4",
                    "input_media_path": "",
                    "status": "completed",
                    "stage": "completed",
                    "progress": 100.0,
                    "subtitle_mode": "translated",
                    "selected_subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "voxcpm_api_url": "http://127.0.0.1:7860",
                    "subtitle_video_preset": "1920x1080",
                    "source_subtitles_count": 0,
                    "translated_subtitles_count": 1,
                    "processed_segments": 1,
                    "segment_count": 1,
                    "cfg_value": 2.0,
                    "inference_timesteps": 10,
                    "generated_subtitle_video_presets": ["1920x1080"],
                    "subtitle_video_variants": [
                        {
                            "preset": "1920x1080",
                            "ass_artifact_key": "ass_1920x1080",
                            "video_artifact_key": "video_1920x1080",
                            "ass_url": "/voxcpm/auto/artifact/20260519_000001/ass_1920x1080",
                            "video_url": "/voxcpm/auto/artifact/20260519_000001/video_1920x1080",
                            "ass_path": str(final_ass.resolve()),
                            "video_path": str(final_video.resolve()),
                        }
                    ],
                    "preferred_video_artifact_key": "video_1920x1080",
                    "artifacts": [
                        {"key": "video", "label": "Dubbed Video MP4 (1920x1080)", "url": "/voxcpm/auto/artifact/20260519_000001/video"},
                        {"key": "mix", "label": "Dubbed Mix WAV", "url": "/voxcpm/auto/artifact/20260519_000001/mix"},
                        {"key": "ass", "label": "Dubbed Final ASS", "url": "/voxcpm/auto/artifact/20260519_000001/ass"},
                    ],
                    "paths": {
                        "dubbed_final_srt": str(final_srt.resolve()),
                        "dubbed_mix": str(final_mix.resolve()),
                        "dubbed_final_ass": str(final_ass.resolve()),
                        "dubbed_video_full": str(final_video.resolve()),
                        "subtitle_video_variants": {
                            "1920x1080": {
                                "ass": str(final_ass.resolve()),
                                "video": str(final_video.resolve()),
                            }
                        },
                        "manifest": str(manifest_path.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(
            voxcpm_dub_api,
            "build_black_video_with_ass_subtitles",
            side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video-variant", encoding="utf-8") or kwargs["output_video_path"],
        ) as render_mock:
            response = self.client.post(
                "/voxcpm/auto/render-video-variant",
                data={"batch_id": "20260519_000001", "subtitle_video_preset": "1080x1920"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(render_mock.call_count, 1)
        self.assertIn("1080x1920", payload["generated_subtitle_video_presets"])
        self.assertEqual(payload["preferred_video_artifact_key"], "video_1080x1920")
        variant_presets = {item["preset"] for item in payload["subtitle_video_variants"]}
        self.assertEqual(variant_presets, {"1920x1080", "1080x1920"})
        self.assertTrue((final_dir / "dubbed_video_full-1080x1920.mp4").exists())
        self.assertTrue((final_dir / "dubbed_final_full-styled-1080x1920.ass").exists())

    def test_render_voxcpm_video_variant_skips_existing_preset(self):
        """已生成过的规格再次请求时，应直接返回，不重复渲染。"""

        out_root = self.voxcpm_output_root / "voxcpm_20260519_000002"
        out_root.mkdir(parents=True, exist_ok=True)
        final_dir = out_root / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        final_srt = final_dir / "dubbed_final_full.srt"
        final_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        final_mix = final_dir / "dubbed_mix_full.wav"
        sf.write(final_mix, np.zeros(16000, dtype=np.float32), 16000)
        final_ass = final_dir / "dubbed_final_full-styled.ass"
        final_ass.write_text("ass", encoding="utf-8")
        final_video = final_dir / "dubbed_video_full.mp4"
        final_video.write_text("video", encoding="utf-8")
        manifest_path = out_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "20260519_000002",
                    "task_id": "20260519_000002",
                    "project_filename": "demo.mp4",
                    "input_media_path": "",
                    "status": "completed",
                    "stage": "completed",
                    "progress": 100.0,
                    "subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "subtitle_video_preset": "1920x1080",
                    "generated_subtitle_video_presets": ["1920x1080"],
                    "subtitle_video_variants": [
                        {
                            "preset": "1920x1080",
                            "ass_artifact_key": "ass_1920x1080",
                            "video_artifact_key": "video_1920x1080",
                            "ass_url": "/voxcpm/auto/artifact/20260519_000002/ass_1920x1080",
                            "video_url": "/voxcpm/auto/artifact/20260519_000002/video_1920x1080",
                            "ass_path": str(final_ass.resolve()),
                            "video_path": str(final_video.resolve()),
                        }
                    ],
                    "preferred_video_artifact_key": "video_1920x1080",
                    "artifacts": [],
                    "paths": {
                        "dubbed_final_srt": str(final_srt.resolve()),
                        "dubbed_mix": str(final_mix.resolve()),
                        "dubbed_final_ass": str(final_ass.resolve()),
                        "dubbed_video_full": str(final_video.resolve()),
                        "subtitle_video_variants": {
                            "1920x1080": {
                                "ass": str(final_ass.resolve()),
                                "video": str(final_video.resolve()),
                            }
                        },
                        "manifest": str(manifest_path.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles") as render_mock:
            response = self.client.post(
                "/voxcpm/auto/render-video-variant",
                data={"batch_id": "20260519_000002", "subtitle_video_preset": "1920x1080"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(render_mock.call_count, 0)
        payload = response.json()
        self.assertEqual(payload["generated_subtitle_video_presets"], ["1920x1080"])

    def test_start_voxcpm_from_project_allows_subtitle_only_mode(self):
        """6 号面板应允许仅凭字幕启动，不再强制要求视频或单参考音。"""

        with (
            patch.object(voxcpm_dub_api.threading, "Thread", FakeThread),
            patch.object(voxcpm_dub_api, "_resolve_project_media_path", side_effect=HTTPException(status_code=404, detail="Current project media not found")),
        ):
            response = self.client.post(
                "/voxcpm/auto/start-from-project",
                data={
                    "filename": "",
                    "original_filename": "",
                    "task_id": "task_1",
                    "source_subtitles_json": json.dumps([{"start": 0.0, "end": 1.0, "text": "Hello"}], ensure_ascii=False),
                    "translated_subtitles_json": json.dumps([], ensure_ascii=False),
                    "subtitle_mode": "source",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret",
                    "ref_text": "你好，这是我的声音。",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = voxcpm_dub_api._task_store.get(payload["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task["input_media_path"], "")
        self.assertEqual(task["speaker_reference_mode"], "preset_only")
        self.assertTrue(FakeThread.instances)
        self.assertTrue(FakeThread.instances[-1].started)

    def test_start_voxcpm_from_project_allows_zero_uploaded_speaker_refs(self):
        """6 号面板未上传任何 speaker 参考音时，也应允许直接走 preset_only。"""

        with (
            patch.object(voxcpm_dub_api.threading, "Thread", FakeThread),
            patch.object(voxcpm_dub_api, "_resolve_project_media_path", side_effect=HTTPException(status_code=404, detail="Current project media not found")),
        ):
            response = self.client.post(
                "/voxcpm/auto/start-from-project",
                data={
                    "filename": "",
                    "original_filename": "",
                    "task_id": "task_no_refs",
                    "source_subtitles_json": json.dumps(
                        [
                            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker_id": "Speaker 1"},
                            {"start": 1.0, "end": 2.0, "text": "World", "speaker_id": "Speaker 2"},
                        ],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": json.dumps([], ensure_ascii=False),
                    "subtitle_mode": "source",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = voxcpm_dub_api._task_store.get(payload["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task["speaker_ids"], ["Speaker 1", "Speaker 2"])
        self.assertEqual(task["speaker_reference_mode"], "preset_only")
        self.assertTrue(FakeThread.instances)
        self.assertEqual(FakeThread.instances[-1].kwargs["uploaded_speaker_ref_map"], {})

    def test_parse_voxcpm_podcast_script_supports_multi_speaker_markdown(self):
        """6 号面板应能解析双人播客脚本，只提取角色台词行。"""

        script = (
            "# Demo Podcast\n\n"
            "> 素材来源：unit test\n\n"
            "## Opening Hook\n\n"
            "（音乐淡入：悬疑）\n\n"
            "**Larei:**【情绪=好奇】你知道 OpenAI 最近做了一件事吗？\n\n"
            "**Tensor:**【情绪=困惑】等等，这是真的吗？\n\n"
            "## 制作备注\n\n"
            "| 元素 | 建议 |\n"
        ).encode("utf-8")

        response = self.client.post(
            "/voxcpm/auto/parse-podcast-script",
            files=[("script_file", ("podcast.md", script, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["title"], "Demo Podcast")
        self.assertEqual(payload["detected_mode"], "multi")
        self.assertEqual(payload["speaker_ids"], ["Larei", "Tensor"])
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["rows"][0]["speaker_id"], "Larei")
        self.assertEqual(payload["rows"][0]["emotion"], "情绪=好奇")
        self.assertIn("OpenAI", payload["rows"][0]["text"])
        self.assertGreater(payload["rows"][0]["end"], payload["rows"][0]["start"])

    def test_parse_voxcpm_podcast_script_supports_single_speaker_markdown(self):
        """6 号面板应能解析单人播客脚本，并保持单 speaker 模式。"""

        script = (
            "# 单人播客\n\n"
            "**Larei:**【情绪=直接】我今天想聊一个事实。\n"
            "它其实比表面看起来更重要。\n\n"
            "(音乐淡出)\n"
        ).encode("utf-8")

        response = self.client.post(
            "/voxcpm/auto/parse-podcast-script",
            files=[("script_file", ("solo.md", script, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["detected_mode"], "single")
        self.assertEqual(payload["speaker_ids"], ["Larei"])
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["speaker_id"], "Larei")
        self.assertIn("我今天想聊一个事实", payload["rows"][0]["text"])
        self.assertIn("它其实比表面看起来更重要", payload["rows"][0]["text"])

    def test_parse_voxcpm_podcast_script_supports_role_header_and_body_on_next_line(self):
        """真实播客脚本常见“角色头单独一行，正文在下一行”，解析器应支持。"""

        script = (
            "# 双人播客\n\n"
            "**Larei:**【情绪=好奇】\n\n"
            "你知道 OpenAI 最近做了一件事吗？\n\n"
            "**Tensor:**【情绪=困惑】\n"
            "等等，这是真的吗？\n"
        ).encode("utf-8")

        response = self.client.post(
            "/voxcpm/auto/parse-podcast-script",
            files=[("script_file", ("realistic.md", script, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["speaker_ids"], ["Larei", "Tensor"])
        self.assertEqual(len(payload["rows"]), 2)
        self.assertIn("你知道 OpenAI 最近做了一件事吗", payload["rows"][0]["text"])
        self.assertIn("等等，这是真的吗", payload["rows"][1]["text"])

    def test_parse_voxcpm_podcast_script_skips_parenthesized_one_line_summary_marker(self):
        """`(**一句话总结：**)` 这类包裹标记不应混入解析后的正文。"""

        script = (
            "# 总结播客\n\n"
            "**Larei:**【情绪=平静】第一段正文。\n\n"
            "(**一句话总结：**)\n\n"
            "**Tensor:**【情绪=认真】第二段正文。\n"
        ).encode("utf-8")

        response = self.client.post(
            "/voxcpm/auto/parse-podcast-script",
            files=[("script_file", ("summary.md", script, "text/markdown"))],
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["rows"]), 2)
        joined = "\n".join(str(row["text"]) for row in payload["rows"])
        self.assertNotIn("一句话总结", joined)
        self.assertIn("第一段正文", joined)
        self.assertIn("第二段正文", joined)

    def test_voxcpm_collect_detected_speaker_ids_prefers_previous_row_before_speaker_1(self):
        """6 号面板 speaker 归一化应先继承上一行，再兜底 Speaker 1。"""

        rows = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 2"},
            {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_id": ""},
            {"start": 2.0, "end": 3.0, "text": "第三句", "speaker_id": "Speaker 1"},
        ]

        speaker_ids = voxcpm_dub_api._collect_detected_speaker_ids(rows)

        self.assertEqual(speaker_ids, ["Speaker 2", "Speaker 1"])

    def test_start_voxcpm_from_project_accepts_parsed_podcast_rows(self):
        """6 号面板播客脚本解析结果应可直接复用现有 start-from-project 链路。"""

        with (
            patch.object(voxcpm_dub_api.threading, "Thread", FakeThread),
            patch.object(voxcpm_dub_api, "_resolve_project_media_path", side_effect=HTTPException(status_code=404, detail="Current project media not found")),
        ):
            response = self.client.post(
                "/voxcpm/auto/start-from-project",
                data={
                    "filename": "",
                    "original_filename": "podcast.md",
                    "task_id": "task_podcast",
                    "source_subtitles_json": json.dumps(
                        [
                            {"start": 0.0, "end": 1.8, "text": "第一句播客台词", "speaker_id": "Larei"},
                            {"start": 1.98, "end": 3.4, "text": "第二句播客台词", "speaker_id": "Tensor"},
                        ],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": json.dumps([], ensure_ascii=False),
                    "subtitle_mode": "source",
                    "source_lang": "Chinese",
                    "target_lang": "Chinese",
                    "api_key": "secret",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = voxcpm_dub_api._task_store.get(payload["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task["speaker_ids"], ["Larei", "Tensor"])
        self.assertTrue(FakeThread.instances)
        self.assertEqual(
            [row["speaker_id"] for row in FakeThread.instances[-1].kwargs["source_rows"]],
            ["Larei", "Tensor"],
        )

    def test_voxcpm_translate_subtitles_if_needed_preserves_speaker_ids(self):
        """6 号面板 source->translate 后不能丢 speaker_id，否则会把多 speaker 配音串成同一人。"""

        source_rows = [
            {"start": 0.0, "end": 1.0, "text": "Hello one", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "Hello two", "speaker_id": "Speaker 2"},
        ]

        class _FakeTranslator:
            """返回稳定两行译文，便于验证 speaker_id 是否被透传。"""

            def __init__(self, *args, **kwargs):
                pass

            def translate_batch(self, *args, **kwargs):
                return ["你好一", "你好二"]

        with patch.object(voxcpm_dub_api, "Translator", _FakeTranslator):
            source_selected_rows, translated_selected_rows, mode = voxcpm_dub_api._translate_subtitles_if_needed(
                subtitle_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="English",
                target_lang="Chinese",
                api_key="dummy-key",
                translate_base_url="https://api.example.com",
                translate_model="test-model",
                translate_system_prompt="",
            )

        self.assertEqual(mode, "translated")
        self.assertEqual([row["speaker_id"] for row in source_selected_rows], ["Speaker 1", "Speaker 2"])
        self.assertEqual([row["speaker_id"] for row in translated_selected_rows], ["Speaker 1", "Speaker 2"])

    def test_voxcpm_translate_subtitles_if_needed_sanitizes_reused_translated_rows(self):
        """6 号面板直接复用现有译文时，也应清掉模型说明性废话。"""

        translated_rows = [
            {
                "start": 97.68,
                "end": 109.2,
                "text": "պայք?不对。 fight. 争斗。 But Chinese output only. Let's correct in final.",
                "speaker_id": "Speaker 1",
            }
        ]

        source_selected_rows, translated_selected_rows, mode = voxcpm_dub_api._translate_subtitles_if_needed(
            subtitle_mode="translated",
            source_rows=[],
            translated_rows=translated_rows,
            source_lang="auto",
            target_lang="Chinese",
            api_key="",
            translate_base_url="",
            translate_model="",
            translate_system_prompt="",
        )

        self.assertEqual(mode, "translated")
        self.assertEqual(len(source_selected_rows), 1)
        self.assertEqual(len(translated_selected_rows), 1)
        self.assertEqual(translated_selected_rows[0]["text"], "争斗")

    def test_voxcpm_translate_subtitles_if_needed_retries_latin_dominant_rows_for_cantonese_target(self):
        """6 号面板配粤语时，英文主导漏译行应做定向重试，不能直接写进 selected_subtitles.srt。"""

        source_rows = [
            {
                "start": 0.0,
                "end": 4.879,
                "text": "During sex, the average man lasts two point five minutes to six minutes.",
                "speaker_id": "Speaker 1",
            }
        ]

        class _FakeTranslator:
            """首次返回英文错误行，二次重试返回粤语，验证兜底是否生效。"""

            def __init__(self, *args, **kwargs):
                self.calls = 0

            def translate_batch(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return ["[Error] During sex, the average man lasts two point five minutes to six minutes."]
                return ["做愛嗰陣，一般男人通常維持兩分半到六分鐘。"]

        with patch.object(voxcpm_dub_api, "Translator", _FakeTranslator):
            source_selected_rows, translated_selected_rows, mode = voxcpm_dub_api._translate_subtitles_if_needed(
                subtitle_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="English",
                target_lang="Cantonese",
                api_key="dummy-key",
                translate_base_url="https://api.example.com",
                translate_model="test-model",
                translate_system_prompt="",
            )

        self.assertEqual(mode, "translated")
        self.assertEqual(len(source_selected_rows), 1)
        self.assertEqual(len(translated_selected_rows), 1)
        self.assertNotIn("[Error]", translated_selected_rows[0]["text"])
        self.assertFalse(voxcpm_dub_api._is_voxcpm_latin_dominant_text(translated_selected_rows[0]["text"]))
        self.assertIn("做愛嗰陣", translated_selected_rows[0]["text"])

    def test_voxcpm_translate_subtitles_if_needed_keeps_full_cantonese_paragraph(self):
        """6 号面板翻译长粤语整段时，不应被清洗器截成单句。"""

        source_rows = [
            {
                "start": 0.0,
                "end": 20.0,
                "text": "原始中文整段",
                "speaker_id": "Larei",
            }
        ]

        long_translation = (
            "我今日想讲一个可能会令好多创业者唔舒服嘅事实。"
            "哈佛创新实验室嘅导师喺课堂上讲过一句说话，原话系：“想法到处都系，根本唔值钱。” "
            "Ideas are everywhere. They're worthless. "
            "你可能觉得自己有一个关于 X、Y、Z 嘅超劲想法。"
            "但系喺佢未绑到一个具体嘅人、一个具体嘅痛点之前——佢其实咩都唔系。"
            "而公司失败嘅头号原因，就系佢哋冇解决一个足够有价值嘅问题。"
        )

        class _FakeTranslator:
            def __init__(self, *args, **kwargs):
                pass

            def translate_batch(self, *args, **kwargs):
                self.kwargs = kwargs
                return [long_translation]

        with patch.object(voxcpm_dub_api, "Translator", _FakeTranslator):
            source_selected_rows, translated_selected_rows, mode = voxcpm_dub_api._translate_subtitles_if_needed(
                subtitle_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="Chinese",
                target_lang="Cantonese-Mainland",
                api_key="dummy-key",
                translate_base_url="https://api.example.com",
                translate_model="test-model",
                translate_system_prompt="",
            )

        self.assertEqual(mode, "translated")
        self.assertEqual(source_selected_rows[0]["text"], "原始中文整段")
        self.assertIn("我今日想讲一个可能会令好多创业者唔舒服嘅事实。", translated_selected_rows[0]["text"])
        self.assertIn("而公司失败嘅头号原因", translated_selected_rows[0]["text"])
        self.assertIn("Ideas are everywhere.", translated_selected_rows[0]["text"])
        self.assertGreater(len(translated_selected_rows[0]["text"]), 80)

    def test_voxcpm_translate_subtitles_if_needed_skips_translation_for_chinese_source_to_chinese(self):
        """6 号面板中文播客脚本配中文时，应直接复用原文，避免额外翻译计费。"""

        source_rows = [
            {"start": 0.0, "end": 1.0, "text": "你好，欢迎来到今天的节目。", "speaker_id": "Larei"},
            {"start": 1.0, "end": 2.0, "text": "我们今天聊一下 AI。", "speaker_id": "Tensor"},
        ]

        class _FailTranslator:
            """如果这条测试还走进翻译器，就直接失败。"""

            def __init__(self, *args, **kwargs):
                raise AssertionError("中文到中文不应调用翻译 API")

        with patch.object(voxcpm_dub_api, "Translator", _FailTranslator):
            source_selected_rows, translated_selected_rows, mode = voxcpm_dub_api._translate_subtitles_if_needed(
                subtitle_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="Chinese",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
            )

        self.assertEqual(mode, "source")
        self.assertEqual([row["text"] for row in source_selected_rows], [row["text"] for row in source_rows])
        self.assertEqual([row["speaker_id"] for row in source_selected_rows], ["Larei", "Tensor"])
        self.assertEqual(translated_selected_rows, [])

    def test_voxcpm_translate_subtitles_if_needed_skips_translation_for_cantonese_source_to_cantonese(self):
        """6 号面板 source 已是粤语、target 也是粤语时，应直接复用原文，避免额外翻译计费。"""

        source_rows = [
            {"start": 0.0, "end": 1.0, "text": "你好，呢個係第一句。", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "我哋而家開始。", "speaker_id": "Speaker 2"},
        ]

        class _FailTranslator:
            """如果这条测试还走进翻译器，就直接失败。"""

            def __init__(self, *args, **kwargs):
                raise AssertionError("粤语到粤语不应调用翻译 API")

        with patch.object(voxcpm_dub_api, "Translator", _FailTranslator):
            source_selected_rows, translated_selected_rows, mode = voxcpm_dub_api._translate_subtitles_if_needed(
                subtitle_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="粤语",
                target_lang="Cantonese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
            )

        self.assertEqual(mode, "source")
        self.assertEqual([row["text"] for row in source_selected_rows], [row["text"] for row in source_rows])
        self.assertEqual([row["speaker_id"] for row in source_selected_rows], ["Speaker 1", "Speaker 2"])
        self.assertEqual(translated_selected_rows, [])

    def test_start_voxcpm_from_project_strips_speaker_prefix_before_passthrough(self):
        """6 号面板 source 直通时，也必须先剥掉正文里的 Speaker 前缀，不能把标签直接喂给 TTS。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        with patch.object(voxcpm_dub_api.threading, "Thread", FakeThread):
            response = self.client.post(
                "/voxcpm/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "voxcpm-project-task",
                    "source_subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "Speaker 1: 喺做爱嗰阵，一般男人可以顶二分半到六分钟"}],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": "[]",
                    "subtitle_mode": "source",
                    "source_lang": "Cantonese",
                    "target_lang": "Cantonese",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(FakeThread.instances)
        source_rows = FakeThread.instances[-1].kwargs["source_rows"]
        self.assertEqual(source_rows[0]["speaker_id"], "Speaker 1")
        self.assertEqual(source_rows[0]["text"], "喺做爱嗰阵，一般男人可以顶二分半到六分钟")

    def test_start_voxcpm_from_project_strips_fullwidth_speaker_prefix_before_passthrough(self):
        """全角冒号的 Speaker 前缀也必须在 6 号面板直通前被剥掉。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        with patch.object(voxcpm_dub_api.threading, "Thread", FakeThread):
            response = self.client.post(
                "/voxcpm/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "voxcpm-project-task-fullwidth",
                    "source_subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "Speaker 1：喺做爱嗰阵，一般男人可以顶二分半到六分钟"}],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": "[]",
                    "subtitle_mode": "source",
                    "source_lang": "Cantonese",
                    "target_lang": "Cantonese",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(FakeThread.instances)
        source_rows = FakeThread.instances[-1].kwargs["source_rows"]
        self.assertEqual(source_rows[0]["speaker_id"], "Speaker 1")
        self.assertEqual(source_rows[0]["text"], "喺做爱嗰阵，一般男人可以顶二分半到六分钟")

    def test_start_voxcpm_from_project_persists_custom_translate_provider(self):
        """6 号面板手填的翻译 base_url/model 不能在任务 payload 里回退成默认值。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        with patch.object(voxcpm_dub_api.threading, "Thread", FakeThread):
            response = self.client.post(
                "/voxcpm/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "voxcpm-project-task-provider",
                    "source_subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "hello project", "speaker_id": "Speaker 1"}],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": "[]",
                    "subtitle_mode": "source",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "translate_base_url": "https://example.com/v1",
                    "translate_model": "gpt-5.4-mini",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = voxcpm_dub_api._task_store.get(payload["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task["translate_base_url"], "https://example.com/v1")
        self.assertEqual(task["translate_model"], "gpt-5.4-mini")
        self.assertTrue(FakeThread.instances)
        thread_kwargs = FakeThread.instances[-1].kwargs
        self.assertEqual(thread_kwargs["translate_base_url"], "https://example.com/v1")
        self.assertEqual(thread_kwargs["translate_model"], "gpt-5.4-mini")

    def test_voxcpm_translate_subtitles_if_needed_skips_translation_for_english_source_to_english(self):
        """6 号面板明确 English -> English 时，也应直接复用原文。"""

        source_rows = [
            {"start": 0.0, "end": 1.0, "text": "Hello and welcome.", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "We start now.", "speaker_id": "Speaker 2"},
        ]

        class _FailTranslator:
            def __init__(self, *args, **kwargs):
                raise AssertionError("English 到 English 不应调用翻译 API")

        with patch.object(voxcpm_dub_api, "Translator", _FailTranslator):
            rows, mode = voxcpm_dub_api._translate_subtitles_if_needed(
                subtitle_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="English",
                target_lang="English",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
            )

        self.assertEqual(mode, "source")
        self.assertEqual([row["text"] for row in rows], [row["text"] for row in source_rows])
        self.assertEqual([row["speaker_id"] for row in rows], ["Speaker 1", "Speaker 2"])

    def test_voxcpm_http_json_retries_incomplete_read(self):
        """VoxCPM HTTP 响应被截断时，应自动重试一次，而不是整批任务直接失败。"""

        class _FakeResponse:
            """最小 urlopen 响应对象。"""

            def __init__(self, body: bytes):
                self.body = body

            def read(self):
                return self.body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        attempts = {"count": 0}

        def fake_urlopen(*args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise IncompleteRead(b'{"audio_base64":"abc"', 10)
            return _FakeResponse(b'{"audio_base64":"ok"}')

        with patch.object(voxcpm_dub_api.urllib.request, "urlopen", side_effect=fake_urlopen):
            payload = voxcpm_dub_api._http_json(
                method="POST",
                url="http://127.0.0.1:7860/api/tts",
                payload={"text": "hello"},
                timeout_sec=1.0,
            )

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(payload["audio_base64"], "ok")

    def test_start_voxcpm_from_project_accepts_partial_speaker_refs(self):
        """6 号面板应允许只上传部分 speaker 参考音，其余 speaker 交给运行时补位。"""

        ref_wav = io.BytesIO()
        sf.write(ref_wav, np.zeros(8000, dtype=np.float32), 16000, format="WAV")

        with (
            patch.object(voxcpm_dub_api.threading, "Thread", FakeThread),
            patch.object(voxcpm_dub_api, "_resolve_project_media_path", side_effect=HTTPException(status_code=404, detail="Current project media not found")),
        ):
            response = self.client.post(
                "/voxcpm/auto/start-from-project",
                files=[
                    ("speaker_ref_files", ("speaker1.wav", ref_wav.getvalue(), "audio/wav")),
                ],
                data={
                    "filename": "",
                    "original_filename": "",
                    "task_id": "task_partial",
                    "source_subtitles_json": json.dumps(
                        [
                            {"start": 0.0, "end": 1.0, "text": "Hello", "speaker_id": "Speaker 1"},
                            {"start": 1.0, "end": 2.0, "text": "World", "speaker_id": "Speaker 2"},
                        ],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": json.dumps([], ensure_ascii=False),
                    "subtitle_mode": "source",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = voxcpm_dub_api._task_store.get(payload["task_id"])
        self.assertIsNotNone(task)
        self.assertEqual(task["speaker_ids"], ["Speaker 1", "Speaker 2"])
        self.assertEqual(task["speaker_reference_mode"], "uploaded_partial")
        self.assertTrue(FakeThread.instances)
        kwargs = FakeThread.instances[-1].kwargs
        self.assertEqual(sorted(kwargs["uploaded_speaker_ref_map"].keys()), ["Speaker 1"])
        self.assertEqual(
            kwargs["uploaded_speaker_ref_map"]["Speaker 1"]["ref_text"],
            "你好，这是我的声音音色，很高兴为你提供配音服务。",
        )
        self.assertEqual(kwargs["ref_text"], "")
        self.assertTrue(FakeThread.instances[-1].started)

    def test_load_voxcpm_batch_marks_failed_batch_resumable_from_selected_subtitles(self):
        """6 号面板加载失败批次时，应基于磁盘 selected_subtitles 标记 prepared 可恢复态。"""

        out_root = self.voxcpm_output_root / "voxcpm_20260518_000003"
        out_root.mkdir(parents=True, exist_ok=True)
        selected_path = out_root / "selected_subtitles.srt"
        selected_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        source_audio = out_root / "source_audio.wav"
        sf.write(source_audio, np.zeros(16000, dtype=np.float32), 16000)
        ref_dir = out_root / "refs"
        ref_dir.mkdir(parents=True, exist_ok=True)
        ref_audio = ref_dir / "ref.wav"
        sf.write(ref_audio, np.zeros(8000, dtype=np.float32), 16000)
        manifest_path = out_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "20260518_000003",
                    "task_id": "20260518_000003",
                    "project_filename": "demo.mp4",
                    "input_media_path": str((self.upload_root / "demo.mp4").resolve()),
                    "status": "failed",
                    "stage": "failed",
                    "progress": 100.0,
                    "subtitle_mode": "translated",
                    "selected_subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "voxcpm_api_url": "http://127.0.0.1:7860",
                    "ref_audio_path": str(ref_audio.resolve()),
                    "ref_text": "你好，这是我的声音。",
                    "cfg_value": 2.0,
                    "inference_timesteps": 10,
                    "processed_segments": 0,
                    "segment_count": 1,
                    "paths": {
                        "source_audio": str(source_audio.resolve()),
                        "selected_subtitles": str(selected_path.resolve()),
                        "manifest": str(manifest_path.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        response = self.client.post("/voxcpm/auto/load-batch", data={"batch_id": "20260518_000003"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["resumable"])
        self.assertEqual(payload["resume_stage"], "prepared")
        self.assertEqual(payload["total_segments"], 1)

    def test_load_voxcpm_batch_restores_translate_provider_from_manifest(self):
        """6 号面板 load-batch 恢复任务视图时，不能把翻译 provider 回退成默认值。"""

        batch_id = "20260518_000003_provider"
        out_root = self.voxcpm_output_root / f"voxcpm_{batch_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        selected_path = out_root / "selected_subtitles.srt"
        selected_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        manifest_path = out_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "task_id": batch_id,
                    "project_filename": "demo.mp4",
                    "input_media_path": str((self.upload_root / "demo.mp4").resolve()),
                    "status": "failed",
                    "stage": "failed",
                    "progress": 100.0,
                    "subtitle_mode": "translated",
                    "selected_subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "voxcpm_api_url": "http://127.0.0.1:7860",
                    "translate_base_url": "https://example.com/v1",
                    "translate_model": "gpt-5.4-mini",
                    "paths": {
                        "selected_subtitles": str(selected_path.resolve()),
                        "manifest": str(manifest_path.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        response = self.client.post("/voxcpm/auto/load-batch", data={"batch_id": batch_id})
        self.assertEqual(response.status_code, 200)
        task = voxcpm_dub_api._task_store.get(batch_id)
        self.assertIsNotNone(task)
        self.assertEqual(task["translate_base_url"], "https://example.com/v1")
        self.assertEqual(task["translate_model"], "gpt-5.4-mini")

    def test_resume_voxcpm_task_requeues_failed_batch(self):
        """6 号面板 resume 应恢复失败批次并把 resume_context 传入后台线程。"""

        out_root = self.voxcpm_output_root / "voxcpm_20260518_000004"
        out_root.mkdir(parents=True, exist_ok=True)
        input_media = self.upload_root / "demo.mp4"
        input_media.write_bytes(b"fake-video")
        selected_path = out_root / "selected_subtitles.srt"
        selected_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        source_audio = out_root / "source_audio.wav"
        sf.write(source_audio, np.zeros(16000, dtype=np.float32), 16000)
        ref_dir = out_root / "refs"
        ref_dir.mkdir(parents=True, exist_ok=True)
        ref_audio = ref_dir / "ref.wav"
        sf.write(ref_audio, np.zeros(8000, dtype=np.float32), 16000)
        manifest_path = out_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "20260518_000004",
                    "task_id": "20260518_000004",
                    "project_filename": "demo.mp4",
                    "input_media_path": str(input_media.resolve()),
                    "status": "failed",
                    "stage": "failed",
                    "progress": 100.0,
                    "subtitle_mode": "translated",
                    "selected_subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "voxcpm_api_url": "http://127.0.0.1:7860",
                    "ref_audio_path": str(ref_audio.resolve()),
                    "ref_text": "你好，这是我的声音。",
                    "cfg_value": 2.5,
                    "inference_timesteps": 12,
                    "subtitle_video_preset": "1440x1080",
                    "processed_segments": 0,
                    "segment_count": 1,
                    "paths": {
                        "source_audio": str(source_audio.resolve()),
                        "selected_subtitles": str(selected_path.resolve()),
                        "manifest": str(manifest_path.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(voxcpm_dub_api.threading, "Thread", FakeThread):
            response = self.client.post("/voxcpm/auto/resume/20260518_000004")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["resume_stage"], "prepared")
        self.assertTrue(FakeThread.instances)
        self.assertTrue(FakeThread.instances[-1].started)
        resume_context = FakeThread.instances[-1].kwargs["resume_context"]
        self.assertEqual(resume_context["selected_subtitle_mode"], "translated")
        self.assertEqual(Path(resume_context["source_audio_path"]).name, "source_audio.wav")
        self.assertEqual(Path(resume_context["ref_audio_path"]).name, "ref.wav")
        self.assertEqual(resume_context["subtitle_video_preset"], "1440x1080")

    def test_resume_voxcpm_task_reuses_translate_provider_from_manifest(self):
        """6 号面板 resume 后台线程必须复用原批次的翻译 provider。"""

        batch_id = "20260518_000004_provider"
        out_root = self.voxcpm_output_root / f"voxcpm_{batch_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        input_media = self.upload_root / "demo-provider.mp4"
        input_media.write_bytes(b"fake-video")
        selected_path = out_root / "selected_subtitles.srt"
        selected_path.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        source_audio = out_root / "source_audio.wav"
        sf.write(source_audio, np.zeros(16000, dtype=np.float32), 16000)
        ref_dir = out_root / "refs"
        ref_dir.mkdir(parents=True, exist_ok=True)
        ref_audio = ref_dir / "ref.wav"
        sf.write(ref_audio, np.zeros(8000, dtype=np.float32), 16000)
        manifest_path = out_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "task_id": batch_id,
                    "project_filename": "demo.mp4",
                    "input_media_path": str(input_media.resolve()),
                    "status": "failed",
                    "stage": "failed",
                    "progress": 100.0,
                    "subtitle_mode": "translated",
                    "selected_subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "voxcpm_api_url": "http://127.0.0.1:7860",
                    "translate_base_url": "https://example.com/v1",
                    "translate_model": "gpt-5.4-mini",
                    "ref_audio_path": str(ref_audio.resolve()),
                    "ref_text": "你好，这是我的声音。",
                    "cfg_value": 2.5,
                    "inference_timesteps": 12,
                    "paths": {
                        "source_audio": str(source_audio.resolve()),
                        "selected_subtitles": str(selected_path.resolve()),
                        "manifest": str(manifest_path.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(voxcpm_dub_api.threading, "Thread", FakeThread):
            response = self.client.post(f"/voxcpm/auto/resume/{batch_id}")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(FakeThread.instances)
        kwargs = FakeThread.instances[-1].kwargs
        self.assertEqual(kwargs["translate_base_url"], "https://example.com/v1")
        self.assertEqual(kwargs["translate_model"], "gpt-5.4-mini")

    def test_run_voxcpm_job_resume_skips_completed_segments(self):
        """6 号面板 resume 续跑时，应复用已完成 segment，只生成缺失条目。"""

        task_id = "20260518_000005"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        input_media = self.upload_root / "demo.mp4"
        input_media.write_bytes(b"fake-video")
        source_audio = out_root / "source_audio.wav"
        sf.write(source_audio, np.zeros(64000, dtype=np.float32), 16000)
        ref_dir = out_root / "refs"
        ref_dir.mkdir(parents=True, exist_ok=True)
        ref_audio = ref_dir / "ref.wav"
        sf.write(ref_audio, np.zeros(8000, dtype=np.float32), 16000)
        segments_dir = out_root / "segments" / "segment_0001"
        segments_dir.mkdir(parents=True, exist_ok=True)
        seg1_final = segments_dir / "seg_0001.wav"
        sf.write(seg1_final, np.zeros(16000, dtype=np.float32), 16000)
        (segments_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "seg_0001",
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "第一句",
                    "paths": {
                        "dubbed_vocals": str(seg1_final.resolve()),
                        "dubbed_mix": str(seg1_final.resolve()),
                    },
                },
            ),
            encoding="utf-8",
        )
        selected_rows = [
            {"start": 0.0, "end": 1.0, "text": "第一句"},
            {"start": 1.0, "end": 2.0, "text": "第二句"},
        ]
        selected_path = out_root / "selected_subtitles.srt"
        selected_path.write_text(voxcpm_dub_api.format_srt(selected_rows), encoding="utf-8")
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="demo.mp4",
            input_media_path=input_media,
            subtitle_mode="translated",
            source_lang="English",
            target_lang="Chinese",
            source_count=0,
            translated_count=2,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
        )
        voxcpm_dub_api._task_store.create(task_id, task)
        resume_context = {
            "selected_rows": selected_rows,
            "completed_segment_indices": {1},
            "reusable_segment_results": [
                {
                    "id": "seg_0001",
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "第一句",
                    "paths": {
                        "dubbed_vocals": str(seg1_final.resolve()),
                        "dubbed_mix": str(seg1_final.resolve()),
                    },
                }
            ],
            "source_audio_path": str(source_audio.resolve()),
            "ref_audio_path": str(ref_audio.resolve()),
            "ref_text": "你好，这是我的声音。",
            "selected_subtitle_mode": "translated",
            "cfg_value": 2.0,
            "inference_timesteps": 10,
        }

        call_texts = []

        def fake_tts(**kwargs):
            call_texts.append(kwargs["text"])
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "build_full_timeline_mix", side_effect=lambda **kwargs: kwargs["output_wav"].write_bytes(b"mix") or kwargs["output_wav"]),
            patch.object(voxcpm_dub_api, "has_video_stream", return_value=False),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=input_media,
                source_rows=[],
                translated_rows=[],
                subtitle_mode="translated",
                source_lang="English",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=ref_audio,
                ref_text="你好，这是我的声音。",
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
                resume_context=resume_context,
            )

        self.assertEqual(call_texts, ["第二句"])
        self.assertTrue((out_root / "segments" / "segment_0002" / "seg_0002.wav").exists())

    def test_run_voxcpm_job_partial_speaker_refs_fill_missing_speakers(self):
        """6 号面板只上传部分 speaker 参考音时，应自动补齐缺失 speaker。"""

        task_id = "20260518_000005_partial"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        input_media = self.upload_root / "demo_partial.mp4"
        input_media.write_bytes(b"fake-video")
        uploaded_dir = out_root / "uploaded"
        uploaded_dir.mkdir(parents=True, exist_ok=True)
        speaker1_ref = uploaded_dir / "speaker1.wav"
        sf.write(speaker1_ref, np.zeros(8000, dtype=np.float32), 16000)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="demo_partial.mp4",
            input_media_path=input_media,
            subtitle_mode="translated",
            source_lang="English",
            target_lang="Chinese",
            source_count=0,
            translated_count=2,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            speaker_ids=["Speaker 1", "Speaker 2"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)

        selected_rows = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_id": "Speaker 2"},
        ]
        uploaded_speaker_ref_map = {
            "Speaker 1": {
                "ref_audio": str(speaker1_ref.resolve()),
                "ref_text": "上传的 Speaker 1 参考文本",
                "reference_mode": "uploaded_partial",
                "upload_filename": "speaker1.wav",
            }
        }
        auto_ref = out_root / "auto_speaker2.wav"
        sf.write(auto_ref, np.zeros(8000, dtype=np.float32), 16000)
        tts_prompt_pairs = []

        def fake_extract_source_audio(_input_path, output_path):
            """为缺失 speaker 性别探测准备 source_audio。"""

            sf.write(output_path, np.zeros(16000, dtype=np.float32), 16000)

        def fake_tts(**kwargs):
            """记录每句使用的参考音，验证 speaker 路由是否正确。"""

            tts_prompt_pairs.append((kwargs["text"], Path(str(kwargs["prompt_audio_path"])).name, kwargs["prompt_text"]))
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "extract_source_audio", side_effect=fake_extract_source_audio),
            patch.object(voxcpm_dub_api, "_infer_missing_speaker_gender_hints", return_value={"Speaker 2": "female"}) as infer_mock,
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available") as validate_mock,
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Speaker 2": {
                        "ref_audio": str(auto_ref.resolve()),
                        "ref_text": "你好，这是我的声音音色，很高兴为你提供配音服务。",
                        "reference_mode": "preset_pool",
                        "upload_filename": "auto_speaker2.wav",
                    }
                },
            ) as pick_mock,
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=input_media,
                source_rows=[],
                translated_rows=selected_rows,
                subtitle_mode="translated",
                source_lang="English",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                uploaded_speaker_ref_map=uploaded_speaker_ref_map,
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
            )

        infer_mock.assert_called_once()
        validate_mock.assert_called_once()
        pick_mock.assert_called_once()
        self.assertEqual(
            pick_mock.call_args.kwargs["speaker_gender_hints"],
            {"Speaker 2": "female"},
        )
        self.assertEqual(
            tts_prompt_pairs,
            [
                ("第一句", "speaker1.wav", "上传的 Speaker 1 参考文本"),
                ("第二句", "auto_speaker2.wav", "你好，这是我的声音音色，很高兴为你提供配音服务。"),
            ],
        )
        task = voxcpm_dub_api._task_store.get(task_id)
        self.assertEqual(task["speaker_reference_mode"], "uploaded_mixed")
        manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["speaker_reference_mode"], "uploaded_mixed")
        self.assertEqual(sorted(manifest["speaker_ref_map"].keys()), ["Speaker 1", "Speaker 2"])

    def test_run_voxcpm_job_without_media_uses_preset_only_mode(self):
        """6 号面板纯字幕多 speaker 且无上传参考音时，应直接走预置参考音补位。"""

        task_id = "20260518_000005_preset"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="subtitle_only_multi",
            input_media_path=None,
            subtitle_mode="translated",
            source_lang="English",
            target_lang="Chinese",
            source_count=0,
            translated_count=2,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            speaker_ids=["Speaker 1", "Speaker 2"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)

        selected_rows = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_id": "Speaker 2"},
        ]
        speaker1_ref = out_root / "preset_speaker1.wav"
        speaker2_ref = out_root / "preset_speaker2.wav"
        sf.write(speaker1_ref, np.zeros(8000, dtype=np.float32), 16000)
        sf.write(speaker2_ref, np.zeros(8000, dtype=np.float32), 16000)
        tts_prompt_names = []

        def fake_tts(**kwargs):
            """记录每句走的是哪份预置参考音。"""

            tts_prompt_names.append(Path(str(kwargs["prompt_audio_path"])).name)
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available") as validate_mock,
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Speaker 1": {
                        "ref_audio": str(speaker1_ref.resolve()),
                        "ref_text": "Speaker 1 默认文本",
                        "reference_mode": "preset_pool",
                    },
                    "Speaker 2": {
                        "ref_audio": str(speaker2_ref.resolve()),
                        "ref_text": "Speaker 2 默认文本",
                        "reference_mode": "preset_pool",
                    },
                },
            ) as pick_mock,
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=None,
                source_rows=[],
                translated_rows=selected_rows,
                subtitle_mode="translated",
                source_lang="English",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                uploaded_speaker_ref_map=None,
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
            )

        validate_mock.assert_called_once()
        pick_mock.assert_called_once()
        self.assertEqual(
            pick_mock.call_args.kwargs["missing_speaker_ids"],
            ["Speaker 1", "Speaker 2"],
        )
        self.assertEqual(tts_prompt_names, ["preset_speaker1.wav", "preset_speaker2.wav"])
        task = voxcpm_dub_api._task_store.get(task_id)
        self.assertEqual(task["speaker_reference_mode"], "preset_only")
        manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["speaker_reference_mode"], "preset_only")

    def test_run_voxcpm_job_subtitle_only_builds_natural_srt_and_black_video(self):
        """6 号面板纯字幕模式应按真实音频时长重建 SRT，并输出黑底字幕视频。"""

        task_id = "20260518_000006"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="subtitle_only",
            input_media_path=None,
            subtitle_mode="translated",
            source_lang="English",
            target_lang="Chinese",
            source_count=0,
            translated_count=2,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            speaker_ids=["Speaker 1", "Speaker 2"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)

        selected_rows = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_id": "Speaker 2"},
        ]
        durations = [1.8, 2.2]
        speaker1_ref = out_root / "preset_speaker1.wav"
        speaker2_ref = out_root / "preset_speaker2.wav"
        sf.write(speaker1_ref, np.zeros(8000, dtype=np.float32), 16000)
        sf.write(speaker2_ref, np.zeros(8000, dtype=np.float32), 16000)

        def fake_tts(**kwargs):
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        def fake_soft_align_segment(**kwargs):
            output_path = kwargs["output_path"]
            sf.write(output_path, np.zeros(16000, dtype=np.float32), 16000)
            return {
                "mode": "natural_passthrough",
                "raw_duration_sec": 1.0,
                "aligned_duration_sec": 1.0,
                "target_duration_sec": 12.0,
                "trimmed_input": False,
                "trimmed_raw_duration_sec": 1.0,
                "trimmed_output_duration_sec": 1.0,
            }

        def fake_soft_align_segment(**kwargs):
            output_path = kwargs["output_path"]
            duration = durations.pop(0)
            sf.write(output_path, np.zeros(int(16000 * duration), dtype=np.float32), 16000)
            return {
                "mode": "natural_passthrough",
                "raw_duration_sec": duration,
                "aligned_duration_sec": duration,
                "target_duration_sec": kwargs["target_duration_sec"],
                "trimmed_input": False,
                "trimmed_raw_duration_sec": duration,
                "trimmed_output_duration_sec": duration,
            }

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available"),
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Speaker 1": {
                        "ref_audio": str(speaker1_ref.resolve()),
                        "ref_text": "Speaker 1 默认文本",
                        "reference_mode": "preset_pool",
                    },
                    "Speaker 2": {
                        "ref_audio": str(speaker2_ref.resolve()),
                        "ref_text": "Speaker 2 默认文本",
                        "reference_mode": "preset_pool",
                    },
                },
            ),
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "_soft_align_segment", side_effect=fake_soft_align_segment),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=None,
                source_rows=[],
                translated_rows=selected_rows,
                subtitle_mode="translated",
                source_lang="English",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
            )

        final_srt = out_root / "final" / "dubbed_final_full.srt"
        final_rebuild_srt = out_root / "final" / "dubbed_final_full-rebuild.srt"
        final_srt_with_speakers = out_root / "final" / "dubbed_final_full_with_speakers.srt"
        selected_srt_with_speakers = out_root / "selected_subtitles_with_speakers.srt"
        final_ass = out_root / "final" / "dubbed_final_full-styled.ass"
        final_video = out_root / "final" / "dubbed_video_full.mp4"
        self.assertTrue(final_srt.exists())
        self.assertTrue(final_rebuild_srt.exists())
        self.assertTrue(final_srt_with_speakers.exists())
        self.assertTrue(selected_srt_with_speakers.exists())
        self.assertTrue(final_ass.exists())
        self.assertTrue(final_video.exists())
        parsed = voxcpm_dub_api.parse_srt(final_srt.read_text(encoding="utf-8"))
        rebuild_parsed = voxcpm_dub_api.parse_srt(final_rebuild_srt.read_text(encoding="utf-8"))
        speaker_copy_parsed = voxcpm_dub_api.parse_srt(final_srt_with_speakers.read_text(encoding="utf-8"))
        self.assertEqual(len(parsed), 2)
        self.assertAlmostEqual(float(parsed[0]["start"]), 0.0, places=2)
        self.assertAlmostEqual(float(parsed[0]["end"]), 1.8, places=2)
        self.assertGreater(float(parsed[1]["start"]), float(parsed[0]["end"]))
        self.assertEqual(len(speaker_copy_parsed), 2)
        self.assertAlmostEqual(float(speaker_copy_parsed[0]["start"]), float(parsed[0]["start"]), places=2)
        self.assertAlmostEqual(float(speaker_copy_parsed[0]["end"]), float(parsed[0]["end"]), places=2)
        self.assertAlmostEqual(float(speaker_copy_parsed[1]["start"]), float(parsed[1]["start"]), places=2)
        self.assertAlmostEqual(float(speaker_copy_parsed[1]["end"]), float(parsed[1]["end"]), places=2)
        self.assertTrue(rebuild_parsed)
        last_end = -1.0
        for row in rebuild_parsed:
            self.assertLessEqual(len(str(row["text"])), 20)
            self.assertGreater(float(row["end"]), float(row["start"]))
            self.assertGreaterEqual(float(row["start"]), last_end)
            last_end = float(row["end"])
        speaker_copy_text = final_srt_with_speakers.read_text(encoding="utf-8")
        selected_speaker_copy_text = selected_srt_with_speakers.read_text(encoding="utf-8")
        self.assertIn("[Speaker 1] 第一句", speaker_copy_text)
        self.assertIn("[Speaker 2] 第二句", speaker_copy_text)
        self.assertIn("[Speaker 1] 第一句", selected_speaker_copy_text)
        self.assertIn("[Speaker 2] 第二句", selected_speaker_copy_text)
        self.assertIn("Fontsize, PrimaryColour", final_ass.read_text(encoding="utf-8"))
        self.assertIn("Arial Unicode MS,144", final_ass.read_text(encoding="utf-8"))
        manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["subtitle_script_variant"], "traditional")
        self.assertEqual(
            manifest["paths"]["selected_subtitles_with_speakers"],
            str(selected_srt_with_speakers.resolve()),
        )
        self.assertEqual(
            manifest["paths"]["dubbed_final_srt_with_speakers"],
            str(final_srt_with_speakers.resolve()),
        )
        self.assertEqual(
            manifest["paths"]["dubbed_final_srt_rebuild"],
            str(final_rebuild_srt.resolve()),
        )
        artifact_keys = {item["key"] for item in manifest.get("artifacts") or []}
        self.assertIn("selected_srt_with_speaker", artifact_keys)
        self.assertIn("srt_rebuild", artifact_keys)
        self.assertIn("srt_with_speaker", artifact_keys)

    def test_run_voxcpm_job_splits_long_rows_before_tts_and_keeps_speaker_ids(self):
        """6 号面板应走 selected -> rebuild -> TTS，且 speaker_id 在短句工作副本中保持稳定。"""

        task_id = "20260519_000010"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="podcast_long_row",
            input_media_path=None,
            subtitle_mode="source",
            source_lang="Chinese",
            target_lang="Chinese",
            source_count=1,
            translated_count=0,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            speaker_ids=["Speaker 2"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)

        long_text = (
            "想法到处都是。应该说是到处都不值钱。你可能觉得自己有一个关于 X、Y、Z 的超棒想法。"
            "但在它被绑定到一个具体的人、一个具体的痛点之前，它什么都不是。"
        )
        selected_rows = [
            {"start": 0.0, "end": 8.0, "text": long_text, "speaker_id": "Speaker 2"},
        ]
        generated_texts: List[str] = []
        speaker2_ref = out_root / "preset_speaker2.wav"
        sf.write(speaker2_ref, np.zeros(8000, dtype=np.float32), 16000)

        def fake_tts(**kwargs):
            generated_texts.append(str(kwargs["text"]))
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        def fake_soft_align_segment(**kwargs):
            output_path = kwargs["output_path"]
            duration = 1.6
            sf.write(output_path, np.zeros(int(16000 * duration), dtype=np.float32), 16000)
            return {
                "mode": "natural_passthrough",
                "raw_duration_sec": duration,
                "aligned_duration_sec": duration,
                "target_duration_sec": kwargs["target_duration_sec"],
                "trimmed_input": False,
                "trimmed_raw_duration_sec": duration,
                "trimmed_output_duration_sec": duration,
            }

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available"),
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Speaker 2": {
                        "ref_audio": str(speaker2_ref.resolve()),
                        "ref_text": "Speaker 2 默认文本",
                        "reference_mode": "preset_pool",
                    },
                },
            ),
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "_soft_align_segment", side_effect=fake_soft_align_segment),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=None,
                source_rows=selected_rows,
                translated_rows=[],
                subtitle_mode="source",
                source_lang="Chinese",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
            )

        self.assertGreater(len(generated_texts), 1)
        self.assertEqual(
            generated_texts[0],
            "想法到处都是。应该说是到处都不值钱。",
        )
        self.assertEqual("".join(generated_texts), long_text)
        self.assertTrue(all(text.strip() for text in generated_texts))

        selected_srt = out_root / "selected_subtitles.srt"
        selected_rebuild_srt = out_root / "selected_subtitles_rebuild.srt"
        selected_srt_with_speakers = out_root / "selected_subtitles_with_speakers.srt"
        final_srt = out_root / "final" / "dubbed_final_full.srt"
        self.assertTrue(selected_srt.exists())
        self.assertTrue(selected_rebuild_srt.exists())
        self.assertTrue(selected_srt_with_speakers.exists())
        self.assertTrue(final_srt.exists())
        self.assertIn(long_text, selected_srt.read_text(encoding="utf-8"))

        selected_parsed = voxcpm_dub_api.parse_srt(selected_srt.read_text(encoding="utf-8"))
        selected_rebuild_parsed = voxcpm_dub_api.parse_srt(selected_rebuild_srt.read_text(encoding="utf-8"))
        selected_speaker_parsed = voxcpm_dub_api.parse_srt(selected_srt_with_speakers.read_text(encoding="utf-8"))
        final_parsed = voxcpm_dub_api.parse_srt(final_srt.read_text(encoding="utf-8"))
        self.assertEqual(len(selected_parsed), 1)
        self.assertEqual([str(item.get("text") or "") for item in selected_rebuild_parsed], generated_texts)
        self.assertEqual(len(selected_speaker_parsed), len(generated_texts))
        self.assertEqual(len(final_parsed), len(generated_texts))
        self.assertTrue(all("[Speaker 2]" in str(item.get("text") or "") for item in selected_speaker_parsed))
        self.assertEqual([str(item.get("text") or "") for item in final_parsed], generated_texts)
        segment_manifests = sorted((out_root / "segments").glob("segment_*/manifest.json"))
        self.assertEqual(len(segment_manifests), len(generated_texts))
        for manifest_path in segment_manifests:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(str(payload.get("speaker_id") or "").strip(), "Speaker 2")
        manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
        tts_rows = list(manifest.get("selected_subtitles_tts_rows") or [])
        self.assertEqual([str(item.get("text") or "") for item in tts_rows], generated_texts)
        self.assertEqual(
            str((manifest.get("paths") or {}).get("selected_subtitles_rebuild") or ""),
            str(selected_rebuild_srt.resolve()),
        )
        self.assertTrue(all(str(item.get("text") or "").strip() for item in tts_rows))

    def test_voxcpm_podcast_script_content_survives_pre_tts_split(self):
        """播客脚本文字内容进入 selected_subtitles 时不能丢开头正文。"""

        source_text = (
            "我今天想聊一个可能会让很多创业者不舒服的事实。 "
            "哈佛创新实验室的导师在课上说了一句话，原话是：\"想法到处都是。应该说是到处都不值钱。\" "
            "Ideas are everywhere. They're worthless. "
            "你可能觉得自己有一个关于 X、Y、Z 的超棒想法。但在它被绑定到一个具体的人、一个具体的痛点之前——它什么都不是。"
        )
        rows = [{"start": 0.0, "end": 24.0, "text": source_text, "speaker_id": "Larei"}]

        split_rows = voxcpm_dub_api._split_voxcpm_rows_before_tts(voxcpm_dub_api._normalize_speaker_ids_for_rows(rows))
        merged_text = "".join(str(row.get("text") or "") for row in split_rows)

        self.assertIn("我今天想聊一个可能会让很多创业者不舒服的事实。", merged_text)
        self.assertIn("哈佛创新实验室的导师在课上说了一句话", merged_text)
        self.assertIn("Ideas are everywhere. They're worthless.", merged_text)
        self.assertNotIn("Ideasareeverywhere", merged_text)
        self.assertEqual("".join(str(row.get("text") or "") for row in split_rows), source_text)

    def test_build_voxcpm_translation_rebuild_rows_prefers_complete_sentences(self):
        """翻译前 rebuild 应优先保持完整句，并允许合并相邻短完整句。"""

        source_text = (
            "Ideas are everywhere. They're worthless. 你可能觉得自己有一个关于 X、Y、Z 的超棒想法。"
            "但在它被绑定到一个具体的人、一个具体的痛点之前，它什么都不是。"
            "而公司失败的头号原因，就是它们没有解决一个足够有价值的问题。"
            "今天我想拆解的，是哈佛 i-Lab 教给创业者的一个极其实用的框架：四个 U。"
        )
        rows = [{"start": 0.0, "end": 30.0, "text": source_text, "speaker_id": "Speaker 2"}]

        rebuild_rows = voxcpm_dub_api._build_voxcpm_translation_rebuild_rows(rows)

        self.assertEqual("".join(str(row.get("text") or "") for row in rebuild_rows), source_text)
        self.assertEqual(
            [str(row.get("text") or "") for row in rebuild_rows],
            [
                "Ideas are everywhere. They're worthless. 你可能觉得自己有一个关于 X、Y、Z 的超棒想法。但在它被绑定到一个具体的人、一个具体的痛点之前，它什么都不是。",
                "而公司失败的头号原因，就是它们没有解决一个足够有价值的问题。今天我想拆解的，是哈佛 i-Lab 教给创业者的一个极其实用的框架：四个 U。",
            ],
        )
        self.assertTrue(all(str(row.get("speaker_id") or "").strip() == "Speaker 2" for row in rebuild_rows))

    def test_build_voxcpm_translation_rebuild_rows_keeps_speaker_id_out_of_text(self):
        """翻译前 rebuild 应保留 sidecar speaker_id，但正文不能再带 Speaker 前缀。"""

        rows = [
            {
                "start": 0.0,
                "end": 6.0,
                "text": "Speaker 1：喺做爱嗰阵，一般男人可以顶二分半到六分钟。",
                "speaker_id": "Speaker 1",
            }
        ]

        rebuild_rows = voxcpm_dub_api._build_voxcpm_translation_rebuild_rows(rows)

        self.assertEqual(len(rebuild_rows), 1)
        self.assertEqual(str(rebuild_rows[0].get("speaker_id") or ""), "Speaker 1")
        self.assertEqual(str(rebuild_rows[0].get("text") or ""), "喺做爱嗰阵，一般男人可以顶二分半到六分钟。")

    def test_voxcpm_selected_subtitles_stays_original_while_tts_copy_splits(self):
        """selected_subtitles.srt 必须保留原始选中字字幕，拆分只写入 TTS 工作副本。"""

        task_id = "20260520_000001"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="podcast_original_selected",
            input_media_path=None,
            subtitle_mode="source",
            source_lang="Chinese",
            target_lang="Chinese",
            source_count=1,
            translated_count=0,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            speaker_ids=["Larei"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)

        original_text = (
            "我今天想聊一个可能会让很多创业者不舒服的事实。哈佛创新实验室的导师在课上说了一句话，原话是："
            "\"想法到处都是。应该说是到处都不值钱。\" Ideas are everywhere. They're worthless. "
            "你可能觉得自己有一个关于 X、Y、Z 的超棒想法。但在它被绑定到一个具体的人、一个具体的痛点之前——它什么都不是。"
        )
        source_rows = [{"start": 0.0, "end": 24.0, "text": original_text, "speaker_id": "Larei"}]
        ref_audio = out_root / "preset_larei.wav"
        sf.write(ref_audio, np.zeros(8000, dtype=np.float32), 16000)

        def fake_tts(**kwargs):
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        def fake_soft_align_segment(**kwargs):
            output_path = kwargs["output_path"]
            duration = 1.2
            sf.write(output_path, np.zeros(int(16000 * duration), dtype=np.float32), 16000)
            return {
                "mode": "natural_passthrough",
                "raw_duration_sec": duration,
                "aligned_duration_sec": duration,
                "target_duration_sec": kwargs["target_duration_sec"],
                "trimmed_input": False,
                "trimmed_raw_duration_sec": duration,
                "trimmed_output_duration_sec": duration,
            }

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available"),
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Larei": {
                        "ref_audio": str(ref_audio.resolve()),
                        "ref_text": "Larei 默认文本",
                        "reference_mode": "preset_pool",
                    },
                },
            ),
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "_soft_align_segment", side_effect=fake_soft_align_segment),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=None,
                source_rows=source_rows,
                translated_rows=[],
                subtitle_mode="source",
                source_lang="Chinese",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
            )

        selected_original = voxcpm_dub_api.parse_srt((out_root / "selected_subtitles.srt").read_text(encoding="utf-8"))
        selected_tts = list(json.loads((out_root / "manifest.json").read_text(encoding="utf-8")).get("selected_subtitles_tts_rows") or [])
        self.assertEqual(len(selected_original), 1)
        self.assertEqual(str(selected_original[0]["text"]), original_text)
        self.assertGreater(len(selected_tts), 1)

    def test_voxcpm_tts_unstable_error_retries_with_smaller_chunks(self):
        """VoxCPM 单句返回明确的缩短文本错误时，应自动拆小重试并继续完成任务。"""

        task_id = "20260521_000127"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="unstable_retry",
            input_media_path=None,
            subtitle_mode="source",
            source_lang="Chinese",
            target_lang="Chinese",
            source_count=1,
            translated_count=0,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            speaker_ids=["Speaker 1"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)

        source_rows = [
            {
                "start": 0.0,
                "end": 6.0,
                "text": "第一句真的有点长。第二句也继续补上。",
                "speaker_id": "Speaker 1",
            }
        ]
        ref_audio = out_root / "preset.wav"
        sf.write(ref_audio, np.zeros(8000, dtype=np.float32), 16000)
        call_texts: List[str] = []

        def fake_tts(**kwargs):
            text = str(kwargs["text"])
            call_texts.append(text)
            if text == "第一句真的有点长。第二句也继续补上。":
                raise RuntimeError(
                    'VoxCPM api http 500: {"error":"Generation remained unstable after 3 attempts '
                    '(best ratio=16.00, best duration=2.56s, duration limit=6.00s). Please shorten the text or try again."}'
                )
            wav = io.BytesIO()
            sf.write(wav, np.zeros(8000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available"),
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Speaker 1": {
                        "ref_audio": str(ref_audio.resolve()),
                        "ref_text": "默认参考文本",
                        "reference_mode": "preset_pool",
                    },
                },
            ),
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=None,
                source_rows=source_rows,
                translated_rows=[],
                subtitle_mode="source",
                source_lang="Chinese",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
            )

        self.assertEqual(
            call_texts,
            ["第一句真的有点长。第二句也继续补上。", "第一句真的有点长。", "第二句也继续补上。"],
        )
        self.assertTrue((out_root / "segments" / "segment_0001" / "seg_0001.wav").exists())
        task_payload = voxcpm_dub_api._task_store.get(task_id)
        self.assertEqual(task_payload["status"], "completed")

    def test_voxcpm_run_job_writes_translated_selected_subtitles_separately(self):
        """6 号面板应走 selected -> rebuild -> translated 三段链路，且不污染源真值。"""

        task_id = "20260520_000099"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="podcast_translated_selected",
            input_media_path=None,
            subtitle_mode="source",
            source_lang="Chinese",
            target_lang="Cantonese-Mainland",
            source_count=1,
            translated_count=0,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            speaker_ids=["Larei"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)

        source_text = (
            "Ideas are everywhere. They're worthless. 你可能觉得自己有一个关于 X、Y、Z 的超棒想法。"
            "但在它被绑定到一个具体的人、一个具体的痛点之前，它什么都不是。"
            "而公司失败的头号原因，就是它们没有解决一个足够有价值的问题。"
            "今天我想拆解的，是哈佛 i-Lab 教给创业者的一个极其实用的框架：四个 U。"
        )
        source_rows = [{"start": 0.0, "end": 18.0, "text": source_text, "speaker_id": "Larei"}]
        ref_audio = out_root / "preset_larei.wav"
        sf.write(ref_audio, np.zeros(8000, dtype=np.float32), 16000)

        translated_batches = []

        class _FakeTranslator:
            def __init__(self, *args, **kwargs):
                pass

            def translate_batch(self, subtitles, *args, **kwargs):
                translated_batches.append(list(subtitles))
                return [f"译文第 {index + 1} 句" for index, _ in enumerate(subtitles)]

        def fake_tts(**kwargs):
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        def fake_soft_align_segment(**kwargs):
            output_path = kwargs["output_path"]
            sf.write(output_path, np.zeros(16000, dtype=np.float32), 16000)
            return {
                "mode": "natural_passthrough",
                "raw_duration_sec": 1.0,
                "aligned_duration_sec": 1.0,
                "target_duration_sec": 12.0,
                "trimmed_input": False,
                "trimmed_raw_duration_sec": 1.0,
                "trimmed_output_duration_sec": 1.0,
            }

        with (
            patch.object(voxcpm_dub_api, "Translator", _FakeTranslator),
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available"),
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Larei": {
                        "ref_audio": str(ref_audio.resolve()),
                        "ref_text": "Larei 默认文本",
                        "reference_mode": "preset_pool",
                    },
                },
            ),
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "_soft_align_segment", side_effect=fake_soft_align_segment),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=None,
                source_rows=source_rows,
                translated_rows=[],
                subtitle_mode="source",
                source_lang="Chinese",
                target_lang="Cantonese-Mainland",
                api_key="dummy-key",
                translate_base_url="https://api.example.com",
                translate_model="test-model",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
            )

        selected_original = voxcpm_dub_api.parse_srt((out_root / "selected_subtitles.srt").read_text(encoding="utf-8"))
        selected_rebuild = voxcpm_dub_api.parse_srt((out_root / "selected_subtitles_rebuild.srt").read_text(encoding="utf-8"))
        selected_translated = voxcpm_dub_api.parse_srt((out_root / "selected_subtitles_translated.srt").read_text(encoding="utf-8"))
        manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
        artifact_keys = [item["key"] for item in manifest.get("artifacts") or []]
        self.assertEqual(selected_original[0]["text"], source_text)
        self.assertGreater(len(selected_rebuild), 1)
        self.assertEqual(len(translated_batches), 1)
        self.assertEqual([row["text"] for row in selected_rebuild], translated_batches[0])
        self.assertEqual(
            [row["text"] for row in selected_translated],
            [f"译文第 {index + 1} 句" for index in range(len(selected_rebuild))],
        )
        self.assertIn("selected_srt", artifact_keys)
        self.assertIn("selected_srt_rebuild", artifact_keys)
        self.assertIn("selected_srt_translated", artifact_keys)

    def test_split_voxcpm_long_text_before_tts_keeps_spaces_inside_english_phrases(self):
        """6 号面板前置拆分处理中英混排长句时，不应吃掉英文词间空格。"""

        text = (
            "Ideas are everywhere. They're worthless. 你可能觉得自己有一个关于 X、Y、Z 的超棒想法。"
            "但在它被绑定到一个具体的人、一个具体的痛点之前，它什么都不是。"
        )

        segments = voxcpm_dub_api._split_voxcpm_long_text_before_tts(text)

        self.assertGreater(len(segments), 1)
        merged = "".join(segments)
        self.assertIn("Ideas are everywhere.", merged)
        self.assertIn("They're worthless.", merged)
        self.assertNotIn("Ideasareeverywhere", merged)
        self.assertNotIn("They'reworthless", merged)
        self.assertEqual(merged, text)
        self.assertEqual(
            segments,
            [
                "Ideas are everywhere. They're worthless.",
                " 你可能觉得自己有一个关于 X、Y、Z 的超棒想法。但在它被绑定到一个具体的人、一个具体的痛点之前，它什么都不是。",
            ],
        )

    def test_split_voxcpm_long_text_before_tts_prefers_punctuation_boundaries(self):
        """6 号面板前置拆分不能在完整句内部按软标点或长度硬切。"""

        text = "因为交税无可避免，所以会计行业、QuickBooks、TurboTax全都是从这里衍生出来的。"

        segments = voxcpm_dub_api._split_voxcpm_long_text_before_tts(text)

        self.assertEqual(segments, [text])
        self.assertNotIn("从这", segments)
        self.assertNotIn("里衍生出来的。", segments)

    def test_split_voxcpm_mixed_text_breaks_on_english_period_before_chinese(self):
        """中英混排短句应保持完整句组，避免 TTS API 被拆太碎。"""

        text = "Ideas are everywhere. They're worthless.你可能觉得自己有一个关于X、Y、Z的超棒想法。"

        segments = voxcpm_dub_api._split_voxcpm_long_text_before_tts(text)

        self.assertEqual(segments, [text])

    def test_split_voxcpm_long_text_merges_adjacent_english_sentences_before_chinese(self):
        """连续英文完整句应优先并成一组，避免 `Ideas are everywhere.` / `They're worthless.` 分裂。"""

        text = (
            '我今天想聊一个可能会让很多创业者不舒服的事实。 哈佛创新实验室的导师在课上说了一句话，'
            '原话是："想法到处都是。应该说是到处都不值钱。" Ideas are everywhere. They\'re worthless. '
            '你可能觉得自己有一个关于 X、Y、Z 的超棒想法。但在它被绑定到一个具体的人、一个具体的痛点之前——它什么都不是。'
            ' 而公司失败的头号原因，就是它们没有解决一个足够有价值的问题。 今天我想拆解的，是哈佛 i-Lab 教给创业者的一个极其实用的框架：四个 U。'
        )

        segments = voxcpm_dub_api._split_voxcpm_long_text_before_tts(text)

        self.assertEqual("".join(segments), text)
        self.assertIn('我今天想聊一个可能会让很多创业者不舒服的事实。', segments[0])
        self.assertIn(
            '哈佛创新实验室的导师在课上说了一句话，原话是："想法到处都是。应该说是到处都不值钱。" Ideas are everywhere. They\'re worthless.',
            segments[1],
        )
        self.assertIn("Ideas are everywhere. They're worthless.", segments[1])

    def test_normalize_cantonese_translation_text_keeps_spaces_across_english_boundaries(self):
        """粤语规整后，中英边界应保留可读空格，不能生成 `。Ideas` 或 `.你可能`。"""

        text = (
            "我今日想講一個可能會令好多創業者唔舒服嘅事實。"
            "哈佛創新實驗室嘅導師喺堂上講咗一句話，原話系想法周圍都有。"
            "應該話系周圍都唔值錢。Ideas are everywhere."
            "They’re worthless.你可能覺得自己有一個關於 X、Y、Z 嘅超正想法。"
        )

        normalized = voxcpm_dub_api.normalize_cantonese_translation_text(text, "Cantonese-Mainland")

        self.assertIn("唔值錢。 Ideas are everywhere.", normalized)
        self.assertIn("They’re worthless. 你可能覺得自己", normalized)
        self.assertNotIn("。Ideas", normalized)
        self.assertNotIn(".你可能", normalized)

    def test_split_voxcpm_long_podcast_row_groups_complete_sentences_only(self):
        """播客长字幕行应拆成完整句组，不能把一句话拆到不同 TTS 段。"""

        text = (
            "Ideas are everywhere. They're worthless. 你可能觉得自己有一个关于 X、Y、Z 的超棒想法。"
            "但在它被绑定到一个具体的人、一个具体的痛点之前，它什么都不是。"
            "而公司失败的头号原因，就是它们没有解决一个足够有价值的问题。"
            "今天我想拆解的，是哈佛 i-Lab 教给创业者的一个极其实用的框架：四个 U。"
        )

        segments = voxcpm_dub_api._split_voxcpm_long_text_before_tts(text)

        self.assertEqual("".join(segments), text)
        self.assertEqual(
            segments,
            [
                "Ideas are everywhere. They're worthless. 你可能觉得自己有一个关于 X、Y、Z 的超棒想法。但在它被绑定到一个具体的人、一个具体的痛点之前，它什么都不是。",
                "而公司失败的头号原因，就是它们没有解决一个足够有价值的问题。今天我想拆解的，是哈佛 i-Lab 教给创业者的一个极其实用的框架：四个 U。",
            ],
        )
        self.assertTrue(all("Ideasareeverywhere" not in segment for segment in segments))
        self.assertTrue(all("觉得自己" in segment or "觉得自" not in segment for segment in segments))

    def test_run_voxcpm_job_simplified_variant_converts_cantonese_final_outputs(self):
        """6 号面板粤语切到简体时，final SRT/ASS/视频字幕文本应统一简体输出。"""

        task_id = "20260518_000006_traditional"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="subtitle_only",
            input_media_path=None,
            subtitle_mode="translated",
            source_lang="粤语",
            target_lang="Cantonese",
            source_count=0,
            translated_count=1,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            subtitle_script_variant="traditional",
            speaker_ids=["Speaker 1"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)

        selected_rows = [
            {"start": 0.0, "end": 1.0, "text": "你好，呢個系我嘅聲音音色，很高興為你提供配音服務。", "speaker_id": "Speaker 1"},
        ]

        def fake_tts(**kwargs):
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available"),
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Speaker 1": {
                        "ref_audio": str((out_root / "preset_speaker1.wav").resolve()),
                        "ref_text": "你好，呢個系我嘅聲音音色，很高興為你提供配音服務。",
                        "reference_mode": "preset_pool",
                    }
                },
            ),
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=lambda **kwargs: Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8") or kwargs["output_video_path"]),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=None,
                source_rows=[],
                translated_rows=selected_rows,
                subtitle_mode="translated",
                source_lang="粤语",
                target_lang="Cantonese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
                subtitle_script_variant="simplified",
            )

        final_srt = (out_root / "final" / "dubbed_final_full.srt").read_text(encoding="utf-8")
        final_ass = (out_root / "final" / "dubbed_final_full-styled.ass").read_text(encoding="utf-8")
        self.assertIn("声音", final_srt)
        self.assertIn("服务", final_srt)
        self.assertIn("声音", final_ass)
        manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["subtitle_script_variant"], "simplified")

    def test_build_voxcpm_centered_ass_from_rows_wraps_lines_and_uses_typewriter_dialogues(self):
        """6 号面板 ASS 应自动换行并拆成多段 Dialogue，避免 120 字号时横向超界。"""

        ass_text = voxcpm_dub_api._build_voxcpm_centered_ass_from_rows(
            [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "这是一段很长很长的字幕内容用来验证中间字幕会自动换行而且逐字显示",
                }
            ],
            source_name="demo.srt",
        )

        self.assertIn("Arial Unicode MS,144", ass_text)
        self.assertIn("&H00FFFFFF", ass_text)
        self.assertIn("&H000066FF", ass_text)
        self.assertIn("&HEEFFFF00", ass_text)
        self.assertIn(",4,4,0,5,", ass_text)
        self.assertIn(r"\N", ass_text)
        self.assertGreaterEqual(ass_text.count("Dialogue:"), 2)

    def test_build_voxcpm_centered_ass_from_rows_supports_portrait_layout(self):
        """6 号面板竖屏字幕视频应切换成 1080x1920 画幅与 102 字号。"""

        ass_text = voxcpm_dub_api._build_voxcpm_centered_ass_from_rows(
            [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "text": "呢段字幕要验证 9:16 竖屏时会收窄每行字符数，而且能分成更多行。",
                }
            ],
            source_name="portrait.srt",
            subtitle_video_preset="1080x1920",
        )

        self.assertIn("PlayResX: 1080", ass_text)
        self.assertIn("PlayResY: 1920", ass_text)
        self.assertIn("Arial Unicode MS,102", ass_text)
        dialogue_lines = [line for line in ass_text.splitlines() if line.startswith("Dialogue:")]
        self.assertTrue(dialogue_lines)
        for line in dialogue_lines:
            text = line.rsplit(",,", 1)[-1]
            self.assertLessEqual(text.count(r"\N") + 1, 6)

    def test_build_voxcpm_centered_ass_from_rows_supports_four_three_layout(self):
        """6 号面板 4:3 字幕视频应切换成 1440x1080 画幅与 120 字号。"""

        ass_text = voxcpm_dub_api._build_voxcpm_centered_ass_from_rows(
            [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "text": "这段字幕用来验证 4:3 画幅时的字号和页内行数限制。",
                }
            ],
            source_name="four-three.srt",
            subtitle_video_preset="1440x1080",
        )

        self.assertIn("PlayResX: 1440", ass_text)
        self.assertIn("PlayResY: 1080", ass_text)
        self.assertIn("Arial Unicode MS,120", ass_text)

    def test_build_voxcpm_centered_ass_from_rows_supports_three_four_layout(self):
        """6 号面板 3:4 字幕视频应切换成 1080x1440 画幅与 112 字号。"""

        ass_text = voxcpm_dub_api._build_voxcpm_centered_ass_from_rows(
            [
                {
                    "start": 0.0,
                    "end": 3.0,
                    "text": "这段字幕用来验证 3:4 画幅时的字号和页内行数限制。",
                }
            ],
            source_name="three-four.srt",
            subtitle_video_preset="1080x1440",
        )

        self.assertIn("PlayResX: 1080", ass_text)
        self.assertIn("PlayResY: 1440", ass_text)
        self.assertIn("Arial Unicode MS,112", ass_text)

    def test_build_voxcpm_centered_ass_from_rows_keeps_full_long_subtitle_visible_before_end(self):
        """超长句应分页显示，且最后一页在结尾前完整保留一段时间。"""

        long_text = (
            "我喺過去一年入面見過好幾個男仔，佢哋都同一個太太結咗婚，而佢太太最珍惜嘅，"
            "就系十到十五分鐘真正有節奏、好有力、好深入嘅性交，最後仲要達到高潮。"
        )
        ass_text = voxcpm_dub_api._build_voxcpm_centered_ass_from_rows(
            [
                {
                    "start": 57.359,
                    "end": 69.724,
                    "text": long_text,
                }
            ],
            source_name="demo.srt",
        )

        self.assertIn("最後仲要達到高潮。", ass_text)
        dialogue_lines = [line for line in ass_text.splitlines() if line.startswith("Dialogue:")]
        self.assertTrue(dialogue_lines)
        self.assertTrue(
            dialogue_lines[-1].startswith("Dialogue: 0,0:01:08.52,0:01:09.72,Default,,0,0,0,,"),
        )
        self.assertIn("最後仲要達到高潮。", dialogue_lines[-1])
        for line in dialogue_lines:
            text = line.rsplit(",,", 1)[-1]
            self.assertLessEqual(text.count(r"\N") + 1, 4)

    def test_run_voxcpm_job_passes_selected_video_preset_to_black_video_builder(self):
        """6 号面板完成渲染时，应按所选画幅把宽高传给黑底字幕视频构建器。"""

        task_id = "20260519_000001_layout"
        out_root = self.voxcpm_output_root / f"voxcpm_{task_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        task = voxcpm_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="subtitle_only",
            input_media_path=None,
            subtitle_mode="translated",
            source_lang="English",
            target_lang="Chinese",
            source_count=0,
            translated_count=1,
            out_root=out_root,
            voxcpm_api_url="http://127.0.0.1:7860",
            subtitle_video_preset="1080x1920",
            speaker_ids=["Speaker 1"],
        )
        voxcpm_dub_api._task_store.create(task_id, task)
        selected_rows = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
        ]
        builder_calls = []

        def fake_tts(**kwargs):
            wav = io.BytesIO()
            sf.write(wav, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
            return {"audio_base64": voxcpm_dub_api.base64.b64encode(wav.getvalue()).decode("utf-8")}

        def fake_black_video_builder(**kwargs):
            builder_calls.append(kwargs)
            Path(kwargs["output_video_path"]).write_text("video", encoding="utf-8")
            return kwargs["output_video_path"]

        with (
            patch.object(voxcpm_dub_api, "_ensure_voxcpm_backend_ready", return_value={"status": "ok", "device": "mps"}),
            patch.object(voxcpm_dub_api, "_validate_preset_ref_voices_available"),
            patch.object(
                voxcpm_dub_api,
                "_pick_preset_ref_voices_for_missing_speakers",
                return_value={
                    "Speaker 1": {
                        "ref_audio": str((out_root / "preset_speaker1.wav").resolve()),
                        "ref_text": "你好，这是我的声音音色，很高兴为你提供配音服务。",
                        "reference_mode": "preset_pool",
                    }
                },
            ),
            patch.object(voxcpm_dub_api, "_call_voxcpm_tts", side_effect=fake_tts),
            patch.object(voxcpm_dub_api, "build_black_video_with_ass_subtitles", side_effect=fake_black_video_builder),
        ):
            voxcpm_dub_api._run_voxcpm_job(
                task_id=task_id,
                input_media_path=None,
                source_rows=[],
                translated_rows=selected_rows,
                subtitle_mode="translated",
                source_lang="English",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                ref_audio_path=None,
                ref_text="",
                voxcpm_api_url="http://127.0.0.1:7860",
                cfg_value=2.0,
                inference_timesteps=10,
                subtitle_video_preset="1080x1920",
            )

        self.assertEqual(len(builder_calls), 1)
        self.assertEqual(builder_calls[0]["width"], 1080)
        self.assertEqual(builder_calls[0]["height"], 1920)
        manifest = json.loads((out_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["subtitle_video_preset"], "1080x1920")

    def test_build_styled_ass_from_rows_uses_fixed_template_and_dialogue_format(self):
        """5号面板 styled ASS 应使用固定样式模板，并输出标准 Dialogue 行。"""

        input_rows = [
            {"start": 1.36, "end": 3.57, "text": "你可能见过一些机器学习模型，", "speaker_id": "Speaker 1"},
        ]

        ass_text = omnivoice_dub_api._build_styled_ass_from_rows(
            input_rows,
            source_name="What-Are-Word-Embeddings.srt",
        )
        self.assertIn("; Converted from What-Are-Word-Embeddings.srt", ass_text)
        self.assertIn("PlayResX: 1920", ass_text)
        self.assertIn("PlayResY: 1080", ass_text)
        self.assertIn(
            "Style: Default,PingFang SC,80,&H00FFFFFF,&H000000FF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,4,0,0,2,80,80,80,1",
            ass_text,
        )
        self.assertIn(
            "Dialogue: 0,0:00:01.36,0:00:03.57,Default,,0,0,0,,你可能见过一些机器学习模型，",
            ass_text,
        )

    def test_omnivoice_selected_text_normalizer_splits_stuck_english_tokens(self):
        """中英混排字幕应拆开粘连英文词，避免 ClaudeCode 这类连写。"""

        normalized = omnivoice_dub_api._normalize_omnivoice_selected_text(
            "第三个最近，ClaudeCodeOPUS四点五，现在四点七。"
        )
        self.assertIn("Claude Code OPUS", normalized)
        self.assertIn("四点五", normalized)

    def test_omnivoice_merge_selected_fragment_rows_merges_short_broken_pairs(self):
        """同 speaker 的短残句应回并，避免 selected 字幕出现半句碎片。"""

        rows = [
            {"start": 12.200, "end": 12.450, "text": "这些项目一夜之间就在", "speaker_id": "Speaker 2"},
            {"start": 12.450, "end": 12.700, "text": "GitHub上爆红，它们的", "speaker_id": "Speaker 2"},
            {"start": 12.700, "end": 13.500, "text": "做法是把GPT三接上几个工", "speaker_id": "Speaker 2"},
        ]

        merged = omnivoice_dub_api._merge_selected_fragment_rows(rows)
        self.assertLess(len(merged), len(rows))
        self.assertIn("Git Hub", merged[0]["text"])

    def test_omnivoice_selected_rows_keeps_speaker_boundaries_in_multi_mode(self):
        """5号链路 selected 后处理应保留 speaker 边界，不得跨 speaker 合并。"""

        rows = [
            {"start": 0.0, "end": 0.3, "text": "这是", "speaker_id": "Speaker 1"},
            {"start": 0.3, "end": 0.7, "text": "第一段。", "speaker_id": "Speaker 1"},
            {"start": 0.72, "end": 1.1, "text": "谢谢你", "speaker_id": "Speaker 2"},
            {"start": 1.1, "end": 1.4, "text": "Pat。", "speaker_id": "Speaker 2"},
        ]

        output = omnivoice_dub_api._optimize_omnivoice_selected_rows(rows)
        speaker_seq = [str(item.get("speaker_id") or "").strip() for item in output]
        self.assertIn("Speaker 1", speaker_seq)
        self.assertIn("Speaker 2", speaker_seq)
        # 不能把首段和次段拼成同一说话人
        self.assertEqual(speaker_seq[0], "Speaker 1")
        self.assertTrue(any(spk == "Speaker 2" for spk in speaker_seq[1:]))

    def test_omnivoice_source_mode_keeps_original_cue_boundaries_for_continuation_lines(self):
        """5号链路 source 直通时，不得把连续英文 cue 压成只剩半句的长窗。"""

        rows = [
            {"start": 734.0, "end": 735.36, "text": "Which is right for Google?", "speaker_id": "Speaker 1"},
            {"start": 735.36, "end": 738.16, "text": "Is it uh you know is there is there some model that", "speaker_id": "Speaker 1"},
            {"start": 738.16, "end": 741.6, "text": "is just too good and and you're gonna hold it back or", "speaker_id": "Speaker 1"},
            {"start": 741.6, "end": 746.96, "text": "is the more iterative deployment strategy that OpenAI takes more aligned with", "speaker_id": "Speaker 1"},
        ]

        source_rows = omnivoice_dub_api._optimize_omnivoice_source_rows(rows, subtitle_mode="source")
        selected_rows = omnivoice_dub_api._optimize_omnivoice_selected_rows(source_rows, subtitle_mode="source")

        self.assertEqual(len(source_rows), 4)
        self.assertEqual(len(selected_rows), 4)
        self.assertEqual(source_rows[0]["text"], "Which is right for Google?")
        self.assertEqual(source_rows[1]["text"], "Is it uh you know is there is there some model that")
        self.assertEqual(source_rows[2]["text"], "is just too good and and you're gonna hold it back or")
        self.assertIn("iterative deployment strategy", source_rows[3]["text"])
        self.assertIn("takes more aligned with", source_rows[3]["text"])
        self.assertEqual([row["text"] for row in selected_rows], [row["text"] for row in source_rows])

    def test_omnivoice_source_mode_does_not_swallow_short_followup_rows(self):
        """5号链路 source 直通时，短尾 cue 不能被错误压成残句或吞进后文。"""

        rows = [
            {"start": 16.4, "end": 19.28, "text": "I'm the CEO of Ford Future. And", "speaker_id": "Speaker 1"},
            {"start": 21.52, "end": 22.16, "text": "today", "speaker_id": "Speaker 1"},
            {
                "start": 22.16,
                "end": 27.2,
                "text": "I am super excited to share a conversation with the man who has been leading Google for the last 10 years, please welcome",
                "speaker_id": "Speaker 1",
            },
            {"start": 27.2, "end": 28.1, "text": "Sundar Pichai.", "speaker_id": "Speaker 1"},
        ]

        source_rows = omnivoice_dub_api._optimize_omnivoice_source_rows(rows, subtitle_mode="source")
        selected_rows = omnivoice_dub_api._optimize_omnivoice_selected_rows(source_rows, subtitle_mode="source")

        self.assertEqual(len(source_rows), 4)
        self.assertEqual(source_rows[1]["text"], "today")
        self.assertTrue(source_rows[2]["text"].startswith("I am super excited"))
        self.assertEqual(source_rows[3]["text"], "Sundar Pichai.")
        self.assertEqual([row["text"] for row in selected_rows], [row["text"] for row in source_rows])

    def test_ensure_speaker_ids_prefers_time_overlap_when_row_count_changes(self):
        """speaker 回填应优先按时间重叠，而不是固定索引，避免跨 speaker 错贴。"""

        rows = [
            {"start": 0.0, "end": 1.0, "text": "a", "speaker_id": ""},
            {"start": 1.0, "end": 2.0, "text": "b", "speaker_id": ""},
            {"start": 2.0, "end": 3.0, "text": "c", "speaker_id": ""},
            {"start": 3.0, "end": 4.0, "text": "d", "speaker_id": ""},
        ]
        fallback_rows = [
            {"start": 0.0, "end": 1.0, "text": "x1", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "x2", "speaker_id": "Speaker 1"},
            {"start": 2.0, "end": 3.0, "text": "x3", "speaker_id": "Speaker 2"},
            {"start": 3.0, "end": 4.0, "text": "x4", "speaker_id": "Speaker 2"},
            {"start": 4.0, "end": 5.0, "text": "x5", "speaker_id": "Speaker 3"},
            {"start": 5.0, "end": 6.0, "text": "x6", "speaker_id": "Speaker 3"},
        ]

        output = omnivoice_dub_api._ensure_speaker_ids(rows, fallback_rows=fallback_rows)
        self.assertEqual([item["speaker_id"] for item in output], ["Speaker 1", "Speaker 1", "Speaker 2", "Speaker 2"])

    def test_ensure_speaker_ids_uses_nearest_fallback_when_no_overlap(self):
        """当没有时间重叠时，应取最近的 fallback speaker，避免默认回到 Speaker 1。"""

        rows = [
            {"start": 11.0, "end": 12.0, "text": "tail", "speaker_id": ""},
        ]
        fallback_rows = [
            {"start": 0.0, "end": 4.0, "text": "a", "speaker_id": "Speaker 1"},
            {"start": 4.0, "end": 8.0, "text": "b", "speaker_id": "Speaker 2"},
            {"start": 8.0, "end": 10.0, "text": "c", "speaker_id": "Speaker 3"},
        ]

        output = omnivoice_dub_api._ensure_speaker_ids(rows, fallback_rows=fallback_rows)
        self.assertEqual(output[0]["speaker_id"], "Speaker 3")

    def test_ensure_speaker_ids_defaults_first_blank_row_to_speaker_1(self):
        """首行缺失 speaker 且没有可对齐来源时，应最终回退到 Speaker 1。"""

        rows = [
            {"start": 0.0, "end": 1.0, "text": "hello", "speaker_id": ""},
        ]

        output = omnivoice_dub_api._ensure_speaker_ids(rows, fallback_rows=[])
        self.assertEqual(output[0]["speaker_id"], "Speaker 1")

    def test_ensure_speaker_ids_prefers_previous_row_before_speaker_1(self):
        """中间缺失 speaker 且没有可对齐来源时，应优先继承上一行 speaker。"""

        rows = [
            {"start": 0.0, "end": 1.0, "text": "a", "speaker_id": "Speaker 2"},
            {"start": 1.0, "end": 2.0, "text": "b", "speaker_id": ""},
            {"start": 2.0, "end": 3.0, "text": "c", "speaker_id": ""},
        ]

        output = omnivoice_dub_api._ensure_speaker_ids(rows, fallback_rows=[])
        self.assertEqual([item["speaker_id"] for item in output], ["Speaker 2", "Speaker 2", "Speaker 2"])

    def test_ensure_speaker_ids_force_align_by_time_overrides_wrong_tag(self):
        """强制按时间对齐时，应覆盖已有但错误的 speaker 标签。"""

        rows = [
            {"start": 0.0, "end": 1.0, "text": "hello", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "world", "speaker_id": "Speaker 1"},
        ]
        fallback_rows = [
            {"start": 0.0, "end": 1.0, "text": "a", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "b", "speaker_id": "Speaker 2"},
        ]

        output = omnivoice_dub_api._ensure_speaker_ids(
            rows,
            fallback_rows=fallback_rows,
            force_align_by_time=True,
        )
        self.assertEqual(output[0]["speaker_id"], "Speaker 1")
        self.assertEqual(output[1]["speaker_id"], "Speaker 2")

    def test_prepare_omnivoice_subtitles_from_project_writes_speaker_copy_artifact(self):
        """prepare-subtitles-from-project 应同时落盘带 speaker 前缀的 selected 字幕副本。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        class _FakeTranslator:
            def __init__(self, *args, **kwargs):
                pass

            def translate_batch(self, subtitles, *args, **kwargs):
                return [f"中文:{text}" for text in subtitles]

        with patch.object(omnivoice_dub_api, "Translator", _FakeTranslator), patch.object(
            omnivoice_dub_api,
            "resolve_translation_api_key",
            return_value="dummy-key",
        ):
            response = self.client.post(
                "/omnivoice/auto/prepare-subtitles-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "source_subtitles_json": json.dumps(
                        [
                            {"start": 0.0, "end": 1.0, "text": "hello", "speaker_id": "Speaker 1"},
                            {"start": 1.0, "end": 2.0, "text": "world", "speaker_id": "Speaker 2"},
                        ],
                        ensure_ascii=False,
                    ),
                    "subtitle_mode": "source",
                    "target_lang": "Chinese",
                    "api_key": "dummy-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        artifact_keys = {item["key"] for item in payload.get("artifacts") or []}
        self.assertIn("selected_srt_with_speaker", artifact_keys)
        manifest_path = self.omnivoice_output_root / f"omnivoice_{payload['task_id']}" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        speaker_copy_path = Path(manifest["paths"]["selected_subtitles_with_speakers"])
        self.assertTrue(speaker_copy_path.exists())
        speaker_copy_text = speaker_copy_path.read_text(encoding="utf-8")
        self.assertIn("[Speaker 1]", speaker_copy_text)
        self.assertIn("[Speaker 2]", speaker_copy_text)

    def test_build_manifest_includes_styled_ass_artifact_and_path(self):
        """5号面板最终 manifest 应暴露 styled ASS 路径与 artifact。"""

        out_root = self.omnivoice_output_root / "omnivoice_demo"
        final_dir = out_root / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        source_audio = out_root / "source.wav"
        source_vocals = out_root / "source_vocals.wav"
        source_bgm = out_root / "source_bgm.wav"
        speaker_ref_map = out_root / "speaker_ref_map.json"
        selected_srt = out_root / "selected_subtitles.srt"
        selected_with_speaker = out_root / "selected_subtitles_with_speakers.srt"
        final_srt = final_dir / "dubbed_final_full.srt"
        final_ass = final_dir / "dubbed_final_full-styled.ass"
        final_vocals = final_dir / "dubbed_vocals_full.wav"
        final_mix = final_dir / "dubbed_mix_full.wav"
        final_video = final_dir / "dubbed_video_full.mp4"
        final_video_burned = final_dir / "dubbed_video_full_burned.mp4"
        separation_report = out_root / "separation_report.json"
        speaker_reference_dir = out_root / "speaker_refs"
        speaker_reference_dir.mkdir(parents=True, exist_ok=True)

        for path in [
            source_audio,
            source_vocals,
            source_bgm,
            speaker_ref_map,
            selected_srt,
            selected_with_speaker,
            final_srt,
            final_ass,
            final_vocals,
            final_mix,
            final_video,
            final_video_burned,
            separation_report,
        ]:
            path.write_text("x", encoding="utf-8")

        task = omnivoice_dub_api._create_task_payload(
            task_id="20260515_123456",
            project_filename="demo.mp4",
            input_media_path=source_audio,
            subtitle_mode="translated",
            source_lang="English",
            target_lang="Chinese",
            source_count=1,
            translated_count=1,
            speaker_ids=["Speaker 1"],
            out_root=out_root,
        )
        task["status"] = "completed"
        task["stage"] = "completed"
        task["progress"] = 100.0

        manifest = omnivoice_dub_api._build_manifest(
            task=task,
            out_root=out_root,
            source_audio_path=source_audio,
            source_vocals_path=source_vocals,
            source_bgm_path=source_bgm,
            speaker_ref_map_path=speaker_ref_map,
            final_srt_path=final_srt,
            final_vocals_path=final_vocals,
            final_mix_path=final_mix,
            final_video_path=final_video,
            separated_video_audio_path=None,
            separation_report_path=separation_report,
            speaker_reference_dir=speaker_reference_dir,
            subtitles_path=selected_srt,
            subtitles_with_speaker_path=selected_with_speaker,
            final_ass_path=final_ass,
            burned_video_path=final_video_burned,
        )

        artifact_keys = {item["key"] for item in manifest.get("artifacts") or []}
        self.assertIn("ass", artifact_keys)
        self.assertIn("video_burned", artifact_keys)
        self.assertEqual(manifest["paths"]["dubbed_final_ass"], str(final_ass.resolve()))
        self.assertEqual(manifest["paths"]["dubbed_video_burned"], str(final_video_burned.resolve()))
        artifact_order = [item["key"] for item in manifest.get("artifacts") or []]
        self.assertLess(artifact_order.index("video_burned"), artifact_order.index("video"))
        self.assertEqual(manifest["source_lang"], "English")
        self.assertEqual(manifest["source_lang_runtime"], "English")
        self.assertEqual(manifest["target_lang"], "Chinese")
        self.assertEqual(manifest["target_lang_runtime"], "zh")

        recreated = omnivoice_dub_api._create_task_from_manifest(manifest)
        self.assertEqual(recreated["source_lang"], "English")
        self.assertEqual(recreated["source_lang_runtime"], "English")
        self.assertEqual(recreated["target_lang"], "Chinese")
        self.assertEqual(recreated["target_lang_runtime"], "zh")

    def test_burn_ass_subtitles_into_video_uses_expected_ffmpeg_args(self):
        """ASS 烧录视频应使用 `ass=` filter、libx264 和固定画质参数。"""

        input_video = self.tmpdir / "input.mp4"
        subtitle_ass = self.tmpdir / "subtitles.ass"
        output_video = self.tmpdir / "output.mp4"
        input_video.write_text("video", encoding="utf-8")
        subtitle_ass.write_text("ass", encoding="utf-8")

        seen = {}

        def _fake_run_cmd(cmd, cwd=None):
            seen["cmd"] = list(cmd)
            output_video.write_text("burned", encoding="utf-8")
            return 0, "", ""

        with patch.object(media_compose, "run_cmd", side_effect=_fake_run_cmd):
            result = media_compose.burn_ass_subtitles_into_video(
                input_video_path=input_video,
                ass_subtitle_path=subtitle_ass,
                output_video_path=output_video,
                video_codec="libx264",
                crf=16,
                preset="slow",
            )

        self.assertEqual(result, output_video)
        cmd = seen["cmd"]
        self.assertIn("-vf", cmd)
        vf_value = cmd[cmd.index("-vf") + 1]
        self.assertIn("ass='", vf_value)
        self.assertIn(str(subtitle_ass.resolve()).replace(":", r"\:"), vf_value)
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "libx264")
        self.assertEqual(cmd[cmd.index("-crf") + 1], "16")
        self.assertEqual(cmd[cmd.index("-preset") + 1], "slow")
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "copy")

    def test_build_black_video_with_ass_subtitles_uses_black_canvas_and_ass_filter(self):
        """黑底字幕视频应使用 color 黑底输入，并把 ASS 烧到中间字幕画面上。"""

        audio_path = self.tmpdir / "input.wav"
        subtitle_ass = self.tmpdir / "subtitles.ass"
        output_video = self.tmpdir / "black.mp4"
        sf.write(audio_path, np.zeros(16000, dtype=np.float32), 16000)
        subtitle_ass.write_text("ass", encoding="utf-8")

        seen = {}

        def _fake_run_cmd(cmd, cwd=None):
            seen["cmd"] = list(cmd)
            output_video.write_text("black-video", encoding="utf-8")
            return 0, "", ""

        with (
            patch.object(media_compose, "run_cmd", side_effect=_fake_run_cmd),
            patch.object(media_compose, "probe_ffprobe_duration", return_value=1.0),
        ):
            result = media_compose.build_black_video_with_ass_subtitles(
                audio_path=audio_path,
                ass_subtitle_path=subtitle_ass,
                output_video_path=output_video,
            )

        self.assertEqual(result, output_video)
        cmd = seen["cmd"]
        self.assertIn("lavfi", cmd)
        self.assertIn("color=c=black:s=1920x1080:r=24:d=1.000000", cmd)
        self.assertIn("-vf", cmd)
        self.assertIn("ass='", cmd[cmd.index("-vf") + 1])
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "libx264")
        self.assertEqual(cmd[cmd.index("-c:a") + 1], "aac")

    def test_prepare_omnivoice_source_stems_falls_back_to_vocals_only_when_demucs_fails(self):
        """5号面板预分离双失败时，应退化为 vocals-only，而不是整任务报错。"""

        out_root = self.omnivoice_output_root / "omnivoice_fallback"
        stems_root = out_root / "stems"
        stems_root.mkdir(parents=True, exist_ok=True)
        input_media = self.tmpdir / "demo.mp4"
        input_media.write_text("video", encoding="utf-8")
        source_audio = stems_root / "source_audio.wav"
        source_vocals = stems_root / "full_source_vocals.wav"
        source_bgm = stems_root / "full_source_bgm.wav"
        separation_report = out_root / "separation_report.json"
        demucs_out = stems_root / "demucs_tmp"

        def _fake_extract_source_audio(*, input_media, output_wav):
            del input_media
            output_wav.write_text("fake-audio", encoding="utf-8")

        with patch.object(
            omnivoice_dub_api,
            "_resolve_omnivoice_separator_device",
            return_value="auto",
        ), patch.object(
            omnivoice_dub_api,
            "extract_source_audio",
            side_effect=_fake_extract_source_audio,
        ), patch.object(
            omnivoice_dub_api,
            "run_cmd",
            side_effect=[
                (1, "", "primary demucs failed"),
                (1, "", "fallback demucs failed"),
            ],
        ):
            result = omnivoice_dub_api._prepare_omnivoice_source_stems(
                input_media_path=input_media,
                source_audio_path=source_audio,
                source_vocals_path=source_vocals,
                source_bgm_path=source_bgm,
                separation_report_path=separation_report,
                demucs_out=demucs_out,
            )

        self.assertTrue(source_audio.exists())
        self.assertTrue(source_vocals.exists())
        self.assertEqual(source_vocals.read_text(encoding="utf-8"), "fake-audio")
        self.assertFalse(source_bgm.exists())
        self.assertTrue(result["degraded_to_vocals_only"])
        self.assertFalse(result["has_bgm_track"])

        report = json.loads(separation_report.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "failed_fallback_vocals_only")
        self.assertFalse(report["has_bgm_track"])
        self.assertEqual(len(report["attempts"]), 2)
        self.assertEqual(report["attempts"][0]["model"], "htdemucs")
        self.assertEqual(report["attempts"][1]["model"], "mdx_extra_q")

    def test_build_omnivoice_chunk_ranges_splits_only_when_over_threshold(self):
        """智能切块会在 40 分钟附近保持整体块长均衡。"""

        ranges = omnivoice_dub_api._build_omnivoice_chunk_ranges(
            total_duration_sec=7800.0,
            chunk_duration_sec=2400.0,
        )

        self.assertEqual(
            ranges,
            [
                (0.0, 2600.0),
                (2600.0, 5200.0),
                (5200.0, 7800.0),
            ],
        )

    def test_build_omnivoice_chunk_plan_prefers_silence_and_snaps_to_subtitle_boundary(self):
        """智能切点应优先落在静音区，并尽量吸附到附近字幕边界。"""

        source_audio = self.tmpdir / "adaptive_source.wav"
        sample_rate = 100
        audio = np.full(sample_rate * 120, 0.3, dtype=np.float32)
        audio[int(41.7 * sample_rate) : int(42.3 * sample_rate)] = 0.0
        audio[int(81.7 * sample_rate) : int(82.3 * sample_rate)] = 0.0
        sf.write(str(source_audio), audio, sample_rate)

        subtitles = [
            {"start": 40.0, "end": 42.0, "text": "A", "speaker_id": "Speaker 1"},
            {"start": 42.0, "end": 43.0, "text": "B", "speaker_id": "Speaker 2"},
            {"start": 80.0, "end": 82.0, "text": "C", "speaker_id": "Speaker 2"},
            {"start": 82.0, "end": 83.0, "text": "D", "speaker_id": "Speaker 1"},
        ]

        plan = omnivoice_dub_api._build_omnivoice_chunk_plan(
            total_duration_sec=120.0,
            source_audio_path=source_audio,
            subtitle_hints=subtitles,
            chunk_duration_sec=40.0,
            min_chunk_duration_sec=30.0,
            max_chunk_duration_sec=50.0,
            search_window_sec=3.0,
        )

        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[0]["end_sec"], 42.0)
        self.assertEqual(plan[0]["split_reason"], "silence")
        self.assertTrue(plan[0]["snapped_to_boundary"])
        self.assertTrue(plan[0]["snapped_to_speaker_change"])
        self.assertEqual(plan[1]["end_sec"], 82.0)
        self.assertEqual(plan[1]["split_reason"], "silence")
        self.assertEqual(plan[2]["split_reason"], "tail")

    def test_prepare_omnivoice_source_stems_dispatches_to_chunked_for_long_video(self):
        """超过 90 分钟时，5号面板应切到 chunked separation。"""

        out_root = self.omnivoice_output_root / "omnivoice_dispatch_long"
        stems_root = out_root / "stems"
        stems_root.mkdir(parents=True, exist_ok=True)
        input_media = self.tmpdir / "long.mp4"
        input_media.write_text("video", encoding="utf-8")
        source_audio = stems_root / "source_audio.wav"
        source_vocals = stems_root / "full_source_vocals.wav"
        source_bgm = stems_root / "full_source_bgm.wav"
        separation_report = out_root / "separation_report.json"
        demucs_out = stems_root / "demucs_tmp"

        def _fake_extract_source_audio(*, input_media, output_wav):
            del input_media
            output_wav.write_text("fake-audio", encoding="utf-8")

        with patch.object(
            omnivoice_dub_api,
            "extract_source_audio",
            side_effect=_fake_extract_source_audio,
        ), patch.object(
            omnivoice_dub_api,
            "_resolve_omnivoice_separator_device",
            return_value="auto",
        ), patch.object(
            omnivoice_dub_api,
            "ffprobe_duration",
            return_value=5400.1,
        ), patch.object(
            omnivoice_dub_api,
            "_prepare_omnivoice_source_stems_chunked",
            return_value={"mode": "chunked", "has_bgm_track": False, "degraded_to_vocals_only": False},
        ) as chunked_mock, patch.object(
            omnivoice_dub_api,
            "_prepare_omnivoice_source_stems_single_pass",
        ) as single_mock:
            result = omnivoice_dub_api._prepare_omnivoice_source_stems(
                input_media_path=input_media,
                source_audio_path=source_audio,
                source_vocals_path=source_vocals,
                source_bgm_path=source_bgm,
                separation_report_path=separation_report,
                demucs_out=demucs_out,
            )

        self.assertEqual(result["mode"], "chunked")
        self.assertTrue(chunked_mock.called)
        self.assertFalse(single_mock.called)

    def test_prepare_omnivoice_source_stems_keeps_single_pass_at_90_minutes(self):
        """90 分钟及以下视频应继续走旧的整段 separation。"""

        out_root = self.omnivoice_output_root / "omnivoice_dispatch_short"
        stems_root = out_root / "stems"
        stems_root.mkdir(parents=True, exist_ok=True)
        input_media = self.tmpdir / "short.mp4"
        input_media.write_text("video", encoding="utf-8")
        source_audio = stems_root / "source_audio.wav"
        source_vocals = stems_root / "full_source_vocals.wav"
        source_bgm = stems_root / "full_source_bgm.wav"
        separation_report = out_root / "separation_report.json"
        demucs_out = stems_root / "demucs_tmp"

        def _fake_extract_source_audio(*, input_media, output_wav):
            del input_media
            output_wav.write_text("fake-audio", encoding="utf-8")

        with patch.object(
            omnivoice_dub_api,
            "extract_source_audio",
            side_effect=_fake_extract_source_audio,
        ), patch.object(
            omnivoice_dub_api,
            "_resolve_omnivoice_separator_device",
            return_value="auto",
        ), patch.object(
            omnivoice_dub_api,
            "ffprobe_duration",
            return_value=5400.0,
        ), patch.object(
            omnivoice_dub_api,
            "_prepare_omnivoice_source_stems_chunked",
        ) as chunked_mock, patch.object(
            omnivoice_dub_api,
            "_prepare_omnivoice_source_stems_single_pass",
            return_value={"has_bgm_track": False, "degraded_to_vocals_only": False},
        ) as single_mock:
            result = omnivoice_dub_api._prepare_omnivoice_source_stems(
                input_media_path=input_media,
                source_audio_path=source_audio,
                source_vocals_path=source_vocals,
                source_bgm_path=source_bgm,
                separation_report_path=separation_report,
                demucs_out=demucs_out,
            )

        self.assertFalse(chunked_mock.called)
        self.assertTrue(single_mock.called)
        self.assertFalse(result["degraded_to_vocals_only"])

    def test_prepare_omnivoice_source_stems_chunked_degrades_only_failed_chunk(self):
        """chunked separation 中单个分块双失败时，应只降级该块而不是整条失败。"""

        out_root = self.omnivoice_output_root / "omnivoice_chunked"
        stems_root = out_root / "stems"
        stems_root.mkdir(parents=True, exist_ok=True)
        input_media = self.tmpdir / "long.mp4"
        input_media.write_text("video", encoding="utf-8")
        source_audio = stems_root / "source_audio.wav"
        source_audio.write_text("source-audio", encoding="utf-8")
        source_vocals = stems_root / "full_source_vocals.wav"
        source_bgm = stems_root / "full_source_bgm.wav"
        separation_report = out_root / "separation_report.json"
        demucs_out = stems_root / "demucs_tmp"

        def _fake_extract_chunk(*, input_media_path, output_wav, start_sec, end_sec):
            del input_media_path
            output_wav.write_text(f"{start_sec:.1f}-{end_sec:.1f}", encoding="utf-8")
            return output_wav

        attempt_results = [
            {
                "separator_device": "auto",
                "attempts": [{"model": "htdemucs", "ok": True, "error": ""}],
                "vocals_src": self.tmpdir / "chunk1_vocals.wav",
                "bgm_src": self.tmpdir / "chunk1_bgm.wav",
            },
            {
                "separator_device": "auto",
                "attempts": [
                    {"model": "htdemucs", "ok": False, "error": "primary failed"},
                    {"model": "mdx_extra_q", "ok": False, "error": "fallback failed"},
                ],
                "vocals_src": None,
                "bgm_src": None,
            },
        ]
        attempt_results[0]["vocals_src"].write_text("vocals-1", encoding="utf-8")
        attempt_results[0]["bgm_src"].write_text("bgm-1", encoding="utf-8")

        composed_outputs = []

        def _fake_compose_vocals_master(*, segments, output_path, source_audio_fallback=None):
            composed_outputs.append(
                {
                    "segments": [dict(item) for item in segments],
                    "output_path": output_path,
                    "source_audio_fallback": source_audio_fallback,
                }
            )
            output_path.write_text("composed", encoding="utf-8")
            return output_path, 44100

        with patch.object(
            omnivoice_dub_api,
            "_build_omnivoice_chunk_ranges",
            return_value=[(0.0, 1200.0), (1200.0, 2400.0)],
        ), patch.object(
            omnivoice_dub_api,
            "_build_omnivoice_chunk_plan",
            return_value=[
                {
                    "start_sec": 0.0,
                    "end_sec": 1200.0,
                    "target_end_sec": 1200.0,
                    "split_reason": "fallback_fixed",
                    "snapped_to_boundary": False,
                    "snapped_to_speaker_change": False,
                },
                {
                    "start_sec": 1200.0,
                    "end_sec": 2400.0,
                    "target_end_sec": 2400.0,
                    "split_reason": "tail",
                    "snapped_to_boundary": False,
                    "snapped_to_speaker_change": False,
                },
            ],
        ), patch.object(
            omnivoice_dub_api,
            "_extract_omnivoice_audio_segment",
            side_effect=_fake_extract_chunk,
        ), patch.object(
            omnivoice_dub_api,
            "_attempt_omnivoice_demucs_separation",
            side_effect=attempt_results,
        ), patch.object(
            omnivoice_dub_api,
            "compose_vocals_master",
            side_effect=_fake_compose_vocals_master,
        ):
            result = omnivoice_dub_api._prepare_omnivoice_source_stems_chunked(
                input_media_path=input_media,
                source_audio_path=source_audio,
                source_vocals_path=source_vocals,
                source_bgm_path=source_bgm,
                separation_report_path=separation_report,
                demucs_out=demucs_out,
                separator_device="auto",
                total_duration_sec=2400.0,
            )

        self.assertTrue(source_vocals.exists())
        self.assertFalse(source_bgm.exists())
        self.assertEqual(len(composed_outputs), 1)
        self.assertEqual(len(composed_outputs[0]["segments"]), 2)
        self.assertEqual(result["mode"], "chunked")
        self.assertFalse(result["has_bgm_track"])
        self.assertTrue(result["degraded_to_vocals_only"])

        report = json.loads(separation_report.read_text(encoding="utf-8"))
        self.assertEqual(report["mode"], "chunked")
        self.assertEqual(report["status"], "partial_fallback_vocals_only")
        self.assertEqual(len(report["ranges"]), 2)
        self.assertEqual(report["ranges"][0]["status"], "ok")
        self.assertEqual(report["ranges"][0]["split_reason"], "fallback_fixed")
        self.assertEqual(report["ranges"][1]["status"], "failed_fallback_vocals_only")
        self.assertEqual(report["ranges"][1]["split_reason"], "tail")
        self.assertFalse(report["has_bgm_track"])

    def test_prepare_omnivoice_source_stems_passthrough_uses_source_audio_as_vocals(self):
        """手动关闭分离时，应直接复用 source_audio.wav 作为人声轨。"""

        out_root = self.omnivoice_output_root / "omnivoice_passthrough"
        stems_root = out_root / "stems"
        stems_root.mkdir(parents=True, exist_ok=True)
        source_audio = stems_root / "source_audio.wav"
        source_audio.write_text("source-audio", encoding="utf-8")
        source_vocals = stems_root / "full_source_vocals.wav"
        source_bgm = stems_root / "full_source_bgm.wav"
        source_bgm.write_text("stale-bgm", encoding="utf-8")
        separation_report = out_root / "separation_report.json"

        result = omnivoice_dub_api._prepare_omnivoice_source_stems_passthrough(
            source_audio_path=source_audio,
            source_vocals_path=source_vocals,
            source_bgm_path=source_bgm,
            separation_report_path=separation_report,
        )

        self.assertTrue(source_vocals.exists())
        self.assertEqual(source_vocals.read_text(encoding="utf-8"), "source-audio")
        self.assertFalse(source_bgm.exists())
        self.assertEqual(result["mode"], "passthrough")
        self.assertFalse(result["has_bgm_track"])
        report = json.loads(separation_report.read_text(encoding="utf-8"))
        self.assertEqual(report["mode"], "passthrough")
        self.assertEqual(report["status"], "skipped_passthrough_vocals_only")
        self.assertFalse(report["has_bgm_track"])

    def test_translate_subtitles_if_needed_restores_empty_rows_from_source_for_omnivoice(self):
        """5 号链路翻译空行应回退 source 文本，避免行数缩水导致后续失配。"""

        source_rows = [
            {"start": 0.0, "end": 1.0, "text": "Hello one", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "Hello two", "speaker_id": "Speaker 1"},
        ]

        class _FakeTranslator:
            def __init__(self, *args, **kwargs):
                pass

            def translate_batch(self, *args, **kwargs):
                return ["你好一", ""]

        with patch.object(omnivoice_dub_api, "Translator", _FakeTranslator), patch.object(
            omnivoice_dub_api,
            "resolve_translation_api_key",
            return_value="dummy-key",
        ):
            rows, mode = omnivoice_dub_api._translate_subtitles_if_needed(
                subtitles_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="English",
                target_lang="中文",
                api_key="",
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                translate_system_prompt="",
                task_id="unit_test",
            )

        self.assertEqual(mode, "translated")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["text"], "你好一")
        self.assertEqual(rows[1]["text"], "Hello two")

    def test_translate_subtitles_if_needed_retries_latin_dominant_rows_for_chinese_target(self):
        """5 号链路遇到英文主导漏译行时，应做二次翻译并替换为中文。"""

        source_rows = [
            {"start": 0.0, "end": 1.0, "text": "Hello one", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "Hello two", "speaker_id": "Speaker 1"},
        ]

        class _FakeTranslator:
            def __init__(self, *args, **kwargs):
                self.calls = 0

            def translate_batch(self, subtitles, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return ["This line is still English and too long", "你好二"]
                return ["你好一（重试）"]

        with patch.object(omnivoice_dub_api, "Translator", _FakeTranslator), patch.object(
            omnivoice_dub_api,
            "resolve_translation_api_key",
            return_value="dummy-key",
        ):
            rows, mode = omnivoice_dub_api._translate_subtitles_if_needed(
                subtitles_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="English",
                target_lang="Chinese",
                api_key="",
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                translate_system_prompt="",
                task_id="unit_test",
            )

        self.assertEqual(mode, "translated")
        self.assertEqual(len(rows), 2)
        self.assertIn("你好一", rows[0]["text"])
        self.assertEqual(rows[1]["text"], "你好二")

    def test_translate_subtitles_if_needed_retries_latin_rows_after_empty_fallback(self):
        """空译文回退 source 后若仍是英文主导，5 号链路应再重译一次。"""

        source_rows = [
            {"start": 0.0, "end": 1.0, "text": "This line should be translated", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "Second line", "speaker_id": "Speaker 1"},
        ]

        class _FakeTranslator:
            def __init__(self, *args, **kwargs):
                self.calls = 0

            def translate_batch(self, subtitles, *args, **kwargs):
                self.calls += 1
                # 首轮：第一条空译文（触发回退 source），第二条正常中文
                if self.calls == 1:
                    return ["", "第二行"]
                # 第二轮：回退后再次英文清洗重译，成功转中文
                return ["第一行（重试后中文）"]

        with patch.object(omnivoice_dub_api, "Translator", _FakeTranslator), patch.object(
            omnivoice_dub_api,
            "resolve_translation_api_key",
            return_value="dummy-key",
        ):
            rows, mode = omnivoice_dub_api._translate_subtitles_if_needed(
                subtitles_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="English",
                target_lang="Chinese",
                api_key="",
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                translate_system_prompt="",
                task_id="unit_test",
            )

        self.assertEqual(mode, "translated")
        self.assertEqual(len(rows), 2)
        self.assertIn("中文", rows[0]["text"])
        self.assertEqual(rows[1]["text"], "第二行")

    def test_omnivoice_translate_subtitles_if_needed_skips_translation_for_english_source_to_english(self):
        """5 号面板明确 English -> English 时，也应直接复用原文。"""

        source_rows = [
            {"start": 0.0, "end": 1.0, "text": "Hello one", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "Hello two", "speaker_id": "Speaker 1"},
        ]

        class _FailTranslator:
            def __init__(self, *args, **kwargs):
                raise AssertionError("English 到 English 不应调用翻译 API")

        with patch.object(omnivoice_dub_api, "Translator", _FailTranslator), patch.object(
            omnivoice_dub_api,
            "resolve_translation_api_key",
            return_value="dummy-key",
        ):
            rows, mode = omnivoice_dub_api._translate_subtitles_if_needed(
                subtitles_mode="source",
                source_rows=source_rows,
                translated_rows=[],
                source_lang="English",
                target_lang="English",
                api_key="",
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                translate_system_prompt="",
                task_id="unit_test",
            )

        self.assertEqual(mode, "source")
        self.assertEqual([row["text"] for row in rows], ["Hello one", "Hello two"])

    def test_omnivoice_preset_ref_voices_fill_missing_speakers(self):
        """5号链路部分上传参考音时，应从 ref-voices/<target_lang>/ 随机补齐缺失 speaker。"""

        ref_root = self.tmpdir / "ref-voices"
        chinese_dir = ref_root / "Chinese"
        chinese_dir.mkdir(parents=True, exist_ok=True)
        (chinese_dir / "a.wav").write_bytes(b"RIFF_fake_a")
        (chinese_dir / "b.wav").write_bytes(b"RIFF_fake_b")

        out_root = self.tmpdir / "out"
        out_root.mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root), patch.object(
            omnivoice_dub_api,
            "_classify_voice_gender_with_local_model",
            return_value=None,
        ):
            filled = omnivoice_dub_api._pick_preset_ref_voices_for_missing_speakers(
                missing_speaker_ids=["Speaker 2", "Speaker 3"],
                target_lang="Chinese",
                out_root=out_root,
            )

        self.assertEqual(set(filled.keys()), {"Speaker 2", "Speaker 3"})
        for speaker_id in ("Speaker 2", "Speaker 3"):
            item = filled[speaker_id]
            self.assertEqual(item["reference_mode"], "preset_pool")
            self.assertTrue(Path(item["ref_audio"]).exists())

    def test_omnivoice_preset_ref_voices_missing_lang_dir_raises(self):
        """缺失 ref-voices/<target_lang>/ 时应给出清晰报错，避免静默错配。"""

        out_root = self.tmpdir / "out"
        out_root.mkdir(parents=True, exist_ok=True)
        ref_root = self.tmpdir / "ref-voices"
        ref_root.mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root):
            with self.assertRaises(RuntimeError):
                omnivoice_dub_api._pick_preset_ref_voices_for_missing_speakers(
                    missing_speaker_ids=["Speaker 2"],
                    target_lang="Chinese",
                    out_root=out_root,
                )

    def test_omnivoice_preset_ref_voices_supports_cantonese_alias(self):
        """粤语别名应能映射到同一组预置参考音目录。"""

        ref_root = self.tmpdir / "ref-voices"
        cantonese_dir = ref_root / "Cantonese"
        cantonese_dir.mkdir(parents=True, exist_ok=True)
        (cantonese_dir / "c1.wav").write_bytes(b"RIFF_fake_c1")

        out_root = self.tmpdir / "out"
        out_root.mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root):
            filled = omnivoice_dub_api._pick_preset_ref_voices_for_missing_speakers(
                missing_speaker_ids=["Speaker 2"],
                target_lang="yue",
                out_root=out_root,
            )

        self.assertIn("Speaker 2", filled)
        self.assertTrue(Path(filled["Speaker 2"]["ref_audio"]).exists())

    def test_omnivoice_preset_ref_voices_supports_cantonese_mainland_alias(self):
        """Cantonese-Mainland 应继续复用 ref-voices/Cantonese。"""

        ref_root = self.tmpdir / "ref-voices"
        cantonese_dir = ref_root / "Cantonese"
        cantonese_dir.mkdir(parents=True, exist_ok=True)
        (cantonese_dir / "c1.wav").write_bytes(b"RIFF_fake_c1")

        out_root = self.tmpdir / "out"
        out_root.mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root):
            filled = omnivoice_dub_api._pick_preset_ref_voices_for_missing_speakers(
                missing_speaker_ids=["Speaker 2"],
                target_lang="Cantonese-Mainland",
                out_root=out_root,
            )

        self.assertIn("Speaker 2", filled)
        self.assertTrue(Path(filled["Speaker 2"]["ref_audio"]).exists())

    def test_speaker_ref_text_switches_by_target_lang(self):
        """默认参考文本应随目标语切换。"""

        self.assertEqual(
            omnivoice_dub_api._speaker_ref_text_for_target_lang("Chinese"),
            "你好，这是我的声音音色，很高兴为你提供配音服务。",
        )
        self.assertEqual(
            omnivoice_dub_api._speaker_ref_text_for_target_lang("Cantonese"),
            "你好，呢個系我嘅聲音音色，很高興為你提供配音服務。",
        )
        self.assertEqual(
            omnivoice_dub_api._speaker_ref_text_for_target_lang("Cantonese-Mainland"),
            "你好，呢個系我嘅聲音音色，很高興為你提供配音服務。",
        )

    def test_translator_build_prompt_distinguishes_two_cantonese_styles(self):
        """翻译 prompt 应区分港式繁体与广东式繁体两档。"""

        translator = object.__new__(translator_module.Translator)

        hk_prompt = translator._build_prompt(["你好"], "Cantonese")
        mainland_prompt = translator._build_prompt(["你好"], "Cantonese-Mainland")

        self.assertIn("Hong Kong style", hk_prompt)
        self.assertIn("Prefer Traditional Chinese characters", hk_prompt)
        self.assertIn("Guangdong / Mainland style", mainland_prompt)
        self.assertIn("Prefer Traditional Chinese characters", mainland_prompt)

    def test_cantonese_prompt_enforces_authentic_vocabulary_and_particles(self):
        """粤语 prompt 应强制地道词汇、禁书面语直译，并允许语气助词。"""

        translator = object.__new__(translator_module.Translator)
        hk_prompt = translator._build_prompt(["这个东西不是这样"], "Cantonese")
        mainland_prompt = translator._build_prompt(["这个东西不是这样"], "Cantonese-Mainland")

        for prompt in (hk_prompt, mainland_prompt):
            self.assertIn("Must use authentic Cantonese vocabulary whenever possible", prompt)
            self.assertIn("Absolutely avoid written Mandarin, literal translation", prompt)
            self.assertIn("Tone must feel naturally spoken in Cantonese", prompt)
            self.assertIn("㗎、啫、啦、呢、呀、咩", prompt)

        self.assertIn("嘢、唔係、咩、搞掂、呢個、咁、返工、食飯", hk_prompt)
        self.assertIn("嘢、唔係、咩、搞掂、呢個、咁、返工、食飯", mainland_prompt)

    def test_pipeline_cantonese_constraints_distinguish_two_styles(self):
        """改写链路的粤语约束也必须同步到两档风格。"""

        hk_constraints = dubbing_pipeline._build_cantonese_prompt_constraints("Cantonese")
        mainland_constraints = dubbing_pipeline._build_cantonese_prompt_constraints("Cantonese-Mainland")

        self.assertIn("Hong Kong style", hk_constraints)
        self.assertIn("Prefer Traditional Chinese characters", hk_constraints)
        self.assertIn("嘢、唔係、咩、搞掂、呢個、咁、返工、食飯", hk_constraints)
        self.assertIn("㗎、啫、啦、呢、呀、咩", hk_constraints)
        self.assertIn("Absolutely avoid written Mandarin, literal translation", hk_constraints)

        self.assertIn("Guangdong / Mainland style", mainland_constraints)
        self.assertIn("Prefer Traditional Chinese characters", mainland_constraints)
        self.assertIn("嘢、唔係、咩、搞掂、呢個、咁、返工、食飯", mainland_constraints)
        self.assertIn("㗎、啫、啦、呢、呀、咩", mainland_constraints)
        self.assertIn("Absolutely avoid written Mandarin, literal translation", mainland_constraints)

    def test_cantonese_translation_normalizer_rewrites_common_mandarin_residue(self):
        """粤语后处理应把常见普通话残留压成更自然的口语表达。"""

        normalized_hk = translator_module.normalize_cantonese_translation_text(
            "你 结婚了，遇到了 这样的 下场，给你带来 了 麻烦。 你把孩子送进学校，被年轻嘅领导边缘化，别不好以为自己只系在大脑里。",
            "Cantonese",
        )
        normalized_mainland = translator_module.normalize_cantonese_translation_text(
            "你 结婚了，遇到了 这样的 下场，给你带来 了 麻烦。 你把孩子送进学校，被年轻嘅领导边缘化，别不好以为自己只系在大脑里。",
            "Cantonese-Mainland",
        )

        self.assertIn("结咗婚", normalized_hk)
        self.assertIn("遇到咗", normalized_hk)
        self.assertIn("咁嘅下场", normalized_hk)
        self.assertIn("俾你带来咗", normalized_hk)
        self.assertIn("将细路送入学校", normalized_hk)
        self.assertIn("俾后生领导边缘化", normalized_hk)
        self.assertIn("唔好以为", normalized_hk)
        self.assertIn("大脑入面", normalized_hk)
        self.assertIn("短句", translator_module.normalize_cantonese_translation_text("一句断语", "Cantonese"))
        self.assertIn("经历", translator_module.normalize_cantonese_translation_text("阅历", "Cantonese"))
        self.assertIn("冇", translator_module.normalize_cantonese_translation_text("都冇有", "Cantonese"))
        self.assertIn("但系", translator_module.normalize_cantonese_translation_text("可系", "Cantonese"))
        self.assertIn("好似", translator_module.normalize_cantonese_translation_text("就像一个导师", "Cantonese"))

        self.assertIn("结咗婚", normalized_mainland)
        self.assertIn("遇到咗", normalized_mainland)
        self.assertIn("咁嘅下场", normalized_mainland)
        self.assertIn("俾你带来咗", normalized_mainland)
        self.assertIn("将细路送入学校", normalized_mainland)
        self.assertIn("俾后生领导边缘化", normalized_mainland)
        self.assertIn("唔好以为", normalized_mainland)
        self.assertIn("大脑入面", normalized_mainland)

    def test_cantonese_translation_normalizer_leaves_non_cantonese_unchanged(self):
        """非粤语目标语不应被这层后处理改写。"""

        text = "You met him there."
        self.assertEqual(
            translator_module.normalize_cantonese_translation_text(text, "Chinese"),
            text,
        )

    def test_validate_preset_ref_voices_available_rejects_empty_cantonese_dir(self):
        """粤语预置目录存在但为空时，应在启动前明确拒绝。"""

        ref_root = self.tmpdir / "ref-voices"
        (ref_root / "Cantonese").mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root):
            with self.assertRaises(Exception) as ctx:
                omnivoice_dub_api._validate_preset_ref_voices_available(
                    target_lang="Cantonese",
                    missing_speaker_ids=["Speaker 2"],
                )

        self.assertIn("Preset reference voices dir is empty for Cantonese", str(ctx.exception))

    def test_omnivoice_preset_ref_voices_prefers_gender_hint_pool(self):
        """缺失 speaker 有男/女提示时，应优先命中对应的预存参考音池。"""

        ref_root = self.tmpdir / "ref-voices"
        male_dir = ref_root / "Chinese" / "male"
        female_dir = ref_root / "Chinese" / "female"
        male_dir.mkdir(parents=True, exist_ok=True)
        female_dir.mkdir(parents=True, exist_ok=True)
        (male_dir / "m1.wav").write_bytes(b"RIFF_fake_m")
        (female_dir / "f1.wav").write_bytes(b"RIFF_fake_f")

        out_root = self.tmpdir / "out"
        out_root.mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root):
            filled = omnivoice_dub_api._pick_preset_ref_voices_for_missing_speakers(
                missing_speaker_ids=["Speaker A", "Speaker B"],
                target_lang="Chinese",
                out_root=out_root,
                speaker_gender_hints={"Speaker A": "male", "Speaker B": "female"},
            )

        self.assertIn("/male/", str(filled["Speaker A"].get("source_path", "")).replace("\\", "/"))
        self.assertIn("/female/", str(filled["Speaker B"].get("source_path", "")).replace("\\", "/"))

    def test_omnivoice_preset_ref_voices_missing_gender_pool_raises(self):
        """缺失 speaker 已判定性别时，若对应目录为空，不应串到另一性别目录。"""

        ref_root = self.tmpdir / "ref-voices"
        female_dir = ref_root / "Chinese" / "female"
        female_dir.mkdir(parents=True, exist_ok=True)
        (female_dir / "f1.wav").write_bytes(b"RIFF_fake_f")

        out_root = self.tmpdir / "out"
        out_root.mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root):
            with self.assertRaises(RuntimeError):
                omnivoice_dub_api._pick_preset_ref_voices_for_missing_speakers(
                    missing_speaker_ids=["Speaker A"],
                    target_lang="Chinese",
                    out_root=out_root,
                    speaker_gender_hints={"Speaker A": "male"},
                )

    def test_omnivoice_preset_ref_voices_excludes_uploaded_filenames(self):
        """随机补齐时应排除已上传并使用过的同名参考音。"""

        ref_root = self.tmpdir / "ref-voices"
        chinese_dir = ref_root / "Chinese"
        chinese_dir.mkdir(parents=True, exist_ok=True)
        (chinese_dir / "used.wav").write_bytes(b"RIFF_fake_used")
        (chinese_dir / "fresh.wav").write_bytes(b"RIFF_fake_fresh")

        out_root = self.tmpdir / "out"
        out_root.mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root), patch.object(
            omnivoice_dub_api,
            "_classify_voice_gender_with_local_model",
            return_value=None,
        ):
            filled = omnivoice_dub_api._pick_preset_ref_voices_for_missing_speakers(
                missing_speaker_ids=["Speaker X"],
                target_lang="Chinese",
                out_root=out_root,
                excluded_source_filenames=["used.wav"],
            )

        picked_name = Path(str(filled["Speaker X"].get("source_path") or "")).name.lower()
        self.assertEqual(picked_name, "fresh.wav")

    def test_omnivoice_infer_voice_gender_label_keeps_directory_hint_priority(self):
        """明确的 male/female 目录提示应直接命中，不必读取音频。"""

        sample_path = self.tmpdir / "ref-voices" / "Chinese" / "male" / "voice.wav"
        sample_path.parent.mkdir(parents=True, exist_ok=True)
        sample_path.write_bytes(b"RIFF_fake_probe")

        with patch.object(omnivoice_dub_api, "load_mono_audio") as mock_load_audio:
            label = omnivoice_dub_api._infer_voice_gender_label(sample_path)

        self.assertEqual(label, "male")
        mock_load_audio.assert_not_called()

    def test_omnivoice_infer_voice_gender_label_uses_local_model_before_pitch(self):
        """没有目录提示时，应优先走本地模型分支，再考虑 pitch 兜底。"""

        sample_path = self.tmpdir / "probe.wav"
        sample_path.write_bytes(b"RIFF_fake_probe")

        with patch.object(omnivoice_dub_api, "_classify_voice_gender_with_local_model", return_value="female") as mock_local, patch.object(
            omnivoice_dub_api,
            "_estimate_voice_pitch_hz",
        ) as mock_pitch:
            label = omnivoice_dub_api._infer_voice_gender_label(sample_path)

        self.assertEqual(label, "female")
        mock_local.assert_called_once()
        mock_pitch.assert_not_called()

    def test_omnivoice_missing_speaker_gender_probe_ignores_path_hint(self):
        """缺失 speaker 的 probe 音频不应因目录名误命中 male/female。"""

        sample_path = self.tmpdir / "speaker_gender_probe" / "male" / "probe.wav"
        sample_path.parent.mkdir(parents=True, exist_ok=True)
        sample_path.write_bytes(b"RIFF_fake_probe")

        with patch.object(
            omnivoice_dub_api,
            "_classify_voice_gender_with_local_model",
            return_value="female",
        ) as mock_local, patch.object(
            omnivoice_dub_api,
            "load_mono_audio",
        ) as mock_load_audio:
            label = omnivoice_dub_api._infer_voice_gender_label(sample_path, use_path_hint=False)

        self.assertEqual(label, "female")
        mock_local.assert_called_once()
        mock_load_audio.assert_not_called()

    def test_start_omnivoice_from_project_can_disable_source_separation(self):
        """5号面板显式关闭分离时，应把布尔值写入任务并传给后台线程。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        with patch.object(omnivoice_dub_api, "_ensure_omnivoice_backend_ready", return_value={"ready": True}), patch.object(
            omnivoice_dub_api.threading,
            "Thread",
            FakeThread,
        ):
            response = self.client.post(
                "/omnivoice/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "legacy-task",
                    "target_lang": "Chinese",
                    "subtitle_mode": "source",
                    "enable_source_separation": "false",
                    "source_subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.0, "text": "hello", "speaker_id": "Speaker 1"}],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": "[]",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        task = omnivoice_dub_api._task_store.get(payload["task_id"])
        self.assertIsNotNone(task)
        self.assertFalse(task["enable_source_separation"])
        self.assertTrue(FakeThread.instances)
        self.assertFalse(FakeThread.instances[-1].kwargs["enable_source_separation"])

    def test_start_omnivoice_from_project_reuses_prepared_selected_subtitles(self):
        """传入 prepared_batch_id 时，应直接复用 selected_subtitles.srt 跳过翻译阶段。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        prepared_batch_id = "20260516_123456"
        prepared_root = self.omnivoice_output_root / f"omnivoice_{prepared_batch_id}"
        prepared_root.mkdir(parents=True, exist_ok=True)
        selected_srt = prepared_root / "selected_subtitles.srt"
        selected_srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n[Speaker 1] 你好\n",
            encoding="utf-8",
        )
        (prepared_root / "manifest.json").write_text(
            json.dumps(
                {
                    "task_id": prepared_batch_id,
                    "batch_id": prepared_batch_id,
                    "paths": {"selected_subtitles": str(selected_srt.resolve())},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(omnivoice_dub_api, "_ensure_omnivoice_backend_ready", return_value={"ready": True}), patch.object(
            omnivoice_dub_api.threading,
            "Thread",
            FakeThread,
        ):
            response = self.client.post(
                "/omnivoice/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "legacy-task",
                    "prepared_batch_id": prepared_batch_id,
                    "target_lang": "Chinese",
                    "subtitle_mode": "source",
                    "source_subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.0, "text": "hello", "speaker_id": "Speaker 1"}],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": "[]",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["task_id"], prepared_batch_id)
        self.assertTrue(FakeThread.instances)
        self.assertEqual(FakeThread.instances[-1].kwargs["subtitle_mode"], "translated")
        reused_translated_rows = FakeThread.instances[-1].kwargs["translated_subtitles"]
        self.assertEqual(len(reused_translated_rows), 1)
        self.assertEqual(reused_translated_rows[0]["speaker_id"], "Speaker 1")

    def test_start_omnivoice_from_project_rejects_partial_cantonese_refs_when_preset_pool_empty(self):
        """5号面板粤语只上传部分 speaker 时，若预置池为空，应在启动接口直接报错。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        ref_root = self.tmpdir / "ref-voices"
        (ref_root / "Cantonese").mkdir(parents=True, exist_ok=True)

        with patch.object(omnivoice_dub_api, "REF_VOICES_ROOT", ref_root), patch.object(
            omnivoice_dub_api, "_ensure_omnivoice_backend_ready", return_value={"ready": True}
        ), patch.object(
            omnivoice_dub_api.sf,
            "info",
            return_value=type("Info", (), {"duration": 1.0})(),
        ), patch.object(
            omnivoice_dub_api.threading,
            "Thread",
            FakeThread,
        ):
            response = self.client.post(
                "/omnivoice/auto/start-from-project",
                files=[
                    ("speaker_ref_files", ("speaker1.wav", b"RIFF_fake", "audio/wav")),
                ],
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "legacy-task",
                    "target_lang": "Cantonese",
                    "subtitle_mode": "translated",
                    "source_subtitles_json": json.dumps(
                        [
                            {"start": 0.0, "end": 1.0, "text": "hello", "speaker_id": "Speaker 1"},
                            {"start": 1.0, "end": 2.0, "text": "world", "speaker_id": "Speaker 2"},
                        ],
                        ensure_ascii=False,
                    ),
                    "translated_subtitles_json": json.dumps(
                        [
                            {"start": 0.0, "end": 1.0, "text": "你好", "speaker_id": "Speaker 1"},
                            {"start": 1.0, "end": 2.0, "text": "世界", "speaker_id": "Speaker 2"},
                        ],
                        ensure_ascii=False,
                    ),
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Preset reference voices dir is empty for Cantonese", response.json()["detail"])
        self.assertFalse(FakeThread.instances)

    def test_load_omnivoice_batch_marks_prepared_batch_resumable(self):
        """5号面板 load-batch 应把 prepared batch 标成可恢复。"""

        batch_id = "20260516_223344"
        out_root = self.omnivoice_output_root / f"omnivoice_{batch_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        selected_srt = out_root / "selected_subtitles.srt"
        selected_with_speaker = out_root / "selected_subtitles_with_speakers.srt"
        selected_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        selected_with_speaker.write_text("1\n00:00:00,000 --> 00:00:01,000\n[Speaker 1] 你好\n", encoding="utf-8")
        (out_root / "manifest.json").write_text(
            json.dumps(
                {
                    "task_id": batch_id,
                    "batch_id": batch_id,
                    "status": "completed",
                    "stage": "prepared:selected_subtitles",
                    "project_filename": "demo.mp4",
                    "input_media_path": str((self.upload_root / "demo.mp4").resolve()),
                    "subtitle_mode": "source",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "source_subtitles_count": 1,
                    "translated_subtitles_count": 1,
                    "speaker_ids": ["Speaker 1"],
                    "segment_count": 1,
                    "paths": {
                        "selected_subtitles": str(selected_srt.resolve()),
                        "selected_subtitles_with_speakers": str(selected_with_speaker.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        response = self.client.post("/omnivoice/auto/load-batch", data={"batch_id": batch_id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["resumable"])
        self.assertEqual(payload["resume_stage"], "prepared")
        self.assertEqual(payload["processed_segments"], 0)
        self.assertEqual(payload["total_segments"], 1)

    def test_load_omnivoice_batch_preserves_cantonese_mainland_display_lang(self):
        """load-batch 应恢复 Cantonese-Mainland 展示值，同时 runtime 保持 yue。"""

        batch_id = "20260517_010203"
        out_root = self.omnivoice_output_root / f"omnivoice_{batch_id}"
        out_root.mkdir(parents=True, exist_ok=True)
        selected_srt = out_root / "selected_subtitles.srt"
        selected_with_speaker = out_root / "selected_subtitles_with_speakers.srt"
        selected_srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
        selected_with_speaker.write_text("1\n00:00:00,000 --> 00:00:01,000\n[Speaker 1] 你好\n", encoding="utf-8")
        (out_root / "manifest.json").write_text(
            json.dumps(
                {
                    "task_id": batch_id,
                    "batch_id": batch_id,
                    "status": "completed",
                    "stage": "prepared:selected_subtitles",
                    "project_filename": "demo.mp4",
                    "input_media_path": str((self.upload_root / "demo.mp4").resolve()),
                    "subtitle_mode": "source",
                    "source_lang": "English",
                    "target_lang": "Cantonese-Mainland",
                    "target_lang_runtime": "yue",
                    "source_subtitles_count": 1,
                    "translated_subtitles_count": 1,
                    "speaker_ids": ["Speaker 1"],
                    "segment_count": 1,
                    "paths": {
                        "selected_subtitles": str(selected_srt.resolve()),
                        "selected_subtitles_with_speakers": str(selected_with_speaker.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        response = self.client.post("/omnivoice/auto/load-batch", data={"batch_id": batch_id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["target_lang"], "Cantonese-Mainland")
        self.assertEqual(payload["target_lang_runtime"], "yue")

    def test_list_omnivoice_batches_exposes_resume_state(self):
        """5号面板 Restore 列表应提前暴露可断点继续状态。"""

        batch_id = "20260516_225500"
        out_root = self.omnivoice_output_root / f"omnivoice_{batch_id}"
        segment_dir = out_root / "segment_jobs" / "segment_0001"
        out_root.mkdir(parents=True, exist_ok=True)
        segment_dir.mkdir(parents=True, exist_ok=True)
        selected_srt = out_root / "selected_subtitles.srt"
        selected_srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n你好\n\n2\n00:00:01,000 --> 00:00:02,000\n世界\n",
            encoding="utf-8",
        )
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "seg_0001",
                    "speaker_id": "Speaker 1",
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "你好",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (segment_dir / "seg_0001.wav").write_text("seg1", encoding="utf-8")
        (out_root / "manifest.json").write_text(
            json.dumps(
                {
                    "task_id": batch_id,
                    "batch_id": batch_id,
                    "status": "failed",
                    "stage": "failed",
                    "project_filename": "demo.mp4",
                    "input_media_path": str((self.upload_root / "demo.mp4").resolve()),
                    "subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "source_subtitles_count": 2,
                    "translated_subtitles_count": 2,
                    "segment_count": 2,
                    "paths": {
                        "selected_subtitles": str(selected_srt.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        response = self.client.get("/omnivoice/auto/batches")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        item = next(entry for entry in items if entry["batch_id"] == batch_id)
        self.assertTrue(item["resumable"])
        self.assertEqual(item["resume_stage"], "dubbing_partial")
        self.assertEqual(item["processed_segments"], 1)
        self.assertEqual(item["total_segments"], 2)

    def test_resume_omnivoice_task_requeues_batch_with_resume_context(self):
        """5号面板 resume 应重用 selected_subtitles 和已存在 segment checkpoint。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        batch_id = "20260516_224455"
        out_root = self.omnivoice_output_root / f"omnivoice_{batch_id}"
        segment_dir = out_root / "segment_jobs" / "segment_0001"
        stems_root = out_root / "stems"
        final_dir = out_root / "final"
        speaker_root = stems_root / "speaker_refs"
        segment_dir.mkdir(parents=True, exist_ok=True)
        speaker_root.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        selected_srt = out_root / "selected_subtitles.srt"
        selected_with_speaker = out_root / "selected_subtitles_with_speakers.srt"
        selected_srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n你好\n\n2\n00:00:01,000 --> 00:00:02,000\n世界\n",
            encoding="utf-8",
        )
        selected_with_speaker.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n[Speaker 1] 你好\n\n2\n00:00:01,000 --> 00:00:02,000\n[Speaker 1] 世界\n",
            encoding="utf-8",
        )
        source_audio = stems_root / "source_audio.wav"
        source_vocals = stems_root / "full_source_vocals.wav"
        source_bgm = stems_root / "full_source_bgm.wav"
        separation_report = out_root / "separation_report.json"
        source_audio.write_text("audio", encoding="utf-8")
        source_vocals.write_text("vocals", encoding="utf-8")
        source_bgm.write_text("bgm", encoding="utf-8")
        separation_report.write_text("{}", encoding="utf-8")
        ref_audio = speaker_root / "speaker1.wav"
        ref_audio.write_text("ref", encoding="utf-8")
        speaker_ref_map = out_root / "speaker_ref_map.json"
        speaker_ref_map.write_text(
            json.dumps(
                {
                    "reference_mode": "uploaded_strict",
                    "speakers": {
                        "Speaker 1": {
                            "ref_audio": str(ref_audio.resolve()),
                            "ref_text": "你好，呢個系我嘅聲音音色，很高興為你提供配音服務。",
                            "duration": 1.0,
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        existing_seg = segment_dir / "seg_0001.wav"
        existing_seg.write_text("seg1", encoding="utf-8")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "seg_0001",
                    "speaker_id": "Speaker 1",
                    "start_sec": 0.0,
                    "end_sec": 1.0,
                    "text": "你好",
                    "tts_audio_path": str(existing_seg.resolve()),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (out_root / "manifest.json").write_text(
            json.dumps(
                {
                    "task_id": batch_id,
                    "batch_id": batch_id,
                    "status": "failed",
                    "stage": "failed",
                    "project_filename": "demo.mp4",
                    "input_media_path": str(media_path.resolve()),
                    "subtitle_mode": "translated",
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "enable_source_separation": True,
                    "source_subtitles_count": 2,
                    "translated_subtitles_count": 2,
                    "speaker_ids": ["Speaker 1"],
                    "speaker_reference_mode": "uploaded_strict",
                    "segment_count": 2,
                    "processed_segments": 1,
                    "paths": {
                        "source_audio": str(source_audio.resolve()),
                        "source_vocals": str(source_vocals.resolve()),
                        "source_bgm": str(source_bgm.resolve()),
                        "speaker_ref_map": str(speaker_ref_map.resolve()),
                        "selected_subtitles": str(selected_srt.resolve()),
                        "selected_subtitles_with_speakers": str(selected_with_speaker.resolve()),
                        "separation_report": str(separation_report.resolve()),
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch.object(omnivoice_dub_api, "_ensure_omnivoice_backend_ready", return_value={"ready": True}), patch.object(
            omnivoice_dub_api.threading,
            "Thread",
            FakeThread,
        ):
            response = self.client.post(f"/omnivoice/auto/resume/{batch_id}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["task_id"], batch_id)
        self.assertEqual(payload["resume_stage"], "dubbing_partial")
        self.assertTrue(FakeThread.instances)
        kwargs = FakeThread.instances[-1].kwargs
        self.assertIn("resume_context", kwargs)
        self.assertTrue(kwargs["resume_context"]["reuse_selected_subtitles"])
        self.assertTrue(kwargs["resume_context"]["reuse_stems"])
        self.assertEqual(kwargs["resume_context"]["completed_segment_indices"], {1})

    def test_run_omnivoice_job_normalizes_cantonese_to_yue_for_generation(self):
        """5号面板粤语输出应在底座调用时使用 yue，而不是仅保留 UI 文本。"""

        task_id = "20260517_000001"
        out_root = self.omnivoice_output_root / f"omnivoice_{task_id}"
        media_path = self.upload_root / "cantonese-demo.mp4"
        media_path.write_bytes(b"video-data")
        selected_rows = [{"start": 0.0, "end": 1.0, "text": "你好", "speaker_id": "Speaker 1"}]
        task = omnivoice_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="cantonese-demo.mp4",
            input_media_path=media_path,
            subtitle_mode="translated",
            source_lang="粤语",
            target_lang="Cantonese",
            enable_source_separation=False,
            source_count=0,
            translated_count=1,
            speaker_ids=["Speaker 1"],
            out_root=out_root,
        )
        omnivoice_dub_api._task_store.create(task_id, task)

        ref_audio = self.tmpdir / "ref.wav"
        ref_audio.write_text("ref", encoding="utf-8")
        speaker_ref_map = {"Speaker 1": {"ref_audio": str(ref_audio.resolve()), "ref_text": "固定参考文案"}}

        def _fake_generate(**kwargs):
            self.assertEqual(kwargs["language"], "yue")
            return b"wav-bytes"

        def _fake_normalize_generated_segment_audio(*, input_path, output_path, target_duration_sec):
            del input_path, target_duration_sec
            output_path.write_text("normalized", encoding="utf-8")
            return output_path, "passthrough"

        def _fake_compose_vocals_master(*, segments, output_path, source_audio_fallback=None):
            del source_audio_fallback
            output_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

        with patch.object(omnivoice_dub_api, "_ensure_omnivoice_backend_ready", return_value={"ready": True}), patch.object(
            omnivoice_dub_api,
            "_translate_subtitles_if_needed",
            return_value=(selected_rows, "translated"),
        ), patch.object(
            omnivoice_dub_api,
            "_prepare_omnivoice_source_stems",
            return_value={"has_bgm_track": False},
        ), patch.object(
            omnivoice_dub_api,
            "_build_speaker_reference_map",
            return_value=speaker_ref_map,
        ), patch.object(
            omnivoice_dub_api,
            "_call_remote_generate",
            side_effect=_fake_generate,
        ), patch.object(
            omnivoice_dub_api,
            "_normalize_generated_segment_audio",
            side_effect=_fake_normalize_generated_segment_audio,
        ), patch.object(
            omnivoice_dub_api,
            "compose_vocals_master",
            side_effect=_fake_compose_vocals_master,
        ), patch.object(
            omnivoice_dub_api,
            "mix_with_bgm",
        ), patch.object(
            omnivoice_dub_api,
            "prepare_dubbed_audio_for_video",
        ), patch.object(
            omnivoice_dub_api,
            "replace_video_audio_two_step",
        ), patch.object(
            omnivoice_dub_api,
            "burn_ass_subtitles_into_video",
        ), patch.object(
            omnivoice_dub_api,
            "has_video_stream",
            return_value=False,
        ), patch.object(
            omnivoice_dub_api.sf,
            "info",
            return_value=type("Info", (), {"duration": 1.0})(),
        ):
            omnivoice_dub_api._run_omnivoice_job(
                task_id=task_id,
                input_media_path=media_path,
                project_filename="cantonese-demo.mp4",
                source_subtitles=selected_rows,
                translated_subtitles=selected_rows,
                subtitle_mode="translated",
                source_lang="粤语",
                target_lang="Cantonese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                omnivoice_api_url="http://127.0.0.1:3900",
                enable_source_separation=False,
                uploaded_speaker_ref_map=None,
            )

        task_after = omnivoice_dub_api._task_store.get(task_id)
        self.assertIsNotNone(task_after)
        self.assertEqual(task_after["target_lang"], "Cantonese")
        self.assertEqual(task_after["target_lang_runtime"], "yue")

    def test_run_omnivoice_job_normalizes_cantonese_mainland_to_yue_for_generation(self):
        """Cantonese-Mainland 应保持展示值，但底座调用仍使用 yue。"""

        task_id = "20260517_000002"
        out_root = self.omnivoice_output_root / f"omnivoice_{task_id}"
        media_path = self.upload_root / "cantonese-mainland-demo.mp4"
        media_path.write_bytes(b"video-data")
        selected_rows = [{"start": 0.0, "end": 1.0, "text": "你好", "speaker_id": "Speaker 1"}]
        task = omnivoice_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="cantonese-mainland-demo.mp4",
            input_media_path=media_path,
            subtitle_mode="translated",
            source_lang="粤语",
            target_lang="Cantonese-Mainland",
            enable_source_separation=False,
            source_count=0,
            translated_count=1,
            speaker_ids=["Speaker 1"],
            out_root=out_root,
        )
        omnivoice_dub_api._task_store.create(task_id, task)

        ref_audio = self.tmpdir / "ref-mainland.wav"
        ref_audio.write_text("ref", encoding="utf-8")
        speaker_ref_map = {"Speaker 1": {"ref_audio": str(ref_audio.resolve()), "ref_text": "固定参考文案"}}

        def _fake_generate(**kwargs):
            self.assertEqual(kwargs["language"], "yue")
            return b"wav-bytes"

        def _fake_normalize_generated_segment_audio(*, input_path, output_path, target_duration_sec):
            del input_path, target_duration_sec
            output_path.write_text("normalized", encoding="utf-8")
            return output_path, "passthrough"

        def _fake_compose_vocals_master(*, segments, output_path, source_audio_fallback=None):
            del source_audio_fallback
            output_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

        with patch.object(omnivoice_dub_api, "_ensure_omnivoice_backend_ready", return_value={"ready": True}), patch.object(
            omnivoice_dub_api,
            "_translate_subtitles_if_needed",
            return_value=(selected_rows, "translated"),
        ), patch.object(
            omnivoice_dub_api,
            "_prepare_omnivoice_source_stems",
            return_value={"has_bgm_track": False},
        ), patch.object(
            omnivoice_dub_api,
            "_build_speaker_reference_map",
            return_value=speaker_ref_map,
        ), patch.object(
            omnivoice_dub_api,
            "_call_remote_generate",
            side_effect=_fake_generate,
        ), patch.object(
            omnivoice_dub_api,
            "_normalize_generated_segment_audio",
            side_effect=_fake_normalize_generated_segment_audio,
        ), patch.object(
            omnivoice_dub_api,
            "compose_vocals_master",
            side_effect=_fake_compose_vocals_master,
        ), patch.object(
            omnivoice_dub_api,
            "mix_with_bgm",
        ), patch.object(
            omnivoice_dub_api,
            "prepare_dubbed_audio_for_video",
        ), patch.object(
            omnivoice_dub_api,
            "replace_video_audio_two_step",
        ), patch.object(
            omnivoice_dub_api,
            "burn_ass_subtitles_into_video",
        ), patch.object(
            omnivoice_dub_api,
            "has_video_stream",
            return_value=False,
        ), patch.object(
            omnivoice_dub_api.sf,
            "info",
            return_value=type("Info", (), {"duration": 1.0})(),
        ):
            omnivoice_dub_api._run_omnivoice_job(
                task_id=task_id,
                input_media_path=media_path,
                project_filename="cantonese-mainland-demo.mp4",
                source_subtitles=selected_rows,
                translated_subtitles=selected_rows,
                subtitle_mode="translated",
                source_lang="粤语",
                target_lang="Cantonese-Mainland",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                omnivoice_api_url="http://127.0.0.1:3900",
                enable_source_separation=False,
                uploaded_speaker_ref_map=None,
            )

        task_after = omnivoice_dub_api._task_store.get(task_id)
        self.assertIsNotNone(task_after)
        self.assertEqual(task_after["target_lang"], "Cantonese-Mainland")
        self.assertEqual(task_after["target_lang_runtime"], "yue")

    def test_run_omnivoice_job_resume_skips_completed_segments(self):
        """resume 场景应复用已完成 segment，只补剩余条目。"""

        task_id = "20260516_225566"
        out_root = self.omnivoice_output_root / f"omnivoice_{task_id}"
        media_path = self.upload_root / "resume-demo.mp4"
        media_path.write_bytes(b"video-data")
        selected_rows = [
            {"start": 0.0, "end": 1.0, "text": "你好世界欢迎光临这是第一段测试文本内容比较长的那种类型", "speaker_id": "Speaker 1"},
            {"start": 1.0, "end": 2.0, "text": "今天天气真不错呀我们一起出去走走看看风景如何呢朋友们", "speaker_id": "Speaker 1"},
        ]
        task = omnivoice_dub_api._create_task_payload(
            task_id=task_id,
            project_filename="resume-demo.mp4",
            input_media_path=media_path,
            subtitle_mode="translated",
            source_lang="English",
            target_lang="Chinese",
            enable_source_separation=True,
            source_count=0,
            translated_count=2,
            speaker_ids=["Speaker 1"],
            out_root=out_root,
        )
        omnivoice_dub_api._task_store.create(task_id, task)

        existing_segment_manifest = {
            "id": "seg_0001",
            "speaker_id": "Speaker 1",
            "start_sec": 0.0,
            "end_sec": 1.0,
            "text": "你好世界欢迎光临这是第一段测试文本内容比较长的那种类型",
            "tts_audio_path": str((out_root / "segment_jobs" / "segment_0001" / "seg_0001.wav").resolve()),
            "duration_sec": 1.0,
            "normalized_duration_sec": 1.0,
        }
        speaker_ref_map = {"Speaker 1": {"ref_audio": str((self.tmpdir / "ref.wav").resolve()), "ref_text": "固定参考文案"}}
        Path(speaker_ref_map["Speaker 1"]["ref_audio"]).write_text("ref", encoding="utf-8")
        stems_root = out_root / "stems"
        stems_root.mkdir(parents=True, exist_ok=True)
        source_audio = stems_root / "source_audio.wav"
        source_vocals = stems_root / "full_source_vocals.wav"
        source_audio.write_text("audio", encoding="utf-8")
        source_vocals.write_text("vocals", encoding="utf-8")
        generate_calls = []

        def _fake_generate(**kwargs):
            generate_calls.append(kwargs["text"])
            return b"wav-bytes"

        def _fake_normalize_generated_segment_audio(*, input_path, output_path, target_duration_sec):
            del input_path, target_duration_sec
            output_path.write_text("normalized", encoding="utf-8")
            return output_path, "passthrough"

        def _fake_prepare_audio(**kwargs):
            kwargs["output_audio_path"].write_text("m4a", encoding="utf-8")

        def _fake_replace_video(**kwargs):
            kwargs["output_video_path"].write_text("mp4", encoding="utf-8")

        def _fake_burn_video(**kwargs):
            kwargs["output_video_path"].write_text("burned", encoding="utf-8")

        def _fake_compose_vocals_master(*, segments, output_path, source_audio_fallback=None):
            del source_audio_fallback
            output_path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")

        def _fake_mix_with_bgm(*, vocals_path, bgm_path, output_path, target_sr):
            del vocals_path, bgm_path, target_sr
            output_path.write_text("mix", encoding="utf-8")

        with patch.object(omnivoice_dub_api, "_ensure_omnivoice_backend_ready", return_value={"ready": True}), patch.object(
            omnivoice_dub_api,
            "_call_remote_generate",
            side_effect=_fake_generate,
        ), patch.object(
            omnivoice_dub_api,
            "_normalize_generated_segment_audio",
            side_effect=_fake_normalize_generated_segment_audio,
        ), patch.object(
            omnivoice_dub_api,
            "compose_vocals_master",
            side_effect=_fake_compose_vocals_master,
        ), patch.object(
            omnivoice_dub_api,
            "mix_with_bgm",
            side_effect=_fake_mix_with_bgm,
        ), patch.object(
            omnivoice_dub_api,
            "prepare_dubbed_audio_for_video",
            side_effect=_fake_prepare_audio,
        ), patch.object(
            omnivoice_dub_api,
            "replace_video_audio_two_step",
            side_effect=_fake_replace_video,
        ), patch.object(
            omnivoice_dub_api,
            "burn_ass_subtitles_into_video",
            side_effect=_fake_burn_video,
        ), patch.object(
            omnivoice_dub_api,
            "ffprobe_duration",
            return_value=2.0,
        ), patch.object(
            omnivoice_dub_api,
            "has_video_stream",
            return_value=False,
        ), patch.object(
            omnivoice_dub_api.sf,
            "info",
            return_value=type("Info", (), {"duration": 1.0})(),
        ):
            omnivoice_dub_api._run_omnivoice_job(
                task_id=task_id,
                input_media_path=media_path,
                project_filename="resume-demo.mp4",
                source_subtitles=[],
                translated_subtitles=[],
                subtitle_mode="translated",
                source_lang="English",
                target_lang="Chinese",
                api_key="",
                translate_base_url="",
                translate_model="",
                translate_system_prompt="",
                omnivoice_api_url="http://127.0.0.1:3900",
                enable_source_separation=True,
                uploaded_speaker_ref_map=None,
                resume_context={
                    "selected_subtitles": selected_rows,
                    "speaker_ref_map": speaker_ref_map,
                    "speaker_reference_mode": "uploaded_strict",
                    "completed_segment_indices": {1},
                    "reusable_segment_results": [existing_segment_manifest],
                    "reuse_selected_subtitles": True,
                    "reuse_stems": True,
                    "reuse_speaker_refs": True,
                    "source_audio_path": str(source_audio.resolve()),
                    "source_vocals_path": str(source_vocals.resolve()),
                    "source_bgm_path": "",
                    "separation_report_path": "",
                    "has_bgm_track": False,
                },
            )

        self.assertEqual(generate_calls, ["今天天气真不错呀我们一起出去走走看看风景如何呢朋友们"])
        task_after = omnivoice_dub_api._task_store.get(task_id)
        self.assertIsNotNone(task_after)
        self.assertEqual(task_after["status"], "completed")
        self.assertEqual(task_after["processed_segments"], 2)

    def test_start_auto_dubbing_runtime_brief_keeps_grouped_for_source_short_merge(self):
        """开启 source short merge 后，index-tts 仍应保持 grouped synthesis。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "short_merge_enabled": "true",
                    "short_merge_threshold": "15",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        runtime_brief = task.get("runtime_brief") or {}
        self.assertIn("grouped=true", runtime_brief.get("grouping", ""))
        self.assertIn("force_fit=true", runtime_brief.get("grouping", ""))
        self.assertEqual(runtime_brief.get("translation"), "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)")
        self.assertIn("--index-max-text-tokens", task["command"])
        token_index = task["command"].index("--index-max-text-tokens")
        self.assertEqual(task["command"][token_index + 1], "40")

    def test_start_auto_dubbing_supports_custom_openai_compatible_provider(self):
        """自定义 OpenAI-compatible base_url/model 时，应透传到 CLI 并显示通用 provider 标签。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "source_lang": "English",
                    "target_lang": "Chinese",
                    "api_key": "custom-key",
                    "translate_base_url": "https://llm.example.com/v1",
                    "translate_model": "gpt-like-model",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["translate_base_url"], "https://llm.example.com/v1")
        self.assertEqual(task["translate_model"], "gpt-like-model")
        runtime_brief = task.get("runtime_brief") or {}
        self.assertEqual(
            runtime_brief.get("translation"),
            "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)",
        )
        self.assertEqual(FakeThread.instances[0].args[2]["TRANSLATE_API_KEY"], "custom-key")
        self.assertIn("--translate-base-url", task["command"])
        self.assertIn("https://llm.example.com/v1", task["command"])
        self.assertIn("--translate-model", task["command"])
        self.assertIn("gpt-like-model", task["command"])

    def test_start_auto_dubbing_accepts_multi_mode_with_uploaded_speaker_refs(self):
        """多人模式应按字幕 speaker 前缀收参考音映射。"""

        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("speaker_ref_files", ("speaker1.wav", b"ref1", "audio/wav")),
                    ("speaker_ref_files", ("speaker2.wav", b"ref2", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "tts_backend": "voxcpm-omnivoice",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1", "Speaker 2"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["dubbing_mode"], "multi")
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(len(task["speaker_ref_map"]), 2)
        self.assertEqual(task["speaker_ref_map"][0]["speaker_id"], "Speaker 1")
        self.assertIn("--speaker-ref-map-json", task["command"])
        self.assertNotIn("--voxcpm-api-url", task["command"])

    def test_start_auto_dubbing_with_speakers_and_zero_uploaded_refs_keeps_old_method(self):
        """有 speaker 但零上传参考音时，应自动推断 multi，并继续走旧方法。"""

        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["dubbing_mode"], "multi")
        self.assertEqual(task["speaker_ref_map"], [])
        self.assertNotIn("--speaker-ref-map-json", task["command"])

    def test_update_from_stdout_counts_translate_requests(self):
        """运行日志里的翻译请求应累计到任务统计中。"""

        task_id = "task_translate_counter"
        dubbing_cli_api._task_store.create(
            task_id,
            {
                "id": task_id,
                "status": "running",
                "stage": "queued",
                "progress": 0.0,
                "stdout_tail": [],
                "translate_request_count": 0,
                "deepseek_request_count": 0,
                "runtime_brief": {"tts_base": "-", "dubbing_mode": "single", "grouping": "-", "timing_mode": "strict", "translation": "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)", "merge": "-", "range": "-", "segment": "-"},
            },
        )

        dubbing_cli_api._update_from_stdout(
            task_id,
            'HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"',
        )

        task = dubbing_cli_api._task_store.get_copy(task_id) or {}
        self.assertEqual(task.get("translate_request_count"), 1)
        self.assertNotIn("deepseek_request_count", task)

    def test_status_compatibly_exposes_translate_request_count_for_legacy_tasks(self):
        """旧任务若仍只有 legacy 翻译计数字段，状态接口也应统一暴露新字段。"""

        task_id = "task_legacy_translate_counter"
        dubbing_cli_api._task_store.create(
            task_id,
            {
                "id": task_id,
                "status": "running",
                "stage": "queued",
                "progress": 0.0,
                "stdout_tail": [],
                "deepseek_request_count": 3,
                "runtime_brief": {
                    "tts_base": "-",
                    "dubbing_mode": "single",
                    "grouping": "-",
                    "timing_mode": "strict",
                    "translation": "run(input=source,via=OpenAI-compatible,rewrite=on,prompt=default)",
                "merge": "-",
                    "range": "-",
                    "segment": "-",
                },
            },
        )

        payload = self.client.get(f"/dubbing/auto/status/{task_id}").json()
        self.assertEqual(payload.get("translate_request_count"), 3)
        self.assertNotIn("deepseek_request_count", payload)

    def test_start_auto_dubbing_treats_single_uploaded_speaker_ref_as_single_mode(self):
        """只上传 1 份参考音时，应自动收敛为 single 模式。"""

        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("speaker_ref_files", ("speaker1.wav", b"ref1", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["dubbing_mode"], "single")
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertTrue(task["single_ref_audio"])
        self.assertEqual(task["speaker_ref_map"], [])
        self.assertIn("--single-speaker-ref", task["command"])
        self.assertNotIn("--speaker-ref-map-json", task["command"])

    def test_start_auto_dubbing_ignores_legacy_omnivoice_backend_request(self):
        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "target_lang": "Chinese",
                    "tts_backend": "omnivoice",
                    "api_key": "secret-key",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["dubbing_mode"], "single")

    def test_start_auto_dubbing_keeps_single_reference_audio_and_prompt_for_index_tts(self):
        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("single_ref_audio_file", ("ref.wav", b"ref-audio", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "tts_backend": "omnivoice",
                    "single_ref_text": "Hello, this is the reference prompt.",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["single_ref_text"], "Hello, this is the reference prompt.")
        self.assertIn("--single-ref-text", task["command"])
        self.assertIn("--single-speaker-ref", task["command"])

    def test_start_from_project_legacy_omnivoice_request_normalizes_to_index_tts(self):
        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        subtitles_json = json.dumps(
            [
                {"start": 0.0, "end": 1.0, "text": "Speaker 1: hello", "speaker_id": "Speaker 1"},
                {"start": 1.0, "end": 2.0, "text": "Speaker 2: world", "speaker_id": "Speaker 2"},
            ],
            ensure_ascii=False,
        )

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                files=[
                    ("single_ref_audio_file", ("ref.wav", b"ref-audio", "audio/wav")),
                ],
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "legacy-task",
                    "subtitles_json": subtitles_json,
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "source",
                    "tts_backend": "omnivoice",
                    "single_ref_text": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["dubbing_mode"], "single")
        self.assertEqual(task["tts_backend"], "index-tts")

    def test_start_auto_dubbing_from_project_preserves_speaker_metadata_sidecar(self):
        """Current Project 启动时应把 speaker_id 额外写成 sidecar。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        subtitles_json = json.dumps(
            [
                {"start": 0.0, "end": 1.0, "text": "你好", "speaker_id": "Speaker 1"},
                {"start": 1.0, "end": 2.0, "text": "世界", "speaker_id": "Speaker 2"},
            ],
            ensure_ascii=False,
        )

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "demo.mp4",
                    "task_id": "legacy-task",
                    "subtitles_json": subtitles_json,
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "translated",
                    "tts_backend": "omnivoice",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        sidecar_path = Path(task["input_speaker_metadata"])
        self.assertTrue(sidecar_path.exists())
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        self.assertEqual(payload[0]["speaker_id"], "Speaker 1")
        self.assertEqual(task["dubbing_mode"], "multi")
        self.assertEqual(task["tts_backend"], "index-tts")

    def test_start_auto_dubbing_keeps_empty_single_ref_text_for_index_tts(self):
        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("single_ref_audio_file", ("ref.wav", b"ref-audio", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "tts_backend": "omnivoice",
                    "single_ref_text": "",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["single_ref_text"], "")
        self.assertNotIn("--single-ref-text", task["command"])

    def test_start_auto_dubbing_normalizes_voxcpm_backend_request_to_index_tts(self):
        """旧的 voxcpm-omnivoice 请求应被统一收敛到 index-tts。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("single_ref_audio_file", ("ref.wav", b"ref-audio", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "tts_backend": "voxcpm-omnivoice",
                    "single_ref_text": "should be ignored",
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")

    def test_start_auto_dubbing_multi_with_legacy_voxcpm_request_still_uses_index_tts(self):
        """多人模式即便传旧 voxcpm 字段，也应统一收敛到 index-tts。"""

        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("speaker_ref_files", ("speaker1.wav", b"ref1", "audio/wav")),
                    ("speaker_ref_files", ("speaker2.wav", b"ref2", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "dubbing_mode": "multi",
                    "tts_backend": "voxcpm-omnivoice",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1", "Speaker 2"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["dubbing_mode"], "multi")

    def test_start_auto_dubbing_multi_mode_with_legacy_omnivoice_request_uses_index_tts(self):
        srt_text = (
            "1\n00:00:00,000 --> 00:00:01,000\nSpeaker 1: hello\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nSpeaker 2: world\n"
        ).encode("utf-8")

        with self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                    ("speaker_ref_files", ("speaker1.wav", b"ref1", "audio/wav")),
                    ("speaker_ref_files", ("speaker2.wav", b"ref2", "audio/wav")),
                ],
                data={
                    "target_lang": "Chinese",
                    "subtitle_mode": "translated",
                    "dubbing_mode": "multi",
                    "tts_backend": "omnivoice",
                    "speaker_ref_speaker_ids_json": json.dumps(["Speaker 1", "Speaker 2"], ensure_ascii=False),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["tts_backend"], "index-tts")
        self.assertEqual(task["dubbing_mode"], "multi")

    def test_start_auto_dubbing_rejects_invalid_dubbing_mode(self):
        """非法 dubbing_mode 应直接报错。"""

        srt_text = "1\n00:00:00,000 --> 00:00:01,000\nHello\n".encode("utf-8")
        with self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start",
                files=[
                    ("video", ("demo.mp4", b"video-data", "video/mp4")),
                    ("subtitle_file", ("manual.srt", srt_text, "application/x-subrip")),
                ],
                data={
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "dubbing_mode": "team",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("dubbing_mode", response.json()["detail"])

    def test_start_from_project_reuses_media_and_subtitles(self):
        """从当前项目启动时，应复用已有媒体和字幕。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        dubbing_cli_api.legacy_runtime.tasks["legacy-task"] = {
            "status": "completed",
            "filename": "demo.srt",
            "video_filename": "demo.mp4",
        }

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "task_id": "legacy-task",
                    "original_filename": "project-original.mp4",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "translated",
                    "subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "Speaker 1: hello project"}],
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["project_filename"], "demo.mp4")
        task = self.client.get(f"/dubbing/auto/status/{payload['task_id']}").json()
        self.assertEqual(task["filename"], "demo.mp4")
        self.assertIn("--input-srt-kind", task["command"])
        self.assertIn("translated", task["command"])

    def test_start_from_project_passes_translate_system_prompt_into_command(self):
        """Current Project 启动时应透传自定义翻译系统提示词。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")
        dubbing_cli_api.legacy_runtime.tasks["legacy-task"] = {
            "status": "completed",
            "filename": "demo.srt",
            "video_filename": "demo.mp4",
        }

        custom_prompt = "你是专业译者，优先保证专有名词一致。"
        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "task_id": "legacy-task",
                    "original_filename": "project-original.mp4",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "source",
                    "translate_system_prompt": custom_prompt,
                    "subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "Speaker 1: hello project"}],
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        task = self.client.get(f"/dubbing/auto/status/{response.json()['task_id']}").json()
        self.assertEqual(task["translate_system_prompt"], custom_prompt)
        self.assertIn("--translate-system-prompt", task["command"])
        prompt_index = task["command"].index("--translate-system-prompt")
        self.assertEqual(task["command"][prompt_index + 1], custom_prompt)

    def test_start_from_project_does_not_duplicate_media_into_dubbing_upload_dir(self):
        """Current Project 启动不应再把媒体复制到 uploads/dubbing/<task_id>/。"""

        media_path = self.upload_root / "demo.mp4"
        media_path.write_bytes(b"video-data")

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            response = self.client.post(
                "/dubbing/auto/start-from-project",
                data={
                    "filename": "demo.mp4",
                    "original_filename": "project-original.mp4",
                    "task_id": "legacy-task",
                    "target_lang": "Chinese",
                    "api_key": "secret-key",
                    "subtitle_mode": "translated",
                    "subtitles_json": json.dumps(
                        [{"start": 0.0, "end": 1.2, "text": "Speaker 1: hello project"}],
                        ensure_ascii=False,
                    ),
                },
            )

        self.assertEqual(response.status_code, 200)
        task_id = response.json()["task_id"]
        private_task = dubbing_cli_api._tasks[task_id]
        # 任务输入媒体应直接指向原始上传路径，而不是 uploads/dubbing/<task_id>/project-original.mp4
        self.assertEqual(Path(private_task["input_path"]).resolve(), media_path.resolve())
        duplicated_media = Path(private_task["upload_dir"]) / "project-original.mp4"
        self.assertFalse(duplicated_media.exists())

    def test_load_batch_restores_completed_task_with_new_fields(self):
        """load-batch 应恢复新合同字段。"""

        batch_dir = self.output_root / "web_20260504_123000" / "longdub_20260504_123000"
        upload_dir = self.upload_root / "20260504_abc"
        upload_dir.mkdir(parents=True, exist_ok=True)
        media_path = upload_dir / "demo.mp4"
        media_path.write_bytes(b"fake-media")
        final_dir = batch_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        audio_path = final_dir / "dubbed_mix_full.wav"
        srt_path = final_dir / "dubbed_final_full.srt"
        audio_path.write_bytes(b"fake-audio")
        srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
        manifest_path = batch_dir / "batch_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "batch_id": "longdub_20260504_123000",
                    "segments_total": 1,
                    "input_media_path": str(media_path),
                    "target_lang": "Chinese",
                    "pipeline_version": "auto-dubbing",
                    "dubbing_mode": "multi",
                    "rewrite_translation": False,
                    "input_srt_kind": "translated",
                    "tts_backend": "index-tts",
                    "speaker_ref_map": [{"speaker_id": "Speaker 1", "ref_audio_path": "/tmp/s1.wav"}],
                    "index_tts_api_url": "http://127.0.0.1:8011",
                    "segments": [{"summary": {"total": 1, "done": 1, "manual_review": 0}}],
                    "paths": {
                        "preferred_audio": str(audio_path),
                        "dubbed_mix_full": str(audio_path),
                        "dubbed_final_full_srt": str(srt_path),
                    },
                }
            ),
            encoding="utf-8",
        )

        response = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260504_123000"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["dubbing_mode"], "multi")
        self.assertEqual(payload["subtitle_mode"], "translated")
        self.assertEqual(payload["tts_backend"], "index-tts")
        self.assertEqual(payload["speaker_ref_map"][0]["speaker_id"], "Speaker 1")

    def test_load_batch_restores_incomplete_batch_for_resume(self):
        """无 batch manifest 时，应按 interrupted job 加载。"""

        batch_dir = self.output_root / "web_20260504_121212" / "longdub_20260504_221212"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        upload_dir = self.upload_root / "20260504_121212"
        upload_dir.mkdir(parents=True, exist_ok=True)
        uploaded_video = upload_dir / "demo.mp4"
        uploaded_video.write_bytes(b"video-data")
        segment_dir.mkdir(parents=True, exist_ok=True)
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "target_lang": "Chinese",
                    "dubbing_mode": "single",
                    "input_srt_kind": "source",
                    "input_media_path": str(batch_dir / "segments" / "segment_0001.wav"),
                    "translated_short_merge_enabled": True,
                    "translated_short_merge_threshold": 9,
                    "tts_backend": "index-tts",
                    "segments": [],
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260504_221212"})
        self.assertEqual(loaded.status_code, 200)
        payload = loaded.json()
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["dubbing_mode"], "single")
        self.assertTrue(payload["translated_short_merge_enabled"])
        self.assertEqual(payload["translated_short_merge_threshold"], 9)
        self.assertIn("interrupted job", payload.get("error", ""))

        with patch.object(dubbing_cli_api.threading, "Thread", FakeThread), self._patch_start_runtime():
            resumed = self.client.post(f"/dubbing/auto/resume/{payload['id']}", data={"api_key": "secret-key"})
        self.assertEqual(resumed.status_code, 200)
        resumed_task = self.client.get(f"/dubbing/auto/status/{resumed.json()['task_id']}").json()
        self.assertIn("--resume-batch-dir", resumed_task["command"])
        self.assertIn(str(uploaded_video.resolve()), resumed_task["command"])

    def test_review_save_and_redub_runs_partial_pipeline(self):
        """save-and-redub 应更新字幕并调用局部重配。"""

        batch_dir = self.output_root / "web_20260504_223000" / "longdub_20260504_202927"
        final_dir = batch_dir / "final"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        (segment_dir / "subtitles").mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        source_srt = final_dir / "source_full.srt"
        translated_srt = final_dir / "translated_full.srt"
        bilingual_srt = final_dir / "dubbed_final_full.srt"
        source_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
        bilingual_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\nHello\n", encoding="utf-8")
        (segment_dir / "subtitles" / "source.srt").write_text(source_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (segment_dir / "subtitles" / "translated.srt").write_text(translated_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (segment_dir / "subtitles" / "dubbed_final.srt").write_text(bilingual_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(self.upload_root / "in.mp4"),
                    "segments": [{"id": "seg_0001", "start_sec": 0.0, "end_sec": 2.0, "translated_text": "你好", "status": "done"}],
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "batch_id": "longdub_20260504_202927",
                    "segments_total": 1,
                    "segments": [{"index": 1, "start_sec": 0.0, "summary": {"total": 1, "done": 1, "manual_review": 0}, "job_dir": str(segment_dir)}],
                    "paths": {
                        "translated_full_srt": str(translated_srt),
                        "dubbed_final_full_srt": str(bilingual_srt),
                        "source_full_srt": str(source_srt),
                    },
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260504_202927"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        with patch.object(dubbing_cli_api, "_rerun_segment_with_translated_srt", return_value=None), patch.object(
            dubbing_cli_api, "_rebuild_batch_outputs", return_value={"batch_rebuilt": True}
        ):
            response = self.client.post(
                f"/dubbing/auto/review/{task_id}/save-and-redub",
                data={"edits_json": json.dumps([{"index": 1, "translated_text": "你好（重配）"}], ensure_ascii=False)},
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "saved_and_redubbed")
        self.assertEqual(payload["redubbed_segments"], 1)

    def test_review_redub_failed_no_candidates_keeps_task_completed(self):
        """没有 missing/manual_review 候选时，redub-failed 应返回 no_candidates。"""

        batch_dir = self.output_root / "web_20260504_220010" / "longdub_20260504_220010"
        final_dir = batch_dir / "final"
        segment_dir = batch_dir / "segment_jobs" / "segment_0001"
        subtitles_dir = segment_dir / "subtitles"
        subtitles_dir.mkdir(parents=True, exist_ok=True)
        final_dir.mkdir(parents=True, exist_ok=True)

        source_srt = final_dir / "source_full.srt"
        translated_srt = final_dir / "translated_full.srt"
        bilingual_srt = final_dir / "dubbed_final_full.srt"
        source_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        translated_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
        bilingual_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\nHello\n", encoding="utf-8")
        (subtitles_dir / "source.srt").write_text(source_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (subtitles_dir / "translated.srt").write_text(translated_srt.read_text(encoding="utf-8"), encoding="utf-8")
        (subtitles_dir / "dubbed_final.srt").write_text(bilingual_srt.read_text(encoding="utf-8"), encoding="utf-8")
        audio_path = segment_dir / "dubbed_segments" / "seg_0001.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"real")
        (segment_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "input_media_path": str(self.upload_root / "in.mp4"),
                    "segments": [{"id": "seg_0001", "start_sec": 0.0, "end_sec": 2.0, "translated_text": "你好", "status": "done", "tts_audio_path": str(audio_path)}],
                }
            ),
            encoding="utf-8",
        )
        (batch_dir / "batch_manifest.json").write_text(
            json.dumps(
                {
                    "batch_id": "longdub_20260504_220010",
                    "segments_total": 1,
                    "segments": [{"index": 1, "start_sec": 0.0, "summary": {"total": 1, "done": 1, "manual_review": 0}, "job_dir": str(segment_dir)}],
                    "paths": {
                        "translated_full_srt": str(translated_srt),
                        "dubbed_final_full_srt": str(bilingual_srt),
                        "source_full_srt": str(source_srt),
                    },
                }
            ),
            encoding="utf-8",
        )

        loaded = self.client.post("/dubbing/auto/load-batch", data={"batch_id": "longdub_20260504_220010"})
        self.assertEqual(loaded.status_code, 200)
        task_id = loaded.json()["id"]

        with patch.object(dubbing_cli_api, "_rerun_segment_with_translated_srt", return_value=None) as rerun_mock:
            response = self.client.post(f"/dubbing/auto/review/{task_id}/redub-failed")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "no_candidates")
        rerun_mock.assert_not_called()

    def test_compact_process_error_output_filters_flash_attn_noise(self):
        """错误提炼应过滤 flash-attn 噪音。"""

        stdout = "[INFO] init:job_started - dubbing job started\nPipeline failed: Translation API key is required."
        stderr = "********\nWarning: flash-attn is not installed. Will only run the manual PyTorch version.\n********\n"
        detail = dubbing_cli_api._compact_process_error_output(stdout, stderr, keep_lines=20)
        self.assertIn("Pipeline failed: Translation API key is required.", detail)
        self.assertNotIn("flash-attn", detail)

    def test_switch_tts_runtime_on_demand_always_ensures_index_tts(self):
        """Auto Dubbing 收口后，运行时切换只应保证 index-tts 服务就绪。"""

        with patch.object(dubbing_cli_api, "_ensure_index_tts_service", return_value=None) as ensure_mock:
            dubbing_cli_api._switch_tts_runtime_on_demand(
                tts_backend="omnivoice",
                index_tts_api_url="http://127.0.0.1:8011",
            )

        ensure_mock.assert_called_once_with("http://127.0.0.1:8011")


@unittest.skipIf(bool(API_TEST_SKIP_REASON), API_TEST_SKIP_REASON or "")
class DubbingCliApiFailureParsingTests(unittest.TestCase):
    """覆盖 CLI 失败摘要提取规则。"""

    def test_extract_cli_failure_detail_prefers_pipeline_failed_line(self):
        stdout_tail = [
            "[INFO] translate:translation_started - translating subtitles",
            "[ERROR] finish:job_failed - pipeline failed",
            "Pipeline failed: Connection error.",
            "Traceback (most recent call last):",
            '  File "/tmp/a.py", line 1, in <module>',
            '    raise RuntimeError("command failed")',
            "RuntimeError: command failed (1): uv run python tools/dub_pipeline.py ...",
        ]

        detail = dubbing_cli_api._extract_cli_failure_detail(stdout_tail)
        self.assertEqual(detail, "Pipeline failed: Connection error.")

        message = dubbing_cli_api._build_cli_exit_error(1, stdout_tail)
        self.assertIn("Pipeline failed: Connection error.", message)
        self.assertNotIn("RuntimeError: command failed", message)

    def test_extract_cli_failure_detail_maps_translation_401_to_auth_message(self):
        stdout_tail = [
            '[INFO] translate:translation_started - translating subtitles',
            'HTTP Request: POST https://api.freemodel.dev/v1/chat/completions "HTTP/1.1 401 Unauthorized"',
            "Pipeline failed: Error code: 401 - {'error': 'Internal server error'}",
        ]

        detail = dubbing_cli_api._extract_cli_failure_detail(stdout_tail)
        self.assertIsNotNone(detail)
        self.assertIn("authentication failed", str(detail).lower())
        self.assertIn("http 401", str(detail).lower())


if __name__ == "__main__":
    unittest.main()
