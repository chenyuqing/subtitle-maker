import os
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - 仅在测试 stub 或缺依赖时触发
    OpenAI = None

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationProviderDefaults:
    """默认翻译供应商配置。

    后续若需要切换默认供应商，只改这里一处即可。
    """

    base_url: str
    model: str


DEFAULT_TRANSLATION_PROVIDER = TranslationProviderDefaults(
    base_url="https://api.deepseek.com",
    model="deepseek-v4-flash",
)
# 兼容现有 import 合同：调用方仍可继续读取原常量名。
DEFAULT_TRANSLATE_BASE_URL = DEFAULT_TRANSLATION_PROVIDER.base_url
DEFAULT_TRANSLATE_MODEL = DEFAULT_TRANSLATION_PROVIDER.model
TRANSLATE_API_KEY_ENV = "TRANSLATE_API_KEY"
LEGACY_TRANSLATE_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEFAULT_TRANSLATION_BATCH_SIZE = 100
MIN_TRANSLATION_RETRY_CHUNK_SIZE = 30
MAX_TRANSLATION_MISSING_RETRY_COUNT = 15
MAX_TRANSLATION_MISSING_RETRY_RATIO = 0.15
TRANSLATION_MISSING_RETRY_CONTEXT_RADIUS = 1


class TranslationProviderError(RuntimeError):
    """翻译 provider 请求失败时抛出的统一异常。"""


def _target_prefers_cjk_text(target_lang: str) -> bool:
    """判断目标语言是否应优先输出中文正文。"""

    lowered = str(target_lang or "").strip().lower()
    if not lowered:
        return False
    markers = ("chinese", "mandarin", "cantonese", "yue", "zh", "中文", "汉语", "漢語", "普通话", "普通話", "粤语", "廣東話", "广东话")
    return any(marker in lowered for marker in markers)


def normalize_language_tag_for_passthrough(language: str) -> str:
    """把前后端语言值归一成稳定标签，供“同语种跳过翻译”判断复用。"""

    lowered = str(language or "").strip().lower()
    if not lowered:
        return ""
    if lowered == "auto":
        return "auto"
    if lowered in {"chinese", "mandarin", "zh", "zh-cn", "zh-hans", "zh-hant", "中文", "汉语", "漢語", "普通话", "普通話"}:
        return "zh"
    if lowered in {
        "cantonese",
        "cantonese-mainland",
        "mainland cantonese",
        "mainland-cantonese",
        "yue",
        "粤语",
        "廣東話",
        "广东话",
        "广东式粤语",
        "廣東式粵語",
        "繁体粤语",
        "繁體粵語",
        "简体粤语",
        "簡體粵語",
    }:
        return "yue"
    if lowered in {"english", "en"}:
        return "en"
    if lowered in {"french", "fr", "français", "francais"}:
        return "fr"
    if lowered in {"german", "de", "deutsch"}:
        return "de"
    if lowered in {"italian", "it", "italiano"}:
        return "it"
    if lowered in {"japanese", "ja", "日本語"}:
        return "ja"
    if lowered in {"korean", "ko", "한국어"}:
        return "ko"
    if lowered in {"portuguese", "pt", "português", "portugues"}:
        return "pt"
    if lowered in {"russian", "ru", "русский", "pусский"}:
        return "ru"
    if lowered in {"spanish", "es", "español", "espanol"}:
        return "es"
    return lowered


def _split_translation_candidate_segments(text: str) -> list[str]:
    """把模型混在一行里的多个候选片段切开，便于挑出真正的正文译文。"""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    segments = [
        segment.strip(" \t\"'“”‘’")
        for segment in re.split(r"\s*(?:[。！？!?]+|(?<!\w)\.(?!\w)|[:：])\s*", normalized)
        if segment.strip(" \t\"'“”‘’")
    ]
    return segments if segments else [normalized]


def _expand_translation_candidate_segments(segments: list[str]) -> list[str]:
    """为中英混合候选补充纯中文子片段，便于挑出真正的最终译文。"""

    expanded: list[str] = []
    for segment in segments:
        normalized_segment = str(segment or "").strip()
        if not normalized_segment:
            continue
        expanded.append(normalized_segment)
        cjk_subsegments = [
            item.strip()
            for item in re.findall(r"[\u4e00-\u9fff]+(?:[，。！？、；：,.!?][\u4e00-\u9fff]+)*", normalized_segment)
            if item.strip()
        ]
        for cjk_segment in cjk_subsegments:
            if cjk_segment not in expanded:
                expanded.append(cjk_segment)
    return expanded


