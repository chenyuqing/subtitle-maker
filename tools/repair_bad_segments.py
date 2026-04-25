#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from subtitle_maker.transcriber import format_srt, parse_srt
from subtitle_maker.backends import (
    check_index_tts_service as check_index_tts_service_impl,
    synthesize_via_index_tts_api as synthesize_via_index_tts_api_impl,
)
from subtitle_maker.core.ffmpeg import (
    run_cmd as run_cmd_impl,
    run_cmd_checked as run_cmd_checked_impl,
)
from subtitle_maker.domains.dubbing import (
    build_atempo_filter_chain as build_atempo_filter_chain_impl,
    compute_effective_target_duration as compute_effective_target_duration_impl,
    fit_audio_to_duration as fit_audio_to_duration_impl,
    trim_silence_edges as trim_silence_edges_impl,
)
from subtitle_maker.domains.media import (
    audio_duration as audio_duration_impl,
    compose_vocals_master as compose_vocals_master_impl,
    concat_wav_files as concat_wav_files_impl,
    merge_bilingual_srt_files as merge_bilingual_srt_files_impl,
    merge_srt_files as merge_srt_files_impl,
    mix_with_bgm as mix_with_bgm_impl,
)
from subtitle_maker.translator import Translator


def iso_now() -> str:
    return datetime.utcnow().isoformat()


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """兼容旧入口：执行命令并返回退出码、stdout、stderr。"""
    return run_cmd_impl(cmd, cwd=cwd)


def run_cmd_checked(cmd: List[str], cwd: Optional[Path] = None) -> None:
    """兼容旧入口：执行命令，失败时保留 stdout/stderr 并抛出异常。"""
    return run_cmd_checked_impl(cmd, cwd=cwd)


def audio_duration(path: Path) -> float:
    """兼容旧入口：读取音频元信息并返回时长秒数。"""
    return audio_duration_impl(path)


def is_cjk_target_lang(target_lang: str) -> bool:
    lowered = (target_lang or "").strip().lower()
    markers = ["chinese", "中文", "mandarin", "cantonese", "zh", "japanese", "korean", "日文", "韩文"]
    return any(marker in lowered for marker in markers)


def merge_text_lines(lines: List[str], *, cjk_mode: bool) -> str:
    if cjk_mode:
        merged = "".join((line or "").strip() for line in lines)
        merged = re.sub(r"\s+", "", merged)
        return merged
    merged = " ".join((line or "").strip() for line in lines)
    merged = re.sub(r"\s+", " ", merged).strip()
    merged = re.sub(r"\s+([,.;:!?])", r"\1", merged)
    return merged


def has_speakable_content(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    return any(char.isalnum() for char in compact)


def is_punctuation_only_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    return bool(re.fullmatch(r"[,.;:!?，。！？、；：…\"'`~\-—_(){}\[\]<>/|\\]+", compact))


def _http_json_request(
    *,
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]],
    timeout_sec: float,
) -> Dict[str, Any]:
    data: Optional[bytes] = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url=url,
        data=data,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"index-tts api http {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"index-tts api connect failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"index-tts api request failed: {exc}") from exc

    try:
        return json.loads(body)
    except Exception as exc:
        raise RuntimeError(f"index-tts api invalid json: {body[:200]}") from exc


def check_index_tts_service(*, api_url: str, timeout_sec: float) -> Dict[str, Any]:
    """兼容旧入口：检查 Index-TTS API 健康状态。"""
    return check_index_tts_service_impl(api_url=api_url, timeout_sec=timeout_sec)


def synthesize_via_index_tts_api(
    *,
    api_url: str,
    timeout_sec: float,
    text: str,
    ref_audio_path: Path,
    output_path: Path,
    top_p: float,
    top_k: int,
    temperature: float,
    max_text_tokens: int,
) -> None:
    """兼容旧入口：通过 Index-TTS API 执行一次合成。"""
    return synthesize_via_index_tts_api_impl(
        api_url=api_url,
        timeout_sec=timeout_sec,
        text=text,
        ref_audio_path=ref_audio_path,
        output_path=output_path,
        emo_audio_prompt=None,
        emo_alpha=1.0,
        use_emo_text=False,
        emo_text=None,
        top_p=top_p,
        top_k=top_k,
        temperature=temperature,
        max_text_tokens=max_text_tokens,
    )


