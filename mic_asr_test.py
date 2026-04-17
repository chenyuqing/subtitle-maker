#!/usr/bin/env python3
"""Microphone real-time ASR test using Qwen3-ASR-0.6B."""

import sounddevice as sd
import numpy as np
import torch
import tempfile
import os
import wave
import time
import sys

# Add src to path for qwen_asr import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from qwen_asr import Qwen3ASRModel

CHUNK_DURATION = 5  # seconds
SAMPLE_RATE = 16000


def main():
    print("Loading ASR model...")
    model = Qwen3ASRModel.from_pretrained(
        "models/Qwen3-ASR-0.6B",
        dtype=torch.float16,
        device_map="mps",
        forced_aligner="models/Qwen3-ForcedAligner-0.6B",
        forced_aligner_kwargs=dict(dtype=torch.float16, device_map="mps"),
    )
    print("Model loaded. Start speaking...")

    audio_buffer = []

    def callback(indata, frames, time, status):
        if status:
            print(f"Status: {status}")
        audio_buffer.append(indata.copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=callback,
        blocksize=SAMPLE_RATE * CHUNK_DURATION,
    ):
        print(f"Recording in {CHUNK_DURATION}s chunks... Press Ctrl+C to stop")
        while True:
            if len(audio_buffer) >= 1:
                audio_data = np.concatenate(audio_buffer, axis=0)
                audio_buffer.clear()

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    temp_path = f.name

                try:
                    with wave.open(temp_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(SAMPLE_RATE)
                        int_data = (audio_data.flatten() * 32767).astype(np.int16)
                        wf.writeframes(int_data.tobytes())

                    results = model.transcribe(audio=temp_path, return_time_stamps=True)
                    for res in results:
                        print(f"> {res.text}")
                finally:
                    os.unlink(temp_path)

            time.sleep(0.1)


if __name__ == "__main__":
    main()
