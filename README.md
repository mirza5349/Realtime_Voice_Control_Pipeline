# local-voice-ai-pipeline

Minimal FastAPI scaffold for a local voice-to-AI-to-action project. The backend bundles local STT, local LLM orchestration, low-fidelity simulator execution, short-lived local TTS artifact delivery, and a lightweight project UI for client walkthroughs.

## Requirements

- Python 3.10+
- `uv`
- Optional: `docker` with Compose plugin, plus local `whisper.cpp`, `piper`, and `ollama` installations for end-to-end projects

## Setup

```bash
uv sync --extra dev
cp .env.example .env
```

## Run

```bash
make run
```

The API will start at `http://127.0.0.1:8000`.

### project UI

```bash
make run-project
```

Open `http://127.0.0.1:8000/project` in a browser. The page lets you create a session, open the websocket stream, upload audio (or pick a bundled sample), watch the event timeline, and inspect the assistant text, audio playback, simulator state, and stage latency side-by-side.

### project Assets

```bash
make project-assets
```

Seeds `.data/project_assets/` with a small sample wav so the UI always has something to upload even without real recordings.

### Docker

```bash
make docker-build
make docker-up
```

The compose stack exposes `http://127.0.0.1:8000/project` and mounts `.data/` for persistence. External binaries (`whisper.cpp`, `piper`, `ollama`) are expected to be served by the host; override `OLLAMA_BASE_URL` or mount volumes to wire them in. Use `make docker-down` to tear it down.

## Developer Commands

```bash
make test
make lint
make format
make project AUDIO=./sample.wav
```

## API Endpoints

- `GET /health`
- `GET /project`
- `POST /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `POST /api/v1/sessions/{session_id}/transcriptions`
- `GET /api/v1/sessions/{session_id}/diagnostics`
- `GET /api/v1/audio/{asset_id}`
- `GET /api/v1/metrics/summary`
- `GET /api/v1/project/context`
- `GET /api/v1/project/samples`
- `GET /api/v1/project/samples/{name}`
- `GET /api/v1/project/sessions/{session_id}/overview`
- `POST /api/v1/sessions/{session_id}/live-audio/start`
- `POST /api/v1/sessions/{session_id}/live-audio/stop`
- `POST /api/v1/sessions/{session_id}/live-audio`
- `WS /api/v1/ws/sessions/{session_id}`

## STT Configuration

Set the local whisper.cpp adapter through `.env`:

```bash
STT_PROVIDER=whisper_cpp
WHISPER_CPP_BINARY_PATH=whisper-cli
WHISPER_CPP_MODEL_PATH=/absolute/path/to/ggml-base.en.bin
WHISPER_CPP_THREADS=4
WHISPER_CPP_LANGUAGE=en
UPLOAD_MAX_BYTES=10485760
```

## LLM Configuration

Set the local LLM adapter through `.env`:

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
LLM_REQUEST_TIMEOUT_SECONDS=30
SESSION_HISTORY_LIMIT=10
```

## Simulator Behavior

Structured action decisions are executed automatically by a low-fidelity in-memory simulator. Each session keeps its own simulator state with heading, velocity, movement flag, and last action.

## TTS Configuration

Set the local Piper adapter and managed audio storage through `.env`:

```bash
TTS_PROVIDER=piper
PIPER_BINARY_PATH=piper
PIPER_MODEL_PATH=/absolute/path/to/en_US-lessac-medium.onnx
AUDIO_STORAGE_DIR=.data/audio
AUDIO_PUBLIC_BASE_PATH=/api/v1/audio
AUDIO_FILE_TTL_SECONDS=3600
```

## Observability Configuration

Tune in-memory tracing and project defaults through `.env`:

```bash
TRACE_HISTORY_LIMIT=100
METRICS_RETENTION_LIMIT=500
project_RUNNER_TIMEOUT_SECONDS=60
```

## project UX Configuration

```bash
project_MODE=true
project_AUTO_CLEANUP_AUDIO=true
project_STARTUP_VALIDATE_PROVIDERS=true
project_SAMPLES_DIR=.data/project_assets
project_SAMPLES_PUBLIC_PATH=/api/v1/project/samples
project_CLEANUP_INTERVAL_SECONDS=300
```

