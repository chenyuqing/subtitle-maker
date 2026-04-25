from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import subprocess
import traceback
import uuid
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse

from subtitle_maker.transcriber import format_srt, merge_subtitles

from .. import legacy_runtime


router = APIRouter(tags=["exports"])


@router.post("/export")
async def export_subtitles(
    task_id: str = Form(...),
    format: str = Form(...),
    subtitles_json: Optional[str] = Form(None),
    translated_subtitles_json: Optional[str] = Form(None),
):
    """导出字幕文件，保留 legacy 回退语义。"""

    task = legacy_runtime.tasks.get(task_id)
    subtitles = []
    translated_subtitles = []

    if task and task.get("status") == "completed":
        subtitles = task.get("subtitles", [])
        translated_subtitles = task.get("translated_subtitles", [])

    if not subtitles and subtitles_json:
        try:
            subtitles = json.loads(subtitles_json)
        except Exception:
            pass

    if not translated_subtitles and translated_subtitles_json:
        try:
            translated_subtitles = json.loads(translated_subtitles_json)
        except Exception:
            pass

    if not subtitles:
        raise HTTPException(status_code=400, detail="Task not found or expired, and no subtitle data provided.")

    final_subtitles = []
    filename_suffix = ""
    if format == "original":
        final_subtitles = subtitles
        filename_suffix = ".srt"
    elif format == "translated":
        if not translated_subtitles:
            raise HTTPException(status_code=400, detail="Translation not available")
        final_subtitles = translated_subtitles
        filename_suffix = ".translated.srt"
    elif format == "bilingual_orig_trans":
        if not translated_subtitles:
            raise HTTPException(status_code=400, detail="Translation not available")
        final_subtitles = merge_subtitles(subtitles, translated_subtitles, order="orig_trans")
        filename_suffix = ".bilingual.srt"
    elif format == "bilingual_trans_orig":
        if not translated_subtitles:
            raise HTTPException(status_code=400, detail="Translation not available")
        final_subtitles = merge_subtitles(subtitles, translated_subtitles, order="trans_orig")
        filename_suffix = ".bilingual.srt"
    else:
        raise HTTPException(status_code=400, detail="Invalid format")

    srt_content = format_srt(final_subtitles)
    filename = f"export_{task_id}{filename_suffix}"
    filepath = os.path.join(legacy_runtime.OUTPUT_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(srt_content)
    return FileResponse(filepath, filename=filename)


@router.get("/download/{filename}")
async def download_file(filename: str):
    """下载 legacy 导出文件。"""

    path = os.path.join(legacy_runtime.OUTPUT_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=filename)


@router.post("/segment")
async def segment_audio(
    background_tasks: BackgroundTasks,
    task_id: str = Form(...),
    max_duration: float = Form(30.0),
    subtitles_json: Optional[str] = Form(None),
):
    """Legacy 切段导出入口；当前阶段仅搬迁，不改算法。"""

    del background_tasks
    task = legacy_runtime.tasks.get(task_id)
    subtitles = []

    if task and task.get("status") == "completed":
        subtitles = task.get("subtitles", [])

    if not subtitles and subtitles_json:
        try:
            subtitles = json.loads(subtitles_json)
        except Exception:
            pass

    if not subtitles:
        raise HTTPException(status_code=400, detail="No subtitles found.")

    video_filename = None
    if task:
        video_filename = task.get("video_filename") or task.get("filename")
    if not video_filename and task and task.get("filename"):
        video_filename = task.get("filename")
    if not video_filename:
        raise HTTPException(status_code=404, detail="Video file not found for this task.")

    video_path = os.path.join(legacy_runtime.UPLOAD_DIR, video_filename)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail=f"Video file {video_filename} not found.")

    segment_task_id = f"seg_{task_id}_{uuid.uuid4().hex[:6]}"
    segment_dir = os.path.join(legacy_runtime.OUTPUT_DIR, segment_task_id)
    os.makedirs(segment_dir, exist_ok=True)

    merged_segments: List[Dict[str, Any]] = []
    if not subtitles:
        return {"status": "empty"}

    sentence_endings = (".", "?", "!", "。", "？", "！", "…")
    quote_endings = ('.\"', '?\"', '!\"', '。\"', '？\"', '！\"', '…”')
    min_duration_ratio = 0.5

    def rebuild_text(block: List[Dict[str, Any]]) -> str:
        return " ".join(sub["text"].strip() for sub in block if sub.get("text")).strip()

    def rebuild_segment(segment: Dict[str, Any]):
        subs = segment.get("subs", [])
        if not subs:
            return
        segment["start"] = subs[0]["start"]
        segment["end"] = subs[-1]["end"]
        segment["text"] = rebuild_text(subs)
        segment["sub_count"] = len(subs)

    def is_sentence_boundary(text: str) -> bool:
        cleaned = text.strip()
        if not cleaned:
            return False
        return cleaned.endswith(sentence_endings) or cleaned.endswith(quote_endings)

    def split_text_chunks(text: str, parts: int) -> List[str]:
        stripped = text.strip()
        if not stripped:
            return [""] * parts

        sentence_parts = [s.strip() for s in re.split(r"(?<=[。！？!?…])", stripped) if s.strip()]
        if len(sentence_parts) >= parts:
            size = math.ceil(len(sentence_parts) / parts)
            chunks: List[str] = []
            for idx in range(parts):
                start = idx * size
                end = min(len(sentence_parts), (idx + 1) * size)
                chunks.append(" ".join(sentence_parts[start:end]).strip())
            return chunks

        words = stripped.split()
        if len(words) >= parts and len(words) > 1:
            size = math.ceil(len(words) / parts)
            chunks = []
            for idx in range(parts):
                start = idx * size
                end = min(len(words), (idx + 1) * size)
                chunks.append(" ".join(words[start:end]).strip())
            return chunks

        char_size = max(1, math.ceil(len(stripped) / parts))
        chunks = []
        for idx in range(parts):
            start = idx * char_size
            end = min(len(stripped), (idx + 1) * char_size)
            chunks.append(stripped[start:end].strip())
        return chunks

    def split_long_subtitle(sub: Dict[str, Any]) -> List[Dict[str, Any]]:
        duration = sub["end"] - sub["start"]
        if duration <= max_duration or duration <= 0:
            return [sub]
        parts = math.ceil(duration / max_duration)
        chunk_duration = duration / parts
        text_chunks = split_text_chunks(sub.get("text", ""), parts)
        chunks = []
        for idx in range(parts):
            start = sub["start"] + idx * chunk_duration
            end = min(sub["start"] + (idx + 1) * chunk_duration, sub["end"])
            chunk_text = text_chunks[idx] if idx < len(text_chunks) else sub.get("text", "")
            new_sub = sub.copy()
            new_sub.update({"start": start, "end": end, "text": chunk_text or sub.get("text", "")})
            chunks.append(new_sub)
        return chunks

    processed_subtitles: List[Dict[str, Any]] = []
    for sub in subtitles:
        processed_subtitles.extend(split_long_subtitle(sub))
    subtitles = processed_subtitles
    if not subtitles:
        return {"status": "empty"}

    def append_segment(block: List[Dict[str, Any]]):
        if not block:
            return
        block_subs = list(block)
        merged_segments.append(
            {
                "start": block_subs[0]["start"],
                "end": block_subs[-1]["end"],
                "text": rebuild_text(block_subs),
                "sub_count": len(block_subs),
                "subs": block_subs,
            }
        )

    current_block: List[Dict[str, Any]] = []
    sentence_boundaries: List[int] = []

    for sub in subtitles:
        current_block.append(sub)
        if is_sentence_boundary(sub["text"]):
            sentence_boundaries.append(len(current_block) - 1)

        while current_block:
            duration = current_block[-1]["end"] - current_block[0]["start"]
            if duration <= max_duration:
                break

            split_idx: Optional[int] = None
            for idx in reversed(sentence_boundaries):
                boundary_duration = current_block[idx]["end"] - current_block[0]["start"]
                if boundary_duration <= max_duration:
                    split_idx = idx
                    break

            if split_idx is None:
                fallback_idx = len(current_block) - 2
                while fallback_idx >= 0:
                    fallback_duration = current_block[fallback_idx]["end"] - current_block[0]["start"]
                    if fallback_duration <= max_duration:
                        split_idx = fallback_idx
                        break
                    fallback_idx -= 1

            if split_idx is None:
                append_segment(current_block[:1])
                current_block = current_block[1:]
                sentence_boundaries = [i - 1 for i in sentence_boundaries if i > 0]
                continue

            emit_block = current_block[: split_idx + 1]
            append_segment(emit_block)
            current_block = current_block[split_idx + 1 :]
            sentence_boundaries = [i - (split_idx + 1) for i in sentence_boundaries if i > split_idx]

    append_segment(current_block)

    i = 0
    while i < len(merged_segments) - 1:
        curr = merged_segments[i]
        next_seg = merged_segments[i + 1]
        curr_duration = curr["end"] - curr["start"]

        if curr_duration >= max_duration * min_duration_ratio:
            i += 1
            continue

        combined_duration = next_seg["end"] - curr["start"]
        if combined_duration <= max_duration:
            curr["subs"].extend(next_seg["subs"])
            rebuild_segment(curr)
            merged_segments.pop(i + 1)
            continue

        moved = False
        while next_seg.get("subs"):
            candidate = next_seg["subs"][0]
            new_duration = candidate["end"] - curr["start"]
            if new_duration > max_duration:
                break
            curr["subs"].append(candidate)
            next_seg["subs"] = next_seg["subs"][1:]
            rebuild_segment(curr)
            if next_seg["subs"]:
                rebuild_segment(next_seg)
            else:
                merged_segments.pop(i + 1)
                moved = True
                break
            moved = True
            curr_duration = curr["end"] - curr["start"]
            if curr_duration >= max_duration * min_duration_ratio:
                break

        if not moved:
            i += 1

    for seg in merged_segments:
        seg.pop("subs", None)

    metadata_rows = []
    try:
        full_wav_path = os.path.join(segment_dir, "full_temp.wav")
        subprocess.run(
            ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", full_wav_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for idx, seg in enumerate(merged_segments):
            seg_filename = f"segment_{idx:04d}.wav"
            seg_path = os.path.join(segment_dir, seg_filename)
            start = seg["start"]
            duration = seg["end"] - seg["start"]
            subprocess.run(
                ["ffmpeg", "-y", "-ss", str(start), "-t", str(duration), "-i", full_wav_path, "-c", "copy", seg_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            metadata_rows.append([seg_filename, seg["text"]])

        csv_path = os.path.join(segment_dir, "metadata.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["file_name", "transcription"])
            writer.writerows(metadata_rows)

        if os.path.exists(full_wav_path):
            os.remove(full_wav_path)

        zip_filename = f"segments_{task_id}.zip"
        zip_path = os.path.join(legacy_runtime.OUTPUT_DIR, zip_filename)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(segment_dir):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    arcname = os.path.relpath(file_path, segment_dir)
                    zipf.write(file_path, arcname)

        shutil.rmtree(segment_dir)
        return {"zip_url": f"/download/{zip_filename}", "count": len(merged_segments)}
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Segmentation failed: {str(exc)}")
