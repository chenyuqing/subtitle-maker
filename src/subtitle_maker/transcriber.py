import torch
import os
import uuid
import ffmpeg
import logging
import re
from transformers import AutoModelForCausalLM, AutoTokenizer
from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner
from qwen_asr.core.transformers_backend.processing_qwen3_asr import Qwen3ASRProcessor

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 句级切分策略常量：优先标点，其次长停顿，尽量避免词级碎片。
SENTENCE_STOP_PUNCT = set(".?!。？！")
SOFT_BREAK_PUNCT = set(",;:，；：")
LONG_PAUSE_SPLIT_SEC = 0.85
SOFT_PAUSE_SPLIT_SEC = 0.45
MIN_SEGMENT_DURATION_SEC = 0.80
MIN_SEGMENT_TOKENS = 3
CONNECTOR_TAIL_WORDS = {
    "and", "but", "or", "so", "is", "are", "was", "were", "to", "of",
    "for", "with", "in", "on", "at", "that", "which", "who", "whom",
    "的", "了", "呢", "啊", "嘛", "吧", "和", "与", "或", "而", "及", "并", "是",
}
CONNECTOR_HEAD_WORDS = {
    "and", "but", "or", "so", "because", "that", "which",
    "is", "are", "was", "were",
    "的", "了", "和", "与", "而", "并", "是",
}
REMOVABLE_HEAD_CONNECTORS = {"and", "but", "so", "that", "which", "and,"}
SPLIT_HINT_WORDS = {
    "and", "but", "so", "because", "that", "which", "who",
    "however", "therefore", "then", "when", "while", "where",
}
LEADING_PUNCT_CHARS = ",.;:，。；：!?？！"
HARD_MIN_SUBTITLE_SEC = 2.0
SOFT_MIN_SUBTITLE_SEC = 2.5
HARD_MAX_SUBTITLE_SEC = 6.0
LINE_MAX_CHARS = 42
LINE_MAX_LINES = 2

