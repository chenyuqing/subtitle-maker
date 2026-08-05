from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "repair_bad_segments.py"
MODULE_SPEC = importlib.util.spec_from_file_location("test_repair_bad_segments_module", MODULE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
repair_bad_segments = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = repair_bad_segments
sys.modules.setdefault("soundfile", SimpleNamespace())
MODULE_SPEC.loader.exec_module(repair_bad_segments)


@pytest.mark.unit
class RepairBadSegmentsTests(unittest.TestCase):
    def test_resolve_segment_reference_audio_prefers_manifest_speaker_ref_map(self) -> None:
        """修复脚本应优先使用 manifest 里的 speaker_ref_map，而不是 refs/ 旧路径。"""

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            ref_audio = tmp_path / "speaker_ref.wav"
            ref_audio.write_bytes(b"wav")
            segment_job_dir = tmp_path / "segment_0001"
            segment_job_dir.mkdir(parents=True, exist_ok=True)

            manifest = {
                "speaker_ref_map": [
                    {"speaker_id": "Speaker 1", "ref_audio_path": str(ref_audio)},
                ]
            }

            resolved = repair_bad_segments._resolve_segment_reference_audio(manifest, segment_job_dir)

        self.assertEqual(resolved, ref_audio)


if __name__ == "__main__":
    unittest.main()
