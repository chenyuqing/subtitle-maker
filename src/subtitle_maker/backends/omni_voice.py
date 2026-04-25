from __future__ import annotations

from .base import TtsBackend, TtsSynthesisRequest


class OmniVoiceBackend(TtsBackend):
    """Phase 7 首轮仅保留 OmniVoice backend 占位接口。"""

    def synthesize(self, request: TtsSynthesisRequest) -> None:
        """当前阶段不把 OmniVoice 接入主运行时。"""

        raise NotImplementedError("OmniVoice backend is not wired in Phase 7 first pass")