class SubtitleGenerator:
    def __init__(self, model_path="Qwen/Qwen3-ASR-0.6B", aligner_path="Qwen/Qwen3-ForcedAligner-0.6B", device="mps", lazy_load=False):
        self.device = device
        self.dtype = torch.float16 if device == "mps" else torch.bfloat16
        self.model_path = model_path
        self.aligner_path = aligner_path
        self.model = None
        
        logger.info(f"Initializing SubtitleGenerator on {device} (Lazy Load: {lazy_load})")
        
        if not lazy_load:
            self.load_model()

    def load_model(self):
        if self.model is not None:
            return

        logger.info(f"Loading ASR models on {self.device} with {self.dtype}...")
        try:
            self.model = Qwen3ASRModel.from_pretrained(
                self.model_path,
                dtype=self.dtype,
                device_map=self.device,
                forced_aligner=self.aligner_path,
                forced_aligner_kwargs=dict(
                    dtype=self.dtype,
                    device_map=self.device,
                ),
            )
            logger.info("ASR Models loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load models: {e}")
            raise

    def unload_model(self):
        if self.model is not None:
            logger.info("Unloading ASR model to free memory...")
            del self.model
            self.model = None
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
            elif torch.cuda.is_available():
                torch.cuda.empty_cache()
            import gc
            gc.collect()
            logger.info("ASR Model unloaded.")

    def preprocess_audio(self, input_path):
        """
        Convert audio to 16kHz mono wav.
        Returns the path to the processed audio.
        """
        session_id = str(uuid.uuid4())
        output_path = f"temp_audio_{session_id}.wav"
        try:
            logger.info(f"Preprocessing audio: {input_path}")
            (
                ffmpeg
                .input(input_path)
                .output(output_path, ac=1, ar=16000, loglevel="quiet")
                .overwrite_output()
                .run()
            )
            return output_path
        except ffmpeg.Error as e:
            logger.error(f"FFmpeg error: {e}")
            raise

    def transcribe(self, audio_path, language=None):
        """
        Transcribe audio and return results with timestamps.
        """
        processed_audio = self.preprocess_audio(audio_path)
        logger.info("Starting transcription...")
        
        try:
            # specific logic for Qwen3-ASR inference
            # result is a list of objects with text, language, and time_stamps
            if language and language.lower() == "auto":
                language = None
                
            results = self.model.transcribe(
                audio=processed_audio,
                language=language,
                return_time_stamps=True
            )
            
            return results
        finally:
             if os.path.exists(processed_audio):
                 os.remove(processed_audio)

    def transcribe_iter(self, audio_path, language=None, chunk_size=30, preprocessed=False):
        """
        Transcribe audio in chunks and YIELD results.
        chunk_size: seconds
        """
        processed_audio = audio_path if preprocessed else self.preprocess_audio(audio_path)
        cleanup_processed = not preprocessed
        # Session ID is embedded in the filename
        # We need it for chunk naming or just use uuid again? 
        # Actually easier to just generate a random ID for chunks
        session_id = str(uuid.uuid4())
        
        # Get duration
        try:
             probe = ffmpeg.probe(processed_audio)
             duration = float(probe['format']['duration'])
        except Exception:
             duration = 3600 # Fallback 1 hour? Or just loop until failure
             
        logger.info(f"Starting chunked transcription (duration: {duration}s, chunk: {chunk_size}s)...")
        
        import math
        chunks = math.ceil(duration / chunk_size)
        
        try:
            for i in range(chunks):
                start_time = i * chunk_size
                
                # Create a temp chunk file
                chunk_path = f"temp_chunk_{session_id}_{i}.wav"
                
                try:
                    (
                        ffmpeg
                        .input(processed_audio, ss=start_time, t=chunk_size)
                        .output(chunk_path, ac=1, ar=16000, loglevel="quiet")
                        .overwrite_output()
                        .run()
                    )
                    
                    # Transcribe chunk
                    if language and language.lower() == "auto":
                        lang_arg = None
                    else:
                        lang_arg = language

                    chunk_results = self.model.transcribe(
                        audio=chunk_path,
                        language=lang_arg,
                        return_time_stamps=True
                    )
                    
                    # Adjust timestamps and convert to DICT immediately to free memory
                    chunk_data = []
                    path_offset = start_time
                    
                    for res in chunk_results:
                        # 'res' is an object with .text, .time_stamps (list of objects)
                        res_dict = {
                            "text": res.text,
                            "time_stamps": []
                        }
                        
                        if hasattr(res, 'time_stamps') and res.time_stamps:
                            for ts in res.time_stamps:
                                # Convert to pure float/str dict
                                ts_dict = {
                                    "text": ts.text,
                                    "start_time": float(ts.start_time + path_offset),
                                    "end_time": float(ts.end_time + path_offset)
                                }
                                res_dict["time_stamps"].append(ts_dict)
                                
                        chunk_data.append(res_dict)
                    
                    # Delete original heavy objects immediately
                    del chunk_results
                    
                    logger.info(f"Yielding chunk {i} results (converted to local dicts)...")
                    yield chunk_data
                    
                except Exception as e:
                    logger.error(f"Error processing chunk {i}: {e}")
                    continue
                finally:
                    if os.path.exists(chunk_path):
                        os.remove(chunk_path)
                    
                    # Explicit cleanup to prevent memory buildup
                    import gc
                    if torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                    gc.collect()
        finally:
            # Clean up the main processed audio if we created it
            if cleanup_processed and os.path.exists(processed_audio):
                os.remove(processed_audio)

    def generate_subtitles(self, results, max_len=40):
        """
        Generate structured subtitles from transcription results.
        Returns a list of dicts: {'start': float, 'end': float, 'text': str}
        Input 'results' should be a list of DICTS now.
        """
        subtitles = []
        
        for res in results:
            # Handle both dict (new) and object (old/direct) just in case, but prioritize dict
            time_stamps = res.get("time_stamps") if isinstance(res, dict) else res.time_stamps
            full_text = res.get("text") if isinstance(res, dict) else res.text
            
            if not time_stamps:
                continue
            
            text_cursor = 0

            # 句级缓冲区：按可读语义累积，不再按词级立刻拆分。
            buffer_parts = []
            buffer_start = None
            buffer_end = None
            buffer_token_count = 0

            for i, ts in enumerate(time_stamps):
                # ts is dict
                token = ts["text"] if isinstance(ts, dict) else ts.text
                start = ts["start_time"] if isinstance(ts, dict) else ts.start_time
                end = ts["end_time"] if isinstance(ts, dict) else ts.end_time
                
                # Find token in full_text to get the "gap" (punctuation/spaces)
                match_index = full_text.find(token, text_cursor)
                
                gap = ""
                if match_index != -1:
                    gap = full_text[text_cursor:match_index]
                    text_cursor = match_index + len(token)

                if buffer_start is None:
                    buffer_start = start

                fragment = f"{gap}{token}"
                buffer_parts.append(fragment)
                buffer_end = end
                buffer_token_count += 1

                next_start = None
                pause_to_next = None
                if i < len(time_stamps) - 1:
                    next_ts = time_stamps[i + 1]
                    next_start = (
                        next_ts["start_time"]
                        if isinstance(next_ts, dict)
                        else next_ts.start_time
                    )
                    pause_to_next = max(0.0, float(next_start - end))

                current_text = "".join(buffer_parts).strip()
                has_stop_punct = any(ch in fragment for ch in SENTENCE_STOP_PUNCT)
                has_soft_break = any(ch in fragment for ch in SOFT_BREAK_PUNCT)
                is_last_token = i == len(time_stamps) - 1

                should_split = False
                if has_stop_punct:
                    should_split = True
                elif pause_to_next is not None and pause_to_next >= LONG_PAUSE_SPLIT_SEC:
                    should_split = True
                elif (
                    len(current_text) >= max_len
                    and (
                        has_soft_break
                        or (pause_to_next is not None and pause_to_next >= SOFT_PAUSE_SPLIT_SEC)
                    )
                ):
                    should_split = True
                elif is_last_token:
                    should_split = True

                if not should_split:
                    continue

                # 避免连接词尾部独立成句，优先继续并入后续 token。
                if _segment_tail_is_connector(current_text) and not is_last_token:
                    continue

                current_duration = 0.0
                if buffer_start is not None and buffer_end is not None:
                    current_duration = max(0.0, float(buffer_end - buffer_start))

                # 过短/过少 token 的片段优先继续累积，降低“is / harness”孤立概率。
                if (
                    current_duration < MIN_SEGMENT_DURATION_SEC
                    or buffer_token_count < MIN_SEGMENT_TOKENS
                ) and not is_last_token:
                    continue

                if current_text and buffer_start is not None and buffer_end is not None:
                    subtitles.append({
                        "start": float(buffer_start),
                        "end": float(buffer_end),
                        "text": current_text,
                    })

                buffer_parts = []
                buffer_start = None
                buffer_end = None
                buffer_token_count = 0

            # 防御式兜底：若循环结束仍残留缓冲，补写最后一条。
            if buffer_parts and buffer_start is not None and buffer_end is not None:
                trailing = full_text[text_cursor:]
                if trailing:
                    buffer_parts.append(trailing)
                final_text = "".join(buffer_parts).strip()
                if final_text:
                    subtitles.append({
                        "start": float(buffer_start),
                        "end": float(buffer_end),
                        "text": final_text,
                    })

        # 每个 chunk 出口做一次轻量清洗，减少碎片/重叠传递到拼接阶段。
        return normalize_subtitle_timeline(subtitles)

    # Methods moved to module level functions


