from __future__ import annotations

import shutil
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import librosa
import numpy as np
import soundfile as sf

from subtitle_maker.backends import IndexTtsBackend, TtsSynthesisRequest
from subtitle_maker.domains.media import audio_duration

from .alignment import (
    apply_atempo,
    compute_effective_target_duration,
    fit_audio_to_duration,
    trim_audio_to_max_duration,
    trim_silence_edges,
)

if TYPE_CHECKING:
    from subtitle_maker.qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel
    from subtitle_maker.translator import Translator


def _is_sentence_end(text: str) -> bool:
    """判断一行文本是否自然收在句末边界。"""

    return bool(re.search(r"[.!?。！？][\"')\]]*\s*$", (text or "").strip()))


def build_synthesis_groups(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    max_gap_sec: float,
    min_group_duration_sec: float,
    max_group_duration_sec: float,
    grouping_strategy: str = "legacy",
) -> List[List[int]]:
    """按历史规则或句末规则把字幕索引分组。"""

    if len(subtitles) <= 1:
        return [[index] for index in range(len(subtitles))]

    strategy = (grouping_strategy or "legacy").strip().lower()
    if strategy not in {"legacy", "sentence"}:
        strategy = "legacy"

    if strategy == "sentence":
        groups: List[List[int]] = []
        current = [0]
        for idx in range(len(subtitles) - 1):
            source_text = (subtitles[idx].get("text") or "").strip()
            translated_text = (translated_lines[idx] if idx < len(translated_lines) else "").strip()
            if _is_sentence_end(source_text) or _is_sentence_end(translated_text):
                groups.append(current[:])
                current = [idx + 1]
            else:
                current.append(idx + 1)
        groups.append(current[:])
        return groups

    effective_min_group_duration = float(min_group_duration_sec)
    groups: List[List[int]] = []
    current = [0]
    current_start = float(subtitles[0]["start"])

    for idx in range(len(subtitles) - 1):
        cur_end = float(subtitles[idx]["end"])
        next_start = float(subtitles[idx + 1]["start"])
        next_end = float(subtitles[idx + 1]["end"])
        gap = next_start - cur_end
        current_duration = cur_end - current_start
        next_duration = next_end - current_start
        source_text = (subtitles[idx].get("text") or "").strip()
        translated_text = (translated_lines[idx] if idx < len(translated_lines) else "").strip()
        sentence_end = _is_sentence_end(source_text) or _is_sentence_end(translated_text)
        hard_break = gap > max_gap_sec or (gap >= 0.0 and next_duration > max_group_duration_sec)
        natural_break = sentence_end and current_duration >= effective_min_group_duration
        if hard_break or natural_break:
            groups.append(current[:])
            current = [idx + 1]
            current_start = float(subtitles[idx + 1]["start"])
        else:
            current.append(idx + 1)

    groups.append(current[:])

    def _group_duration(index_group: List[int]) -> float:
        start = float(subtitles[index_group[0]].get("start", 0.0) or 0.0)
        end = float(subtitles[index_group[-1]].get("end", start) or start)
        return max(0.0, end - start)

    merged_groups: List[List[int]] = []
    for group in groups:
        if not merged_groups:
            merged_groups.append(group[:])
            continue
        if _group_duration(group) < effective_min_group_duration:
            merged_groups[-1].extend(group)
        else:
            merged_groups.append(group[:])
    return merged_groups


def synthesize_text_once(
    *,
    tts_backend: str,
    index_tts_via_api: bool,
    index_tts_api_url: str,
    index_tts_api_timeout_sec: float,
    tts_qwen: Optional[Qwen3TTSModel],
    qwen_prompt_items: Optional[List[Any]],
    tts_index: Optional[Any],
    ref_audio_path: Path,
    index_emo_audio_prompt: Optional[Path],
    index_emo_alpha: float,
    index_use_emo_text: bool,
    index_emo_text: Optional[str],
    index_top_p: float,
    index_top_k: int,
    index_temperature: float,
    index_max_text_tokens: int,
    text: str,
    output_path: Path,
) -> None:
    """执行一次单句 TTS 合成，并把 backend 分发收口。"""

    if tts_backend == "qwen":
        if tts_qwen is None or qwen_prompt_items is None:
            raise RuntimeError("qwen backend not initialized")
        wavs, sample_rate = tts_qwen.generate_voice_clone(
            text=text,
            language="Auto",
            voice_clone_prompt=qwen_prompt_items,
            x_vector_only_mode=True,
            non_streaming_mode=True,
        )
        wav = np.asarray(wavs[0], dtype=np.float32)
        sf.write(str(output_path), wav, sample_rate)
        return

    if tts_backend == "index-tts":
        backend = IndexTtsBackend(
            via_api=index_tts_via_api,
            api_url=index_tts_api_url,
            timeout_sec=index_tts_api_timeout_sec,
            local_model=tts_index,
        )
        backend.synthesize(
            TtsSynthesisRequest(
                text=text,
                ref_audio_path=ref_audio_path,
                output_path=output_path,
                emo_audio_prompt=index_emo_audio_prompt,
                emo_alpha=index_emo_alpha,
                use_emo_text=index_use_emo_text,
                emo_text=index_emo_text,
                top_p=index_top_p,
                top_k=index_top_k,
                temperature=index_temperature,
                max_text_tokens=index_max_text_tokens,
            )
        )
        return

    raise RuntimeError(f"Unsupported tts backend: {tts_backend}")


def _iso_now() -> str:
    """生成当前 UTC 时间戳字符串。"""

    return datetime.utcnow().isoformat()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """把数值限制在给定上下界之间。"""

    return max(minimum, min(maximum, value))


def _is_cjk_target_lang(target_lang: str) -> bool:
    """判断目标语种是否属于中日韩文本模式。"""

    lowered = (target_lang or "").strip().lower()
    markers = ["chinese", "中文", "mandarin", "cantonese", "zh", "japanese", "korean", "日文", "韩文"]
    return any(marker in lowered for marker in markers)


def _has_speakable_content(text: str) -> bool:
    """判断文本是否包含可发音内容。"""

    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    return any(char.isalnum() for char in compact)


