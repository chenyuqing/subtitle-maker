from __future__ import annotations

import re
from typing import Any, Dict, List


def merge_text_lines(lines: List[str], *, cjk_mode: bool) -> str:
    """按语言模式把多行文本合并成一条可比较的字幕文本。"""
    if cjk_mode:
        merged = "".join((line or "").strip() for line in lines)
        return re.sub(r"\s+", "", merged)

    merged = " ".join((line or "").strip() for line in lines)
    merged = re.sub(r"\s+", " ", merged).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", merged)


def infer_cjk_mode_from_lines(lines: List[str]) -> bool:
    """根据文本字符分布粗略判断是否应按 CJK 模式处理。"""
    merged = "".join(lines)
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", merged))
    latin_count = len(re.findall(r"[A-Za-z]", merged))
    return cjk_count > 0 and cjk_count >= max(1, latin_count // 2)


def is_sentence_end(text: str) -> bool:
    """判断文本是否以强句末标点结束。"""
    return bool(re.search(r"[.!?。！？][\"')\]]*\s*$", (text or "").strip()))


def is_orphan_like_line(text: str) -> bool:
    """判断文本是否像孤儿残句，避免被单独保留。"""
    compact = re.sub(r"\s+", "", (text or ""))
    if not compact or len(compact) <= 1:
        return True
    if re.fullmatch(r"[,.;:!?，。！？、；：…]+", compact):
        return True
    orphan_words = {
        "of",
        "to",
        "the",
        "a",
        "an",
        "and",
        "or",
        "is",
        "are",
        "in",
        "on",
        "at",
        "的",
        "了",
        "吗",
        "呢",
        "啊",
        "吧",
    }
    return compact.lower() in orphan_words


def ends_with_soft_sentence_break(text: str) -> bool:
    """判断文本是否以逗号等软停顿结束。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return bool(re.search(r"[,;:，、；：…]\s*$", cleaned))


def ends_with_explicit_break(text: str) -> bool:
    """判断文本是否以显式切分标点结束。"""
    return is_sentence_end(text) or ends_with_soft_sentence_break(text)


def subtitle_group_duration(items: List[Dict[str, Any]]) -> float:
    """返回连续字幕组的总时长。"""
    if not items:
        return 0.0
    return max(0.0, float(items[-1]["end"]) - float(items[0]["start"]))


def subtitle_group_text(items: List[Dict[str, Any]], *, cjk_mode: bool) -> str:
    """按语言模式合并连续字幕组文本。"""
    return merge_text_lines([(item.get("text") or "").strip() for item in items], cjk_mode=cjk_mode)


def subtitle_text_units(text: str, *, cjk_mode: bool) -> int:
    """估算文本负载，用于长度和时长规则评分。"""
    cleaned = (text or "").strip()
    if not cleaned:
        return 0
    if cjk_mode:
        return len(re.sub(r"\s+", "", cleaned))
    return len(re.sub(r"\s+", " ", cleaned))


def asr_sentence_text_limit(*, max_line_width: int, cjk_mode: bool) -> int:
    """给句级合并提供较宽松的文本上限。"""
    width = max(8, int(max_line_width or 0))
    if cjk_mode:
        return max(48, width * 2)
    return max(160, width * 4)


def soft_source_layout_text_limit(*, max_line_width: int, cjk_mode: bool) -> int:
    """给规则评分使用更严格的软上限。"""
    width = max(8, int(max_line_width or 0))
    if cjk_mode:
        return max(28, width + 6)
    return max(70, int(round(width * 2.25)))


def extract_edge_tokens(text: str) -> List[str]:
    """抽取文本首尾 token，辅助判断连接词坏切点。"""
    return re.findall(r"[A-Za-z']+|[\u4e00-\u9fff]+", (text or "").lower())


def ends_with_connector(text: str) -> bool:
    """判断文本是否以连接词结尾。"""
    tokens = extract_edge_tokens(text)
    if not tokens:
        return False
    return tokens[-1] in {
        "a",
        "an",
        "and",
        "as",
        "at",
        "because",
        "but",
        "for",
        "from",
        "if",
        "in",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "to",
        "when",
        "while",
        "with",
        "了",
        "但",
        "又",
        "和",
        "就",
        "而",
        "还",
    }


def starts_with_connector(text: str) -> bool:
    """判断文本是否以连接词起头。"""
    tokens = extract_edge_tokens(text)
    if not tokens:
        return False
    return tokens[0] in {
        "and",
        "as",
        "because",
        "but",
        "for",
        "if",
        "no",
        "or",
        "so",
        "that",
        "then",
        "to",
        "when",
        "while",
        "with",
        "但",
        "又",
        "和",
        "就",
        "而",
        "还",
    }


def build_rebalanced_subtitle(block: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把连续 cue 块重建成新的字幕项，时间保持原边界。"""
    if len(block) == 1:
        return dict(block[0])
    cjk_mode = infer_cjk_mode_from_lines([(item.get("text") or "") for item in block])
    merged = dict(block[0])
    merged["start"] = float(block[0]["start"])
    merged["end"] = float(block[-1]["end"])
    merged["text"] = subtitle_group_text(block, cjk_mode=cjk_mode)
    return merged

