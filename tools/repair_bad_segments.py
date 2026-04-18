#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from subtitle_maker.translator import Translator


def iso_now() -> str:
    return datetime.utcnow().isoformat()


def run_cmd(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_cmd_checked(cmd: List[str], cwd: Optional[Path] = None) -> None:
    code, out, err = run_cmd(cmd, cwd=cwd)
    if code != 0:
        raise RuntimeError(f"command failed ({code}): {' '.join(cmd)}\n{out}\n{err}")


def audio_duration(path: Path) -> float:
    return float(sf.info(str(path)).duration)


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
    url = api_url.rstrip("/") + "/health"
    payload = _http_json_request(method="GET", url=url, payload=None, timeout_sec=timeout_sec)
    if not payload.get("ok"):
        raise RuntimeError(f"index-tts service unhealthy: {payload}")
    return payload


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
    payload = {
        "text": text,
        "spk_audio_prompt": str(ref_audio_path.expanduser().resolve()),
        "output_path": str(output_path.expanduser().resolve()),
        "emo_audio_prompt": None,
        "emo_alpha": 1.0,
        "use_emo_text": False,
        "emo_text": None,
        "top_p": top_p,
        "top_k": top_k,
        "temperature": temperature,
        "max_text_tokens_per_segment": max_text_tokens,
    }
    url = api_url.rstrip("/") + "/synthesize"
    result = _http_json_request(
        method="POST",
        url=url,
        payload=payload,
        timeout_sec=timeout_sec,
    )
    if not result.get("ok"):
        raise RuntimeError(f"index-tts api returned non-ok: {result}")
    if not output_path.exists():
        raise RuntimeError("index-tts api finished but output missing")


def build_atempo_filter_chain(tempo: float) -> str:
    value = max(1e-4, float(tempo))
    factors: List[float] = []
    while value > 2.0:
        factors.append(2.0)
        value /= 2.0
    while value < 0.5:
        factors.append(0.5)
        value /= 0.5
    factors.append(value)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)


def fit_audio_to_duration(
    *,
    input_path: Path,
    output_path: Path,
    target_duration_sec: float,
) -> None:
    target = max(0.05, float(target_duration_sec))
    actual = max(0.01, audio_duration(input_path))
    if actual <= target:
        filter_expr = f"apad=pad_dur={target:.6f},atrim=0:{target:.6f}"
    else:
        tempo = actual / target
        atempo_chain = build_atempo_filter_chain(tempo)
        filter_expr = f"{atempo_chain},apad=pad_dur={target:.6f},atrim=0:{target:.6f}"
    run_cmd_checked(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-filter:a",
            filter_expr,
            "-vn",
            str(output_path),
        ]
    )


def compute_effective_target_duration(
    *,
    start_sec: float,
    end_sec: float,
    next_start_sec: float | None,
    gap_guard_sec: float = 0.10,
) -> Tuple[float, float]:
    """根据下一句开始时间扩展可用时长，减少过度压缩。"""
    base_target_sec = max(0.05, float(end_sec) - float(start_sec))
    if next_start_sec is None:
        return base_target_sec, 0.0
    gap_sec = float(next_start_sec) - float(end_sec)
    if gap_sec <= 0:
        return base_target_sec, 0.0
    borrow_sec = max(0.0, gap_sec - max(0.0, float(gap_guard_sec)))
    return max(base_target_sec, base_target_sec + borrow_sec), borrow_sec


