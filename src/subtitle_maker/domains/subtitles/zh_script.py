from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

try:  # pragma: no cover - 本地环境未必安装
    import zhconv  # type: ignore
except Exception:  # pragma: no cover - 运行时按需回退
    zhconv = None


def _normalize_variant(variant: str) -> str:
    """把脚本开关归一成简体或繁体。"""

    lowered = str(variant or "").strip().lower()
    if lowered in {"traditional", "t", "trad", "tw", "tc", "繁体", "繁體", "繁体中文", "繁體中文"}:
        return "traditional"
    return "simplified"


@lru_cache(maxsize=1)
def _load_sibling_char_converter() -> object | None:
    """尽量复用仓库里已有的简繁转换实现，减少重复维护。"""

    candidate_paths = [
        Path(__file__).resolve().parents[5] / "GPT-SoVITS" / "GPT_SoVITS" / "text" / "zh_normalization" / "char_convert.py",
        Path(__file__).resolve().parents[5] / "GPT-SoVITS-CPUFast" / "GPT_SoVITS" / "text" / "zh_normalization" / "char_convert.py",
        Path(__file__).resolve().parents[5] / "GPT-SoVITS" / "external" / "GPT-SoVITS-CPUFast" / "GPT_SoVITS" / "text" / "zh_normalization" / "char_convert.py",
    ]
    for candidate in candidate_paths:
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location("subtitle_maker_zh_char_convert", candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None


def convert_chinese_script_text(text: str, variant: str) -> str:
    """按目标脚本把中文正文转换成简体或繁体。"""

    normalized_text = str(text or "")
    normalized_variant = _normalize_variant(variant)
    if not normalized_text.strip():
        return normalized_text.strip()

    if zhconv is not None:
        target = "zh-tw" if normalized_variant == "traditional" else "zh-cn"
        return str(zhconv.convert(normalized_text, target))

    converter = _load_sibling_char_converter()
    if converter is not None:
        if normalized_variant == "traditional" and hasattr(converter, "simplified_to_traditional"):
            return str(converter.simplified_to_traditional(normalized_text))
        if normalized_variant == "simplified" and hasattr(converter, "tranditional_to_simplified"):
            return str(converter.tranditional_to_simplified(normalized_text))

    return normalized_text


def convert_chinese_script_rows(rows: List[Dict[str, Any]], variant: str) -> List[Dict[str, Any]]:
    """把字幕行的 text 按脚本开关批量转换，保留时间戳与 speaker。"""

    return [
        {
            **dict(row),
            "text": convert_chinese_script_text(str(row.get("text") or ""), variant),
        }
        for row in list(rows or [])
    ]
