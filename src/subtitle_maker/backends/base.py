from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class TtsSynthesisRequest:
    """统一描述一次 TTS 合成所需的输入参数。"""

    text: str
    ref_audio_path: Path
    output_path: Path
    # 备胎链路可选传入参考文本，避免模型内部转录导致语义漂移。
    ref_text: Optional[str] = None
    # 备胎链路可选传入目标语种提示，提升跨语种稳定性。
    language: Optional[str] = None
    emo_audio_prompt: Optional[Path] = None
    emo_alpha: float = 1.0
    use_emo_text: bool = False
    emo_text: Optional[str] = None
    top_p: float = 0.8
    top_k: int = 30
    temperature: float = 0.8
    max_text_tokens: int = 120
    # 目标时长（秒）：供支持时长控制的后端（如 OmniVoice）直接按时长生成。
    target_duration_sec: Optional[float] = None
    # OmniVoice 专用开关：是否启用模型内部 output 后处理（去静音等）。
    # 仅在 OmniVoice backend 读取；其他 backend 会忽略。
    omnivoice_postprocess_output: Optional[bool] = None
    # OmniVoice 可选随机种子：传入后同参可复现。
    omnivoice_seed: Optional[int] = None
    # 允许后端在必要时跳过部分前置硬校验（例如组合后端短句兜底场景）。
    allow_relaxed_validation: bool = False


class TtsBackend(ABC):
    """约束各 TTS backend 的最小运行时接口。"""

    @abstractmethod
    def synthesize(self, request: TtsSynthesisRequest) -> None:
        """执行一次文本到音频的合成，并把结果写入目标路径。"""