def trim_silence_edges(
    *,
    input_path: Path,
    output_path: Path,
    threshold_db: float = -35.0,
    pad_sec: float = 0.03,
    min_keep_sec: float = 0.10,
) -> Tuple[float, float]:
    wav, sr = sf.read(str(input_path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        mono = wav.mean(axis=1)
    else:
        mono = np.asarray(wav)
    mono = np.asarray(mono, dtype=np.float32)

    full_duration = float(len(mono) / sr) if len(mono) > 0 else 0.0
    if mono.size == 0:
        sf.write(str(output_path), wav, sr)
        return full_duration, full_duration

    threshold_amp = float(10 ** (threshold_db / 20.0))
    active = np.where(np.abs(mono) >= threshold_amp)[0]
    if active.size == 0:
        sf.write(str(output_path), wav, sr)
        return full_duration, full_duration

    pad_samples = max(0, int(pad_sec * sr))
    start = max(0, int(active[0]) - pad_samples)
    end = min(len(mono), int(active[-1]) + 1 + pad_samples)
    min_keep_samples = max(1, int(min_keep_sec * sr))
    if end - start < min_keep_samples:
        center = int((start + end) / 2)
        half = int(min_keep_samples / 2)
        start = max(0, center - half)
        end = min(len(mono), start + min_keep_samples)

    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        trimmed = wav[start:end, :]
    else:
        trimmed = wav[start:end]
    sf.write(str(output_path), trimmed, sr)
    trimmed_duration = float(max(0, end - start) / sr)
    return full_duration, trimmed_duration


def compose_vocals_master(
    *,
    segments: List[Dict[str, Any]],
    output_path: Path,
) -> Tuple[Path, int]:
    valid_segments = [
        segment
        for segment in segments
        if Path(segment["tts_audio_path"]).exists() and not bool(segment.get("skip_compose", False))
    ]
    if not valid_segments:
        raise RuntimeError("no segment audio produced")

    valid_segments.sort(key=lambda item: float(item["start_sec"]))

    first_audio, sr = sf.read(valid_segments[0]["tts_audio_path"])
    if isinstance(first_audio, np.ndarray) and first_audio.ndim > 1:
        first_audio = first_audio.mean(axis=1)

    max_len = 0
    cached: List[Tuple[Dict[str, Any], np.ndarray]] = []
    for index, segment in enumerate(valid_segments):
        wav, cur_sr = sf.read(segment["tts_audio_path"])
        if isinstance(wav, np.ndarray) and wav.ndim > 1:
            wav = wav.mean(axis=1)
        if cur_sr != sr:
            raise RuntimeError("inconsistent segment sample rates")

        start_sample = int(float(segment["start_sec"]) * sr)
        # 关键逻辑：若存在“借静音后”的有效目标时长，合成窗口也要同步扩展，
        # 否则会在最终拼轨阶段把尾音二次截断。
        if segment.get("effective_target_duration_sec") is not None:
            own_end_sec = float(segment["start_sec"]) + max(
                0.05, float(segment.get("effective_target_duration_sec", 0.0) or 0.0)
            )
        else:
            own_end_sec = float(segment.get("group_anchor_end_sec", segment["end_sec"]))
        own_end_sample = max(start_sample + 1, int(own_end_sec * sr))

        if index + 1 < len(valid_segments):
            next_start_sample = int(float(valid_segments[index + 1]["start_sec"]) * sr)
            if next_start_sample > start_sample:
                window_end_sample = min(own_end_sample, next_start_sample)
            else:
                window_end_sample = own_end_sample
        else:
            window_end_sample = own_end_sample

        max_allowed_len = max(1, window_end_sample - start_sample)
        clipped = np.asarray(wav, dtype=np.float32)[:max_allowed_len]
        cached.append((segment, clipped))
        max_len = max(max_len, start_sample + len(clipped))

    master = np.zeros(max_len, dtype=np.float32)
    for segment, wav in cached:
        start_sample = int(float(segment["start_sec"]) * sr)
        end_sample = start_sample + len(wav)
        master[start_sample:end_sample] = wav

    peak = float(np.max(np.abs(master))) if master.size > 0 else 1.0
    if peak > 0.99:
        master = master / peak * 0.99

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), master, sr)
    return output_path, sr


def mix_with_bgm(
    *,
    vocals_path: Path,
    bgm_path: Path,
    output_path: Path,
    target_sr: int,
) -> None:
    run_cmd_checked(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(vocals_path),
            "-i",
            str(bgm_path),
            "-filter_complex",
            "[0:a]volume=1.0[v];[1:a]volume=1.0[b];[v][b]amix=inputs=2:duration=longest:dropout_transition=0[m]",
            "-map",
            "[m]",
            "-ac",
            "1",
            "-ar",
            str(target_sr),
            str(output_path),
        ]
    )


def concat_wav_files(inputs: List[Path], output_wav: Path) -> None:
    if not inputs:
        return
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    list_path = output_wav.parent / f"{output_wav.stem}_concat.txt"
    lines: List[str] = []
    for item in inputs:
        escaped = str(item.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_cmd_checked(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-ac",
            "1",
            "-ar",
            "44100",
            str(output_wav),
        ]
    )


