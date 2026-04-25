from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from subtitle_maker.domains.media import concat_generated_wavs

from .base import TtsBackend, TtsSynthesisRequest


def _http_json_request(
    *,
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]],
    timeout_sec: float,
) -> Dict[str, Any]:
    """执行 Index-TTS HTTP 请求，并统一错误语义。"""

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
        raise RuntimeError(f"E-TTS-001 index-tts api http {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"E-TTS-001 index-tts api connect failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"E-TTS-001 index-tts api request failed: {exc}") from exc

    try:
        return json.loads(body)
    except Exception as exc:
        raise RuntimeError(f"E-TTS-001 index-tts api invalid json: {body[:200]}") from exc


def check_index_tts_service(*, api_url: str, timeout_sec: float) -> Dict[str, Any]:
    """检查 Index-TTS API 健康状态。"""

    url = api_url.rstrip("/") + "/health"
    payload = _http_json_request(method="GET", url=url, payload=None, timeout_sec=timeout_sec)
    if not payload.get("ok"):
        raise RuntimeError(f"E-TTS-001 index-tts service unhealthy: {payload}")
    return payload


def release_index_tts_api_model(*, api_url: str, timeout_sec: float) -> Dict[str, Any]:
    """请求 Index-TTS API 主动释放模型显存。"""

    url = api_url.rstrip("/") + "/model/release"
    payload = _http_json_request(
        method="POST",
        url=url,
        payload={},
        timeout_sec=timeout_sec,
    )
    if not payload.get("ok"):
        raise RuntimeError(f"E-TTS-001 index-tts api release failed: {payload}")
    return payload


