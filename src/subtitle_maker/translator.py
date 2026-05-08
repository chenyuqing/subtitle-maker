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


def _is_cantonese_target_lang(target_lang: str) -> bool:
    lowered = (target_lang or "").strip().lower()
    markers = ["cantonese", "粤语", "廣東話", "广东话", "yue"]
    return any(marker in lowered for marker in markers)


def _cantonese_prompt_constraints() -> str:
    return (
        "Cantonese constraints:\n"
        "- Use natural spoken Cantonese (Hong Kong style), not written Mandarin.\n"
        "- Prefer Traditional Chinese characters for output.\n"
        "- Keep colloquial Cantonese function words natural (e.g. 佢/我哋/你哋/喺/咗/嘅/唔/咩/呀/喇/啦).\n"
        "- Avoid stiff Mandarin book-style wording when a Cantonese alternative exists.\n\n"
    )


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
                + _cantonese_prompt_constraints()
                + "Maintain the tone and meaning. Output format must correspond line by line.\n"
                + "Return ONLY the translated lines, numbered as in the input.\n\n"
                + f"Input:\n{input_text}\n"
            )
        return prompt

    def _parse_translated_lines(self, content: str, expected_len: int):
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

    def translate_batch(
        self,
        subtitles,
        target_lang="Chinese",
        system_prompt=None,
        chunk_size=100,
        *,
        system_prompt_is_final: bool = False,
    ):
        if not subtitles:
            return []

        all_translated = []
        total = len(subtitles)
        
        for i in range(0, total, chunk_size):
            batch = subtitles[i:i+chunk_size]
            current_batch_texts = [sub if isinstance(sub, str) else sub['text'] for sub in batch] # Handle minimal strings or dicts
            
            logger.info(f"Translating batch {i//chunk_size + 1}/{(total + chunk_size - 1)//chunk_size} ({len(batch)} lines)...")
            
            try:
                client = self._ensure_client()
                final_system_prompt = (
                    str(system_prompt).strip()
                    if system_prompt_is_final and str(system_prompt or "").strip()
                    else build_translation_system_prompt(system_prompt)
                )
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": final_system_prompt},
                        {"role": "user", "content": self._build_prompt(current_batch_texts, target_lang)}
                    ],
                    stream=False
                )
                content = response.choices[0].message.content.strip()
                parsed = self._parse_translated_lines(content, len(batch))
                all_translated.extend(parsed)
                
            except Exception as e:
                logger.error(f"Batch translation failed: {e}")
                # Fallback for this batch
                all_translated.extend([f"[Error] {t}" for t in current_batch_texts])
                
        return all_translated
