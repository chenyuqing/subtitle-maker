from __future__ import annotations

import os
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from .base import TtsBackend, TtsSynthesisRequest


DEFAULT_OMNIVOICE_API_URL = "http://127.0.0.1:8020"
DEFAULT_OMNIVOICE_QUALITY_MIN_RATIO = 0.72
DEFAULT_OMNIVOICE_QUALITY_MIN_TARGET_SEC = 1.2
REPO_ROOT = Path(__file__).resolve().parents[3]
OMNIVOICE_START_SCRIPT = REPO_ROOT / "start_omnivoice_api.sh"
OMNIVOICE_STOP_SCRIPT = REPO_ROOT / "stop_omnivoice_api.sh"
DEFAULT_OMNIVOICE_CONSERVATIVE_API_OVERRIDES: Dict[str, Any] = {
    "speed": 0.9,
    "num_step": 48,
    "guidance_scale": 2.5,
    "denoise": True,
    "postprocess_output": True,
}


class OmniVoiceQualityGateError(RuntimeError):
    """OmniVoice 生成完成但明显偏离目标时长时的专用错误。"""


def _normalize_omnivoice_language(language_hint: Optional[str]) -> Optional[str]:
    """把常见目标语种名称映射为 OmniVoice 识别更稳定的语言代码。"""

    raw = (language_hint or "").strip()
    if not raw:
        return None
    lowered = raw.lower()
    alias_map = {
        "chinese": "zh",
        "中文": "zh",
        "mandarin": "zh",
        "cantonese": "yue",
        "粤语": "yue",
        "english": "en",
        "日语": "ja",
        "japanese": "ja",
        "韩语": "ko",
        "korean": "ko",
        "french": "fr",
        "german": "de",
        "italian": "it",
        "spanish": "es",
        "portuguese": "pt",
        "russian": "ru",
    }
    for marker, code in alias_map.items():
        if marker in lowered:
            return code
    # 若无法命中常见别名，保留原值交给 OmniVoice 自行解析。
    return raw


def _compact_process_error(output: str, *, keep_lines: int = 14) -> str:
    """压缩子进程错误输出，避免把整段冗长日志直接抛到上游。"""

    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if not lines:
        return "no process output"
    return " | ".join(lines[-keep_lines:])


def _normalize_api_base_url(api_url: str) -> str:
    """标准化 OmniVoice API 地址，避免末尾斜杠影响本地判断。"""

    normalized = str(api_url or "").strip().rstrip("/")
    return normalized or DEFAULT_OMNIVOICE_API_URL


def _is_local_default_omnivoice_api(api_url: str) -> bool:
    """仅允许对本机默认 OmniVoice 服务执行自动恢复。"""

    return _normalize_api_base_url(api_url) == DEFAULT_OMNIVOICE_API_URL


def _should_attempt_local_omnivoice_recovery(exc: Exception) -> bool:
    """仅对明显的本地服务掉线/断连症状触发重启恢复。"""

    detail = str(exc or "").lower()
    recovery_markers = (
        "connect failed",
        "remote end closed connection without response",
        "connection refused",
        "connection reset",
        "connection aborted",
        "timed out",
        "output missing",
    )
    return any(marker in detail for marker in recovery_markers)