def _normalize_compare_text(text: str) -> str:
    """将文本规整为可比对格式（去空白/标点、小写）。"""

    normalized = re.sub(r"[\W_]+", "", str(text or "").lower(), flags=re.UNICODE)
    return normalized.strip()


def _extract_text_tokens(text: str) -> list[str]:
    """提取用于重叠判断的 token（英文词 + 中文单字）。"""

    return re.findall(r"[A-Za-z0-9']+|[\u4e00-\u9fff]", str(text or ""), flags=re.UNICODE)


def _count_reading_units(text: str) -> int:
    """估算可读单元数量，用于判定短碎片。"""

    return len(_extract_text_tokens(text))


def _segment_tail_is_connector(text: str) -> bool:
    """判断句尾是否是连接词/语气尾词，避免把它们独立切出去。"""

    tokens = _extract_text_tokens(text)
    if not tokens:
        return False
    tail = tokens[-1].lower()
    return tail in CONNECTOR_TAIL_WORDS


def _segment_head_is_connector(text: str) -> bool:
    """判断句首是否是弱连接词，避免被切成下一句开头。"""

    tokens = _extract_text_tokens(text)
    if not tokens:
        return False
    head = tokens[0].lower()
    return head in CONNECTOR_HEAD_WORDS


def _strip_leading_punctuation(text: str) -> str:
    """移除句首孤立标点，减少“, and ... / . And ...”这类机器感开头。"""

    cleaned = re.sub(
        rf"^[{re.escape(LEADING_PUNCT_CHARS)}\s]+",
        "",
        str(text or ""),
        flags=re.UNICODE,
    )
    return cleaned.strip()


