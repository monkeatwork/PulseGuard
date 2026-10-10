"""L1 telemetry adapter interface (REMEDIATION_TASK.md D1).

Every source of MFA telemetry -- a benchmark replay, the interactive
simulator, and (future work, not implemented) Entra ID sign-in logs, the Okta
System Log or the Duo Admin API -- is a TelemetryAdapter: something that
yields canonical PulseGuardEvents. The ingestion service does not care where
events come from; it runs an adapter and produces whatever it yields to
`pulseguard.events.raw`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Iterator, Optional, Protocol

from pulseguard_common.event_schema import PulseGuardEvent


class EventSink(Protocol):
    def produce(self, event: PulseGuardEvent) -> None: ...
    def flush(self, timeout: float = 10.0) -> int: ...


class TelemetryAdapter(ABC):
    """`events()` yields canonical events in the order they should be
    ingested; pacing (sleeping between events) is the adapter's concern."""

    name: str = "abstract"

    @abstractmethod
    def events(self) -> Iterator[PulseGuardEvent]: ...

    def run(
        self,
        sink: EventSink,
        on_event: Optional[Callable[[PulseGuardEvent], None]] = None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> int:
        count = 0
        for event in self.events():
            if should_stop():
                break
            sink.produce(event)
            count += 1
            if on_event is not None:
                on_event(event)
        sink.flush()
        return count
