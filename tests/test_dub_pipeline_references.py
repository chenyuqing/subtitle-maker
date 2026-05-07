from __future__ import annotations

import inspect
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
DUB_PIPELINE_PATH = REPO_ROOT / "tools" / "dub_pipeline.py"
MODULE_SPEC = importlib.util.spec_from_file_location("test_dub_pipeline_references_module", DUB_PIPELINE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
dub_pipeline = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = dub_pipeline


class _FakeTorch:
    float16 = "float16"
    bfloat16 = "bfloat16"
    float32 = "float32"


sys.modules.setdefault("torch", _FakeTorch())
sys.modules.setdefault("ffmpeg", SimpleNamespace())
sys.modules.setdefault("openai", SimpleNamespace(OpenAI=object))
sys.modules.setdefault("librosa", SimpleNamespace())
sys.modules.setdefault("transformers", SimpleNamespace(AutoModelForCausalLM=object, AutoTokenizer=object))
sys.modules.setdefault(
    "qwen_asr",
    SimpleNamespace(Qwen3ASRModel=object, Qwen3ForcedAligner=object),
)
sys.modules.setdefault(
    "qwen_asr.core.transformers_backend.processing_qwen3_asr",
    SimpleNamespace(Qwen3ASRProcessor=object),
)
class _FakeSoundFile:
    @staticmethod
    def read(_path):
        return [], 16000

    @staticmethod
    def write(_path, _data, _sr):
        return None

    @staticmethod
    def info(_path):
        return SimpleNamespace(duration=1.0)

original_soundfile_module = sys.modules.get("soundfile")
original_subtitle_modules = {
    name: module
    for name, module in sys.modules.items()
    if name == "subtitle_maker" or name.startswith("subtitle_maker.")
}
sys.modules["soundfile"] = _FakeSoundFile()
MODULE_SPEC.loader.exec_module(dub_pipeline)
if original_soundfile_module is None:
    sys.modules.pop("soundfile", None)
else:
    sys.modules["soundfile"] = original_soundfile_module
for name in list(sys.modules.keys()):
    if name == "subtitle_maker" or name.startswith("subtitle_maker."):
        if name not in original_subtitle_modules:
            sys.modules.pop(name, None)
for name, module in original_subtitle_modules.items():
    sys.modules[name] = module


class DubPipelineReferenceTests(unittest.TestCase):
    def test_extract_reference_audio_from_first_subtitle_impl_is_used_for_single_default(self) -> None:
        """单人模式默认参考音应从首条字幕起点开始截取，不再直接从整段音频首个能量峰取。"""

        source = inspect.getsource(dub_pipeline.main)
        self.assertIn("extract_reference_audio_from_first_subtitle(", source)

    def test_build_backend_reference_selector_reuses_first_track_reference_for_same_speaker(self) -> None:
        """当前参考音选择器应逐句命中 subtitle_ref_map。"""

        tmpdir = Path(tempfile.mkdtemp(prefix="dub_pipeline_track_ref_test_"))
        default_ref = tmpdir / "shared.wav"
        ref_a = tmpdir / "track_a_first.wav"
        ref_b = tmpdir / "track_a_second.wav"
        ref_unknown = tmpdir / "unknown.wav"
        for path in (default_ref, ref_a, ref_b, ref_unknown):
            path.write_bytes(b"wav")

        subtitles = [
            {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_track_id": "track_a"},
            {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_track_id": "track_a"},
            {"start": 2.0, "end": 3.0, "text": "第三句", "speaker_track_id": "unknown"},
        ]
        subtitle_ref_map = {
            0: ref_a,
            1: ref_b,
            2: ref_unknown,
        }

        with patch.object(dub_pipeline, "read_reference_duration_sec", return_value=2.0):
            selector, stats = dub_pipeline.build_backend_reference_selector(
                tts_backend="index-tts",
                subtitles=subtitles,
                subtitle_ref_map=subtitle_ref_map,
                default_ref=default_ref,
            )

        self.assertEqual(selector(0).audio_path, ref_a)
        self.assertEqual(selector(1).audio_path, ref_b)
        self.assertEqual(selector(2).audio_path, ref_unknown)
        self.assertEqual(selector(0).reference_text, "第一句")
        self.assertEqual(stats["reference_strategy"], "sentence_original_audio_per_subtitle")

    def test_main_multi_mode_does_not_fallback_to_single_ref(self) -> None:
        """严格多人模式应走专用 helper，而不是在 main 里内联回退逻辑。"""

        source = inspect.getsource(dub_pipeline.main)
        self.assertIn("build_strict_speaker_reference_selector(", source)
        self.assertIn("index-tts strict speaker mapping missing reference for", source)

    def test_main_no_longer_reads_removed_legacy_runtime_args(self) -> None:
        """CLI parser 已删掉旧底座参数后，main 也不能再读取这些不存在的 args.*。"""

        source = inspect.getsource(dub_pipeline.main)
        self.assertNotIn("args.fallback_tts_backend", source)
        self.assertNotIn("args.omnivoice_root", source)
        self.assertNotIn("args.omnivoice_python_bin", source)
        self.assertNotIn("args.omnivoice_model", source)
        self.assertNotIn("args.omnivoice_device", source)
        self.assertNotIn("args.omnivoice_via_api", source)
        self.assertNotIn("args.omnivoice_api_url", source)
        self.assertNotIn("args.voxcpm_api_url", source)

    def test_main_index_tts_multi_with_speaker_map_uses_strict_speaker_reference_strategy(self) -> None:
        """Index-TTS 多人模式传入 speaker_ref_map_json 时，应启用严格 speaker 映射策略。"""

        source = inspect.getsource(dub_pipeline.main)
        self.assertIn("build_strict_speaker_reference_selector(", source)

    def test_main_index_tts_multi_with_speaker_map_validates_missing_speaker_id_rows(self) -> None:
        """Index-TTS 严格 speaker 模式应对缺失 speaker_id 行直接报错。"""

        source = inspect.getsource(dub_pipeline.main)
        self.assertIn("index-tts strict speaker mapping missing speaker_id at row", source)

    def test_main_index_tts_multi_with_speaker_map_validates_missing_reference_mapping(self) -> None:
        """Index-TTS 严格 speaker 模式应对未映射 speaker_id 直接报错。"""

        source = inspect.getsource(dub_pipeline.main)
        self.assertIn("index-tts strict speaker mapping missing reference for", source)

    def test_build_strict_speaker_reference_selector_uses_uploaded_reference_map(self) -> None:
        """严格 speaker 模式应直接使用上传映射，不依赖逐句 subtitle_ref_map。"""

        tmpdir = Path(tempfile.mkdtemp(prefix="dub_pipeline_strict_speaker_refs_"))
        speaker_a = tmpdir / "speaker_a.wav"
        speaker_b = tmpdir / "speaker_b.wav"
        speaker_a.write_bytes(b"a")
        speaker_b.write_bytes(b"b")
        selector, stats = dub_pipeline.build_strict_speaker_reference_selector(
            subtitles=[
                {"start": 0.0, "end": 1.0, "text": "第一句", "speaker_id": "Speaker 1"},
                {"start": 1.0, "end": 2.0, "text": "第二句", "speaker_id": "Speaker 2"},
            ],
            speaker_ref_map={
                "Speaker 1": speaker_a,
                "Speaker 2": speaker_b,
            },
            detected_speaker_ids=["Speaker 1", "Speaker 2"],
        )

        self.assertEqual(selector(0).audio_path, speaker_a)
        self.assertEqual(selector(1).audio_path, speaker_b)
        self.assertEqual(selector(0).reference_text, "第一句")
        self.assertEqual(stats["reference_strategy"], "index_tts_strict_speaker_refs")
        self.assertEqual(stats["subtitle_reference_count"], 0)

    def test_enforce_subtitle_timestamps_preserves_speaker_metadata(self) -> None:
        """时间戳校正不应丢失 speaker_id 等元数据。"""

        normalized = dub_pipeline.enforce_subtitle_timestamps(
            subtitles=[
                {"start": 0.0, "end": 1.0, "text": "A", "speaker_id": "Speaker 1"},
                {"start": 1.0, "end": 2.0, "text": "B", "speaker_id": "Speaker 2"},
            ],
            media_duration_sec=2.0,
        )
        self.assertEqual([row.get("speaker_id") for row in normalized], ["Speaker 1", "Speaker 2"])

    def test_main_builds_subtitle_reference_map_from_vocals_stem(self) -> None:
        """当前 CLI 主链路必须从 vocals stem 抽逐句参考音，不能回退到原始混音。"""

        source = inspect.getsource(dub_pipeline.main)
        self.assertIn("source_audio=separation.vocals_audio", source)

if __name__ == "__main__":
    unittest.main()
