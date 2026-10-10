from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from services.mitigation.app.webhook_client import StepUpWebhookClient


def test_trigger_step_up_returns_true_on_200():
    with patch("services.mitigation.app.webhook_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        client = StepUpWebhookClient("http://idp.internal")
        assert client.trigger_step_up("user1", "session1", "high fused score") is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "http://idp.internal/step-up"
        assert kwargs["json"]["user_id"] == "user1"


def test_trigger_step_up_returns_false_on_non_200():
    with patch("services.mitigation.app.webhook_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=503)
        client = StepUpWebhookClient("http://idp.internal")
        assert client.trigger_step_up("user1", "session1", "reason") is False


def test_trigger_step_up_returns_false_never_raises_on_network_error():
    with patch("services.mitigation.app.webhook_client.httpx.post") as mock_post:
        mock_post.side_effect = httpx.ConnectTimeout("boom")
        client = StepUpWebhookClient("http://idp.internal")
        assert client.trigger_step_up("user1", "session1", "reason") is False


def test_trigger_alt_factor_hits_the_correct_path():
    with patch("services.mitigation.app.webhook_client.httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        client = StepUpWebhookClient("http://idp.internal/")  # trailing slash handled
        client.trigger_alt_factor("user1", "session1", "escalated")
        args, _ = mock_post.call_args
        assert args[0] == "http://idp.internal/alt-factor"
