#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import importlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Type
from urllib.parse import urlparse

import soundfile as sf
import torch


DEFAULT_INDEX_TTS_ROOT = Path("/Users/tim/Documents/vibe-coding/MVP/index-tts-1108").resolve()
DEFAULT_CFG_PATH = (DEFAULT_INDEX_TTS_ROOT / "checkpoints" / "config.yaml").resolve()
DEFAULT_MODEL_DIR = (DEFAULT_INDEX_TTS_ROOT / "checkpoints").resolve()


def _ensure_file(path_text: str, field_name: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"{field_name} not found: {path}")
    if not path.is_file():
        raise ValueError(f"{field_name} must be a file: {path}")
    return path


def _load_index_tts_class(root_dir: Path) -> Type[Any]:
    resolved_root = root_dir.expanduser().resolve()
    if not resolved_root.exists():
        raise RuntimeError(f"index-tts root not found: {resolved_root}")
    if str(resolved_root) not in sys.path:
        sys.path.insert(0, str(resolved_root))
    try:
        module = importlib.import_module("indextts.infer_v2")
    except Exception as exc:
        raise RuntimeError(
            f"failed to import indextts from {resolved_root}; "
            f"start this server with the index-tts virtualenv"
        ) from exc
    return module.IndexTTS2


class ServerState:
    def __init__(self, cfg: Dict[str, Any]):
        self.tts: Optional[Any] = None
        self.cfg = cfg
        self.lock = threading.Lock()
        self.index_tts_cls = _load_index_tts_class(Path(cfg["indextts_root"]))

    def _build_tts(self) -> Any:
        return self.index_tts_cls(
            cfg_path=str(self.cfg["cfg_path"]),
            model_dir=str(self.cfg["model_dir"]),
            use_fp16=bool(self.cfg["use_fp16"]),
            device=str(self.cfg["device"]),
            use_accel=bool(self.cfg["use_accel"]),
            use_torch_compile=bool(self.cfg["use_torch_compile"]),
        )

    def ensure_loaded(self) -> Any:
        if self.tts is None:
            self.tts = self._build_tts()
        return self.tts

    def release(self) -> bool:
        if self.tts is None:
            return False
        del self.tts
        self.tts = None
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()
        return True


state: Optional[ServerState] = None


class IndexTTSRequestHandler(BaseHTTPRequestHandler):
    server_version = "IndexTTSHTTP/1.0"

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
                "service_state": "ready" if state.tts is not None else "idle",
                "loaded": state.tts is not None,
                "model": "IndexTTS2",
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
        if state is None:
            raise RuntimeError("server not initialized")
        with state.lock:
            released = state.release()
        self._send_json({"ok": True, "released": released, "status": "idle"})

    def _handle_synthesize(self) -> None:
        if state is None:
            raise RuntimeError("model not loaded")

        data = self._read_json()
        text = str(data.get("text") or "").strip()
        if not text:
            raise ValueError("text is required")
        spk_audio_prompt = _ensure_file(str(data.get("spk_audio_prompt") or ""), "spk_audio_prompt")
        output_path = Path(str(data.get("output_path") or "")).expanduser().resolve()
        if not str(output_path):
            raise ValueError("output_path is required")

        emo_audio_prompt: Optional[Path] = None
        if data.get("emo_audio_prompt"):
            emo_audio_prompt = _ensure_file(str(data["emo_audio_prompt"]), "emo_audio_prompt")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with state.lock:
            tts = state.ensure_loaded()
            tts.infer(
                spk_audio_prompt=str(spk_audio_prompt),
                text=text,
                output_path=str(output_path),
                emo_audio_prompt=str(emo_audio_prompt) if emo_audio_prompt else None,
                emo_alpha=float(data.get("emo_alpha", 1.0)),
                use_emo_text=bool(data.get("use_emo_text", False)),
                emo_text=data.get("emo_text"),
                verbose=False,
                max_text_tokens_per_segment=int(data.get("max_text_tokens_per_segment", 120)),
                top_p=float(data.get("top_p", 0.8)),
                top_k=int(data.get("top_k", 30)),
                temperature=float(data.get("temperature", 0.8)),
            )

        if not output_path.exists():
            raise RuntimeError("synthesis finished but output file missing")

        info = sf.info(str(output_path))
        self._send_json(
            {
                "ok": True,
                "output_path": str(output_path),
                "duration_sec": float(info.duration),
                "sample_rate": int(info.samplerate),
            }
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index-TTS HTTP API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--indextts-root", default=str(DEFAULT_INDEX_TTS_ROOT))
    parser.add_argument("--cfg-path", default=str(DEFAULT_CFG_PATH))
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--device", default="mps")
    parser.add_argument("--use-fp16", action="store_true")
    parser.add_argument("--use-accel", action="store_true")
    parser.add_argument("--use-torch-compile", action="store_true")
    parser.add_argument("--load-on-startup", action="store_true")
    return parser.parse_args()


def main() -> int:
    global state
    args = parse_args()

    indextts_root = Path(args.indextts_root).expanduser().resolve()
    cfg_path = Path(args.cfg_path).expanduser().resolve()
    model_dir = Path(args.model_dir).expanduser().resolve()
    if not indextts_root.exists():
        raise SystemExit(f"index-tts root not found: {indextts_root}")
    if not cfg_path.exists():
        raise SystemExit(f"config not found: {cfg_path}")
    if not model_dir.exists():
        raise SystemExit(f"model_dir not found: {model_dir}")

    state = ServerState(
        cfg={
            "indextts_root": str(indextts_root),
            "cfg_path": str(cfg_path),
            "model_dir": str(model_dir),
            "device": args.device,
            "use_fp16": bool(args.use_fp16),
            "use_accel": bool(args.use_accel),
            "use_torch_compile": bool(args.use_torch_compile),
        },
    )
    if bool(args.load_on_startup):
        state.ensure_loaded()

    server = ThreadingHTTPServer((args.host, args.port), IndexTTSRequestHandler)
    print(f"Index-TTS API listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if state is not None:
            with state.lock:
                state.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