def _strip_leading_connector_token(text: str) -> str:
    """在无法并回前句时，移除弱连接词句首，提升阅读自然度。"""

    compact = re.sub(r"\s+", " ", str(text or "").strip(), flags=re.UNICODE).strip()
    if not compact:
        return ""
    match = re.match(r"^([A-Za-z']+)\b\s*(.*)$", compact)
    if not match:
        return compact
    head = match.group(1).lower()
    tail = match.group(2).strip()
    if head not in REMOVABLE_HEAD_CONNECTORS or not tail:
        return compact
    return tail


def _estimate_text_split_index(text: str) -> int | None:
    """为长句寻找更自然的拆分点，优先软标点与连接词附近。"""

    compact = re.sub(r"\s+", " ", str(text or "").strip(), flags=re.UNICODE)
    if not compact:
        return None

    mid = len(compact) // 2
    candidate_idx: list[int] = []

    # 先找靠近中点的软标点，拆分效果最稳定。
    for match in re.finditer(r"[,:;，；：]", compact):
        idx = match.start()
        if len(compact) * 0.2 <= idx <= len(compact) * 0.8:
            candidate_idx.append(idx + 1)

    if candidate_idx:
        return min(candidate_idx, key=lambda value: abs(value - mid))

    # 再找连接词前的位置（避免把 "and/but/so" 单独留在下一句）。
    for match in re.finditer(r"\b([A-Za-z']+)\b", compact):
        token = match.group(1).lower()
        if token not in SPLIT_HINT_WORDS:
            continue
        # 断在连接词后，避免右侧新句以弱词开头。
        idx = match.end()
        if len(compact) * 0.2 <= idx <= len(compact) * 0.8:
            candidate_idx.append(idx)

    if candidate_idx:
        return min(candidate_idx, key=lambda value: abs(value - mid))

    # 最后兜底：在中点附近找空格。
    left_space = compact.rfind(" ", 0, mid)
    right_space = compact.find(" ", mid)
    options = [pos for pos in (left_space, right_space) if pos > 0]
    if options:
        return min(options, key=lambda value: abs(value - mid))

    return None


def _split_long_subtitle_row(
    row: dict,
    *,
    min_duration_sec: float,
    max_duration_sec: float,
    overlap_pad_sec: float,
) -> list[dict]:
    """把超长字幕拆成两条，时间按文本比例映射，保持总时长不变。"""

    start = float(row.get("start", 0.0))
    end = float(row.get("end", start))
    text = re.sub(r"\s+", " ", str(row.get("text", "")).strip(), flags=re.UNICODE).strip()
    duration = max(0.0, end - start)
    if not text or duration <= max_duration_sec:
        return [row]

    split_idx = _estimate_text_split_index(text)
    if split_idx is None:
        # 无自然切点时，退化为中点切，确保超长句不会原样透传。
        split_idx = len(text) // 2

    left_text = text[:split_idx].strip()
    right_text = text[split_idx:].strip()
    if not left_text or not right_text:
        return [row]

    total_len = max(1, len(left_text) + len(right_text))
    left_ratio = len(left_text) / total_len
    split_time = start + duration * left_ratio

    min_slot = max(float(min_duration_sec), 0.5)
    split_time = max(start + min_slot, min(split_time, end - min_slot))
    right_start = split_time + max(0.0, float(overlap_pad_sec))
    if right_start >= end:
        right_start = split_time

    left = {
        "start": start,
        "end": split_time,
        "text": left_text,
    }
    right = {
        "start": right_start,
        "end": end,
        "text": right_text,
    }
    return [left, right]


