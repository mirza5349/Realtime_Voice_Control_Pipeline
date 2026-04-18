#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

SAMPLES_DIR="${DEMO_SAMPLES_DIR:-.data/demo_assets}"
SAMPLE_NAME="${DEMO_SAMPLE_NAME:-sample_silence.wav}"
SAMPLE_DURATION_MS="${DEMO_SAMPLE_DURATION_MS:-1000}"

mkdir -p "${SAMPLES_DIR}"

python3 - "$SAMPLES_DIR" "$SAMPLE_NAME" "$SAMPLE_DURATION_MS" <<'PY'
import sys
import wave
from pathlib import Path

samples_dir = Path(sys.argv[1])
sample_name = sys.argv[2]
duration_ms = int(sys.argv[3])

samples_dir.mkdir(parents=True, exist_ok=True)
output = samples_dir / sample_name

if output.exists():
    print(f"[prepare_demo_assets] {output} already exists, leaving it alone")
    raise SystemExit(0)

frame_rate = 16000
frames = max(1, int(frame_rate * duration_ms / 1000))
with wave.open(str(output), "wb") as wav_file:
    wav_file.setnchannels(1)
    wav_file.setsampwidth(2)
    wav_file.setframerate(frame_rate)
    wav_file.writeframes(b"\x00\x00" * frames)

print(f"[prepare_demo_assets] wrote {output}")
PY

echo "[prepare_demo_assets] sample assets ready under ${SAMPLES_DIR}"
