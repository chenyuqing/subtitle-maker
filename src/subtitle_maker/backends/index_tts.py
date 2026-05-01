from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from subtitle_maker.domains.media import concat_generated_wavs

from .base import TtsBackend, TtsSynthesisRequest


DEFAULT_INDEX_TTS_RECOVERY_WAIT_SEC = 180.0
DEFAULT_INDEX_TTS_RECOVERY_POLL_SEC = 1.0


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
) -> Dict[str, Any]:
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
    return result


def _is_index_tts_transient_error(exc: Exception) -> bool:
    """判断是否为可恢复的短暂故障（重启窗口/连接抖动）。"""

    detail = str(exc or "").lower()
    transient_markers = (
        "http 503",
        "connect failed",
        "connection refused",
        "connection reset",
        "remote end closed connection",
        "timed out",
        "service unavailable",
    )
    return any(marker in detail for marker in transient_markers)


def _wait_index_tts_service_ready(
    *,
    api_url: str,
    timeout_sec: float,
    wait_sec: float = DEFAULT_INDEX_TTS_RECOVERY_WAIT_SEC,
    poll_sec: float = DEFAULT_INDEX_TTS_RECOVERY_POLL_SEC,
) -> Dict[str, Any]:
    """轮询等待 Index-TTS 服务恢复健康，避免重启窗口内连续 missing。"""

    deadline = time.time() + max(5.0, float(wait_sec))
    last_exc: Optional[Exception] = None
    while time.time() < deadline:
        try:
            return check_index_tts_service(api_url=api_url, timeout_sec=timeout_sec)
        except Exception as exc:
            last_exc = exc
            time.sleep(max(0.2, float(poll_sec)))
    if last_exc is None:
        raise RuntimeError("E-TTS-001 index-tts service recovery timeout")
    raise RuntimeError(f"E-TTS-001 index-tts service recovery timeout: {last_exc}") from last_exc


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

        # 允许最多三次尝试：覆盖“重启窗口 + 首次冷启动 + 一次真实重试”。
        errors: List[str] = []
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                result = synthesize_via_index_tts_api(
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
                # 到达自动重启阈值时，服务会在本次响应后退出重启；
                # 这里主动等待恢复，避免下一句直接打到 503。
                if bool(result.get("restart_pending")):
                    _wait_index_tts_service_ready(
                        api_url=self.api_url,
                        timeout_sec=self.timeout_sec,
                    )
                return
            except Exception as exc:
                errors.append(f"attempt{attempt}={exc}")
                # 短暂故障先等服务健康恢复（常见于 auto-restart 窗口）。
                if _is_index_tts_transient_error(exc):
                    try:
                        _wait_index_tts_service_ready(
                            api_url=self.api_url,
                            timeout_sec=self.timeout_sec,
                        )
                    except Exception as wait_exc:
                        errors.append(f"attempt{attempt}_wait={wait_exc}")
                # 无论是否短暂故障，都尝试释放一次模型，降低后续爆显存概率。
                try:
                    release_index_tts_api_model(api_url=self.api_url, timeout_sec=self.timeout_sec)
                except Exception as release_exc:
                    errors.append(f"attempt{attempt}_release={release_exc}")
                if attempt >= max_attempts:
                    joined = "; ".join(errors)
                    raise RuntimeError(
                        "E-TTS-001 index-tts api failed after retries: "
                        f"{joined}"
                    ) from exc

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
