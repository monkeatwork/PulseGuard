"""Fires the step-up / alternate-factor webhook to the identity provider
(CLAUDE.md, L5: "mitigation controller ... force step-up webhook").
"""

from __future__ import annotations

import httpx


class StepUpWebhookClient:
    def __init__(self, base_url: str, timeout_seconds: float = 5.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def trigger_step_up(self, user_id: str, session_id: str, reason: str) -> bool:
        """Returns True if the IdP accepted the step-up request. Never
        raises: a webhook failure is treated as "not yet confirmed," which
        the caller can retry or treat conservatively -- it never escalates
        to a lockout on its own (see controller.py's anti-DoS invariant)."""
        return self._post("/step-up", user_id, session_id, reason)

    def trigger_alt_factor(self, user_id: str, session_id: str, reason: str) -> bool:
        return self._post("/alt-factor", user_id, session_id, reason)

    def _post(self, path: str, user_id: str, session_id: str, reason: str) -> bool:
        try:
            resp = httpx.post(
                f"{self._base_url}{path}",
                json={"user_id": user_id, "session_id": session_id, "reason": reason},
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