def build_atempo_filter_chain(tempo: float) -> str:
    """兼容旧入口：构造 ffmpeg atempo 过滤链。"""
    return build_atempo_filter_chain_impl(tempo)


def fit_audio_to_duration(
    *,
    input_path: Path,
    output_path: Path,
    target_duration_sec: float,
) -> None:
    """兼容旧入口：把音频拟合到目标时长。"""
    return fit_audio_to_duration_impl(
        input_path=input_path,
        output_path=output_path,
        target_duration_sec=target_duration_sec,
    )


def compute_effective_target_duration(
    *,
    start_sec: float,
    end_sec: float,
    next_start_sec: float | None,
    gap_guard_sec: float = 0.10,
) -> Tuple[float, float]:
    """兼容旧入口：计算可借静音后的有效目标时长。"""
    return compute_effective_target_duration_impl(
        start_sec=start_sec,
        end_sec=end_sec,
        next_start_sec=next_start_sec,
        gap_guard_sec=gap_guard_sec,
    )


def trim_silence_edges(
    *,
    input_path: Path,
    output_path: Path,
    threshold_db: float = -35.0,
    pad_sec: float = 0.03,
    min_keep_sec: float = 0.10,
) -> Tuple[float, float]:
    """兼容旧入口：裁掉音频首尾静音。"""
    return trim_silence_edges_impl(
        input_path=input_path,
        output_path=output_path,
        threshold_db=threshold_db,
        pad_sec=pad_sec,
        min_keep_sec=min_keep_sec,
    )


def compose_vocals_master(
    *,
    segments: List[Dict[str, Any]],
    output_path: Path,
) -> Tuple[Path, int]:
    """兼容旧入口：把逐句或逐段配音按时间轴回填为一条 master vocals。"""
    return compose_vocals_master_impl(segments=segments, output_path=output_path)


def mix_with_bgm(
    *,
    vocals_path: Path,
    bgm_path: Path,
    output_path: Path,
    target_sr: int,
) -> None:
    """兼容旧入口：混合配音人声和背景音。"""
    return mix_with_bgm_impl(
        vocals_path=vocals_path,
        bgm_path=bgm_path,
        output_path=output_path,
        target_sr=target_sr,
        error_prefix=None,
    )


def concat_wav_files(inputs: List[Path], output_wav: Path) -> None:
    """兼容旧入口：拼接多个 wav 文件。"""
    return concat_wav_files_impl(inputs, output_wav, sample_rate=44100, error_on_empty=False)


def merge_srt_files(
    *,
    inputs: List[Tuple[Path, float]],
    output_srt: Path,
) -> None:
    """兼容旧入口：把多段 SRT 按全局时间轴偏移拼接为完整字幕。"""
    return merge_srt_files_impl(inputs=inputs, output_srt=output_srt)


def merge_bilingual_srt_files(
    *,
    translated_inputs: List[Tuple[Path, float]],
    source_inputs: List[Tuple[Path, float]],
    output_srt: Path,
    translated_first: bool = True,
) -> None:
    """兼容旧入口：把原文和译文双轨字幕拼接为完整双语字幕。"""
    return merge_bilingual_srt_files_impl(
        translated_inputs=translated_inputs,
        source_inputs=source_inputs,
        output_srt=output_srt,
        translated_first=translated_first,
    )


def resolve_output_path(path_text: Optional[str]) -> Optional[Path]:
    if not path_text:
        return None
    raw = Path(path_text).expanduser()
    if raw.is_absolute():
        return raw
    return (REPO_ROOT / raw).resolve()


