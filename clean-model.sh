#!/usr/bin/env bash
set -euo pipefail

# clean-model.sh
# Releases in-memory ASR / aligner / TTS weights so the Mac's RAM is freed
# without deleting downloaded model files. The FastAPI app already exposes
# helper endpoints that unload models and flush caches; this script simply
# calls them and gives user-friendly logging.

API_URL="${API_URL:-http://127.0.0.1:8000}"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to call ${API_URL}; please install curl." >&2
  exit 1
fi

echo "Requesting Qwen ASR/TTS unload via ${API_URL}/model/all/release ..."
if curl -fsS -X POST "${API_URL}/model/all/release" >/dev/null; then
  echo "✔️  FastAPI reported that all models are released."
else
  echo "⚠️  Release endpoint failed; attempting ASR-only endpoint..." >&2
  if curl -fsS -X POST "${API_URL}/model/asr/release" >/dev/null; then
    echo "✔️  ASR release succeeded. TTS will unload automatically on next dub run."
  else
    echo "❌  Could not reach the release endpoints at ${API_URL}. Is the server running?" >&2
    exit 1
  fi
fi

echo "Freeing OS cache (macOS purge)..."
if command -v purge >/dev/null 2>&1; then
  sudo purge || true
else
  echo "macOS 'purge' command not found; skipping." >&2
fi

echo "Done. Large models should now be out of memory."
