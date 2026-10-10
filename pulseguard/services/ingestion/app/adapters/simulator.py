"""Interactive simulator adapter (L1): a live push-fatigue attack against a
human -- the person at the dashboard plays the victim.

An attacker loop sends push prompts at a fixed pacing; the victim answers on
a simulated phone in the dashboard, and the REAL reaction time (prompt shown
-> button pressed) becomes `decision_latency_ms`. Those events go through
the same Kafka -> feature engine -> detection -> mitigation pipeline as
everything else. Nothing is scripted downstream: if the victim's latency
collapses into reflexive taps, the detector sees it, the controller forces a
step-up through the mock IdP, and the attacker's pushes stop being honoured.

`mode="benign"` is the negative control: the user starts their own logins
from their own device, and nothing should fire.
"""

from __future__ import annotations

import queue
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterator, Literal, Optional

from pulseguard_common.event_schema import Decision, EventType, Geo, PulseGuardEvent
from services.ingestion.app.adapters.base import TelemetryAdapter

Mode = Literal["attack", "benign"]

VICTIM_DEVICE = "victim-iphone-15"
VICTIM_IP = "10.20.0.5"
VICTIM_UA = "Authenticator/7.2 (iOS 18)"
ATTACKER_DEVICE = "unknown-device-7f3a"
ATTACKER_UA = "python-requests/2.32 (credential replay)"
PROMPT_TIMEOUT_SECONDS = 30.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PendingPrompt:
    prompt_id: str
    ts: datetime
    origin_ip: str
    origin_device: str


@dataclass
class SimulatorSession(TelemetryAdapter):
    """One victim. `events()` drains a queue fed by the attacker loop and
    the victim's responses, so the session plugs into TelemetryAdapter.run
    like any other source."""

    mode: Mode = "attack"
    pacing_seconds: float = 6.0
    max_prompts: int = 20
    country: str = "IN"
    user_id: str = field(default_factory=lambda: f"victim-{uuid.uuid4().hex[:6]}")
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    attacker_ip: str = field(default_factory=lambda: f"198.51.100.{random.randint(2, 250)}")
    is_push_blocked: Callable[[str], bool] = lambda user_id: False

    name = "simulator"

    def __post_init__(self):
        self.sim_id = uuid.uuid4().hex[:12]
        self.status = "running"  # running | compromised | protected | finished | stopped
        self.pending: Optional[PendingPrompt] = None
        self.prompts_sent = 0
        self.history: list[dict] = []
        self.messages: list[dict] = []
        self.started = _now()
        self._queue: "queue.Queue[Optional[PulseGuardEvent]]" = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()

    # --- TelemetryAdapter -------------------------------------------------
    def events(self) -> Iterator[PulseGuardEvent]:
        while True:
            event = self._queue.get()
            if event is None:
                return
            yield event

    # --- event construction ----------------------------------------------
    def _event(self, event_type: EventType, ts: datetime, ip: str, device: str, ua: str,
               decision: Optional[Decision] = None, latency_ms: Optional[int] = None) -> PulseGuardEvent:
        return PulseGuardEvent(
            event_id=uuid.uuid4(), user_id=self.user_id, ts=ts, event_type=event_type, decision=decision,
            decision_latency_ms=latency_ms, src_ip=ip, geo=Geo(country=self.country), device_id=device,
            user_agent=ua, session_id=self.session_id, ingest_ts=_now(),
        )

    def _note(self, kind: str, text: str) -> None:
        self.messages.append({"ts": _now().isoformat(), "kind": kind, "text": text})

    def send_prompt(self, origin: str = "attacker") -> Optional[PendingPrompt]:
        with self._lock:
            if self.pending is not None or self.status != "running":
                return None
            ip, device = (self.attacker_ip, ATTACKER_DEVICE) if origin == "attacker" else (VICTIM_IP, VICTIM_DEVICE)
            ua = ATTACKER_UA if origin == "attacker" else VICTIM_UA
            ts = _now()
            self.pending = PendingPrompt(str(uuid.uuid4()), ts, ip, device)
            self.prompts_sent += 1
            self._queue.put(self._event(EventType.MFA_PROMPT, ts, ip, device, ua))
            return self.pending

    def respond(self, decision: str) -> dict:
        with self._lock:
            if self.pending is None:
                raise LookupError("no prompt is waiting for an answer")
            prompt = self.pending
            self.pending = None
            ts = _now()
            latency_ms = max(0, int((ts - prompt.ts).total_seconds() * 1000))
            self._queue.put(self._event(EventType.MFA_DECISION, ts, VICTIM_IP, VICTIM_DEVICE, VICTIM_UA,
                                        Decision(decision), latency_ms))
            entry = {"ts": ts.isoformat(), "decision": decision, "latency_ms": latency_ms,
                     "origin": "attacker" if prompt.origin_device == ATTACKER_DEVICE else "you"}
            self.history.append(entry)
            return entry

    def _expire_stale_prompt(self) -> None:
        with self._lock:
            if self.pending and (_now() - self.pending.ts).total_seconds() > PROMPT_TIMEOUT_SECONDS:
                ts = _now()
                self._queue.put(self._event(EventType.MFA_DECISION, ts, VICTIM_IP, VICTIM_DEVICE, VICTIM_UA,
                                            Decision.TIMEOUT, None))
                self.history.append({"ts": ts.isoformat(), "decision": "timeout", "latency_ms": None, "origin": "attacker"})
                self.pending = None

    # --- attacker loop -----------------------------------------------------
    def attacker_loop(self) -> None:
        self._note("info", f"Attacker at {self.attacker_ip} has the password and starts pushing prompts.")
        while not self._stop.is_set() and self.status == "running":
            self._expire_stale_prompt()
            if self.is_push_blocked(self.user_id):
                self.status = "protected"
                self._note("protected", "PulseGuard forced a step-up challenge: blind push approvals are suspended for this account.")
                break
            if self.prompts_sent >= self.max_prompts and self.pending is None:
                self.status = "finished"
                self._note("info", "The attacker gave up.")
                break
            if self.pending is None:
                self.send_prompt("attacker")
            self._stop.wait(self.pacing_seconds)
        self.close()

    def stop(self) -> None:
        self._stop.set()
        if self.status == "running":
            self.status = "stopped"
        self.close()

    def close(self) -> None:
        self._queue.put(None)

    def snapshot(self) -> dict:
        p = self.pending
        return {
            "sim_id": self.sim_id, "user_id": self.user_id, "mode": self.mode, "status": self.status,
            "pacing_seconds": self.pacing_seconds, "prompts_sent": self.prompts_sent, "max_prompts": self.max_prompts,
            "pending": None if p is None else {"prompt_id": p.prompt_id, "ts": p.ts.isoformat(),
                                               "origin_ip": p.origin_ip, "origin_device": p.origin_device,
                                               "country": self.country},
            "history": list(self.history), "messages": list(self.messages), "started": self.started.isoformat(),
        }


def wait_for(predicate: Callable[[], bool], timeout: float, interval: float = 0.15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