def _wrap_subtitle_lines(text: str, *, max_chars: int = LINE_MAX_CHARS, max_lines: int = LINE_MAX_LINES) -> str:
    """将字幕文本按阅读习惯换行：优先 1-2 行，尽量每行不超过 max_chars。"""

    compact = re.sub(r"\s+", " ", str(text or "").strip(), flags=re.UNICODE).strip()
    if not compact:
        return ""

    # 中文无空格场景：按字符宽度硬切，优先限制在两行内。
    if " " not in compact:
        if len(compact) <= max_chars:
            return compact
        if max_lines <= 1:
            return compact
        head = compact[:max_chars]
        tail = compact[max_chars:]
        return f"{head}\n{tail}".strip()

    words = compact.split(" ")
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        if len(lines) >= max_lines - 1:
            current.append(word)
            continue

        candidate = " ".join(current + [word]).strip()
        if not current or len(candidate) <= max_chars:
            current.append(word)
            continue

        lines.append(" ".join(current))
        current = [word]

    if current:
        lines.append(" ".join(current))

    if not lines:
        return compact

    # 总长度可控时，做一次两行再平衡，尽量让每行都不超过 max_chars。
    if (
        len(lines) == 2
        and (len(lines[0]) > max_chars or len(lines[1]) > max_chars)
        and len(compact) <= max_chars * max_lines
    ):
        cut = compact.rfind(" ", 0, max_chars + 1)
        if cut <= 0:
            cut = compact.find(" ", max_chars)
        if cut > 0:
            left = compact[:cut].strip()
            right = compact[cut + 1 :].strip()
            if left and right:
                lines = [left, right]

    return "\n".join(line.strip() for line in lines if line.strip())


def _join_subtitle_text(left: str, right: str) -> str:
    """拼接字幕文本：中英文统一按空格拼接，再做空白归一。"""

    joined = f"{str(left or '').strip()} {str(right or '').strip()}".strip()
    return re.sub(r"\s+", " ", joined, flags=re.UNICODE).strip()


def _build_overlap_merged_text(tail_text: str, head_text: str) -> str | None:
    """尝试按 token 前后缀重叠合并两段文本；无法合并返回 None。"""

    tail_tokens = _extract_text_tokens(tail_text)
    head_tokens = _extract_text_tokens(head_text)
    if not tail_tokens or not head_tokens:
        return None

    max_overlap = min(6, len(tail_tokens), len(head_tokens))
    for overlap in range(max_overlap, 1, -1):
        tail_suffix = [token.lower() for token in tail_tokens[-overlap:]]
        head_prefix = [token.lower() for token in head_tokens[:overlap]]
        if tail_suffix != head_prefix:
            continue
        merged_tokens = tail_tokens + head_tokens[overlap:]
        if not merged_tokens:
            return None
        # 当前 ASR 片段以英文演讲为主，重叠拼接统一空格可显著减少重复词读感。
        return " ".join(merged_tokens)
    return None


