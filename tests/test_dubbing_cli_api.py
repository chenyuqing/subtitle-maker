from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

API_TEST_SKIP_REASON = ""
try:
    from subtitle_maker import dubbing_cli_api
    from subtitle_maker import omnivoice_dub_api
    from subtitle_maker import web
    from subtitle_maker.domains.media import compose as media_compose
except ModuleNotFoundError as exc:  # pragma: no cover - 仅在缺三方依赖的本地环境触发
    dubbing_cli_api = None
    omnivoice_dub_api = None
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

        dubbing_cli_api._tasks.clear()
        dubbing_cli_api.legacy_runtime.tasks.clear()
        omnivoice_dub_api._task_store.clear()
        FakeThread.instances = []

        self.patchers = [
            patch.object(dubbing_cli_api, "UPLOAD_ROOT", self.upload_root),
            patch.object(dubbing_cli_api, "OUTPUT_ROOT", self.output_root),
            patch.object(dubbing_cli_api, "TOOL_PATH", self.tool_path),
            patch.object(dubbing_cli_api.legacy_runtime, "UPLOAD_DIR", str(self.upload_root)),
            patch.object(omnivoice_dub_api, "OUTPUT_ROOT", self.omnivoice_output_root),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(dubbing_cli_api._tasks.clear)
        self.addCleanup(dubbing_cli_api.legacy_runtime.tasks.clear)
        self.addCleanup(omnivoice_dub_api._task_store.clear)
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
                target_lang="中文",
                api_key="",
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                translate_system_prompt="",
                task_id="unit_test",
            )

        self.assertEqual(mode, "source")
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
                target_lang="Chinese",
                api_key="",
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                translate_system_prompt="",
                task_id="unit_test",
            )

        self.assertEqual(mode, "source")
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
                target_lang="Chinese",
                api_key="",
                translate_base_url="https://api.deepseek.com",
                translate_model="deepseek-v4-flash",
                translate_system_prompt="",
                task_id="unit_test",
            )

        self.assertEqual(mode, "source")
        self.assertEqual(len(rows), 2)
        self.assertIn("中文", rows[0]["text"])
        self.assertEqual(rows[1]["text"], "第二行")

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