def repair_segment_job(
    *,
    segment_job_dir: Path,
    translator: Translator,
    target_lang: str,
    api_url: str,
    api_timeout_sec: float,
    top_p: float,
    top_k: int,
    temperature: float,
    max_text_tokens: int,
) -> Dict[str, Any]:
    manifest_path = segment_job_dir / "manifest.json"
    source_srt_path = segment_job_dir / "subtitles" / "source.srt"
    translated_srt_path = segment_job_dir / "subtitles" / "translated.srt"
    dubbed_final_srt_path = segment_job_dir / "subtitles" / "dubbed_final.srt"
    ref_audio_path = segment_job_dir / "refs" / "single_speaker_ref.wav"
    segment_audio_dir = segment_job_dir / "dubbed_segments"

    if not manifest_path.exists():
        raise RuntimeError(f"manifest not found: {manifest_path}")
    if not source_srt_path.exists() or not translated_srt_path.exists():
        raise RuntimeError(f"srt not found in {segment_job_dir}")
    if not ref_audio_path.exists():
        raise RuntimeError(f"ref audio not found: {ref_audio_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    segment_records = manifest.get("segments", [])
    source_subs = parse_srt(source_srt_path.read_text(encoding="utf-8"))
    translated_subs = parse_srt(translated_srt_path.read_text(encoding="utf-8"))
    if len(source_subs) != len(translated_subs):
        raise RuntimeError("source/translated count mismatch")
    if len(source_subs) != len(segment_records):
        raise RuntimeError("manifest/srt count mismatch")

    bad_indices: List[int] = []
    for idx, (src, tgt) in enumerate(zip(source_subs, translated_subs)):
        src_text = (src["text"] or "").strip()
        tgt_text = (tgt["text"] or "").strip()
        if has_speakable_content(src_text) and is_punctuation_only_text(tgt_text):
            bad_indices.append(idx)

    if not bad_indices:
        return {
            "segment_job": segment_job_dir.name,
            "bad_lines": 0,
            "repaired_lines": 0,
            "affected_groups": 0,
        }

    retry_inputs = [source_subs[idx]["text"] for idx in bad_indices]
    retry_system_prompt = (
        "You are a professional subtitle translator. "
        "Translate each input line faithfully and naturally. "
        "Never output only punctuation or ellipsis."
    )
    retried = translator.translate_batch(
        retry_inputs,
        target_lang=target_lang,
        system_prompt=retry_system_prompt,
        chunk_size=50,
    )

    translated_lines = [item["text"] for item in translated_subs]
    repaired_lines = 0
    for idx, candidate in zip(bad_indices, retried):
        text = (candidate or "").strip()
        if text and has_speakable_content(text) and not is_punctuation_only_text(text):
            translated_lines[idx] = text
            repaired_lines += 1
        else:
            translated_lines[idx] = (source_subs[idx]["text"] or "").strip()

    for idx, line in enumerate(translated_lines):
        translated_subs[idx]["text"] = line
        source_subs[idx]["text"] = source_subs[idx]["text"]
        segment_records[idx]["translated_text"] = line

    translated_srt_path.write_text(format_srt(translated_subs), encoding="utf-8")
    dubbed_final_items: List[Dict[str, Any]] = []
    for src, line in zip(source_subs, translated_lines):
        dubbed_final_items.append(
            {
                "start": float(src["start"]),
                "end": float(src["end"]),
                "text": line,
            }
        )
    dubbed_final_srt_path.write_text(format_srt(dubbed_final_items), encoding="utf-8")

    cjk_mode = is_cjk_target_lang(target_lang)
    affected_group_ids = sorted(
        {
            segment_records[idx].get("group_id")
            for idx in bad_indices
            if segment_records[idx].get("group_id")
        }
    )

    for group_id in affected_group_ids:
        group_members: List[Tuple[int, Dict[str, Any]]] = [
            (index, record)
            for index, record in enumerate(segment_records)
            if record.get("group_id") == group_id
        ]
        group_members.sort(key=lambda item: float(item[1]["start_sec"]))
        if not group_members:
            continue

        anchor_index, anchor_record = next(
            (
                (index, record)
                for index, record in group_members
                if not bool(record.get("skip_compose", False))
            ),
            group_members[0],
        )
        group_text = merge_text_lines(
            [record.get("translated_text", "") for _, record in group_members],
            cjk_mode=cjk_mode,
        )
        group_target_duration = max(0.05, float(anchor_record.get("target_duration_sec", 0.05)))
        group_start_sec = float(group_members[0][1].get("start_sec", 0.0) or 0.0)
        group_end_sec = float(anchor_record.get("group_anchor_end_sec", anchor_record.get("end_sec", group_start_sec)) or group_start_sec)
        next_start_sec: float | None = None
        for candidate in segment_records:
            candidate_start = float(candidate.get("start_sec", group_end_sec) or group_end_sec)
            candidate_group = candidate.get("group_id")
            if candidate_group == group_id:
                continue
            if candidate_start >= group_end_sec - 1e-6:
                if next_start_sec is None or candidate_start < next_start_sec:
                    next_start_sec = candidate_start
        effective_target_duration, borrowed_gap_sec = compute_effective_target_duration(
            start_sec=group_start_sec,
            end_sec=group_end_sec,
            next_start_sec=next_start_sec,
        )

        raw_path = segment_audio_dir / f"{group_id}_raw.wav"
        trim_path = segment_audio_dir / f"{group_id}_trim.wav"
        fit_path = segment_audio_dir / f"{group_id}_fit.wav"
        silent_path = segment_audio_dir / f"{group_id}_silent.wav"
        segment_audio_dir.mkdir(parents=True, exist_ok=True)

        if has_speakable_content(group_text):
            synthesize_via_index_tts_api(
                api_url=api_url,
                timeout_sec=api_timeout_sec,
                text=group_text,
                ref_audio_path=ref_audio_path,
                output_path=raw_path,
                top_p=top_p,
                top_k=top_k,
                temperature=temperature,
                max_text_tokens=max_text_tokens,
            )
            use_path = raw_path
            _, after_trim = trim_silence_edges(
                input_path=raw_path,
                output_path=trim_path,
            )
            if after_trim >= 0.05:
                use_path = trim_path
            fit_audio_to_duration(
                input_path=use_path,
                output_path=fit_path,
                target_duration_sec=effective_target_duration,
            )
            use_path = fit_path
        else:
            ref_sr = 16000
            try:
                ref_sr = max(8000, int(sf.info(str(ref_audio_path)).samplerate))
            except Exception:
                ref_sr = 16000
            sample_count = max(1, int(round(group_target_duration * ref_sr)))
            sf.write(str(silent_path), np.zeros(sample_count, dtype=np.float32), ref_sr)
            use_path = silent_path

        actual = audio_duration(use_path)
        delta = actual - group_target_duration
        effective_delta = actual - effective_target_duration

        for index, record in group_members:
            record["tts_audio_path"] = str(use_path.resolve())
            if index == anchor_index:
                record["group_text"] = group_text
                record["actual_duration_sec"] = round(actual, 3)
                record["delta_sec"] = round(delta, 3)
                record["effective_target_duration_sec"] = round(effective_target_duration, 3)
                record["borrowed_gap_sec"] = round(borrowed_gap_sec, 3)
                record["effective_delta_sec"] = round(effective_delta, 3)
                record["status"] = "done"
                record["skip_compose"] = False
                if "group_anchor_end_sec" not in record:
                    record["group_anchor_end_sec"] = record.get("end_sec")

    vocals_path = resolve_output_path(manifest.get("paths", {}).get("dubbed_vocals")) or (segment_job_dir / "dubbed_vocals.wav")
    vocals_path = vocals_path.resolve()
    vocals_path.parent.mkdir(parents=True, exist_ok=True)
    vocals_master, sr = compose_vocals_master(segments=segment_records, output_path=vocals_path)

    bgm_path = resolve_output_path(manifest.get("paths", {}).get("source_bgm"))
    mix_path = resolve_output_path(manifest.get("paths", {}).get("dubbed_mix")) or (segment_job_dir / "dubbed_mix.wav")
    if bgm_path and bgm_path.exists():
        mix_path = mix_path.resolve()
        mix_path.parent.mkdir(parents=True, exist_ok=True)
        mix_with_bgm(vocals_path=vocals_master, bgm_path=bgm_path, output_path=mix_path, target_sr=sr)

    manifest["updated_at"] = iso_now()
    manifest["segments"] = segment_records
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "segment_job": segment_job_dir.name,
        "bad_lines": len(bad_indices),
        "repaired_lines": repaired_lines,
        "affected_groups": len(affected_group_ids),
    }