When `project_AUTO_CLEANUP_AUDIO=true` the application periodically deletes expired audio artifacts in the background. `project_STARTUP_VALIDATE_PROVIDERS=true` emits warnings at startup when the configured STT, LLM, or TTS provider binaries or models cannot be located, so missing local dependencies surface clearly before the first interaction.

## Live Microphone Configuration

```bash
LIVE_AUDIO_ENABLED=true
LIVE_AUDIO_MAX_SECONDS_PER_UTTERANCE=10
LIVE_AUDIO_MIN_SECONDS_PER_UTTERANCE=0.5
LIVE_AUDIO_MAX_QUEUE_PER_SESSION=5
LIVE_AUDIO_AUTOPLAY_DEFAULT=true
LIVE_AUDIO_SILENCE_WINDOW_MS=1200
```

The project UI supports browser-native microphone capture with silence-based utterance segmentation. Each detected utterance is posted to `POST /api/v1/sessions/{session_id}/live-audio` (multipart `file` + `duration_ms`), enqueued per session, and processed serially through the same STT → LLM → simulator → TTS pipeline used for file uploads. Live websocket events (`live_audio.started`, `live_audio.utterance_captured`, `live_audio.processing_started`, `live_audio.processing_completed`, `live_audio.idle`) expose microphone state without replacing the existing event flow. Set `LIVE_AUDIO_AUTOPLAY_DEFAULT=false` to disable immediate playback of assistant audio.

## Quick Check

```bash
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/api/v1/sessions -H "Content-Type: application/json" -d '{}'
```

## Websocket Check

```bash
uv run python - <<'PY'
import asyncio
import json

import httpx
import websockets


async def main() -> None:
    async with httpx.AsyncClient() as client:
        response = await client.post("http://127.0.0.1:8000/api/v1/sessions", json={})
        session_id = response.json()["session_id"]

    async with websockets.connect(f"ws://127.0.0.1:8000/api/v1/ws/sessions/{session_id}") as websocket:
        print(await websocket.recv())
        await websocket.send(json.dumps({"type": "client.ping", "payload": {"message": "hello"}}))
        print(await websocket.recv())
        await websocket.send(json.dumps({"type": "session.request_state", "payload": {}}))
        print(await websocket.recv())


asyncio.run(main())
PY
```

## Transcription Check

```bash
curl -X POST \
  http://127.0.0.1:8000/api/v1/sessions/$SESSION_ID/transcriptions \
  -F "file=@sample.wav;type=audio/wav"
```

## Ollama Check

```bash
ollama serve
ollama pull llama3.2:3b
```

## project Runner

With the server running, execute a repeatable end-to-end check:

```bash
make project AUDIO=./sample.wav
```

Or run the CLI directly:

```bash
uv run local-voice-ai-project ./sample.wav --base-url http://127.0.0.1:8000
```

## Recording a Client Walkthrough

Suggested sequence for capturing a polished client-facing recording:

1. Start a fresh shell and run `make project-assets` to seed `.data/project_assets/`.
2. Start the server with `make run-project` (or `docker compose up`) so the `/project` UI is reachable.
3. Open `http://127.0.0.1:8000/project` in a clean browser profile, and resize the window to 1280x800 for consistent framing.
4. Hit record on your screen capture tool (OBS, QuickTime, or similar).
5. Narrate and click through the UI in this order:
   - Show the service/environment header and provider chips.
   - Create a new session and open the websocket stream.
   - Upload the bundled sample (or drag in your own `.wav`).
   - Walk through the event timeline as each stage fires.
   - Highlight the transcript, assistant response, audio playback, simulator state, and latency metrics.
   - Upload a second file to show repeatable behavior.
6. Stop recording, trim the file, and export at 1080p/30fps.

## Execution Flow

After a successful transcription, the pipeline emits:

- `transcription.started`
- `transcription.completed`
- `llm.started`
- `llm.completed`
- `assistant.response`
- `tts.started`
- `tts.completed`
- `assistant.audio_ready`
- `action.decided`
- `action.execution_started`
- `action.execution_completed`
- `simulator.state_updated`

## Metrics Summary Example

```json
{
  "active_sessions": 1,
  "active_websockets": 1,
  "completed_requests": 3,
  "failed_requests": 1,
  "recent_error_count": 1,
  "avg_transcription_duration_ms": 42.0,
  "avg_llm_duration_ms": 18.0,
  "avg_execution_duration_ms": 0.0,
  "avg_tts_duration_ms": 210.0,
  "avg_end_to_end_duration_ms": 12.0
}
```

