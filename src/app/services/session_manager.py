from datetime import datetime, timezone
from threading import Lock
from uuid import UUID, uuid4

from app.models.session import CreateSessionRequest, Session, SessionStatus


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[UUID, Session] = {}
        self._lock = Lock()

    def create_session(self, request: CreateSessionRequest | None = None) -> Session:
        _ = request
        timestamp = datetime.now(timezone.utc)
        session = Session(
            session_id=uuid4(),
            status=SessionStatus.INITIALIZED,
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session.model_copy(deep=True)

    def get_session(self, session_id: UUID) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            return None
        return session.model_copy(deep=True)

    def list_sessions(self) -> list[Session]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [session.model_copy(deep=True) for session in sessions]

    def update_status(self, session_id: UUID, status: SessionStatus) -> Session | None:
        timestamp = datetime.now(timezone.utc)
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            updated_session = session.model_copy(
                update={
                    "status": status,
                    "updated_at": timestamp,
                }
            )
            self._sessions[session_id] = updated_session
        return updated_session.model_copy(deep=True)