def rebuild_batch_outputs(batch_dir: Path) -> Dict[str, Any]:
    batch_manifest_path = batch_dir / "batch_manifest.json"
    if not batch_manifest_path.exists():
        return {"batch_rebuilt": False, "reason": "batch_manifest_missing"}

    batch_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
    segment_entries = sorted(batch_manifest.get("segments", []), key=lambda item: int(item["index"]))
    final_paths = batch_manifest.get("paths", {})

    vocals_inputs: List[Path] = []
    mix_inputs: List[Path] = []
    bgm_inputs: List[Path] = []
    source_srt_inputs: List[Tuple[Path, float]] = []
    translated_srt_inputs: List[Tuple[Path, float]] = []
    dubbed_final_srt_inputs: List[Tuple[Path, float]] = []
    # 复用 dub_long_video 的“全时轴重建”能力所需上下文。
    segment_runtime_items: List[Dict[str, Any]] = []

    for entry in segment_entries:
        start_sec = float(entry["start_sec"])
        job_dir = Path(entry["job_dir"])
        manifest_path = job_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        paths = manifest.get("paths", {})

        vocals = resolve_output_path(paths.get("dubbed_vocals"))
        mix = resolve_output_path(paths.get("dubbed_mix"))
        bgm = resolve_output_path(paths.get("source_bgm"))
        source_srt = resolve_output_path(paths.get("source_srt"))
        translated_srt = resolve_output_path(paths.get("translated_srt"))
        dubbed_final_srt = resolve_output_path(paths.get("dubbed_final_srt"))

        fallback_source_srt = job_dir / "subtitles" / "source.srt"
        fallback_translated_srt = job_dir / "subtitles" / "translated.srt"
        fallback_dubbed_final_srt = job_dir / "subtitles" / "dubbed_final.srt"
        if (source_srt is None or not source_srt.exists()) and fallback_source_srt.exists():
            source_srt = fallback_source_srt
        if (translated_srt is None or not translated_srt.exists()) and fallback_translated_srt.exists():
            translated_srt = fallback_translated_srt
        if (dubbed_final_srt is None or not dubbed_final_srt.exists()) and fallback_dubbed_final_srt.exists():
            dubbed_final_srt = fallback_dubbed_final_srt

        if vocals and vocals.exists():
            vocals_inputs.append(vocals)
        if mix and mix.exists():
            mix_inputs.append(mix)
        if bgm and bgm.exists():
            bgm_inputs.append(bgm)
        if source_srt and source_srt.exists():
            source_srt_inputs.append((source_srt, start_sec))
        if translated_srt and translated_srt.exists():
            translated_srt_inputs.append((translated_srt, start_sec))
        if dubbed_final_srt and dubbed_final_srt.exists():
            dubbed_final_srt_inputs.append((dubbed_final_srt, start_sec))
        segment_audio = resolve_output_path(entry.get("segment_audio")) or (batch_dir / "segments" / f"segment_{int(entry['index']):04d}.wav")
        segment_runtime_items.append(
            {
                "index": int(entry["index"]),
                "start_sec": start_sec,
                "end_sec": float(entry.get("end_sec", start_sec) or start_sec),
                "segment_audio": segment_audio,
                "job_dir": job_dir,
                "manifest": manifest,
            }
        )

    out_vocals = resolve_output_path(final_paths.get("dubbed_vocals_full")) or (batch_dir / "final" / "dubbed_vocals_full.wav")
    out_mix = resolve_output_path(final_paths.get("dubbed_mix_full")) or (batch_dir / "final" / "dubbed_mix_full.wav")
    out_bgm = resolve_output_path(final_paths.get("source_bgm_full")) or (batch_dir / "final" / "source_bgm_full.wav")
    out_source_srt = resolve_output_path(final_paths.get("source_full_srt")) or (batch_dir / "final" / "source_full.srt")
    out_translated_srt = resolve_output_path(final_paths.get("translated_full_srt")) or (batch_dir / "final" / "translated_full.srt")
    out_dubbed_final_srt = resolve_output_path(final_paths.get("dubbed_final_full_srt")) or (batch_dir / "final" / "dubbed_final_full.srt")

    vocals_rebuilt = False
    mix_rebuilt = False
    bgm_rebuilt = False
    source_srt_rebuilt = False
    translated_srt_rebuilt = False
    dubbed_final_srt_rebuilt = False

    if out_vocals and len(vocals_inputs) == len(segment_entries):
        concat_wav_files(vocals_inputs, out_vocals)
        vocals_rebuilt = True
    # 优先复用 dub_long_video 的全时轴混音实现：
    # - 区间内使用分段配音/混音
    # - 区间外自动保留原始声音
    # 这样可避免局部重配后“非配音区静音”的问题。
    if out_mix:
        try:
            tool_path = REPO_ROOT / "tools" / "dub_long_video.py"
            spec = importlib.util.spec_from_file_location("dub_long_video_runtime", str(tool_path))
            if spec is not None and spec.loader is not None:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                SegmentResult = module.SegmentResult
                source_audio = (batch_dir / "source_audio.wav").resolve()
                if not source_audio.exists() and segment_runtime_items:
                    first_paths = (segment_runtime_items[0].get("manifest") or {}).get("paths") or {}
                    source_audio = resolve_output_path(first_paths.get("source_audio")) or source_audio
                if source_audio and Path(source_audio).exists():
                    timeline_results = [
                        SegmentResult(
                            index=int(item["index"]),
                            start_sec=float(item["start_sec"]),
                            end_sec=float(item["end_sec"]),
                            segment_audio=Path(item["segment_audio"]),
                            job_dir=Path(item["job_dir"]),
                            manifest=dict(item["manifest"]),
                        )
                        for item in sorted(segment_runtime_items, key=lambda value: int(value["index"]))
                    ]
                    built_mix = module.build_full_timeline_mix(
                        results=timeline_results,
                        output_wav=out_mix,
                        source_audio=Path(source_audio),
                    )
                    mix_rebuilt = bool(built_mix and Path(built_mix).exists())
        except Exception:
            mix_rebuilt = False
    # 若全时轴重建不可用，再回退到旧的拼接模式。
    # 注意：局部重配场景禁止再回退到“concat 段内 mix”。
    # 原因：该路径在某些任务会导致区间外听感异常（被误认为静音/丢原声）。
    # 若全时轴重建失败，宁可保留旧 mix，也不覆盖成潜在错误结果。
    if out_bgm and len(bgm_inputs) == len(segment_entries):
        concat_wav_files(bgm_inputs, out_bgm)
        bgm_rebuilt = True
    if out_source_srt and len(source_srt_inputs) == len(segment_entries):
        merge_srt_files(inputs=source_srt_inputs, output_srt=out_source_srt)
        source_srt_rebuilt = True
    if out_translated_srt and len(translated_srt_inputs) == len(segment_entries):
        merge_srt_files(inputs=translated_srt_inputs, output_srt=out_translated_srt)
        translated_srt_rebuilt = True
    bilingual_translated_inputs = (
        dubbed_final_srt_inputs if len(dubbed_final_srt_inputs) == len(segment_entries) else translated_srt_inputs
    )
    if out_dubbed_final_srt and len(source_srt_inputs) == len(segment_entries) and len(bilingual_translated_inputs) == len(
        segment_entries
    ):
        merge_bilingual_srt_files(
            translated_inputs=bilingual_translated_inputs,
            source_inputs=source_srt_inputs,
            output_srt=out_dubbed_final_srt,
            translated_first=True,
        )
        dubbed_final_srt_rebuilt = True

    # 关键修复：
    # 局部重配重拼时，如果某类产物未能完整重建，不要把已有 final 路径清空。
    # 否则前端会从 mix 回退到 vocals，表现成“只有配音区有声，其他像静音”。
    if vocals_rebuilt and out_vocals and out_vocals.exists():
        final_paths["dubbed_vocals_full"] = str(out_vocals.resolve())
    elif not final_paths.get("dubbed_vocals_full"):
        final_paths["dubbed_vocals_full"] = None

    if mix_rebuilt and out_mix and out_mix.exists():
        final_paths["dubbed_mix_full"] = str(out_mix.resolve())
    else:
        existing_mix = resolve_output_path(final_paths.get("dubbed_mix_full"))
        if not (existing_mix and existing_mix.exists()):
            final_paths["dubbed_mix_full"] = None

    if bgm_rebuilt and out_bgm and out_bgm.exists():
        final_paths["source_bgm_full"] = str(out_bgm.resolve())
    elif not final_paths.get("source_bgm_full"):
        final_paths["source_bgm_full"] = None

    if source_srt_rebuilt and out_source_srt and out_source_srt.exists():
        final_paths["source_full_srt"] = str(out_source_srt.resolve())
    elif not final_paths.get("source_full_srt"):
        final_paths["source_full_srt"] = None

    if translated_srt_rebuilt and out_translated_srt and out_translated_srt.exists():
        final_paths["translated_full_srt"] = str(out_translated_srt.resolve())
    elif not final_paths.get("translated_full_srt"):
        final_paths["translated_full_srt"] = None

    if dubbed_final_srt_rebuilt and out_dubbed_final_srt and out_dubbed_final_srt.exists():
        final_paths["dubbed_final_full_srt"] = str(out_dubbed_final_srt.resolve())
    elif not final_paths.get("dubbed_final_full_srt"):
        final_paths["dubbed_final_full_srt"] = None

    # 同步 preferred_audio，优先 mix，保证前端默认播放可保留原声的成品轨。
    effective_mix = resolve_output_path(final_paths.get("dubbed_mix_full"))
    effective_vocals = resolve_output_path(final_paths.get("dubbed_vocals_full"))
    if effective_mix and effective_mix.exists():
        final_paths["preferred_audio"] = str(effective_mix.resolve())
    elif effective_vocals and effective_vocals.exists():
        final_paths["preferred_audio"] = str(effective_vocals.resolve())
    else:
        final_paths["preferred_audio"] = None

    batch_manifest["updated_at"] = iso_now()
    batch_manifest["paths"] = final_paths
    batch_manifest_path.write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "batch_rebuilt": True,
        "vocals_inputs": len(vocals_inputs),
        "mix_inputs": len(mix_inputs),
        "bgm_inputs": len(bgm_inputs),
        "source_srt_inputs": len(source_srt_inputs),
        "translated_srt_inputs": len(translated_srt_inputs),
        "dubbed_final_srt_inputs": len(dubbed_final_srt_inputs),
        "vocals_rebuilt": vocals_rebuilt,
        "mix_rebuilt": mix_rebuilt,
        "bgm_rebuilt": bgm_rebuilt,
    }