def sanitize_translation_text(text: str, target_lang: str) -> str:
    """清洗翻译正文，剥离模型说明性废话，尽量保留最终可用译文。"""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    # 先处理常见“最终答案 + 模型说明”尾巴。
    explanation_tail_patterns = (
        r"(?is)\s+(?:but|however)\s+chinese\s+output\s+only\b.*$",
        r"(?is)\s+let'?s\s+correct\s+in\s+final\b.*$",
        r"(?is)\s+(?:final\s+answer|final\s+output)\b.*$",
        r"(?is)\s+(?:please\s+)?output\s+only\b.*$",
    )
    for pattern in explanation_tail_patterns:
        normalized = re.sub(pattern, "", normalized).strip()

    if not _target_prefers_cjk_text(target_lang):
        return normalized

    # 中文目标语种下，若同一条里混进外语解释，优先挑 CJK 占优、且不像解释句的片段。
    best_candidate = normalized
    best_score = -10**9
    for candidate in _expand_translation_candidate_segments(_split_translation_candidate_segments(normalized)):
        lowered = candidate.lower()
        cjk_count = len(re.findall(r"[\u4e00-\u9fff]", candidate))
        latin_count = len(re.findall(r"[A-Za-z]", candidate))
        other_letter_count = len(re.findall(r"[^\W\d_A-Za-z\u4e00-\u9fff]", candidate, flags=re.UNICODE))
        score = cjk_count * 10 - latin_count * 3
        score -= other_letter_count * 6
        if re.search(r"\b(?:output|translate|translation|correct|final|english|chinese|only|let's|fight)\b", lowered):
            score -= 25
        if any(marker in candidate for marker in ("不对", "唔对", "錯誤", "错误", "改成", "更正")):
            score -= 18
        if re.search(r"[?？]", candidate):
            score -= 8
        if not candidate.strip():
            score -= 100
        if score >= best_score:
            best_candidate = candidate.strip()
            best_score = score

    # 再做一次保守收尾，避免残留英文说明尾巴。
    best_candidate = re.sub(r"(?is)\s+(?:but|however)\b.*$", "", best_candidate).strip()
    best_candidate = re.sub(r"(?is)\s+let'?s\b.*$", "", best_candidate).strip()
    if best_candidate:
        return best_candidate
    return normalized


def _normalize_cantonese_target_variant(target_lang: str) -> str:
    """把目标语归一为具体粤语变体，便于分别控制翻译风格。"""

    lowered = (target_lang or "").strip().lower()
    if not lowered:
        return ""
    mainland_markers = [
        "cantonese-mainland",
        "mainland cantonese",
        "mainland-cantonese",
        "广东式粤语",
        "廣東式粵語",
        "繁体粤语",
        "繁體粵語",
        "简体粤语",
        "簡體粵語",
    ]
    if any(marker in lowered for marker in mainland_markers):
        return "cantonese-mainland"
    cantonese_markers = ["cantonese", "粤语", "廣東話", "广东话", "yue"]
    if any(marker in lowered for marker in cantonese_markers):
        return "cantonese"
    return ""

def _is_cantonese_target_lang(target_lang: str) -> bool:
    return bool(_normalize_cantonese_target_variant(target_lang))


def _cantonese_prompt_constraints(target_lang: str) -> str:
    variant = _normalize_cantonese_target_variant(target_lang)
    if variant == "cantonese-mainland":
        return (
            "Cantonese constraints:\n"
            "- Use natural spoken Cantonese (Guangdong / Mainland style), not written Mandarin.\n"
            "- Prefer Traditional Chinese characters for output.\n"
            "- Must use authentic Cantonese vocabulary whenever possible, for example: 嘢、唔係、咩、搞掂、呢個、咁、返工、食飯.\n"
            "- Keep colloquial Cantonese function words natural in Traditional form (e.g. 佢/我哋/你哋/喺/咗/嘅/唔/咩/呀/喇/啦).\n"
            "- Tone must feel naturally spoken in Cantonese; add suitable sentence-final particles when appropriate (e.g. 㗎、啫、啦、呢、呀、咩).\n"
            "- Absolutely avoid written Mandarin, literal translation, or stiff book-style phrasing when a Cantonese alternative exists.\n\n"
        )
    return (
        "Cantonese constraints:\n"
        "- Use natural spoken Cantonese (Hong Kong style), not written Mandarin.\n"
        "- Prefer Traditional Chinese characters for output.\n"
        "- Must use authentic Cantonese vocabulary whenever possible, for example: 嘢、唔係、咩、搞掂、呢個、咁、返工、食飯.\n"
        "- Keep colloquial Cantonese function words natural (e.g. 佢/我哋/你哋/喺/咗/嘅/唔/咩/呀/喇/啦).\n"
        "- Tone must feel naturally spoken in Cantonese; add suitable sentence-final particles when appropriate (e.g. 㗎、啫、啦、呢、呀、咩).\n"
        "- Absolutely avoid written Mandarin, literal translation, or stiff book-style phrasing when a Cantonese alternative exists.\n\n"
    )


