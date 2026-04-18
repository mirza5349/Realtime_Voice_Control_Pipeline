from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from app.models.metrics import (
    RequestStageTimings,
    RequestTrace,
    RequestTraceStatus,
    RuntimeErrorInfo,
    StageTiming,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TraceStage(str, Enum):
    TRANSCRIPTION = "transcription"
    LLM = "llm"
    EXECUTION = "execution"
    TTS = "tts"


@dataclass(slots=True)
class TraceStageState:
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None

    def start(self, timestamp: datetime) -> None:
        self.started_at = timestamp
        self.completed_at = None
        self.duration_ms = None

    def complete(self, timestamp: datetime, duration_ms: int | None = None) -> None:
        if self.started_at is None:
            self.started_at = timestamp
        self.completed_at = timestamp
        if duration_ms is None and self.started_at is not None:
            duration_ms = max(0, int((timestamp - self.started_at).total_seconds() * 1000))
        self.duration_ms = duration_ms

    def to_model(self) -> StageTiming | None:
        if self.started_at is None and self.completed_at is None and self.duration_ms is None:
            return None
        return StageTiming(
            started_at=self.started_at,
            completed_at=self.completed_at,
            duration_ms=self.duration_ms,
        )


@dataclass(slots=True)
class RequestTraceState:
    session_id: UUID
    request_id: UUID
    started_at: datetime
    completed_at: datetime | None = None
    status: RequestTraceStatus = RequestTraceStatus.IN_PROGRESS
    transcription: TraceStageState = field(default_factory=TraceStageState)
    llm: TraceStageState = field(default_factory=TraceStageState)
    execution: TraceStageState = field(default_factory=TraceStageState)
    tts: TraceStageState = field(default_factory=TraceStageState)
    end_to_end_duration_ms: int | None = None
    last_error: RuntimeErrorInfo | None = None

    def start_stage(self, stage: TraceStage, timestamp: datetime | None = None) -> None:
        self._stage_for(stage).start(timestamp or utc_now())

    def complete_stage(
        self,
        stage: TraceStage,
        duration_ms: int | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        self._stage_for(stage).complete(timestamp or utc_now(), duration_ms=duration_ms)

    def mark_end_to_end(self, timestamp: datetime | None = None) -> None:
        completed_at = timestamp or utc_now()
        self.end_to_end_duration_ms = max(
            0,
            int((completed_at - self.started_at).total_seconds() * 1000),
        )

    def record_error(self, error: RuntimeErrorInfo) -> None:
        self.last_error = error

    def complete(self, timestamp: datetime | None = None) -> None:
        self.completed_at = timestamp or utc_now()
        self.status = RequestTraceStatus.COMPLETED

    def fail(self, error: RuntimeErrorInfo, timestamp: datetime | None = None) -> None:
        self.record_error(error)
        self.completed_at = timestamp or error.timestamp
        self.status = RequestTraceStatus.FAILED

    def to_model(self) -> RequestTrace:
        stage_timings = RequestStageTimings(
            transcription=self.transcription.to_model(),
            llm=self.llm.to_model(),
            execution=self.execution.to_model(),
            tts=self.tts.to_model(),
        )
        return RequestTrace(
            request_id=self.request_id,
            started_at=self.started_at,
            completed_at=self.completed_at,
            status=self.status,
            transcription_duration_ms=stage_timings.transcription.duration_ms
            if stage_timings.transcription is not None
            else None,
            llm_duration_ms=stage_timings.llm.duration_ms
            if stage_timings.llm is not None
            else None,
            execution_duration_ms=stage_timings.execution.duration_ms
            if stage_timings.execution is not None
            else None,
            tts_duration_ms=stage_timings.tts.duration_ms
            if stage_timings.tts is not None
            else None,
            end_to_end_duration_ms=self.end_to_end_duration_ms,
            stage_timings=stage_timings,
            last_error=self.last_error,
        )

    def _stage_for(self, stage: TraceStage) -> TraceStageState:
        if stage == TraceStage.TRANSCRIPTION:
            return self.transcription
        if stage == TraceStage.LLM:
            return self.llm
        if stage == TraceStage.EXECUTION:
            return self.execution
        if stage == TraceStage.TTS:
            return self.tts
        raise ValueError(f"Unsupported trace stage: {stage}")