def _run_local_omnivoice_script(
    script_path: Path,
    *,
    timeout_sec: int,
    env: Optional[Dict[str, str]] = None,
) -> str:
    """执行本地 OmniVoice 管理脚本，失败时抛出带摘要的错误。"""

    if not script_path.exists():
        raise RuntimeError(f"script missing: {script_path}")
    try:
        proc = subprocess.run(
            [str(script_path)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{script_path.name} timeout after {timeout_sec}s") from exc
    except Exception as exc:
        raise RuntimeError(f"{script_path.name} spawn failed: {exc}") from exc
    if proc.returncode != 0:
        detail = ((proc.stderr or "").strip() or (proc.stdout or "").strip() or f"exit {proc.returncode}")
        raise RuntimeError(f"{script_path.name} failed: {detail}")
    return (proc.stdout or "").strip() or "ok"


def _recover_local_omnivoice_service(api_url: str, *, timeout_sec: float) -> None:
    """尝试恢复本地 OmniVoice API，优先直接拉起，必要时 stop/start 一次。"""

    if not _is_local_default_omnivoice_api(api_url):
        return

    startup_timeout_raw = str(os.environ.get("OMNIVOICE_AUTO_START_TIMEOUT_SEC", "420") or "420").strip()
    try:
        startup_timeout_sec = int(startup_timeout_raw)
    except ValueError:
        startup_timeout_sec = 420
    startup_timeout_sec = max(60, min(1800, startup_timeout_sec))
    env = os.environ.copy()
    env.setdefault("OMNIVOICE_START_WAIT_SEC", str(max(60, startup_timeout_sec - 30)))

    try:
        _run_local_omnivoice_script(
            OMNIVOICE_START_SCRIPT,
            timeout_sec=startup_timeout_sec,
            env=env,
        )
        return
    except RuntimeError as first_start_exc:
        stop_detail = ""
        try:
            _run_local_omnivoice_script(
                OMNIVOICE_STOP_SCRIPT,
                timeout_sec=min(30, max(10, int(timeout_sec))),
            )
            stop_detail = "stop/start retry executed"
        except RuntimeError as stop_exc:
            stop_detail = str(stop_exc)

        try:
            _run_local_omnivoice_script(
                OMNIVOICE_START_SCRIPT,
                timeout_sec=startup_timeout_sec,
                env=env,
            )
            return
        except RuntimeError as second_start_exc:
            raise RuntimeError(
                "local omnivoice recovery failed: "
                f"first_start={first_start_exc}; "
                f"stop={stop_detail}; "
                f"second_start={second_start_exc}"
            ) from second_start_exc


def _http_json_request(
    *,
    method: str,
    url: str,
    payload: Optional[Dict[str, Any]],
    timeout_sec: float,
) -> Dict[str, Any]:
    """执行 OmniVoice HTTP 请求并统一错误语义。"""

    data: Optional[bytes] = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url=url,
        data=data,
        headers=headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"E-TTS-001 omnivoice api http {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"E-TTS-001 omnivoice api connect failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"E-TTS-001 omnivoice api request failed: {exc}") from exc

    try:
        return json.loads(body)
    except Exception as exc:
        raise RuntimeError(f"E-TTS-001 omnivoice api invalid json: {body[:200]}") from exc


class OmniVoiceBackend(TtsBackend):
    """OmniVoice backend：优先走本地 API，必要时支持 CLI 直连。"""

    def __init__(
        self,
        *,
        python_bin: str,
        root_dir: str,
        model: str,
        device: str = "auto",
        timeout_sec: float = 300.0,
        via_api: bool = True,
        api_url: str = "",
    ) -> None:
        self.python_bin = str(python_bin or "").strip()
        self.root_dir = Path(str(root_dir or "").strip()).expanduser()
        self.model = str(model or "").strip()
        self.device = str(device or "auto").strip().lower() or "auto"
        self.timeout_sec = max(1.0, float(timeout_sec))
        self.via_api = bool(via_api)
        self.api_url = str(api_url or "").strip() or os.environ.get("OMNIVOICE_API_URL", DEFAULT_OMNIVOICE_API_URL)

    def _build_quality_retry_overrides(self) -> Dict[str, Any]:
        """返回 OmniVoice 质量补救时使用的更保守参数。"""

        return dict(DEFAULT_OMNIVOICE_CONSERVATIVE_API_OVERRIDES)

    def _extract_duration_ratio(self, request: TtsSynthesisRequest, result: Optional[Dict[str, Any]]) -> Optional[float]:
        """从 API 响应提取时长比值；缺失时按 target/actual 兜底计算。"""

        if not isinstance(result, dict):
            return None
        ratio_value = result.get("duration_ratio")
        try:
            if ratio_value is not None:
                return max(0.0, float(ratio_value))
        except (TypeError, ValueError):
            pass
        target_duration = request.target_duration_sec
        actual_value = result.get("actual_duration_sec", result.get("duration_sec"))
        try:
            target_duration_float = float(target_duration) if target_duration is not None else None
            actual_duration_float = float(actual_value) if actual_value is not None else None
        except (TypeError, ValueError):
            return None
        if target_duration_float is None or target_duration_float <= 0.0 or actual_duration_float is None:
            return None
        return max(0.0, actual_duration_float / target_duration_float)

    def _should_retry_for_quality(self, request: TtsSynthesisRequest, result: Optional[Dict[str, Any]]) -> bool:
        """只对明显快于目标时长的结果触发一次保守 profile 重试。"""

        target_duration = request.target_duration_sec
        if target_duration is None:
            return False
        try:
            target_duration_float = float(target_duration)
        except (TypeError, ValueError):
            return False
        if target_duration_float < DEFAULT_OMNIVOICE_QUALITY_MIN_TARGET_SEC:
            return False
        ratio = self._extract_duration_ratio(request, result)
        if ratio is None:
            return False
        return ratio < DEFAULT_OMNIVOICE_QUALITY_MIN_RATIO

    def _format_quality_result_summary(
        self,
        request: TtsSynthesisRequest,
        result: Optional[Dict[str, Any]],
        *,
        profile_name: str,
    ) -> str:
        """把一次 OmniVoice 结果压成短摘要，便于错误里直观看两轮差异。"""

        if not isinstance(result, dict):
            return f"{profile_name}:no-metadata"
        ratio = self._extract_duration_ratio(request, result)
        actual_value = result.get("actual_duration_sec", result.get("duration_sec"))
        return (
            f"{profile_name}:actual={actual_value},"
            f"ratio={None if ratio is None else round(float(ratio), 3)},"
            f"retry_profile={result.get('retry_profile')}"
        )

    def _validate_runtime(self) -> None:
        """校验 OmniVoice 运行参数，尽早给出可读错误。"""

        if not self.python_bin:
            raise RuntimeError("E-TTS-001 omnivoice python bin is required")
        python_path = Path(self.python_bin).expanduser()
        if not python_path.exists():
            raise RuntimeError(f"E-TTS-001 omnivoice python bin not found: {python_path}")
        if not os.access(python_path, os.X_OK):
            raise RuntimeError(f"E-TTS-001 omnivoice python bin is not executable: {python_path}")
        if not self.root_dir.exists():
            raise RuntimeError(f"E-TTS-001 omnivoice root not found: {self.root_dir}")
        if not self.model:
            raise RuntimeError("E-TTS-001 omnivoice model is required")

    def _validate_request(self, request: TtsSynthesisRequest) -> None:
        """校验 OmniVoice 单次请求，避免进入已知高失败率工作区间。"""

        target_duration = request.target_duration_sec
        if target_duration is None:
            return
        try:
            target_duration_float = float(target_duration)
        except (TypeError, ValueError):
            return
        if 0.0 < target_duration_float < DEFAULT_OMNIVOICE_QUALITY_MIN_TARGET_SEC:
            raise RuntimeError(
                "E-TTS-001 omnivoice target duration below safe floor: "
                f"{target_duration_float:.3f}s < {DEFAULT_OMNIVOICE_QUALITY_MIN_TARGET_SEC:.1f}s"
            )

    def _synthesize_via_cli(self, request: TtsSynthesisRequest) -> None:
        """通过 OmniVoice CLI 执行合成。"""

        self._validate_runtime()
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        language = _normalize_omnivoice_language(request.language)
        command = [
            str(Path(self.python_bin).expanduser().resolve()),
            "-m",
            "omnivoice.cli.infer",
            "--model",
            self.model,
            "--text",
            request.text,
            "--output",
            str(request.output_path.expanduser().resolve()),
            "--ref_audio",
            str(request.ref_audio_path.expanduser().resolve()),
        ]
        # 逐句参考文本优先显式透传，避免 OmniVoice 内部自动转录参考音频。
        if (request.ref_text or "").strip():
            command.extend(["--ref_text", str(request.ref_text).strip()])
        if language:
            command.extend(["--language", language])
        if self.device != "auto":
            command.extend(["--device", self.device])
        # 让 OmniVoice 直接按目标时长生成，减少后续硬裁切导致的句尾丢失。
        if request.target_duration_sec is not None:
            command.extend(["--duration", f"{max(0.05, float(request.target_duration_sec)):.6f}"])

        try:
            proc = subprocess.run(
                command,
                cwd=str(self.root_dir.resolve()),
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"E-TTS-001 omnivoice timeout after {self.timeout_sec:.1f}s") from exc
        except Exception as exc:
            raise RuntimeError(f"E-TTS-001 omnivoice spawn failed: {exc}") from exc

        if proc.returncode != 0:
            detail = _compact_process_error((proc.stdout or "") + "\n" + (proc.stderr or ""))
            raise RuntimeError(f"E-TTS-001 omnivoice infer failed ({proc.returncode}): {detail}")
        if (not request.output_path.exists()) or request.output_path.stat().st_size <= 44:
            raise RuntimeError("E-TTS-001 omnivoice output missing or empty")

    def _release_api_model(self) -> None:
        """通知 OmniVoice API 释放模型，不中断主流程。"""

        try:
            _http_json_request(
                method="POST",
                url=self.api_url.rstrip("/") + "/model/release",
                payload={},
                timeout_sec=max(1.0, min(self.timeout_sec, 20.0)),
            )
        except Exception:
            return

    def _synthesize_via_api(
        self,
        request: TtsSynthesisRequest,
        *,
        profile_name: str = "default",
        runtime_overrides: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """通过 OmniVoice API 执行合成。"""

        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        language = _normalize_omnivoice_language(request.language)
        payload = {
            "text": request.text,
            "output_path": str(request.output_path.expanduser().resolve()),
            "ref_audio": str(request.ref_audio_path.expanduser().resolve()),
            "ref_text": (request.ref_text or "").strip() or None,
            "language": language,
            # duration 优先让模型在生成阶段贴近时间线，避免后处理硬截断。
            "duration": (
                max(0.05, float(request.target_duration_sec))
                if request.target_duration_sec is not None
                else None
            ),
            "retry_profile": str(profile_name or "default").strip() or "default",
        }
        if runtime_overrides:
            payload.update(dict(runtime_overrides))
        result = _http_json_request(
            method="POST",
            url=self.api_url.rstrip("/") + "/synthesize",
            payload=payload,
            timeout_sec=self.timeout_sec,
        )
        if not result.get("ok"):
            raise RuntimeError(f"E-TTS-001 omnivoice api returned non-ok: {result}")
        if (not request.output_path.exists()) or request.output_path.stat().st_size <= 44:
            raise RuntimeError("E-TTS-001 omnivoice api finished but output missing")
        return result

    def _synthesize_via_api_with_quality_gate(self, request: TtsSynthesisRequest) -> None:
        """先按默认 profile 合成，明显过快时切保守 profile 再试一次。"""

        first_result = self._synthesize_via_api(request, profile_name="default")
        if not self._should_retry_for_quality(request, first_result):
            return
        retry_result = self._synthesize_via_api(
            request,
            profile_name="conservative",
            runtime_overrides=self._build_quality_retry_overrides(),
        )
        if not self._should_retry_for_quality(request, retry_result):
            return
        raise OmniVoiceQualityGateError(
            "E-TTS-001 omnivoice quality gate failed: "
            f"{self._format_quality_result_summary(request, first_result, profile_name='default')}; "
            f"{self._format_quality_result_summary(request, retry_result, profile_name='conservative')}"
        )

    def synthesize(self, request: TtsSynthesisRequest) -> None:
        """执行 OmniVoice 单句合成，并在失败时统一抛出 E-TTS-001。"""

        self._validate_request(request)
        if not self.via_api:
            self._synthesize_via_cli(request)
            return
        recovery_error: Optional[Exception] = None
        try:
            self._synthesize_via_api_with_quality_gate(request)
            return
        except OmniVoiceQualityGateError:
            self._release_api_model()
            raise
        except Exception as first_exc:
            self._release_api_model()
            if _should_attempt_local_omnivoice_recovery(first_exc):
                try:
                    # 本地服务中途掉线时，先恢复进程，再执行第二次同句重试。
                    _recover_local_omnivoice_service(self.api_url, timeout_sec=self.timeout_sec)
                except Exception as recovery_exc:
                    recovery_error = recovery_exc
            try:
                self._synthesize_via_api_with_quality_gate(request)
                return
            except OmniVoiceQualityGateError as second_quality_exc:
                recovery_suffix = f"; recovery={recovery_error}" if recovery_error is not None else ""
                raise RuntimeError(f"{second_quality_exc}{recovery_suffix}") from second_quality_exc
            except Exception as second_exc:
                recovery_suffix = f"; recovery={recovery_error}" if recovery_error is not None else ""
                raise RuntimeError(
                    "E-TTS-001 omnivoice api failed after one retry: "
                    f"first={first_exc}; second={second_exc}{recovery_suffix}"
                ) from second_exc