def merge_chunk_subtitles(
    existing_subtitles: list[dict] | None,
    incoming_subtitles: list[dict] | None,
    *,
    boundary_window_sec: float = 1.0,
    overlap_pad_sec: float = 0.01,
) -> list[dict]:
    """
    在 chunk 边界做轻量去重拼接，避免“尾句和首句重复覆盖”。

    说明：
    - 仅比较 existing 尾句与 incoming 首句；
    - 命中重复时合并首句，不命中则正常拼接；
    - 若出现时间交叉但文本不重复，做最小起点后移保护。
    """

    existing = [dict(item) for item in (existing_subtitles or [])]
    incoming = [dict(item) for item in (incoming_subtitles or [])]
    if not existing:
        return incoming
    if not incoming:
        return existing

    tail = existing[-1]
    head = incoming[0]
    tail_end = float(tail.get("end", 0.0))
    head_start = float(head.get("start", 0.0))

    if head_start <= tail_end + max(0.0, float(boundary_window_sec)):
        tail_text = str(tail.get("text", "")).strip()
        head_text = str(head.get("text", "")).strip()
        tail_norm = _normalize_compare_text(tail_text)
        head_norm = _normalize_compare_text(head_text)

        duplicate_like = False
        if tail_norm and head_norm:
            duplicate_like = (
                tail_norm == head_norm
                or tail_norm in head_norm
                or head_norm in tail_norm
            )

        if duplicate_like:
            # 完整重复场景：保留信息量更长的一条，避免边界重复闪现。
            merged_text = tail_text if len(tail_text) >= len(head_text) else head_text
            tail["text"] = merged_text
            tail["end"] = max(float(tail.get("end", 0.0)), float(head.get("end", 0.0)))
            existing[-1] = tail
            incoming = incoming[1:]
        else:
            # 部分重叠场景：尝试按 token 前后缀去重（如“means is | is we ...”）。
            overlap_merged = _build_overlap_merged_text(tail_text, head_text)
            if overlap_merged:
                tail["text"] = overlap_merged
                tail["end"] = max(float(tail.get("end", 0.0)), float(head.get("end", 0.0)))
                existing[-1] = tail
                incoming = incoming[1:]
            elif head_start < tail_end:
                # 仅时间交叉场景：最小后移首句起点，防止播放器重叠闪烁。
                new_start = tail_end + max(0.0, float(overlap_pad_sec))
                head["start"] = new_start
                if float(head.get("end", 0.0)) <= new_start:
                    head["end"] = new_start + 0.20
                incoming[0] = head

    return existing + incoming


