from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse

import httpx
import websockets

from app.core.config import get_settings


async def run_demo(audio_file: Path, base_url: str, timeout_seconds: int) -> int:
    settings = get_settings()
    base_url = base_url.rstrip("/")
    websocket_url = _to_websocket_url(base_url)

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        create_response = await client.post(f"{base_url}/api/v1/sessions", json={})
        create_response.raise_for_status()
        session_id = create_response.json()["session_id"]

        print(f"service: {settings.app_name}")
        print(f"session_id: {session_id}")
        print(f"audio_file: {audio_file}")
        print()
        print("timeline:")

        async with websockets.connect(
            f"{websocket_url}/api/v1/ws/sessions/{session_id}",
            open_timeout=timeout_seconds,
        ) as websocket:
            start = perf_counter()
            request_response = await client.post(
                f"{base_url}/api/v1/sessions/{session_id}/transcriptions",
                files={"file": (audio_file.name, audio_file.read_bytes(), "audio/wav")},
            )
            request_response.raise_for_status()

            seen_audio_ready = False
            seen_terminal_execution = False

            while perf_counter() - start < timeout_seconds:
                remaining = timeout_seconds - (perf_counter() - start)
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                except TimeoutError:
                    break

                event = json.loads(message)
                print(_format_event(event))
                event_type = event["type"]
                if event_type == "assistant.audio_ready":
                    seen_audio_ready = True
                if event_type == "simulator.state_updated":
                    seen_terminal_execution = True
                if event_type == "action.execution_completed":
                    if event["payload"]["success"] is False:
                        seen_terminal_execution = True
                if seen_audio_ready and seen_terminal_execution:
                    break

        diagnostics = await client.get(f"{base_url}/api/v1/sessions/{session_id}/diagnostics")
        diagnostics.raise_for_status()
        summary = await client.get(f"{base_url}/api/v1/metrics/summary")
        summary.raise_for_status()

    print()
    print("diagnostics:")
    print(json.dumps(diagnostics.json(), indent=2))
    print()
    print("metrics:")
    print(json.dumps(summary.json(), indent=2))
    return 0


def _to_websocket_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}"


def _format_event(event: dict[str, object]) -> str:
    timestamp = event.get("timestamp", "")
    event_type = event.get("type", "")
    payload = event.get("payload", {})
    return f"- {timestamp} {event_type} {json.dumps(payload, sort_keys=True)}"


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="local-voice-ai-demo")
    parser.add_argument("audio_file", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=settings.demo_runner_timeout_seconds,
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.audio_file.exists():
        parser.error(f"Audio file not found: {args.audio_file}")
    return asyncio.run(
        run_demo(
            audio_file=args.audio_file,
            base_url=args.base_url,
            timeout_seconds=args.timeout_seconds,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
