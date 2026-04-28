#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import importlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Type
from urllib.parse import urlparse

import soundfile as sf
import torch
import torchaudio


DEFAULT_OMNIVOICE_ROOT = Path("/Users/tim/Documents/vibe-coding/MVP/OmniVoice").resolve()
DEFAULT_OMNIVOICE_MODEL = str((DEFAULT_OMNIVOICE_ROOT / "omnivoice" / "checkpoints").resolve())


def _log_server_event(level: str, event: str, **data: Any) -> None:
    """把 OmniVoice 服务端关键事件写成结构化 JSON，便于后台排障。"""

    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "level": str(level or "INFO").upper(),
        "event": str(event or "").strip() or "unknown",
        "data": data,
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _read_bool(value: Any, default: bool = False) -> bool:
    """把字符串/数字布尔值解析为 True/False。"""

    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _load_omnivoice_class(root_dir: Path) -> Type[Any]:
    """从给定 OmniVoice 根目录加载 OmniVoice 模型类。"""

    resolved_root = root_dir.expanduser().resolve()
    if not resolved_root.exists():
        raise RuntimeError(f"omnivoice root not found: {resolved_root}")
    if str(resolved_root) not in sys.path:
        sys.path.insert(0, str(resolved_root))
    try:
        module = importlib.import_module("omnivoice.models.omnivoice")
    except Exception as exc:
        raise RuntimeError(
            f"failed to import omnivoice from {resolved_root}; "
            "start this server with the OmniVoice virtualenv"
        ) from exc
    return module.OmniVoice


def _ensure_optional_file(path_text: str) -> Optional[Path]:
    """解析可选文件路径，存在时返回绝对路径，不存在时报错。"""

    raw = str(path_text or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"file not found: {path}")
    if not path.is_file():
        raise ValueError(f"path must be a file: {path}")
    return path