def synthesize_via_index_tts_api(
    *,
    api_url: str,
    timeout_sec: float,
    text: str,
    ref_audio_path: Path,
    output_path: Path,
    emo_audio_prompt: Optional[Path],
    emo_alpha: float,
    use_emo_text: bool,
    emo_text: Optional[str],
    top_p: float,
    top_k: int,
    temperature: float,
    max_text_tokens: int,
) -> None:
    """通过 Index-TTS HTTP API 执行一次合成。"""

    payload = {
        "text": text,
        "spk_audio_prompt": str(ref_audio_path.expanduser().resolve()),
        "output_path": str(output_path.expanduser().resolve()),
        "emo_audio_prompt": str(emo_audio_prompt.expanduser().resolve()) if emo_audio_prompt else None,
        "emo_alpha": emo_alpha,
        "use_emo_text": use_emo_text,
        "emo_text": emo_text,
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
        raise RuntimeError(f"E-TTS-001 index-tts api returned non-ok: {result}")
    if not output_path.exists():
        raise RuntimeError("E-TTS-001 index-tts api finished but output missing")


def split_text_for_index_tts(text: str, *, max_text_tokens: int) -> List[str]:
    """按中英文差异把长文本切成 Index-TTS 更稳的分片。"""

    content = (text or "").strip()
    if not content:
        return [content]

    has_cjk = bool(re.search(r"[\u3400-\u9fff]", content))
    if has_cjk:
        budget_chars = max(12, int(max_text_tokens * 0.45))
        units = re.findall(r"[^。！？!?；;，,、\n]+[。！？!?；;，,、]?", content)
    else:
        budget_chars = max(24, int(max_text_tokens * 0.90))
        units = re.findall(r"[^.!?;,:，。！？；：\n]+[.!?;,:，。！？；：]?", content)

    if not units:
        units = [content]

    chunks: List[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}{unit}".strip()
        if not current:
            current = unit.strip()
            continue
        if len(candidate) <= budget_chars:
            current = candidate
        else:
            chunks.append(current.strip())
            current = unit.strip()
    if current:
        chunks.append(current.strip())

    final_chunks: List[str] = []
    for chunk in chunks:
        if len(chunk) <= budget_chars:
            final_chunks.append(chunk)
            continue
        start = 0
        while start < len(chunk):
            end = min(len(chunk), start + budget_chars)
            part = chunk[start:end].strip()
            if part:
                final_chunks.append(part)
            start = end
    return final_chunks or [content]


class IndexTtsBackend(TtsBackend):
    """收口 Index-TTS 的 API / 本地模型双形态分发。"""

    def __init__(
        self,
        *,
        via_api: bool,
        api_url: str,
        timeout_sec: float,
        local_model: Optional[Any],
    ) -> None:
        self.via_api = bool(via_api)
        self.api_url = str(api_url)
        self.timeout_sec = float(timeout_sec)
        self.local_model = local_model

    def _synthesize_local(self, request: TtsSynthesisRequest) -> None:
        """通过本地 Index-TTS 模型执行一次合成。"""

        if self.local_model is None:
            raise RuntimeError("E-TTS-001 index-tts backend not initialized")
        self.local_model.infer(
            spk_audio_prompt=str(request.ref_audio_path),
            text=request.text,
            output_path=str(request.output_path),
            emo_audio_prompt=str(request.emo_audio_prompt) if request.emo_audio_prompt else None,
            emo_alpha=request.emo_alpha,
            use_emo_text=request.use_emo_text,
            emo_text=request.emo_text,
            verbose=False,
            max_text_tokens_per_segment=request.max_text_tokens,
            top_p=request.top_p,
            top_k=request.top_k,
            temperature=request.temperature,
        )
        if not request.output_path.exists():
            raise RuntimeError("E-TTS-001 index-tts produced no output audio")

    def _synthesize_api(self, request: TtsSynthesisRequest) -> None:
        """通过 HTTP API 执行一次合成，并保留一次释放后重试。"""

        try:
            synthesize_via_index_tts_api(
                api_url=self.api_url,
                timeout_sec=self.timeout_sec,
                text=request.text,
                ref_audio_path=request.ref_audio_path,
                output_path=request.output_path,
                emo_audio_prompt=request.emo_audio_prompt,
                emo_alpha=request.emo_alpha,
                use_emo_text=request.use_emo_text,
                emo_text=request.emo_text,
                top_p=request.top_p,
                top_k=request.top_k,
                temperature=request.temperature,
                max_text_tokens=request.max_text_tokens,
            )
            return
        except Exception as first_exc:
            try:
                release_index_tts_api_model(api_url=self.api_url, timeout_sec=self.timeout_sec)
            except Exception:
                pass
            try:
                synthesize_via_index_tts_api(
                    api_url=self.api_url,
                    timeout_sec=self.timeout_sec,
                    text=request.text,
                    ref_audio_path=request.ref_audio_path,
                    output_path=request.output_path,
                    emo_audio_prompt=request.emo_audio_prompt,
                    emo_alpha=request.emo_alpha,
                    use_emo_text=request.use_emo_text,
                    emo_text=request.emo_text,
                    top_p=request.top_p,
                    top_k=request.top_k,
                    temperature=request.temperature,
                    max_text_tokens=request.max_text_tokens,
                )
                return
            except Exception as second_exc:
                raise RuntimeError(
                    f"E-TTS-001 index-tts api failed after one retry: first={first_exc}; second={second_exc}"
                ) from second_exc

    def _synthesize_one(self, request: TtsSynthesisRequest) -> None:
        """执行单个文本分片的合成。"""

        if self.via_api:
            self._synthesize_api(request)
            return
        self._synthesize_local(request)

    def synthesize(self, request: TtsSynthesisRequest) -> None:
        """按分片规则执行整句 Index-TTS 合成。"""

        chunks = split_text_for_index_tts(request.text, max_text_tokens=request.max_text_tokens)
        part_paths: List[Path] = []
        for index, chunk in enumerate(chunks):
            chunk_output = request.output_path.with_name(f"{request.output_path.stem}_part{index:03d}.wav")
            self._synthesize_one(
                TtsSynthesisRequest(
                    text=chunk,
                    ref_audio_path=request.ref_audio_path,
                    output_path=chunk_output,
                    emo_audio_prompt=request.emo_audio_prompt,
                    emo_alpha=request.emo_alpha,
                    use_emo_text=request.use_emo_text,
                    emo_text=request.emo_text,
                    top_p=request.top_p,
                    top_k=request.top_k,
                    temperature=request.temperature,
                    max_text_tokens=request.max_text_tokens,
                )
            )
            part_paths.append(chunk_output)

        try:
            concat_generated_wavs(part_paths, request.output_path)
        finally:
            for part_path in part_paths:
                try:
                    if part_path.exists():
                        part_path.unlink()
                except Exception:
                    pass
