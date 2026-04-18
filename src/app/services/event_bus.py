from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar, cast


class Event(Protocol):
    type: str


EventT = TypeVar("EventT", bound=Event)
EventHandler = Callable[[EventT], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler[Any]]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler[Any]) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: EventT) -> None:
        handlers = list(self._handlers.get(event.type, ()))
        for handler in handlers:
            await cast(EventHandler[EventT], handler)(event)