def _audio_is_effectively_silent(
    path: Path,
    *,
    rms_threshold: float = 0.005,
    peak_threshold: float = 0.02,
    min_duration_sec: float = 0.20,
) -> bool:
    """按 RMS、峰值和最小时长综合判断音频是否近似静音。"""

    if not path.exists():
        return True
    wav, sample_rate = sf.read(str(path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    if mono.size == 0 or sample_rate <= 0:
        return True
    duration = float(mono.size / sample_rate)
    if duration < min_duration_sec:
        return True
    rms = float(np.sqrt(np.mean(mono * mono)))
    peak = float(np.max(np.abs(mono)))
    return rms < rms_threshold and peak < peak_threshold


def _extract_prosody_fingerprint(path: Path) -> Optional[Dict[str, float]]:
    """提取语音韵律指纹，供 V2 候选评分比较情绪一致性。"""

    if not path.exists():
        return None
    wav, sample_rate = sf.read(str(path))
    if isinstance(wav, np.ndarray) and wav.ndim > 1:
        wav = wav.mean(axis=1)
    mono = np.asarray(wav, dtype=np.float32)
    if mono.size < 32 or sample_rate <= 0:
        return None

    target_sr = 22050
    if sample_rate != target_sr:
        mono = librosa.resample(mono, orig_sr=sample_rate, target_sr=target_sr)
        sample_rate = target_sr
    if mono.size < 32:
        return None

    rms = librosa.feature.rms(y=mono, frame_length=1024, hop_length=256)[0]
    zcr = librosa.feature.zero_crossing_rate(y=mono, frame_length=1024, hop_length=256)[0]
    onset_env = librosa.onset.onset_strength(y=mono, sr=sample_rate, hop_length=256)
    if rms.size == 0 or zcr.size == 0 or onset_env.size == 0:
        return None

    silence_threshold = max(1e-6, float(np.percentile(rms, 35)))
    pause_ratio = float(np.mean(rms <= silence_threshold))
    return {
        "rms_mean": float(np.mean(rms)),
        "rms_std": float(np.std(rms)),
        "zcr_mean": float(np.mean(zcr)),
        "zcr_std": float(np.std(zcr)),
        "onset_mean": float(np.mean(onset_env)),
        "onset_std": float(np.std(onset_env)),
        "pause_ratio": float(np.clip(pause_ratio, 0.0, 1.0)),
    }


def _compute_prosody_distance(
    *,
    candidate_fp: Optional[Dict[str, float]],
    reference_fp: Optional[Dict[str, float]],
) -> float:
    """计算候选与参考韵律距离，值越小越接近。"""

    if candidate_fp is None or reference_fp is None:
        return 1.0

    def rel_diff(a: float, b: float, eps: float = 1e-6) -> float:
        return min(3.0, abs(float(a) - float(b)) / (abs(float(b)) + eps))

    weighted_features = [
        ("rms_mean", 0.18),
        ("rms_std", 0.14),
        ("zcr_mean", 0.14),
        ("zcr_std", 0.10),
        ("onset_mean", 0.18),
        ("onset_std", 0.14),
        ("pause_ratio", 0.12),
    ]
    total_weight = sum(weight for _, weight in weighted_features)
    if total_weight <= 0:
        return 1.0
    score = 0.0
    for key, weight in weighted_features:
        score += weight * rel_diff(candidate_fp.get(key, 0.0), reference_fp.get(key, 0.0))
    return float(max(0.0, score / total_weight))


def _group_subtitle_is_empty(
    *,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    indices: List[int],
) -> bool:
    """判断一组字幕在原文和译文上是否都没有可发音内容。"""

    for index in indices:
        src = (subtitles[index].get("text") or "").strip()
        tgt = (translated_lines[index] if index < len(translated_lines) else "").strip()
        if _has_speakable_content(src) or _has_speakable_content(tgt):
            return False
    return True


def _merge_text_lines(lines: List[str], *, cjk_mode: bool) -> str:
    """把多行文本按语种模式合并成一段待配音文本。"""

    if cjk_mode:
        merged = "".join((line or "").strip() for line in lines)
        merged = re.sub(r"\s+", "", merged)
        return merged
    merged = " ".join((line or "").strip() for line in lines)
    merged = re.sub(r"\s+", " ", merged).strip()
    merged = re.sub(r"\s+([,.;:!?])", r"\1", merged)
    return merged


def _retranslate_single_line(
    *,
    translator: Translator,
    source_text: str,
    current_translation: str,
    target_lang: str,
    target_duration_sec: float,
    need_shorter: bool,
    aggressiveness: int,
) -> str:
    """按当前目标时长要求改写单句翻译文本。"""

    direction = "shorter" if need_shorter else "slightly longer"
    prompt = (
        f"Rewrite the translated subtitle in {target_lang}.\n"
        f"Goal: make it {direction} while preserving meaning.\n"
        f"Target speaking duration: {target_duration_sec:.2f}s.\n"
        f"Aggressiveness: {aggressiveness}/2.\n\n"
        f"Source: {source_text}\n"
        f"Current translation: {current_translation}\n\n"
        "Return ONE line only. No numbering. No explanations."
    )
    response = translator.client.chat.completions.create(
        model=translator.model,
        messages=[
            {"role": "system", "content": "You rewrite subtitle lines for dubbing duration fit."},
            {"role": "user", "content": prompt},
        ],
        stream=False,
    )
    text = (response.choices[0].message.content or "").strip()
    return text or current_translation


def synthesize_segments_grouped(
    *,
    tts_backend: str,
    index_tts_via_api: bool,
    index_tts_api_url: str,
    index_tts_api_timeout_sec: float,
    tts_qwen: Optional[Qwen3TTSModel],
    qwen_prompt_items: Optional[List[Any]],
    tts_index: Optional[Any],
    ref_audio_path: Path,
    ref_audio_selector: Optional[Callable[[int], Path]],
    source_media_duration_sec: Optional[float],
    index_emo_audio_prompt: Optional[Path],
    index_emo_alpha: float,
    index_use_emo_text: bool,
    index_emo_text: Optional[str],
    index_top_p: float,
    index_top_k: int,
    index_temperature: float,
    index_max_text_tokens: int,
    force_fit_timing: bool,
    group_gap_sec: float,
    group_min_duration_sec: float,
    group_max_duration_sec: float,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    segment_dir: Path,
    delta_pass_ms: float,
    timing_mode: str,
    balanced_max_tempo_shift: float,
    balanced_min_line_sec: float,
    grouping_strategy: str,
    logger: Any,
    target_lang: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """执行 grouped / legacy 路径的整组合成编排。"""

    del balanced_min_line_sec
    segment_dir.mkdir(parents=True, exist_ok=True)
    records_by_index: Dict[int, Dict[str, Any]] = {}
    manual_review: List[Dict[str, Any]] = []

    groups = build_synthesis_groups(
        subtitles=subtitles,
        translated_lines=translated_lines,
        max_gap_sec=group_gap_sec,
        min_group_duration_sec=group_min_duration_sec,
        max_group_duration_sec=group_max_duration_sec,
        grouping_strategy=grouping_strategy,
    )
    cjk_mode = _is_cjk_target_lang(target_lang)

    for group_no, indices in enumerate(groups, start=1):
        group_id = f"group_{group_no:04d}"
        group_start = float(subtitles[indices[0]]["start"])
        group_end = float(subtitles[indices[-1]]["end"])
        group_target_duration = max(0.05, group_end - group_start)
        next_start_for_group: Optional[float] = None
        next_index = indices[-1] + 1
        if next_index < len(subtitles):
            next_start_for_group = float(subtitles[next_index].get("start", group_end) or group_end)
        elif source_media_duration_sec is not None:
            next_start_for_group = float(source_media_duration_sec)
        group_effective_target_duration, group_borrowed_gap_sec = compute_effective_target_duration(
            start_sec=group_start,
            end_sec=group_end,
            next_start_sec=next_start_for_group,
        )
        group_texts = [
            (translated_lines[index] if index < len(translated_lines) else subtitles[index]["text"]) or subtitles[index]["text"]
            for index in indices
        ]
        group_text = _merge_text_lines(group_texts, cjk_mode=cjk_mode)
        subtitle_empty = _group_subtitle_is_empty(
            subtitles=subtitles,
            translated_lines=translated_lines,
            indices=indices,
        )
        logger.log("INFO", "tts", "group_tts_started", f"synthesizing {group_id}", data={"segments": len(indices)})
        group_ref_audio_path = ref_audio_selector(indices[0]) if ref_audio_selector else ref_audio_path

        raw_path = segment_dir / f"{group_id}_raw.wav"
        fit_path = segment_dir / f"{group_id}_fit.wav"
        attempts_base: List[Dict[str, Any]] = []
        group_review_reason: Optional[Dict[str, Any]] = None
        try:
            if force_fit_timing and fit_path.exists():
                reused_actual = audio_duration(fit_path)
                use_path = fit_path
                attempts_base.append(
                    {
                        "attempt_no": 0,
                        "action": "group_reuse_fit",
                        "input_text": group_text,
                        "actual_duration_sec": round(reused_actual, 3),
                        "delta_sec": round(reused_actual - group_target_duration, 3),
                        "result": "pass",
                        "error": None,
                        "ts": _iso_now(),
                    }
                )
                logger.log(
                    "INFO",
                    "tts",
                    "group_tts_reused",
                    f"reused existing synthesized audio: {group_id}",
                    data={"path": str(fit_path)},
                )
            else:
                non_speech_group = not _has_speakable_content(group_text)
                if non_speech_group:
                    ref_sr = 16000
                    try:
                        ref_sr = max(8000, int(sf.info(str(group_ref_audio_path)).samplerate))
                    except Exception:
                        ref_sr = 16000
                    sample_count = max(1, int(round(group_target_duration * ref_sr)))
                    silence_path = segment_dir / f"{group_id}_silent.wav"
                    sf.write(str(silence_path), np.zeros(sample_count, dtype=np.float32), ref_sr)
                    use_path = silence_path
                    silent_actual = audio_duration(silence_path)
                    attempts_base.append(
                        {
                            "attempt_no": 0,
                            "action": "group_non_speech_silence",
                            "input_text": group_text,
                            "actual_duration_sec": round(silent_actual, 3),
                            "delta_sec": round(silent_actual - group_target_duration, 3),
                            "result": "pass",
                            "error": None,
                            "ts": _iso_now(),
                        }
                    )
                    logger.log(
                        "INFO",
                        "tts",
                        "group_non_speech_detected",
                        f"non-speech group uses silence: {group_id}",
                        data={"group_text": group_text},
                    )
                else:
                    synthesize_text_once(
                        tts_backend=tts_backend,
                        index_tts_via_api=index_tts_via_api,
                        index_tts_api_url=index_tts_api_url,
                        index_tts_api_timeout_sec=index_tts_api_timeout_sec,
                        tts_qwen=tts_qwen,
                        qwen_prompt_items=qwen_prompt_items,
                        tts_index=tts_index,
                        ref_audio_path=group_ref_audio_path,
                        index_emo_audio_prompt=index_emo_audio_prompt,
                        index_emo_alpha=index_emo_alpha,
                        index_use_emo_text=index_use_emo_text,
                        index_emo_text=index_emo_text,
                        index_top_p=index_top_p,
                        index_top_k=index_top_k,
                        index_temperature=index_temperature,
                        index_max_text_tokens=index_max_text_tokens,
                        text=group_text,
                        output_path=raw_path,
                    )
                    raw_actual = audio_duration(raw_path)
                    attempts_base.append(
                        {
                            "attempt_no": 0,
                            "action": "group_tts",
                            "input_text": group_text,
                            "actual_duration_sec": round(raw_actual, 3),
                            "delta_sec": round(raw_actual - group_target_duration, 3),
                            "result": "pass",
                            "error": None,
                            "ts": _iso_now(),
                        }
                    )

                    trim_path = segment_dir / f"{group_id}_trim.wav"
                    use_path = raw_path
                    try:
                        before_trim, after_trim = trim_silence_edges(
                            input_path=raw_path,
                            output_path=trim_path,
                        )
                        attempts_base.append(
                            {
                                "attempt_no": 0,
                                "action": "group_trim_edges",
                                "input_text": group_text,
                                "actual_duration_sec": round(after_trim, 3),
                                "delta_sec": round(after_trim - group_target_duration, 3),
                                "result": "pass",
                                "error": None,
                                "data": {
                                    "before_trim_sec": round(before_trim, 3),
                                    "after_trim_sec": round(after_trim, 3),
                                },
                                "ts": _iso_now(),
                            }
                        )
                        if after_trim >= 0.05:
                            use_path = trim_path
                    except Exception as trim_exc:
                        attempts_base.append(
                            {
                                "attempt_no": 0,
                                "action": "group_trim_edges",
                                "input_text": group_text,
                                "actual_duration_sec": round(raw_actual, 3),
                                "delta_sec": round(raw_actual - group_target_duration, 3),
                                "result": "fail",
                                "error": f"E-ALN-001 {type(trim_exc).__name__}: {trim_exc}",
                                "ts": _iso_now(),
                            }
                        )

                    if force_fit_timing:
                        raw_group_actual = audio_duration(use_path)
                        raw_group_delta = raw_group_actual - group_target_duration
                        raw_group_delta_effective = raw_group_actual - group_effective_target_duration
                        if grouping_strategy == "sentence":
                            if raw_group_actual > group_effective_target_duration:
                                sentence_fit_path = segment_dir / f"{group_id}_sentence_fit.wav"
                                try:
                                    fit_audio_to_duration(
                                        input_path=use_path,
                                        output_path=sentence_fit_path,
                                        target_duration_sec=group_effective_target_duration,
                                    )
                                    fitted_actual = audio_duration(sentence_fit_path)
                                    attempts_base.append(
                                        {
                                            "attempt_no": 0,
                                            "action": "group_sentence_fit_duration",
                                            "input_text": group_text,
                                            "actual_duration_sec": round(fitted_actual, 3),
                                            "delta_sec": round(fitted_actual - group_target_duration, 3),
                                            "result": "pass",
                                            "error": None,
                                            "data": {
                                                "effective_target_sec": round(group_effective_target_duration, 3),
                                                "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                            },
                                            "ts": _iso_now(),
                                        }
                                    )
                                    use_path = sentence_fit_path
                                except Exception as fit_exc:
                                    sentence_cap_path = segment_dir / f"{group_id}_sentence_cap.wav"
                                    trim_audio_to_max_duration(
                                        input_path=use_path,
                                        output_path=sentence_cap_path,
                                        max_duration_sec=group_effective_target_duration,
                                    )
                                    capped_actual = audio_duration(sentence_cap_path)
                                    attempts_base.append(
                                        {
                                            "attempt_no": 0,
                                            "action": "group_sentence_cap_duration_fallback",
                                            "input_text": group_text,
                                            "actual_duration_sec": round(capped_actual, 3),
                                            "delta_sec": round(capped_actual - group_target_duration, 3),
                                            "result": "pass",
                                            "error": f"E-ALN-001 sentence fit failed: {fit_exc}",
                                            "data": {
                                                "effective_target_sec": round(group_effective_target_duration, 3),
                                                "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                            },
                                            "ts": _iso_now(),
                                        }
                                    )
                                    use_path = sentence_cap_path
                            else:
                                attempts_base.append(
                                    {
                                        "attempt_no": 0,
                                        "action": "group_sentence_keep_natural",
                                        "input_text": group_text,
                                        "actual_duration_sec": round(raw_group_actual, 3),
                                        "delta_sec": round(raw_group_delta, 3),
                                        "result": "pass",
                                        "error": None,
                                        "data": {
                                            "effective_target_sec": round(group_effective_target_duration, 3),
                                            "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                            "effective_delta_sec": round(raw_group_delta_effective, 3),
                                        },
                                        "ts": _iso_now(),
                                    }
                                )
                        elif timing_mode == "strict":
                            fit_audio_to_duration(
                                input_path=use_path,
                                output_path=fit_path,
                                target_duration_sec=group_effective_target_duration,
                            )
                            fit_actual = audio_duration(fit_path)
                            attempts_base.append(
                                {
                                    "attempt_no": 0,
                                    "action": "group_fit_timing",
                                    "input_text": group_text,
                                    "actual_duration_sec": round(fit_actual, 3),
                                    "delta_sec": round(fit_actual - group_target_duration, 3),
                                    "result": "pass",
                                    "error": None,
                                    "data": {
                                        "effective_target_sec": round(group_effective_target_duration, 3),
                                        "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                    },
                                    "ts": _iso_now(),
                                }
                            )
                            use_path = fit_path
                        else:
                            relative_shift = abs(raw_group_delta_effective) / max(0.05, group_effective_target_duration)
                            if relative_shift > max(0.0, float(balanced_max_tempo_shift)):
                                fit_audio_to_duration(
                                    input_path=use_path,
                                    output_path=fit_path,
                                    target_duration_sec=group_effective_target_duration,
                                )
                                fit_actual = audio_duration(fit_path)
                                attempts_base.append(
                                    {
                                        "attempt_no": 0,
                                        "action": "group_balanced_fallback_strict",
                                        "input_text": group_text,
                                        "actual_duration_sec": round(fit_actual, 3),
                                        "delta_sec": round(fit_actual - group_target_duration, 3),
                                        "result": "pass",
                                        "error": None,
                                        "data": {
                                            "effective_target_sec": round(group_effective_target_duration, 3),
                                            "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                        },
                                        "ts": _iso_now(),
                                    }
                                )
                                use_path = fit_path
                            else:
                                attempts_base.append(
                                    {
                                        "attempt_no": 0,
                                        "action": "group_balanced_keep_natural",
                                        "input_text": group_text,
                                        "actual_duration_sec": round(raw_group_actual, 3),
                                        "delta_sec": round(raw_group_delta, 3),
                                        "result": "pass",
                                        "error": None,
                                        "data": {
                                            "effective_target_sec": round(group_effective_target_duration, 3),
                                            "borrowed_gap_sec": round(group_borrowed_gap_sec, 3),
                                            "effective_delta_sec": round(raw_group_delta_effective, 3),
                                        },
                                        "ts": _iso_now(),
                                    }
                                )

            if (not subtitle_empty) and _audio_is_effectively_silent(use_path):
                attempts_base.append(
                    {
                        "attempt_no": 1,
                        "action": "group_silence_check",
                        "input_text": group_text,
                        "actual_duration_sec": round(audio_duration(use_path), 3),
                        "delta_sec": round(audio_duration(use_path) - group_target_duration, 3),
                        "result": "fail",
                        "error": "E-TTS-001 detected silent-like output",
                        "ts": _iso_now(),
                    }
                )
                logger.log(
                    "WARN",
                    "tts",
                    "group_silence_detected",
                    f"silent-like group detected, retry once: {group_id}",
                    data={"path": str(use_path)},
                )

                retry_raw = segment_dir / f"{group_id}_retry1_raw.wav"
                retry_trim = segment_dir / f"{group_id}_retry1_trim.wav"
                retry_fit = segment_dir / f"{group_id}_retry1_fit.wav"
                retry_use = retry_raw

                synthesize_text_once(
                    tts_backend=tts_backend,
                    index_tts_via_api=index_tts_via_api,
                    index_tts_api_url=index_tts_api_url,
                    index_tts_api_timeout_sec=index_tts_api_timeout_sec,
                    tts_qwen=tts_qwen,
                    qwen_prompt_items=qwen_prompt_items,
                    tts_index=tts_index,
                    ref_audio_path=group_ref_audio_path,
                    index_emo_audio_prompt=index_emo_audio_prompt,
                    index_emo_alpha=index_emo_alpha,
                    index_use_emo_text=index_use_emo_text,
                    index_emo_text=index_emo_text,
                    index_top_p=index_top_p,
                    index_top_k=index_top_k,
                    index_temperature=index_temperature,
                    index_max_text_tokens=index_max_text_tokens,
                    text=group_text,
                    output_path=retry_raw,
                )
                try:
                    _, retry_trim_dur = trim_silence_edges(
                        input_path=retry_raw,
                        output_path=retry_trim,
                    )
                    if retry_trim_dur >= 0.05:
                        retry_use = retry_trim
                except Exception:
                    retry_use = retry_raw

                if force_fit_timing:
                    retry_actual = audio_duration(retry_use)
                    retry_delta_effective = retry_actual - group_effective_target_duration
                    if grouping_strategy == "sentence":
                        if retry_actual > group_effective_target_duration:
                            try:
                                fit_audio_to_duration(
                                    input_path=retry_use,
                                    output_path=retry_fit,
                                    target_duration_sec=group_effective_target_duration,
                                )
                                retry_use = retry_fit
                            except Exception:
                                trim_audio_to_max_duration(
                                    input_path=retry_use,
                                    output_path=retry_fit,
                                    max_duration_sec=group_effective_target_duration,
                                )
                                retry_use = retry_fit
                    elif timing_mode == "strict":
                        fit_audio_to_duration(
                            input_path=retry_use,
                            output_path=retry_fit,
                            target_duration_sec=group_effective_target_duration,
                        )
                        retry_use = retry_fit
                    else:
                        relative_shift = abs(retry_delta_effective) / max(0.05, group_effective_target_duration)
                        if relative_shift > max(0.0, float(balanced_max_tempo_shift)):
                            fit_audio_to_duration(
                                input_path=retry_use,
                                output_path=retry_fit,
                                target_duration_sec=group_effective_target_duration,
                            )
                            retry_use = retry_fit

                retry_still_silent = _audio_is_effectively_silent(retry_use)
                attempts_base.append(
                    {
                        "attempt_no": 1,
                        "action": "group_retry_after_silence",
                        "input_text": group_text,
                        "actual_duration_sec": round(audio_duration(retry_use), 3),
                        "delta_sec": round(audio_duration(retry_use) - group_target_duration, 3),
                        "result": "pass" if not retry_still_silent else "fail",
                        "error": None if not retry_still_silent else "E-TTS-001 still silent after one retry",
                        "ts": _iso_now(),
                    }
                )
                if not retry_still_silent:
                    use_path = retry_use
                else:
                    group_review_reason = {
                        "reason_code": "tts_silent_after_retry",
                        "reason_detail": "silent-like audio remains after one retry",
                        "last_delta_sec": None,
                        "last_attempt_no": 1,
                        "error_code": "E-TTS-001",
                        "error_stage": "tts",
                    }

            group_actual = audio_duration(use_path)
            group_delta = group_actual - group_target_duration
            group_delta_effective = group_actual - group_effective_target_duration
            anchor_status = "done" if abs(group_delta_effective) * 1000 <= delta_pass_ms else "manual_review"
            if group_review_reason is not None:
                anchor_status = "manual_review"

            for local_index, global_index in enumerate(indices):
                seg_id = f"seg_{global_index + 1:04d}"
                seg_start = float(subtitles[global_index]["start"])
                seg_end = float(subtitles[global_index]["end"])
                seg_target = max(0.05, seg_end - seg_start)
                translated_text = (
                    translated_lines[global_index]
                    if global_index < len(translated_lines)
                    else subtitles[global_index]["text"]
                )

                record: Dict[str, Any] = {
                    "id": seg_id,
                    "start_sec": round(seg_start, 3),
                    "end_sec": round(seg_end, 3),
                    "target_duration_sec": round(seg_target, 3),
                    "source_text": subtitles[global_index]["text"],
                    "translated_text": translated_text,
                    "segment_type": "speech" if _has_speakable_content(translated_text or subtitles[global_index]["text"]) else "non_speech",
                    "voice_ref_path": str(group_ref_audio_path),
                    "tts_audio_path": str(use_path),
                    "actual_duration_sec": 0.0,
                    "delta_sec": 0.0,
                    "status": "done",
                    "retry_count": 0,
                    "attempt_history": [dict(item) for item in attempts_base],
                    "skip_compose": True,
                    "group_id": group_id,
                }

                if local_index == 0:
                    record["target_duration_sec"] = round(group_target_duration, 3)
                    record["actual_duration_sec"] = round(group_actual, 3)
                    record["delta_sec"] = round(group_delta, 3)
                    record["status"] = anchor_status
                    record["skip_compose"] = False
                    record["group_anchor_end_sec"] = round(group_end, 3)
                    record["group_text"] = group_text
                    record["effective_target_duration_sec"] = round(group_effective_target_duration, 3)
                    record["borrowed_gap_sec"] = round(group_borrowed_gap_sec, 3)
                    record["effective_delta_sec"] = round(group_delta_effective, 3)

                records_by_index[global_index] = record

            if anchor_status != "done":
                review_template = dict(group_review_reason or {})
                if not review_template:
                    review_template = {
                        "reason_code": "duration_exceeded_after_retries",
                        "reason_detail": "grouped synthesis group out of threshold",
                        "last_delta_sec": round(group_delta, 3),
                        "last_effective_delta_sec": round(group_delta_effective, 3),
                        "last_attempt_no": 0,
                        "error_code": "E-ALN-001",
                        "error_stage": "duration_align",
                    }
                for global_index in indices:
                    seg_id = f"seg_{global_index + 1:04d}"
                    records_by_index[global_index]["status"] = "manual_review"
                    manual_review.append({"segment_id": seg_id, **review_template})
        except Exception as exc:
            logger.log(
                "ERROR",
                "tts",
                "group_tts_failed",
                f"{group_id} synthesis failed",
                data={"error": str(exc)},
            )
            for global_index in indices:
                seg_id = f"seg_{global_index + 1:04d}"
                target_duration = max(0.05, float(subtitles[global_index]["end"]) - float(subtitles[global_index]["start"]))
                missing_path = segment_dir / f"{seg_id}_missing.wav"
                sf.write(str(missing_path), np.zeros(max(1600, int(16000 * target_duration)), dtype=np.float32), 16000)
                records_by_index[global_index] = {
                    "id": seg_id,
                    "start_sec": round(float(subtitles[global_index]["start"]), 3),
                    "end_sec": round(float(subtitles[global_index]["end"]), 3),
                    "target_duration_sec": round(target_duration, 3),
                    "source_text": subtitles[global_index]["text"],
                    "translated_text": translated_lines[global_index] if global_index < len(translated_lines) else subtitles[global_index]["text"],
                    "segment_type": "speech" if _has_speakable_content(translated_lines[global_index] if global_index < len(translated_lines) else subtitles[global_index]["text"]) else "non_speech",
                    "voice_ref_path": str(group_ref_audio_path),
                    "tts_audio_path": str(missing_path),
                    "actual_duration_sec": round(audio_duration(missing_path), 3),
                    "delta_sec": round(audio_duration(missing_path) - target_duration, 3),
                    "status": "manual_review",
                    "retry_count": 0,
                    "attempt_history": [
                        {
                            "attempt_no": 0,
                            "action": "group_tts",
                            "input_text": group_text,
                            "actual_duration_sec": None,
                            "delta_sec": None,
                            "result": "fail",
                            "error": f"E-TTS-001 {type(exc).__name__}: {exc}",
                            "ts": _iso_now(),
                        }
                    ],
                }
                manual_review.append(
                    {
                        "segment_id": seg_id,
                        "reason_code": "tts_failed",
                        "reason_detail": str(exc),
                        "last_delta_sec": None,
                        "last_attempt_no": 0,
                        "error_code": "E-TTS-001",
                        "error_stage": "tts",
                    }
                )

    records = [records_by_index[index] for index in sorted(records_by_index.keys())]
    return records, manual_review


def synthesize_segments(
    *,
    tts_backend: str,
    index_tts_via_api: bool,
    index_tts_api_url: str,
    index_tts_api_timeout_sec: float,
    tts_qwen: Optional[Qwen3TTSModel],
    qwen_prompt_items: Optional[List[Any]],
    tts_index: Optional[Any],
    ref_audio_path: Path,
    ref_audio_selector: Optional[Callable[[int], Path]],
    source_vocals_audio: Path,
    source_media_duration_sec: Optional[float],
    index_emo_audio_prompt: Optional[Path],
    index_emo_alpha: float,
    index_use_emo_text: bool,
    index_emo_text: Optional[str],
    index_top_p: float,
    index_top_k: int,
    index_temperature: float,
    index_max_text_tokens: int,
    force_fit_timing: bool,
    subtitles: List[Dict[str, Any]],
    translated_lines: List[str],
    segment_dir: Path,
    delta_pass_ms: float,
    delta_rewrite_ms: float,
    atempo_min: float,
    atempo_max: float,
    max_retry: int,
    translator: Optional[Translator],
    target_lang: str,
    allow_rewrite_translation: bool,
    prefer_translated_text: bool,
    existing_records_by_id: Optional[Dict[str, Dict[str, Any]]],
    redub_line_indices: Optional[set[int]],
    v2_mode: bool,
    logger: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """执行逐句合成主循环。"""

    del source_vocals_audio
    segment_dir.mkdir(parents=True, exist_ok=True)
    for stale_path in segment_dir.glob("seg_*_a*.wav"):
        try:
            stale_path.unlink(missing_ok=True)
        except Exception:
            pass
    records: List[Dict[str, Any]] = []
    manual_review: List[Dict[str, Any]] = []
    ref_fp_cache: Dict[str, Optional[Dict[str, float]]] = {}

    for idx, (subtitle, translated_text) in enumerate(zip(subtitles, translated_lines), start=1):
        seg_id = f"seg_{idx:04d}"
        seg_ref_audio_path = ref_audio_selector(idx - 1) if ref_audio_selector else ref_audio_path
        start_sec = float(subtitle["start"])
        end_sec = float(subtitle["end"])
        target_duration = max(0.05, end_sec - start_sec)
        next_start_sec: Optional[float] = None
        if idx < len(subtitles):
            next_start_sec = float(subtitles[idx].get("start", end_sec) or end_sec)
        elif source_media_duration_sec is not None:
            next_start_sec = float(source_media_duration_sec)
        effective_target_duration, borrowed_gap_sec = compute_effective_target_duration(
            start_sec=start_sec,
            end_sec=end_sec,
            next_start_sec=next_start_sec,
        )
        source_text = subtitle["text"]
        current_text = (translated_text or "").strip() if prefer_translated_text else (translated_text or source_text)

        if redub_line_indices is not None and idx not in redub_line_indices:
            reused = (existing_records_by_id or {}).get(seg_id) if existing_records_by_id else None
            reused_audio = Path(str(reused.get("tts_audio_path") or "")).expanduser() if reused else None
            if reused and reused_audio and reused_audio.exists():
                reused_record = dict(reused)
                reused_record["source_text"] = source_text
                reused_record["translated_text"] = current_text
                reused_record["start_sec"] = round(start_sec, 3)
                reused_record["end_sec"] = round(end_sec, 3)
                reused_record["target_duration_sec"] = round(target_duration, 3)
                reused_record["segment_type"] = "speech" if _has_speakable_content(current_text) else "non_speech"
                history = list(reused_record.get("attempt_history") or [])
                history.append(
                    {
                        "attempt_no": 0,
                        "action": "reuse_existing",
                        "input_text": current_text,
                        "actual_duration_sec": reused_record.get("actual_duration_sec"),
                        "delta_sec": reused_record.get("delta_sec"),
                        "result": "pass",
                        "error": None,
                        "ts": _iso_now(),
                    }
                )
                reused_record["attempt_history"] = history
                records.append(reused_record)
                logger.log("INFO", "tts", "segment_tts_reused", f"reuse existing audio for {seg_id}", segment_id=seg_id)
                if reused_record.get("status") != "done":
                    manual_review.append(
                        {
                            "segment_id": seg_id,
                            "reason_code": "reuse_existing_not_done",
                            "reason_detail": "reused existing record is not done",
                            "last_delta_sec": reused_record.get("delta_sec"),
                            "last_effective_delta_sec": reused_record.get("effective_delta_sec"),
                            "last_attempt_no": reused_record.get("retry_count"),
                            "error_code": reused_record.get("error_code"),
                            "error_stage": reused_record.get("error_stage"),
                        }
                    )
                continue

        attempts: List[Dict[str, Any]] = []
        attempt_artifacts: List[Path] = []
        best: Optional[Dict[str, Any]] = None
        final_status = "failed"
        retry_count = 0
        failure_reason_code = "duration_exceeded_after_retries"
        failure_error_code = "E-ALN-001"
        failure_stage = "duration_align"

        logger.log("INFO", "tts", "segment_tts_started", f"synthesizing {seg_id}", segment_id=seg_id)
        seg_emo_audio_prompt = seg_ref_audio_path

        ref_key = str(seg_ref_audio_path.resolve()) if seg_ref_audio_path.exists() else str(seg_ref_audio_path)
        if ref_key not in ref_fp_cache:
            ref_fp_cache[ref_key] = _extract_prosody_fingerprint(seg_ref_audio_path)
        reference_fp = ref_fp_cache.get(ref_key)

        def evaluate_candidate(path: Path, actual_sec: float, delta_sec: float, attempt_no: int, action: str) -> Dict[str, Any]:
            duration_error_ratio = abs(float(actual_sec) - float(effective_target_duration)) / max(
                0.05,
                float(effective_target_duration),
            )
            prosody_distance = None
            if v2_mode:
                candidate_fp = _extract_prosody_fingerprint(path)
                prosody_distance = _compute_prosody_distance(candidate_fp=candidate_fp, reference_fp=reference_fp)
                selection_score = 0.55 * duration_error_ratio + 0.45 * float(prosody_distance)
            else:
                selection_score = duration_error_ratio
            return {
                "path": path,
                "actual_sec": float(actual_sec),
                "delta_sec": float(delta_sec),
                "attempt_no": int(attempt_no),
                "action": action,
                "duration_error_ratio": float(duration_error_ratio),
                "prosody_distance": None if prosody_distance is None else float(prosody_distance),
                "selection_score": float(selection_score),
            }

        def maybe_update_best(candidate: Dict[str, Any]) -> None:
            nonlocal best
            if best is None or float(candidate["selection_score"]) < float(best["selection_score"]):
                best = candidate

        for attempt_no in range(0, max_retry + 1):
            raw_path = segment_dir / f"{seg_id}_a{attempt_no}.wav"
            attempt_artifacts.append(raw_path)
            try:
                synthesize_text_once(
                    tts_backend=tts_backend,
                    index_tts_via_api=index_tts_via_api,
                    index_tts_api_url=index_tts_api_url,
                    index_tts_api_timeout_sec=index_tts_api_timeout_sec,
                    tts_qwen=tts_qwen,
                    qwen_prompt_items=qwen_prompt_items,
                    tts_index=tts_index,
                    ref_audio_path=seg_ref_audio_path,
                    index_emo_audio_prompt=seg_emo_audio_prompt,
                    index_emo_alpha=index_emo_alpha,
                    index_use_emo_text=index_use_emo_text,
                    index_emo_text=index_emo_text,
                    index_top_p=index_top_p,
                    index_top_k=index_top_k,
                    index_temperature=index_temperature,
                    index_max_text_tokens=index_max_text_tokens,
                    text=current_text,
                    output_path=raw_path,
                )
            except Exception as exc:
                failure_reason_code = "tts_failed"
                failure_error_code = "E-TTS-001"
                failure_stage = "tts"
                attempts.append(
                    {
                        "attempt_no": attempt_no,
                        "action": "tts",
                        "input_text": current_text,
                        "actual_duration_sec": None,
                        "delta_sec": None,
                        "result": "fail",
                        "error": f"E-TTS-001 {type(exc).__name__}: {exc}",
                        "ts": _iso_now(),
                    }
                )
                logger.log(
                    "ERROR",
                    "tts",
                    "segment_tts_failed",
                    f"{seg_id} tts failed",
                    segment_id=seg_id,
                    data={"error_code": "E-TTS-001", "error": str(exc)},
                )
                break

            actual = audio_duration(raw_path)
            min_valid_duration = max(0.20, min(0.60, target_duration * 0.25))
            invalid_audio = _audio_is_effectively_silent(raw_path) or actual < min_valid_duration
            if invalid_audio:
                failure_reason_code = "tts_invalid_audio"
                failure_error_code = "E-TTS-002"
                failure_stage = "tts"
                attempts.append(
                    {
                        "attempt_no": attempt_no,
                        "action": "validate_audio",
                        "input_text": current_text,
                        "actual_duration_sec": round(actual, 3),
                        "delta_sec": round(actual - target_duration, 3),
                        "result": "fail",
                        "error": f"E-TTS-002 invalid audio output (too short/silent, min={min_valid_duration:.2f}s)",
                        "ts": _iso_now(),
                    }
                )
                if seg_ref_audio_path != ref_audio_path:
                    seg_ref_audio_path = ref_audio_path
                    ref_key = str(seg_ref_audio_path.resolve()) if seg_ref_audio_path.exists() else str(seg_ref_audio_path)
                    if ref_key not in ref_fp_cache:
                        ref_fp_cache[ref_key] = _extract_prosody_fingerprint(seg_ref_audio_path)
                    reference_fp = ref_fp_cache.get(ref_key)
                if attempt_no < max_retry:
                    continue
                break
            delta = actual - target_duration
            delta_effective = actual - effective_target_duration
            abs_delta = abs(delta_effective)
            attempts.append(
                {
                    "attempt_no": attempt_no,
                    "action": "tts",
                    "input_text": current_text,
                    "actual_duration_sec": round(actual, 3),
                    "delta_sec": round(delta, 3),
                    "result": "pass" if abs_delta * 1000 <= delta_pass_ms else "fail",
                    "error": None,
                    "data": {
                        "effective_target_sec": round(effective_target_duration, 3),
                        "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                        "effective_delta_sec": round(delta_effective, 3),
                    },
                    "ts": _iso_now(),
                }
            )

            if force_fit_timing:
                fit_path = segment_dir / f"{seg_id}_a{attempt_no}_fit.wav"
                try:
                    fit_audio_to_duration(
                        input_path=raw_path,
                        output_path=fit_path,
                        target_duration_sec=effective_target_duration,
                    )
                    attempt_artifacts.append(fit_path)
                    actual_fit = audio_duration(fit_path)
                    delta_fit = actual_fit - target_duration
                    delta_fit_effective = actual_fit - effective_target_duration
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "fit_timing",
                            "input_text": current_text,
                            "actual_duration_sec": round(actual_fit, 3),
                            "delta_sec": round(delta_fit, 3),
                            "result": "pass",
                            "error": None,
                            "data": {
                                "effective_target_sec": round(effective_target_duration, 3),
                                "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                                "effective_delta_sec": round(delta_fit_effective, 3),
                            },
                            "ts": _iso_now(),
                        }
                    )
                    maybe_update_best(
                        evaluate_candidate(
                            path=fit_path,
                            actual_sec=actual_fit,
                            delta_sec=delta_fit,
                            attempt_no=attempt_no,
                            action="fit_timing",
                        )
                    )
                    final_status = "done"
                    retry_count = attempt_no
                    break
                except Exception as exc:
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "fit_timing",
                            "input_text": current_text,
                            "actual_duration_sec": round(actual, 3),
                            "delta_sec": round(delta, 3),
                            "result": "fail",
                            "error": f"E-ALN-001 {type(exc).__name__}: {exc}",
                            "data": {
                                "effective_target_sec": round(effective_target_duration, 3),
                                "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                                "effective_delta_sec": round(delta_effective, 3),
                            },
                            "ts": _iso_now(),
                        }
                    )

            maybe_update_best(
                evaluate_candidate(
                    path=raw_path,
                    actual_sec=actual,
                    delta_sec=delta,
                    attempt_no=attempt_no,
                    action="tts",
                )
            )

            if abs_delta * 1000 <= delta_pass_ms:
                final_status = "done"
                retry_count = attempt_no
                break

            if abs_delta * 1000 <= delta_rewrite_ms:
                tempo = _clamp(actual / effective_target_duration, atempo_min, atempo_max)
                adjusted_path = segment_dir / f"{seg_id}_a{attempt_no}_atempo.wav"
                try:
                    apply_atempo(input_path=raw_path, output_path=adjusted_path, tempo=tempo)
                    attempt_artifacts.append(adjusted_path)
                    actual2 = audio_duration(adjusted_path)
                    delta2 = actual2 - target_duration
                    delta2_effective = actual2 - effective_target_duration
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "atempo",
                            "input_text": current_text,
                            "actual_duration_sec": round(actual2, 3),
                            "delta_sec": round(delta2, 3),
                            "result": "pass" if abs(delta2_effective) * 1000 <= delta_pass_ms else "fail",
                            "error": None,
                            "data": {
                                "effective_target_sec": round(effective_target_duration, 3),
                                "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                                "effective_delta_sec": round(delta2_effective, 3),
                            },
                            "ts": _iso_now(),
                        }
                    )
                    maybe_update_best(
                        evaluate_candidate(
                            path=adjusted_path,
                            actual_sec=actual2,
                            delta_sec=delta2,
                            attempt_no=attempt_no,
                            action="atempo",
                        )
                    )
                    if abs(delta2_effective) * 1000 <= delta_pass_ms:
                        final_status = "done"
                        retry_count = attempt_no
                        break
                except Exception as exc:
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "atempo",
                            "input_text": current_text,
                            "actual_duration_sec": round(actual, 3),
                            "delta_sec": round(delta, 3),
                            "result": "fail",
                            "error": f"E-ALN-001 {type(exc).__name__}: {exc}",
                            "data": {
                                "effective_target_sec": round(effective_target_duration, 3),
                                "borrowed_gap_sec": round(borrowed_gap_sec, 3),
                                "effective_delta_sec": round(delta_effective, 3),
                            },
                            "ts": _iso_now(),
                        }
                    )

            if allow_rewrite_translation and attempt_no < max_retry:
                need_shorter = delta > 0
                try:
                    if translator is None:
                        raise RuntimeError("translator is not initialized for rewrite step")
                    rewritten = _retranslate_single_line(
                        translator=translator,
                        source_text=source_text,
                        current_translation=current_text,
                        target_lang=target_lang,
                        target_duration_sec=target_duration,
                        need_shorter=need_shorter,
                        aggressiveness=attempt_no + 1,
                    )
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "retranslate_tts",
                            "input_text": rewritten,
                            "actual_duration_sec": None,
                            "delta_sec": None,
                            "result": "pass",
                            "error": None,
                            "ts": _iso_now(),
                        }
                    )
                    current_text = rewritten
                except Exception as exc:
                    failure_reason_code = "translation_empty_or_error"
                    failure_error_code = "E-TRN-002"
                    failure_stage = "translate"
                    attempts.append(
                        {
                            "attempt_no": attempt_no,
                            "action": "retranslate_tts",
                            "input_text": current_text,
                            "actual_duration_sec": None,
                            "delta_sec": None,
                            "result": "fail",
                            "error": f"E-TRN-002 {type(exc).__name__}: {exc}",
                            "ts": _iso_now(),
                        }
                    )

        if best is None:
            output_path = segment_dir / f"{seg_id}_missing.wav"
            sf.write(str(output_path), np.zeros(1600, dtype=np.float32), 16000)
            actual_best = 0.1
            delta_best = actual_best - target_duration
            best_score = None
            best_duration_error_ratio = None
            best_prosody_distance = None
        else:
            output_path = segment_dir / f"{seg_id}.wav"
            shutil.copy2(best["path"], output_path)
            actual_best = float(best["actual_sec"])
            delta_best = float(best["delta_sec"])
            best_score = float(best["selection_score"])
            best_duration_error_ratio = float(best["duration_error_ratio"])
            best_prosody_distance = best["prosody_distance"]
            retry_count = max(retry_count, int(best.get("attempt_no", retry_count)))
        effective_delta_best = actual_best - effective_target_duration

        if final_status != "done" and v2_mode and best is not None:
            final_status = "done"
            attempts.append(
                {
                    "attempt_no": int(best.get("attempt_no", retry_count)),
                    "action": "v2_accept_best_tradeoff",
                    "input_text": current_text,
                    "actual_duration_sec": round(actual_best, 3),
                    "delta_sec": round(delta_best, 3),
                    "result": "pass",
                    "error": None,
                    "data": {
                        "selection_score": round(float(best_score or 0.0), 4),
                        "duration_error_ratio": round(float(best_duration_error_ratio or 0.0), 4),
                        "prosody_distance": None if best_prosody_distance is None else round(float(best_prosody_distance), 4),
                    },
                    "ts": _iso_now(),
                }
            )

        record: Dict[str, Any] = {
            "id": seg_id,
            "start_sec": round(start_sec, 3),
            "end_sec": round(end_sec, 3),
            "target_duration_sec": round(target_duration, 3),
            "source_text": source_text,
            "translated_text": current_text,
            "segment_type": "speech" if _has_speakable_content(current_text) else "non_speech",
            "voice_ref_path": str(seg_ref_audio_path),
            "tts_audio_path": str(output_path),
            "actual_duration_sec": round(actual_best, 3),
            "delta_sec": round(delta_best, 3),
            "effective_target_duration_sec": round(effective_target_duration, 3),
            "borrowed_gap_sec": round(borrowed_gap_sec, 3),
            "effective_delta_sec": round(effective_delta_best, 3),
            "selection_score": None if best_score is None else round(float(best_score), 4),
            "duration_error_ratio": None if best_duration_error_ratio is None else round(float(best_duration_error_ratio), 4),
            "prosody_distance": None if best_prosody_distance is None else round(float(best_prosody_distance), 4),
            "status": final_status if final_status == "done" else "manual_review",
            "retry_count": retry_count,
            "attempt_history": attempts,
        }
        records.append(record)

        if record["status"] != "done":
            manual_review.append(
                {
                    "segment_id": seg_id,
                    "reason_code": failure_reason_code,
                    "reason_detail": "segment not within pass threshold after retries",
                    "last_delta_sec": round(delta_best, 3),
                    "last_effective_delta_sec": round(effective_delta_best, 3),
                    "last_attempt_no": max_retry,
                    "error_code": failure_error_code,
                    "error_stage": failure_stage,
                }
            )
            logger.log(
                "WARN",
                "duration_align",
                "segment_manual_review_marked",
                f"{seg_id} marked manual review",
                segment_id=seg_id,
                data={
                    "error_code": failure_error_code,
                    "delta_sec": round(delta_best, 3),
                    "effective_delta_sec": round(effective_delta_best, 3),
                },
            )

        for artifact in attempt_artifacts:
            try:
                if artifact.exists():
                    artifact.unlink(missing_ok=True)
            except Exception:
                pass

    return records, manual_review