def merge_srt_files(
    *,
    inputs: List[Tuple[Path, float]],
    output_srt: Path,
) -> None:
    merged: List[Dict[str, Any]] = []
    for path, offset_sec in inputs:
        subs = parse_srt(path.read_text(encoding="utf-8"))
        for item in subs:
            merged.append(
                {
                    "start": float(item["start"]) + offset_sec,
                    "end": float(item["end"]) + offset_sec,
                    "text": item["text"],
                }
            )
    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text(format_srt(merged), encoding="utf-8")


def merge_bilingual_srt_files(
    *,
    translated_inputs: List[Tuple[Path, float]],
    source_inputs: List[Tuple[Path, float]],
    output_srt: Path,
    translated_first: bool = True,
) -> None:
    merged: List[Dict[str, Any]] = []
    for (translated_path, translated_offset), (source_path, source_offset) in zip(translated_inputs, source_inputs):
        if abs(float(translated_offset) - float(source_offset)) > 1e-6:
            raise RuntimeError("offset mismatch while building bilingual srt")
        translated_subs = parse_srt(translated_path.read_text(encoding="utf-8"))
        source_subs = parse_srt(source_path.read_text(encoding="utf-8"))
        if len(translated_subs) != len(source_subs):
            raise RuntimeError("line count mismatch while building bilingual srt")

        for translated, source in zip(translated_subs, source_subs):
            translated_text = (translated.get("text") or "").strip()
            source_text = (source.get("text") or "").strip()
            if translated_first:
                text = translated_text if not source_text else f"{translated_text}\n{source_text}"
            else:
                text = source_text if not translated_text else f"{source_text}\n{translated_text}"
            merged.append(
                {
                    "start": float(translated["start"]) + translated_offset,
                    "end": float(translated["end"]) + translated_offset,
                    "text": text,
                }
            )

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    output_srt.write_text(format_srt(merged), encoding="utf-8")


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

    out_vocals = resolve_output_path(final_paths.get("dubbed_vocals_full")) or (batch_dir / "final" / "dubbed_vocals_full.wav")
    out_mix = resolve_output_path(final_paths.get("dubbed_mix_full")) or (batch_dir / "final" / "dubbed_mix_full.wav")
    out_bgm = resolve_output_path(final_paths.get("source_bgm_full")) or (batch_dir / "final" / "source_bgm_full.wav")
    out_source_srt = resolve_output_path(final_paths.get("source_full_srt")) or (batch_dir / "final" / "source_full.srt")
    out_translated_srt = resolve_output_path(final_paths.get("translated_full_srt")) or (batch_dir / "final" / "translated_full.srt")
    out_dubbed_final_srt = resolve_output_path(final_paths.get("dubbed_final_full_srt")) or (batch_dir / "final" / "dubbed_final_full.srt")

    if out_vocals and len(vocals_inputs) == len(segment_entries):
        concat_wav_files(vocals_inputs, out_vocals)
    if out_mix and len(mix_inputs) == len(segment_entries):
        concat_wav_files(mix_inputs, out_mix)
    if out_bgm and len(bgm_inputs) == len(segment_entries):
        concat_wav_files(bgm_inputs, out_bgm)
    if out_source_srt and len(source_srt_inputs) == len(segment_entries):
        merge_srt_files(inputs=source_srt_inputs, output_srt=out_source_srt)
    if out_translated_srt and len(translated_srt_inputs) == len(segment_entries):
        merge_srt_files(inputs=translated_srt_inputs, output_srt=out_translated_srt)
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

    final_paths["dubbed_vocals_full"] = str(out_vocals.resolve()) if len(vocals_inputs) == len(segment_entries) else None
    final_paths["dubbed_mix_full"] = str(out_mix.resolve()) if len(mix_inputs) == len(segment_entries) else None
    final_paths["source_bgm_full"] = str(out_bgm.resolve()) if len(bgm_inputs) == len(segment_entries) else None
    final_paths["source_full_srt"] = str(out_source_srt.resolve()) if len(source_srt_inputs) == len(segment_entries) else None
    final_paths["translated_full_srt"] = (
        str(out_translated_srt.resolve()) if len(translated_srt_inputs) == len(segment_entries) else None
    )
    final_paths["dubbed_final_full_srt"] = (
        str(out_dubbed_final_srt.resolve())
        if len(source_srt_inputs) == len(segment_entries) and len(bilingual_translated_inputs) == len(segment_entries)
        else None
    )

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