def parse_segment_indexes(text: str) -> List[int]:
    items: List[int] = []
    for part in text.split(","):
        value = part.strip()
        if not value:
            continue
        items.append(int(value))
    return sorted(set(items))


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair punctuation-only bad lines for selected segment jobs.")
    parser.add_argument("--batch-dir", required=True, help="Path to longdub batch directory")
    parser.add_argument("--segment-indexes", required=True, help="Comma-separated segment indexes, e.g. 1,2")
    parser.add_argument("--target-lang", default="Chinese")
    parser.add_argument("--translate-base-url", default="https://api.deepseek.com")
    parser.add_argument("--translate-model", default="deepseek-chat")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--index-tts-api-url", default="http://127.0.0.1:8010")
    parser.add_argument("--index-tts-api-timeout-sec", type=float, default=900.0)
    parser.add_argument("--index-top-p", type=float, default=0.8)
    parser.add_argument("--index-top-k", type=int, default=30)
    parser.add_argument("--index-temperature", type=float, default=0.8)
    parser.add_argument("--index-max-text-tokens", type=int, default=120)
    args = parser.parse_args()

    batch_dir = Path(args.batch_dir).expanduser().resolve()
    if not batch_dir.exists():
        raise FileNotFoundError(f"batch dir not found: {batch_dir}")

    segment_indexes = parse_segment_indexes(args.segment_indexes)
    batch_manifest_path = batch_dir / "batch_manifest.json"
    if not batch_manifest_path.exists():
        raise RuntimeError("batch_manifest.json not found")
    batch_manifest = json.loads(batch_manifest_path.read_text(encoding="utf-8"))
    index_to_job: Dict[int, Path] = {}
    for item in batch_manifest.get("segments", []):
        index_to_job[int(item["index"])] = Path(item["job_dir"]).expanduser().resolve()

    missing = [index for index in segment_indexes if index not in index_to_job]
    if missing:
        raise RuntimeError(f"segment index not found in batch_manifest: {missing}")

    api_key = args.api_key or __import__("os").environ.get(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"missing api key (--api-key or {args.api_key_env})")

    check_index_tts_service(api_url=args.index_tts_api_url, timeout_sec=args.index_tts_api_timeout_sec)
    translator = Translator(
        api_key=api_key,
        base_url=args.translate_base_url,
        model=args.translate_model,
    )

    reports: List[Dict[str, Any]] = []
    for index in segment_indexes:
        job_dir = index_to_job[index]
        print(f"[repair] segment {index} -> {job_dir.name}")
        report = repair_segment_job(
            segment_job_dir=job_dir,
            translator=translator,
            target_lang=args.target_lang,
            api_url=args.index_tts_api_url,
            api_timeout_sec=args.index_tts_api_timeout_sec,
            top_p=args.index_top_p,
            top_k=args.index_top_k,
            temperature=args.index_temperature,
            max_text_tokens=args.index_max_text_tokens,
        )
        reports.append(report)
        print(f"[repair] done: {report}")

    rebuild = rebuild_batch_outputs(batch_dir)
    print(json.dumps({"reports": reports, "rebuild": rebuild}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