def normalize_subtitle_timeline(
    subtitles: list[dict] | None,
    *,
    overlap_pad_sec: float = 0.01,
    min_duration_sec: float = 0.20,
    short_duration_sec: float = HARD_MIN_SUBTITLE_SEC,
    short_unit_limit: int = 4,
    short_merge_gap_sec: float = 0.35,
    soft_short_duration_sec: float = SOFT_MIN_SUBTITLE_SEC,
    hard_max_duration_sec: float = HARD_MAX_SUBTITLE_SEC,
) -> list[dict]:
    """
    轻量时间轴+阅读节奏兜底（O(n)）：
    - 排序、去空行、保证 start < end；
    - 做最小 overlap clamp；
    - 合并短句、修复弱词起句、拆分超长句。
    """

    if not subtitles:
        return []

    normalized: list[dict] = []
    for raw in sorted(subtitles, key=lambda item: float(item.get("start", 0.0))):
        text = re.sub(r"\s+", " ", str(raw.get("text", "")).strip(), flags=re.UNICODE).strip()
        if not text:
            continue

        start = float(raw.get("start", 0.0))
        end = float(raw.get("end", start))
        if end <= start:
            end = start + max(0.01, float(min_duration_sec))

        if normalized:
            prev_end = float(normalized[-1]["end"])
            min_start = prev_end + max(0.0, float(overlap_pad_sec))
            if start < min_start:
                start = min_start
            if end <= start:
                end = start + max(0.01, float(min_duration_sec))

        normalized.append({
            "start": start,
            "end": end,
            "text": text,
        })

    if not normalized:
        return []

    merged: list[dict] = []
    idx = 0
    while idx < len(normalized):
        current = normalized[idx]
        duration = float(current["end"]) - float(current["start"])
        units = _count_reading_units(current["text"])
        starts_with_punct = bool(
            re.match(
                rf"^[{re.escape(LEADING_PUNCT_CHARS)}]",
                str(current.get("text", "")).strip(),
                flags=re.UNICODE,
            )
        )
        starts_with_connector = _segment_head_is_connector(current["text"])
        is_short = (
            duration < float(short_duration_sec)
            or (
                duration < float(soft_short_duration_sec)
                and (
                    starts_with_punct
                    or starts_with_connector
                    or (
                        units <= int(short_unit_limit)
                        and duration < float(short_duration_sec) * 1.05
                    )
                )
            )
        )

        if not is_short:
            merged.append(current)
            idx += 1
            continue

        prev_item = merged[-1] if merged else None
        next_item = normalized[idx + 1] if idx + 1 < len(normalized) else None
        merged_to_neighbor = False

        if prev_item is not None:
            gap_to_prev = float(current["start"]) - float(prev_item["end"])
            if gap_to_prev <= float(short_merge_gap_sec):
                prev_item["text"] = _join_subtitle_text(prev_item["text"], current["text"])
                prev_item["end"] = max(float(prev_item["end"]), float(current["end"]))
                merged[-1] = prev_item
                merged_to_neighbor = True

        if not merged_to_neighbor and next_item is not None:
            gap_to_next = float(next_item["start"]) - float(current["end"])
            if gap_to_next <= float(short_merge_gap_sec):
                next_item["start"] = min(float(current["start"]), float(next_item["start"]))
                next_item["text"] = _join_subtitle_text(current["text"], next_item["text"])
                normalized[idx + 1] = next_item
                merged_to_neighbor = True

        if not merged_to_neighbor:
            merged.append(current)

        idx += 1

    # 第二阶段：修复句首标点/弱连接词，优先并回上一句。
    repaired: list[dict] = []
    for current in merged:
        raw_text = str(current.get("text", "")).strip()
        if not raw_text:
            continue
        had_leading_punct = bool(
            re.match(
                rf"^[{re.escape(LEADING_PUNCT_CHARS)}]",
                raw_text,
                flags=re.UNICODE,
            )
        )
        fixed_text = _strip_leading_punctuation(raw_text)
        if not fixed_text:
            continue
        current["text"] = fixed_text

        if repaired:
            prev = repaired[-1]
            gap_to_prev = float(current["start"]) - float(prev["end"])
            starts_with_connector = _segment_head_is_connector(fixed_text)
            cur_duration = float(current["end"]) - float(current["start"])
            combined_duration = float(current["end"]) - float(prev["start"])
            attach_gap_limit = max(float(short_merge_gap_sec), 0.80)
            if starts_with_connector:
                # 连接词起句允许更大的并句窗口，优先保证语义连贯。
                attach_gap_limit = max(attach_gap_limit, 1.50)
            should_attach_prev = (
                gap_to_prev <= attach_gap_limit
                and (
                    had_leading_punct
                    or starts_with_connector
                    or cur_duration < float(short_duration_sec)
                )
                and (
                    not starts_with_connector
                    or combined_duration <= float(hard_max_duration_sec) + 0.20
                )
            )
            if should_attach_prev:
                prev["text"] = _join_subtitle_text(prev["text"], fixed_text)
                prev["end"] = max(float(prev["end"]), float(current["end"]))
                repaired[-1] = prev
                continue

            if starts_with_connector:
                # 无法并句时，尽量去掉弱连接词句首，减少“and/that 开头”机器感。
                fixed_text = _strip_leading_connector_token(fixed_text)
                if not fixed_text:
                    continue
                current["text"] = fixed_text

        repaired.append(current)

    # 第三阶段：拆分超长句（>6s），控制阅读节奏峰值。
    split_rows: list[dict] = []
    for row in repaired:
        pending = [row]
        # 允许最多递归拆 3 次，避免极端长句只拆一刀仍超长。
        for _ in range(3):
            next_pending: list[dict] = []
            changed = False
            for item in pending:
                duration = float(item.get("end", 0.0)) - float(item.get("start", 0.0))
                text_len = len(str(item.get("text", "")).strip())
                need_split_by_duration = duration > float(hard_max_duration_sec)
                need_split_by_text = text_len > int(LINE_MAX_CHARS * 1.50)
                if not need_split_by_duration and not need_split_by_text:
                    next_pending.append(item)
                    continue
                split_parts = _split_long_subtitle_row(
                    item,
                    min_duration_sec=min_duration_sec,
                    max_duration_sec=hard_max_duration_sec,
                    overlap_pad_sec=overlap_pad_sec,
                )
                if len(split_parts) == 1:
                    next_pending.append(item)
                    continue
                next_pending.extend(split_parts)
                changed = True
            pending = next_pending
            if not changed:
                break
        split_rows.extend(pending)

    # 拆分后再做一次句首修复，避免新切点生成弱词起句。
    post_split_repaired: list[dict] = []
    for row in split_rows:
        text = _strip_leading_punctuation(str(row.get("text", "")).strip())
        if not text:
            continue
        row["text"] = text
        starts_with_connector = _segment_head_is_connector(text)
        if post_split_repaired and starts_with_connector:
            prev = post_split_repaired[-1]
            gap_to_prev = float(row["start"]) - float(prev["end"])
            combined_duration = float(row["end"]) - float(prev["start"])
            if gap_to_prev <= 1.00:
                if combined_duration > float(hard_max_duration_sec) + 0.20:
                    text = _strip_leading_connector_token(text)
                    if not text:
                        continue
                    row["text"] = text
                    post_split_repaired.append(row)
                    continue
                prev["text"] = _join_subtitle_text(prev["text"], text)
                prev["end"] = max(float(prev["end"]), float(row["end"]))
                post_split_repaired[-1] = prev
                continue
            text = _strip_leading_connector_token(text)
            if not text:
                continue
            row["text"] = text
        post_split_repaired.append(row)

    # 末尾再做一次时间轴 clamp，确保拆分后仍严格单调。
    final_rows: list[dict] = []
    for row in post_split_repaired:
        text = re.sub(r"\s+", " ", str(row.get("text", "")).strip(), flags=re.UNICODE).strip()
        if not text:
            continue
        start = float(row.get("start", 0.0))
        end = float(row.get("end", start))
        if final_rows:
            min_start = float(final_rows[-1]["end"]) + max(0.0, float(overlap_pad_sec))
            if start < min_start:
                start = min_start
        if end <= start:
            end = start + max(0.01, float(min_duration_sec))
        final_rows.append({
            "start": start,
            "end": end,
            "text": text,
        })

    return final_rows