## Session Diagnostics Example

```json
{
  "session_id": "00000000-0000-0000-0000-000000000000",
  "session_status": "active",
  "active_connection": true,
  "current_simulator_state": {
    "heading_deg": 0.0,
    "velocity": 0.0,
    "is_moving": false,
    "last_action": "status_report",
    "updated_at": "2026-01-01T00:00:00Z"
  },
  "recent_requests": [
    {
      "request_id": "00000000-0000-0000-0000-000000000001",
      "started_at": "2026-01-01T00:00:00Z",
      "completed_at": "2026-01-01T00:00:01Z",
      "status": "completed",
      "transcription_duration_ms": 42,
      "llm_duration_ms": 18,
      "execution_duration_ms": 0,
      "tts_duration_ms": 210,
      "end_to_end_duration_ms": 300,
      "stage_timings": {
        "transcription": {
          "started_at": "2026-01-01T00:00:00Z",
          "completed_at": "2026-01-01T00:00:00Z",
          "duration_ms": 42
        },
        "llm": {
          "started_at": "2026-01-01T00:00:00Z",
          "completed_at": "2026-01-01T00:00:00Z",
          "duration_ms": 18
        },
        "execution": {
          "started_at": "2026-01-01T00:00:00Z",
          "completed_at": "2026-01-01T00:00:01Z",
          "duration_ms": 0
        },
        "tts": {
          "started_at": "2026-01-01T00:00:00Z",
          "completed_at": "2026-01-01T00:00:00Z",
          "duration_ms": 210
        }
      },
      "last_error": null
    }
  ],
  "last_error": null,
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-01T00:00:00Z"
}
```

## Structure

```text
.
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── README.md
├── pyproject.toml
├── scripts
│   ├── prepare_project_assets.sh
│   └── run_project.sh
├── src
│   └── app
│       ├── api
│       │   ├── router.py
│       │   ├── routes
│       │   │   ├── audio.py
│       │   │   ├── project.py
│       │   │   ├── health.py
│       │   │   ├── metrics.py
│       │   │   ├── session.py
│       │   │   └── transcription.py
│       │   └── ws
│       │       ├── __init__.py
│       │       └── routes.py
│       ├── cli
│       │   └── project_runner.py
│       ├── core
│       │   ├── config.py
│       │   └── logging.py
│       ├── main.py
│       ├── models
│       │   ├── action.py
│       │   ├── audio.py
│       │   ├── project.py
│       │   ├── events.py
│       │   ├── llm.py
│       │   ├── metrics.py
│       │   ├── session.py
│       │   ├── simulator.py
│       │   ├── transcription.py
│       │   └── tts.py
│       ├── services
│       │   ├── audio_store.py
│       │   ├── connection_manager.py
│       │   ├── project_service.py
│       │   ├── diagnostics_service.py
│       │   ├── event_bus.py
│       │   ├── execution_service.py
│       │   ├── llm
│       │   │   ├── base.py
│       │   │   └── ollama.py
│       │   ├── metrics_collector.py
│       │   ├── orchestrator.py
│       │   ├── prompt_builder.py
│       │   ├── session_manager.py
│       │   ├── session_runtime.py
│       │   ├── simulator
│       │   │   ├── base.py
│       │   │   └── low_fidelity.py
│       │   ├── stt
│       │   │   ├── base.py
│       │   │   └── whisper_cpp.py
│       │   ├── tracing.py
│       │   ├── transcription_service.py
│       │   ├── tts
│       │   │   ├── base.py
│       │   │   └── piper.py
│       │   └── tts_service.py
│       └── web
│           ├── static
│           │   ├── project.css
│           │   └── project.js
│           └── templates
│               └── project.html
└── tests
    ├── test_audio_asset_http.py
    ├── test_project_ui_http.py
    ├── test_end_to_end_diagnostics.py
    ├── test_execution_ws_flow.py
    ├── test_health.py
    ├── test_llm_ws_flow.py
    ├── test_metrics_http.py
    ├── test_orchestrator.py
    ├── test_simulator.py
    ├── test_transcription_http.py
    ├── test_transcription_ws_flow.py
    ├── test_tts_service.py
    ├── test_tts_ws_flow.py
    └── test_ws_session.py
```
