#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import soundfile as sf
import torch
from pyannote.audio import Pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pyannote diarization in isolated python env.")
    parser.add_argument("--audio", required=True, help="Input wav path")
    parser.add_argument("--model-source", required=True, help="HF model id or local config/model path")
    parser.add_argument("--output-json", required=True, help="Output diarization json path")
    parser.add_argument("--device", default="auto", help="cpu/cuda/mps/auto")
    parser.add_argument("--hf-token", default=None, help="Optional HF token")
    return parser.parse_args()


def resolve_model_source(raw: str) -> str:
    # 关键逻辑：兼容“目录路径”与“config.yaml 文件”两种本地输入，避免 worker 侧再做网络请求
    path = Path(raw).expanduser()
    if path.exists():
        if path.is_dir():
            config = path / "config.yaml"
            if config.exists():
                return str(config.resolve())
        return str(path.resolve())
    return raw


def run_diarization(*, audio_path: Path, model_source: str, device: str, hf_token: str | None) -> List[Dict[str, Any]]:
    # 按 pyannote pipeline 输出统一结构，供主流程按字幕时间重叠映射 speaker_id
    load_kwargs: Dict[str, Any] = {}
    if hf_token:
        load_kwargs["token"] = hf_token
    pipeline = Pipeline.from_pretrained(resolve_model_source(model_source), **load_kwargs)
    if device == "auto":
        run_device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        run_device = torch.device(device)
    try:
        pipeline.to(run_device)
    except Exception:
        pass

    # 关键逻辑：使用内存波形输入，绕开 pyannote 4.x 对 torchcodec/FFmpeg 动态库的依赖
    wav, sample_rate = sf.read(str(audio_path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    waveform = torch.from_numpy(mono).unsqueeze(0)
    diarization = pipeline({"waveform": waveform, "sample_rate": int(sample_rate)})
    # 兼容 pyannote 不同版本输出：可能是 Annotation，也可能是带 speaker_diarization 的结果对象
    annotation = diarization
    if not hasattr(annotation, "itertracks"):
        if hasattr(diarization, "speaker_diarization"):
            annotation = diarization.speaker_diarization
        elif hasattr(diarization, "to_annotation"):
            annotation = diarization.to_annotation()
        else:
            raise RuntimeError(f"unsupported diarization output type: {type(diarization)}")

    output: List[Dict[str, Any]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        start = float(turn.start)
        end = float(turn.end)
        if end <= start:
            continue
        output.append({"start": start, "end": end, "speaker_id": str(speaker)})
    return output


def main() -> int:
    args = parse_args()
    audio_path = Path(args.audio).expanduser().resolve()
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    segments = run_diarization(
        audio_path=audio_path,
        model_source=args.model_source,
        device=args.device,
        hf_token=args.hf_token,
    )
    output_json.write_text(json.dumps({"segments": segments}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