def normalize_cantonese_translation_text(text: str, target_lang: str) -> str:
    """把粤语译文规整成更口语化的表面形式。"""

    variant = _normalize_cantonese_target_variant(target_lang)
    if not variant:
        return str(text or "").strip()

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    # 先保留词序，再把多余空格压平；这里只移除中文之间的冗余空格，
    # 不能把中英边界空格一并吃掉，否则会变成 `。Ideas` / `.你可能` 这种粘连。
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", normalized)
    normalized = re.sub(r"\s*([，。！？、；：])\s*", r"\1", normalized)
    normalized = re.sub(r"\s*([,!?])\s*", r"\1 ", normalized)
    normalized = re.sub(r"\s*([.])\s*", r". ", normalized)
    normalized = re.sub(r"([\u4e00-\u9fff])\s+([A-Za-z])", r"\1 \2", normalized)
    normalized = re.sub(r"([A-Za-z])\s+([\u4e00-\u9fff])", r"\1 \2", normalized)
    normalized = re.sub(r"([。！？])([A-Za-z])", r"\1 \2", normalized)

    phrase_rules = [
        ("结婚了", "结咗婚"),
        ("遇到了", "遇到咗"),
        ("崩溃了", "崩溃咗"),
        ("没有了", "冇咗"),
        ("变成了", "变成咗"),
        ("咁位", "地位"),
        ("天翻咁覆", "天翻地覆"),
        ("心经呢也", "心经呢樣嘢"),
        ("入面面", "入面"),
        ("胸腔里", "胸腔入面"),
        ("听懂", "听明"),
        ("半辈子", "大半世"),
        ("豪车", "靓车"),
        ("话语权", "话事权"),
        ("胆寒", "心寒"),
        ("嚟同你推荐", "嚟同你介绍"),
        ("做出极之", "做啲极之"),
        ("独立嘅课题", "独立嘅个体"),
        ("好似大海一样", "好似大海咁"),
        ("平和与智慧", "平和同智慧"),
        ("仲喺向外攀附", "仲向外攀附"),
        ("也俾咗自己自由", "亦俾咗自己自由"),
        ("这种", "呢種"),
        ("把孩子送进", "将细路送入"),
        ("把公司掏空", "将公司掏空"),
        ("把自己嘅价值绑定", "将自己嘅价值绑定"),
        ("被年轻嘅领导边缘化", "俾后生领导边缘化"),
        ("被人骂", "俾人闹"),
        ("被逼得", "俾逼到"),
        ("这么认为", "咁认为"),
        ("这样的下场", "咁嘅下场"),
        ("这样的", "咁嘅"),
        ("这样嘅下场", "咁嘅下场"),
        ("这样", "咁样"),
        ("这里", "呢度"),
        ("大脑里", "大脑入面"),
        ("银行卡里", "银行卡入面"),
        ("红尘里", "红尘入面"),
        ("郑重地", "郑重咁"),
        ("狠狠地", "狠狠咁"),
        ("迅速地", "迅速咁"),
        ("并冇给你带来", "并冇俾你带来"),
        ("给你带来", "俾你带来"),
        ("给你推荐", "俾你推荐"),
        ("带来了", "带来咗"),
        ("让我哋", "等我哋"),
        ("让我们", "等我哋"),
        ("让我", "等我"),
        ("就像", "就好似"),
        ("像个", "好似个"),
        ("像一位", "好似一位"),
        ("带着", "带住"),
        ("不好以为", "唔好以为"),
        ("可系", "但系"),
        ("一句断语", "一句短句"),
        ("世人", "啲人"),
        ("听友", "听众"),
        ("老太太们", "阿婆"),
        ("毒打", "折磨"),
        ("死磕", "死顶"),
        ("借由", "藉住"),
        ("安慰剂", "定心丸"),
        ("四围", "四周围"),
        ("断语", "短句"),
        ("阅历", "经历"),
        ("冇有", "冇"),
        ("没有", "冇"),
        ("唔 系", "唔係"),
        ("可 系", "但系"),
        ("呢唔单止", "呢句嘢唔单止"),
    ]
    for source, target in phrase_rules:
        normalized = normalized.replace(source, target)

    # 按整体目标语种收尾：两档都统一繁体落盘，但仍保留不同口语风格约束。
    if variant == "cantonese-mainland":
        variant_rules = [
            ("呢个", "呢個"),
            ("嗰个", "嗰個"),
            ("咁样", "咁樣"),
            ("呢样", "呢樣"),
            ("呢种", "呢種"),
            ("食饭", "食飯"),
            ("唔系", "唔係"),
            ("唔好", "唔好"),
            ("係", "系"),
            ("佢哋", "佢哋"),
            ("咗咗", "咗"),
        ]
    else:
        variant_rules = [
            ("呢个", "呢個"),
            ("嗰个", "嗰個"),
            ("咁样", "咁樣"),
            ("呢样", "呢樣"),
            ("呢种", "呢種"),
            ("食饭", "食飯"),
            ("唔系", "唔係"),
            ("系", "系"),
            ("佢哋", "佢哋"),
            ("咗咗", "咗"),
        ]
    for source, target in variant_rules:
        normalized = normalized.replace(source, target)

    normalized = re.sub(r"(?<=[\u4e00-\u9fff])里(?=[\u4e00-\u9fff])", "入面", normalized)
    normalized = re.sub(r"咁樣的", "咁嘅", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])了(?=[\u4e00-\u9fff，。！？、；：,.!?]|$)", "咗", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])地(?=[\u4e00-\u9fff])", "咁", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])把(?=[\u4e00-\u9fff])", "将", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])被(?=[\u4e00-\u9fff])", "俾", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])给(?=[\u4e00-\u9fff])", "俾", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])让(?=[\u4e00-\u9fff])", "令", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])像(?=[\u4e00-\u9fff])", "好似", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])着(?=[\u4e00-\u9fff])", "住", normalized)

    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"([\u4e00-\u9fff])\s+([\u4e00-\u9fff])", r"\1\2", normalized)
    normalized = re.sub(r"\s*([，。！？、；：])\s*", r"\1", normalized)
    normalized = re.sub(r"\s*([,!?])\s*", r"\1 ", normalized)
    normalized = re.sub(r"\s*([.])\s*", r". ", normalized)
    normalized = re.sub(r"([\u4e00-\u9fff])\s+([A-Za-z])", r"\1 \2", normalized)
    normalized = re.sub(r"([A-Za-z])\s+([\u4e00-\u9fff])", r"\1 \2", normalized)
    normalized = re.sub(r"([。！？])([A-Za-z])", r"\1 \2", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


DEFAULT_TRANSLATION_SYSTEM_PROMPT = (
    "你是专业的字幕翻译助手。\n"
    "硬性规则：\n"
    "1. 把阿拉伯数字翻译成自然的中文数字表达，例如 50 翻译成五十。\n"
    "2. 译文里不要出现冒号。\n"
    "3. 对于大写字母缩写，前后保留空格，例如 AI 的发展。\n"
    "4. 保持原意、语气自然、逐行对应，不要添加解释。\n"
)


def resolve_translation_api_key(api_key: str | None = None, api_key_env: str | None = None) -> str:
    """统一解析翻译 API key，优先显式传入，再回退新旧环境变量。"""

    explicit_key = str(api_key or "").strip()
    if explicit_key:
        return explicit_key

    env_names: list[str] = []
    preferred_env = str(api_key_env or "").strip()
    if preferred_env:
        env_names.append(preferred_env)
    for env_name in (TRANSLATE_API_KEY_ENV, LEGACY_TRANSLATE_API_KEY_ENV):
        if env_name not in env_names:
            env_names.append(env_name)

    for env_name in env_names:
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            return value
    return ""


def get_translate_provider_label(base_url: str | None) -> str:
    """根据 base_url 生成展示用 provider 标签。

    对外展示统一使用通用 provider 语义，避免把默认供应商实现细节暴露到产品文案里。
    """

    return "OpenAI-compatible"


def get_translate_provider_host(base_url: str | None) -> str:
    """提取 provider host，便于日志或调试时展示。"""

    raw = str(base_url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    return str(parsed.netloc or "").strip()


def build_translation_system_prompt(user_prompt: str | None = None) -> str:
    """统一构造翻译 system prompt，默认规则始终在前，用户补充要求追加在后。"""

    custom_prompt = str(user_prompt or "").strip()
    if not custom_prompt:
        return DEFAULT_TRANSLATION_SYSTEM_PROMPT
    return (
        f"{DEFAULT_TRANSLATION_SYSTEM_PROMPT}\n"
        "用户附加要求：\n"
        f"{custom_prompt}"
    )


def _normalize_prompt_text(text: str | None) -> str:
    """把单条字幕里的内部换行折叠掉，避免翻译 prompt 把一个 cue 拆成多行。"""

    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return ""
    cleaned = cleaned.replace("\n", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


class Translator:
    def __init__(
        self,
        api_key=None,
        base_url=DEFAULT_TRANSLATE_BASE_URL,
        model=DEFAULT_TRANSLATE_MODEL,
        api_key_env: str | None = None,
    ):
        self.base_url = base_url
        self.model = model

        final_api_key = resolve_translation_api_key(api_key=api_key, api_key_env=api_key_env)
        if not final_api_key:
            raise ValueError(
                "Translation API key is required. Pass it via --api_key or set "
                f"{TRANSLATE_API_KEY_ENV} / {LEGACY_TRANSLATE_API_KEY_ENV}."
            )

        self.api_key = final_api_key
        self.client = None

    def _ensure_client(self):
        """按需创建 OpenAI 客户端，避免测试只打补丁时提前触发依赖初始化。"""

        if self.client is not None:
            return self.client
        if OpenAI is None or not callable(OpenAI):
            raise RuntimeError("OpenAI client is unavailable. Install openai or provide a test double.")
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        return self.client

    def _build_prompt(self, subtitles, target_lang):
        # 单条字幕可能包含 cue 内部换行，先折叠成单行，避免模型把它误读成新条目。
        input_text = "\n".join(
            [f"{i+1}. {_normalize_prompt_text(text)}" for i, text in enumerate(subtitles)]
        )
        prompt = f"""Translate the following lines into {target_lang}.
Maintain the tone and meaning. Output format must correspond line by line.
Return ONLY the translated lines, numbered as in the input.

Input:
{input_text}
"""
        if _is_cantonese_target_lang(target_lang):
            prompt = (
                f"Translate the following lines into {target_lang}.\n"
                + _cantonese_prompt_constraints(target_lang)
                + "Maintain the tone and meaning. Output format must correspond line by line.\n"
                + "Return ONLY the translated lines, numbered as in the input.\n\n"
                + f"Input:\n{input_text}\n"
            )
        return prompt

    def _is_translation_noise_line(self, line: str) -> bool:
        """判定是否为翻译回复中的说明/噪声行，避免污染编号条目。"""

        stripped = str(line or "").strip()
        if not stripped:
            return True
        lowered = stripped.lower()
        english_prefixes = (
            "note:",
            "notes:",
            "explanation:",
            "output:",
            "translation:",
            "translated:",
        )
        chinese_prefixes = (
            "注：",
            "注:",
            "说明：",
            "说明:",
            "译文：",
            "翻译：",
            "以下是翻译",
            "以下为翻译",
        )
        if lowered.startswith(english_prefixes):
            return True
        if stripped.startswith(chinese_prefixes):
            return True
        if re.match(r"^[\(\[（【].*(注|说明|解释).*[)）\]】]$", stripped):
            return True
        return False

    def _parse_numbered_translation_blocks(self, content: str) -> dict[int, str]:
        """按“编号块”解析翻译回复；同一编号下的多行会聚合成一条译文。"""

        numbered_pattern = re.compile(r"^\s*(\d+)\s*[.)、:：\-）]?\s*(.*)$")
        blocks: dict[int, str] = {}
        current_index: int | None = None
        current_lines: list[str] = []

        def _flush_current_block() -> None:
            nonlocal current_index, current_lines
            if current_index is None:
                return
            merged = re.sub(r"\s+", " ", " ".join(current_lines)).strip()
            if not merged:
                current_index = None
                current_lines = []
                return
            if current_index in blocks:
                blocks[current_index] = f"{blocks[current_index]} {merged}".strip()
            else:
                blocks[current_index] = merged
            current_index = None
            current_lines = []

        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            matched = numbered_pattern.match(line)
            if matched:
                _flush_current_block()
                current_index = int(matched.group(1))
                first_text = matched.group(2).strip()
                current_lines = [first_text] if first_text else []
                continue
            if current_index is None:
                continue
            if self._is_translation_noise_line(line):
                continue
            current_lines.append(line)

        _flush_current_block()
        return blocks

    def _parse_translated_lines_legacy(self, content: str, expected_len: int):
        """兼容旧逐行解析策略；仅在识别不到编号块时回退。"""

        translated_lines = []
        for line in content.split('\n'):
            if "." in line:
                parts = line.split(".", 1)
                if parts[0].strip().isdigit():
                    translated_lines.append(parts[1].strip())
                    continue
            if line.strip():
                translated_lines.append(line.strip())

        if len(translated_lines) != expected_len:
            logger.warning("Translation count mismatch: %s vs %s", expected_len, len(translated_lines))
            if len(translated_lines) < expected_len:
                translated_lines.extend([""] * (expected_len - len(translated_lines)))
            else:
                translated_lines = translated_lines[:expected_len]
        return translated_lines

    def _parse_translated_lines(self, content: str, expected_len: int):
        """优先按编号块解析译文，并保留空槽位供上游识别漏行。"""

        numbered_blocks = self._parse_numbered_translation_blocks(content)
        if not numbered_blocks:
            return self._parse_translated_lines_legacy(content, expected_len)

        translated_lines = [""] * expected_len
        matched_in_range = 0
        for idx, text in numbered_blocks.items():
            if 1 <= idx <= expected_len:
                translated_lines[idx - 1] = text
                matched_in_range += 1

        if matched_in_range == 0:
            logger.warning(
                "Numbered translation blocks found but all out of range: expected=%s parsed_keys=%s",
                expected_len,
                sorted(numbered_blocks.keys()),
            )
            return self._parse_translated_lines_legacy(content, expected_len)

        parsed_count = sum(1 for line in translated_lines if line)
        if parsed_count != expected_len:
            logger.warning(
                "Translation count mismatch after numbered-block parse: expected=%s parsed=%s",
                expected_len,
                parsed_count,
            )
        return translated_lines

    def _build_translation_system_prompt(
        self,
        *,
        system_prompt: str | None,
        system_prompt_is_final: bool,
    ) -> str:
        """统一构造翻译请求的 system prompt，避免重试时重复拼接不一致。"""

        if system_prompt_is_final and str(system_prompt or "").strip():
            return str(system_prompt).strip()
        return build_translation_system_prompt(system_prompt)

    def _translate_with_user_prompt(
        self,
        *,
        user_prompt: str,
        expected_len: int,
        system_prompt=None,
        system_prompt_is_final: bool = False,
    ) -> tuple[list[str], int]:
        """发送一次翻译请求并按固定期望行数解析结果。"""

        client = self._ensure_client()
        final_system_prompt = self._build_translation_system_prompt(
            system_prompt=system_prompt,
            system_prompt_is_final=system_prompt_is_final,
        )
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": final_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
        )
        content = response.choices[0].message.content.strip()
        parsed = self._parse_translated_lines(content, expected_len)
        parsed_count = sum(1 for line in parsed if str(line or "").strip())
        return parsed, parsed_count

    def _find_missing_translation_indexes(self, parsed_lines: list[str]) -> list[int]:
        """找出译文解析后仍为空的行索引，供局部补译使用。"""

        missing_indexes: list[int] = []
        for index, line in enumerate(parsed_lines):
            if str(line or "").strip():
                continue
            missing_indexes.append(index)
        return missing_indexes

    def _should_retry_missing_only(
        self,
        *,
        expected_len: int,
        missing_indexes: list[int],
    ) -> bool:
        """根据缺失规模判断是否优先走局部补译，而不是整半批重试。"""

        missing_count = len(missing_indexes)
        if missing_count <= 0 or expected_len <= 0:
            return False
        missing_ratio = float(missing_count) / float(expected_len)
        return (
            missing_count <= int(MAX_TRANSLATION_MISSING_RETRY_COUNT)
            or missing_ratio <= float(MAX_TRANSLATION_MISSING_RETRY_RATIO)
        )

    def _build_missing_translation_retry_prompt(
        self,
        *,
        subtitles,
        missing_indexes: list[int],
        target_lang: str,
        context_radius: int = TRANSLATION_MISSING_RETRY_CONTEXT_RADIUS,
    ) -> str:
        """为缺失行构造带前后文的小补译 prompt，只要求返回缺失目标行。"""

        safe_radius = max(0, int(context_radius))
        prompt_lines = [
            f"Translate the missing target lines into {target_lang}.",
            "Use the nearby context only to understand meaning and tone.",
            "Return ONLY the translated target lines, numbered exactly from 1.",
            "Do not output context lines, notes, or explanations.",
            "",
            "Missing targets with nearby context:",
        ]
        total = len(subtitles)
        for local_index, missing_index in enumerate(missing_indexes, start=1):
            prompt_lines.append(f"Target {local_index}:")
            for context_index in range(
                max(0, int(missing_index) - safe_radius),
                min(total, int(missing_index) + safe_radius + 1),
            ):
                role = "TARGET" if context_index == missing_index else "CONTEXT"
                text = subtitles[context_index]
                if not isinstance(text, str):
                    text = str(text.get("text") or "")
                normalized_text = _normalize_prompt_text(str(text or ""))
                prompt_lines.append(
                    f"- {role} original_line_{context_index + 1}: {normalized_text}"
                )
            prompt_lines.append("")
        prompt_lines.append("Output:")
        prompt_lines.append("1. <translation for target 1>")
        return "\n".join(prompt_lines).strip() + "\n"

    def _retry_missing_lines_with_context(
        self,
        *,
        subtitles,
        parsed_lines: list[str],
        missing_indexes: list[int],
        target_lang="Chinese",
        system_prompt=None,
        system_prompt_is_final: bool = False,
    ) -> tuple[list[str], int]:
        """仅重译缺失行，并把补回结果按原索引写回整批译文。"""

        retry_prompt = self._build_missing_translation_retry_prompt(
            subtitles=subtitles,
            missing_indexes=missing_indexes,
            target_lang=target_lang,
        )
        retry_outputs, retry_count = self._translate_with_user_prompt(
            user_prompt=retry_prompt,
            expected_len=len(missing_indexes),
            system_prompt=system_prompt,
            system_prompt_is_final=system_prompt_is_final,
        )
        recovered = list(parsed_lines)
        for missing_index, retry_text in zip(missing_indexes, retry_outputs):
            normalized_retry_text = str(retry_text or "").strip()
            if normalized_retry_text:
                recovered[missing_index] = normalized_retry_text
        recovered_count = sum(1 for line in recovered if str(line or "").strip())
        return recovered, max(retry_count, recovered_count)

    def _translate_one_batch(
        self,
        subtitles,
        *,
        target_lang="Chinese",
        system_prompt=None,
        system_prompt_is_final: bool = False,
    ) -> tuple[list[str], int]:
        """执行单个翻译批次请求，并返回解析结果及命中行数。"""

        current_batch_texts = [sub if isinstance(sub, str) else sub["text"] for sub in subtitles]
        return self._translate_with_user_prompt(
            user_prompt=self._build_prompt(current_batch_texts, target_lang),
            expected_len=len(subtitles),
            system_prompt=system_prompt,
            system_prompt_is_final=system_prompt_is_final,
        )

    def _translate_batch_with_split_retry(
        self,
        subtitles,
        *,
        target_lang="Chinese",
        system_prompt=None,
        system_prompt_is_final: bool = False,
        min_retry_chunk_size: int | None = None,
    ) -> list[str]:
        """单批漏行时先局部补译缺失行，补不齐再递归拆小重试。"""

        parsed, parsed_count = self._translate_one_batch(
            subtitles,
            target_lang=target_lang,
            system_prompt=system_prompt,
            system_prompt_is_final=system_prompt_is_final,
        )
        expected_len = len(subtitles)
        if parsed_count >= expected_len:
            return parsed

        safe_min_retry_chunk_size = max(1, int(min_retry_chunk_size or MIN_TRANSLATION_RETRY_CHUNK_SIZE))
        missing_indexes = self._find_missing_translation_indexes(parsed)
        if self._should_retry_missing_only(expected_len=expected_len, missing_indexes=missing_indexes):
            logger.warning(
                "Translation batch incomplete, retrying missing lines only: expected=%s missing=%s",
                expected_len,
                len(missing_indexes),
            )
            recovered, recovered_count = self._retry_missing_lines_with_context(
                subtitles=subtitles,
                parsed_lines=parsed,
                missing_indexes=missing_indexes,
                target_lang=target_lang,
                system_prompt=system_prompt,
                system_prompt_is_final=system_prompt_is_final,
            )
            if recovered_count >= expected_len:
                logger.warning(
                    "Translation missing-line retry recovered: expected=%s recovered=%s",
                    expected_len,
                    recovered_count,
                )
                return recovered
            logger.warning(
                "Translation missing-line retry still incomplete, falling back to split retry: expected=%s missing=%s",
                expected_len,
                len(self._find_missing_translation_indexes(recovered)),
            )
            parsed = recovered
            parsed_count = recovered_count

        if expected_len <= safe_min_retry_chunk_size:
            logger.warning(
                "Translation batch incomplete at minimum retry size: expected=%s parsed=%s chunk_size=%s",
                expected_len,
                parsed_count,
                expected_len,
            )
            return parsed

        next_chunk_size = max(safe_min_retry_chunk_size, expected_len // 2)
        logger.warning(
            "Translation batch incomplete, retrying with smaller chunks: expected=%s parsed=%s next_chunk_size=%s",
            expected_len,
            parsed_count,
            next_chunk_size,
        )
        split_index = max(1, min(expected_len - 1, expected_len // 2))
        left = self._translate_batch_with_split_retry(
            subtitles[:split_index],
            target_lang=target_lang,
            system_prompt=system_prompt,
            system_prompt_is_final=system_prompt_is_final,
            min_retry_chunk_size=safe_min_retry_chunk_size,
        )
        right = self._translate_batch_with_split_retry(
            subtitles[split_index:],
            target_lang=target_lang,
            system_prompt=system_prompt,
            system_prompt_is_final=system_prompt_is_final,
            min_retry_chunk_size=safe_min_retry_chunk_size,
        )
        recovered = left + right
        recovered_count = sum(1 for line in recovered if str(line or "").strip())
        if recovered_count >= expected_len:
            logger.warning(
                "Translation batch recovered after split retry: expected=%s recovered=%s",
                expected_len,
                recovered_count,
            )
        return recovered

    def translate_batch(
        self,
        subtitles,
        target_lang="Chinese",
        system_prompt=None,
        chunk_size=DEFAULT_TRANSLATION_BATCH_SIZE,
        *,
        system_prompt_is_final: bool = False,
        sanitize_outputs: bool = True,
    ):
        """按批量翻译字幕；可按调用方语义决定是否启用共享激进清洗。"""

        if not subtitles:
            return []

        all_translated = []
        total = len(subtitles)
        
        for i in range(0, total, chunk_size):
            batch = subtitles[i:i+chunk_size]
            logger.info(f"Translating batch {i//chunk_size + 1}/{(total + chunk_size - 1)//chunk_size} ({len(batch)} lines)...")

            try:
                parsed = self._translate_batch_with_split_retry(
                    batch,
                    target_lang=target_lang,
                    system_prompt=system_prompt,
                    system_prompt_is_final=system_prompt_is_final,
                )
                # 共享清洗器适合处理明显脏输出；像 6 号面板这类需要保留整段正文的场景，
                # 会在上层改走更保守的专用清洗，因此这里允许按调用方显式关闭。
                if sanitize_outputs:
                    parsed = [sanitize_translation_text(text, target_lang) for text in parsed]
                if _is_cantonese_target_lang(target_lang):
                    parsed = [normalize_cantonese_translation_text(text, target_lang) for text in parsed]
                all_translated.extend(parsed)

            except Exception as e:
                logger.error(f"Batch translation failed: {e}")
                raise TranslationProviderError(
                    f"Translation provider request failed for batch {i//chunk_size + 1}: {e}"
                ) from e

        return all_translated

    def test_connection(self) -> dict[str, str]:
        """发送最小化请求，验证当前 OpenAI-compatible 配置是否可连通。"""

        client = self._ensure_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a connectivity test for an OpenAI-compatible translation API. Reply with OK.",
                },
                {"role": "user", "content": "ping"},
            ],
            temperature=0.0,
            max_tokens=1,
            stream=False,
        )
        content = ""
        try:
            content = response.choices[0].message.content or ""
        except Exception:
            content = ""
        return {"reply": content.strip()[:64]}