def seconds_to_srt_time(seconds):
    millis = int((seconds % 1) * 1000)
    seconds = int(seconds)
    minutes = seconds // 60
    hours = minutes // 60
    minutes = minutes % 60
    seconds = seconds % 60
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

def format_srt(subtitles):
    """
    Convert structured subtitles to SRT string.
    """
    srt_content = []
    for i, sub in enumerate(subtitles):
        start_str = seconds_to_srt_time(sub['start'])
        end_str = seconds_to_srt_time(sub['end'])
        # 输出前做显示换行：优先 1~2 行、每行尽量不超过 42 字符。
        display_text = _wrap_subtitle_lines(
            sub.get("text", ""),
            max_chars=LINE_MAX_CHARS,
            max_lines=LINE_MAX_LINES,
        )
        srt_content.append(f"{i+1}\n{start_str} --> {end_str}\n{display_text}\n")
        
    return "\n".join(srt_content)

def merge_subtitles(original, translated, order="orig_trans"):
    """
    Merge original and translated subtitles into a single list.
    order: 'orig_trans' (Original then Translation) or 'trans_orig' (Translation then Original)
    """
    merged = []
    # Zip safely, though lengths should be equal from translator
    for o, t in zip(original, translated):
        new_sub = o.copy()
        o_text = o['text']
        t_text = t['text']
        
        if order == "orig_trans":
            new_sub['text'] = f"{o_text}\n{t_text}"
        elif order == "trans_orig":
            new_sub['text'] = f"{t_text}\n{o_text}"
        
        merged.append(new_sub)
    return merged

def parse_srt(srt_content: str):
    """
    Parse an SRT string into a list of subtitles.
    Returns: [{'start': float, 'end': float, 'text': str}, ...]
    """
    subtitles = []
    blocks = srt_content.strip().split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 3:
            continue
            
        # Line 1: Index (skip)
        
        # Line 2: Timecode
        timecode = lines[1]
        if '-->' not in timecode:
            continue
            
        start_str, end_str = timecode.split('-->')
        
        # Line 3+: Text
        text = "\n".join(lines[2:])
        
        try:
            start = _srt_time_to_seconds(start_str.strip())
            end = _srt_time_to_seconds(end_str.strip())
            subtitles.append({
                'start': start,
                'end': end,
                'text': text
            })
        except Exception:
            continue
            
    return subtitles

def _srt_time_to_seconds(time_str):
    # 00:00:00,000
    time_str = time_str.replace(',', '.')
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds
