from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict


REPO_ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = REPO_ROOT / "start_index_tts_api.sh"
STOP_SCRIPT = REPO_ROOT / "stop_index_tts_api.sh"
DEFAULT_API_URL = "http://127.0.0.1:8010"


def _post_json(url: str, payload: Dict[str, Any] | None = None, timeout: float = 5.0) -> Dict[str, Any]:
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def get_index_tts_status(api_url: str = DEFAULT_API_URL) -> Dict[str, Any]:
    try:
        payload = _get_json(api_url.rstrip("/") + "/health", timeout=3.0)
        return {
            "ok": bool(payload.get("ok")),
            "reachable": True,
            "status": payload.get("status"),
            "payload": payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "reachable": False,
            "status": "offline",
            "error": str(exc),
        }


def start_index_tts_service() -> Dict[str, Any]:
    if not START_SCRIPT.exists():
        return {"ok": False, "detail": f"start script not found: {START_SCRIPT}"}
    proc = subprocess.run(
        [str(START_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    status = get_index_tts_status()
    return {
        "ok": proc.returncode == 0 and status.get("reachable", False),
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
        "status": status,
    }


def stop_index_tts_service() -> Dict[str, Any]:
    if not STOP_SCRIPT.exists():
        return {"ok": False, "detail": f"stop script not found: {STOP_SCRIPT}"}
    proc = subprocess.run(
        [str(STOP_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def release_index_tts_model(api_url: str = DEFAULT_API_URL) -> Dict[str, Any]:
    try:
        payload = _post_json(api_url.rstrip("/") + "/model/release", timeout=5.0)
        return {"ok": True, "payload": payload}
    except urllib.error.URLError as exc:
        return {"ok": False, "detail": str(exc)}
    except Exception as exc:
        return {"ok": False, "detail": str(exc)}