def _resolve_runtime_params(payload: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """把请求覆盖项与服务默认配置合并成一次合成真正使用的参数。"""

    return {
        "num_step": int(payload.get("num_step", cfg["num_step"])),
        "guidance_scale": float(payload.get("guidance_scale", cfg["guidance_scale"])),
        "speed": float(payload.get("speed", cfg["speed"])),
        "t_shift": float(payload.get("t_shift", cfg["t_shift"])),
        "denoise": _read_bool(payload.get("denoise"), default=cfg["denoise"]),
        "postprocess_output": _read_bool(
            payload.get("postprocess_output"),
            default=cfg["postprocess_output"],
        ),
        "layer_penalty_factor": float(payload.get("layer_penalty_factor", cfg["layer_penalty_factor"])),
        "position_temperature": float(payload.get("position_temperature", cfg["position_temperature"])),
        "class_temperature": float(payload.get("class_temperature", cfg["class_temperature"])),
    }


def _compute_duration_ratio(target_duration_sec: Optional[float], actual_duration_sec: float) -> Optional[float]:
    """根据目标时长和实际时长计算时长比值；目标缺失时返回 None。"""

    if target_duration_sec is None:
        return None
    if float(target_duration_sec) <= 0.0:
        return None
    return max(0.0, float(actual_duration_sec) / float(target_duration_sec))


class ServerState:
    """维护 OmniVoice 模型实例的线程安全状态。"""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.model: Optional[Any] = None
        self.omnivoice_cls = _load_omnivoice_class(Path(cfg["omnivoice_root"]))

    def _resolve_dtype(self) -> Any:
        """根据设备选择更稳的 dtype（CPU 走 float32，GPU/MPS 优先 float16）。"""

        device = str(self.cfg.get("device") or "").strip().lower()
        if device.startswith("cpu"):
            return torch.float32
        return torch.float16

    def ensure_loaded(self) -> Any:
        """按需加载 OmniVoice 模型，已加载则直接复用。"""

        if self.model is None:
            _log_server_event(
                "INFO",
                "model_loading_started",
                model=str(self.cfg.get("model") or ""),
                device=str(self.cfg.get("device") or ""),
            )
            self.model = self.omnivoice_cls.from_pretrained(
                str(self.cfg["model"]),
                device_map=str(self.cfg["device"]),
                dtype=self._resolve_dtype(),
            )
            _log_server_event(
                "INFO",
                "model_loading_finished",
                model=str(self.cfg.get("model") or ""),
                device=str(self.cfg.get("device") or ""),
            )
        return self.model

    def release(self) -> bool:
        """释放模型与显存缓存，返回是否真的释放过模型。"""

        if self.model is None:
            return False
        del self.model
        self.model = None
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        _log_server_event("INFO", "model_released")
        return True

    def synthesize(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """执行一次 OmniVoice 合成，并返回输出文件信息。"""

        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        output_path = Path(str(payload.get("output_path") or "")).expanduser().resolve()
        if not str(output_path):
            raise ValueError("output_path is required")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ref_audio = _ensure_optional_file(str(payload.get("ref_audio") or ""))
        ref_text = str(payload.get("ref_text") or "").strip() or None
        language = str(payload.get("language") or "").strip() or None
        instruct = str(payload.get("instruct") or "").strip() or None
        duration = payload.get("duration", None)
        if duration is not None:
            duration = float(duration)
        retry_profile = str(payload.get("retry_profile") or "default").strip() or "default"
        runtime_params = _resolve_runtime_params(payload, self.cfg)

        model = self.ensure_loaded()
        audios = model.generate(
            text=text,
            language=language,
            ref_audio=str(ref_audio) if ref_audio else None,
            ref_text=ref_text,
            instruct=instruct,
            duration=duration,
            num_step=int(runtime_params["num_step"]),
            guidance_scale=float(runtime_params["guidance_scale"]),
            speed=float(runtime_params["speed"]),
            t_shift=float(runtime_params["t_shift"]),
            denoise=bool(runtime_params["denoise"]),
            postprocess_output=bool(runtime_params["postprocess_output"]),
            layer_penalty_factor=float(runtime_params["layer_penalty_factor"]),
            position_temperature=float(runtime_params["position_temperature"]),
            class_temperature=float(runtime_params["class_temperature"]),
        )
        torchaudio.save(str(output_path), audios[0], int(model.sampling_rate))
        if not output_path.exists():
            raise RuntimeError("synthesis finished but output file missing")
        info = sf.info(str(output_path))
        actual_duration_sec = float(info.duration)
        duration_ratio = _compute_duration_ratio(duration, actual_duration_sec)
        return {
            "output_path": str(output_path),
            "duration_sec": actual_duration_sec,
            "actual_duration_sec": actual_duration_sec,
            "target_duration_sec": duration,
            "duration_ratio": duration_ratio,
            "sample_rate": int(info.samplerate),
            "retry_profile": retry_profile,
            **runtime_params,
        }


state: Optional[ServerState] = None


class OmniVoiceRequestHandler(BaseHTTPRequestHandler):
    """OmniVoice HTTP API：提供 health/synthesize/release 三个核心端点。"""

    server_version = "OmniVoiceHTTP/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            raise ValueError("empty request body")
        raw = self.rfile.read(content_length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"invalid json body: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("json body must be an object")
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path != "/health":
            self._send_json({"detail": "not found"}, status=404)
            return
        if state is None:
            self._send_json({"ok": False, "status": "not_loaded"})
            return
        self._send_json(
            {
                "ok": True,
                "status": "ok",
                "service_state": "ready" if state.model is not None else "idle",
                "loaded": state.model is not None,
                "model": state.cfg.get("model"),
                "cfg": state.cfg,
            }
        )

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/synthesize":
                self._handle_synthesize()
                return
            if path == "/model/release":
                self._handle_release()
                return
            self._send_json({"detail": "not found"}, status=404)
        except ValueError as exc:
            self._send_json({"detail": str(exc)}, status=400)
        except RuntimeError as exc:
            self._send_json({"detail": str(exc)}, status=503)
        except Exception as exc:
            self._send_json({"detail": str(exc)}, status=500)

    def _handle_release(self) -> None:
        """释放模型并回收显存。"""

        if state is None:
            raise RuntimeError("server not initialized")
        _log_server_event("INFO", "release_requested")
        with state.lock:
            released = state.release()
        self._send_json({"ok": True, "released": released, "status": "idle"})

    def _handle_synthesize(self) -> None:
        """执行一次 TTS 合成。"""

        if state is None:
            raise RuntimeError("server not initialized")
        data = self._read_json()
        request_id = f"req_{time.time_ns()}"
        text = str(data.get("text") or "")
        output_path = str(data.get("output_path") or "")
        start_at = time.perf_counter()
        _log_server_event(
            "INFO",
            "synthesize_started",
            request_id=request_id,
            output_path=output_path,
            ref_audio=str(data.get("ref_audio") or ""),
            language=str(data.get("language") or ""),
            target_duration_sec=data.get("duration"),
            retry_profile=str(data.get("retry_profile") or "default"),
            text_length=len(text),
            text_preview=text[:80],
        )
        try:
            with state.lock:
                result = state.synthesize(data)
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start_at) * 1000, 1)
            _log_server_event(
                "ERROR",
                "synthesize_failed",
                request_id=request_id,
                output_path=output_path,
                elapsed_ms=elapsed_ms,
                target_duration_sec=data.get("duration"),
                retry_profile=str(data.get("retry_profile") or "default"),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        elapsed_ms = round((time.perf_counter() - start_at) * 1000, 1)
        _log_server_event(
            "INFO",
            "synthesize_finished",
            request_id=request_id,
            output_path=str(result.get("output_path") or output_path),
            elapsed_ms=elapsed_ms,
            target_duration_sec=result.get("target_duration_sec"),
            actual_duration_sec=result.get("actual_duration_sec", result.get("duration_sec")),
            duration_ratio=result.get("duration_ratio"),
            retry_profile=result.get("retry_profile"),
            speed=result.get("speed"),
            num_step=result.get("num_step"),
            guidance_scale=result.get("guidance_scale"),
            denoise=result.get("denoise"),
            postprocess_output=result.get("postprocess_output"),
            duration_sec=result.get("duration_sec"),
            sample_rate=result.get("sample_rate"),
        )
        self._send_json({"ok": True, **result})


def parse_args() -> argparse.Namespace:
    """解析启动参数。"""

    parser = argparse.ArgumentParser(description="OmniVoice HTTP API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8020)
    parser.add_argument("--omnivoice-root", default=str(DEFAULT_OMNIVOICE_ROOT))
    parser.add_argument("--model", default=DEFAULT_OMNIVOICE_MODEL)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--num-step", type=int, default=32)
    parser.add_argument("--guidance-scale", type=float, default=2.0)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--t-shift", type=float, default=0.1)
    parser.add_argument("--denoise", default="true")
    parser.add_argument("--postprocess-output", default="true")
    parser.add_argument("--layer-penalty-factor", type=float, default=5.0)
    parser.add_argument("--position-temperature", type=float, default=5.0)
    parser.add_argument("--class-temperature", type=float, default=0.0)
    parser.add_argument("--load-on-startup", action="store_true")
    return parser.parse_args()


def main() -> int:
    """启动 OmniVoice HTTP 服务。"""

    global state
    args = parse_args()
    omnivoice_root = Path(args.omnivoice_root).expanduser().resolve()
    if not omnivoice_root.exists():
        raise SystemExit(f"omnivoice root not found: {omnivoice_root}")

    state = ServerState(
        cfg={
            "omnivoice_root": str(omnivoice_root),
            "model": str(args.model),
            "device": str(args.device),
            "num_step": int(args.num_step),
            "guidance_scale": float(args.guidance_scale),
            "speed": float(args.speed),
            "t_shift": float(args.t_shift),
            "denoise": _read_bool(args.denoise, default=True),
            "postprocess_output": _read_bool(args.postprocess_output, default=True),
            "layer_penalty_factor": float(args.layer_penalty_factor),
            "position_temperature": float(args.position_temperature),
            "class_temperature": float(args.class_temperature),
        },
    )

    if bool(args.load_on_startup):
        with state.lock:
            state.ensure_loaded()

    server = ThreadingHTTPServer((args.host, int(args.port)), OmniVoiceRequestHandler)
    print(f"OmniVoice API listening on http://{args.host}:{args.port}")
    _log_server_event(
        "INFO",
        "server_started",
        host=str(args.host),
        port=int(args.port),
        model=str(args.model),
        device=str(args.device),
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _log_server_event("INFO", "server_stopped")
        if state is not None:
            with state.lock:
                state.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
