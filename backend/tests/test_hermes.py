"""
Unit tests for HermesProvider.

All HTTP calls are intercepted — no live Hermes gateway is required.
The gateway token is injected as a mock value; the real token never appears here.

Tests:
  1  Correct URL constructed from hermes_base_url setting.
  2  Correct model name sent in payload.
  3  Authorization header contains the Bearer token.
  4  Messages list forwarded unchanged in payload.
  5  max_tokens forwarded correctly.
  6  Successful JSON response is returned unchanged.
  7  HTTP 4xx/5xx errors propagate as httpx.HTTPStatusError.
  8  Gateway token never appears in raised exceptions or error strings.
  9  Missing token raises ValueError before any HTTP call.
 10  health() hits /health without auth and returns parsed JSON.
 11  Existing Nebius provider is unaffected (smoke test).
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

from app.providers.hermes import HermesProvider
from app.providers.nebius import NebiusProvider


def _hermes_settings(token: str = "mock-hermes-token-xyz") -> MagicMock:
    """Build a mock Settings object for HermesProvider tests."""
    s = MagicMock()
    s.hermes_gateway_token = token
    s.hermes_base_url = "http://127.0.0.1:8642/v1"
    s.hermes_model = "hermes-agent"
    s.model_timeout_seconds = 10.0
    return s


def _nebius_settings() -> MagicMock:
    """Build a mock Settings object for the Nebius regression smoke test."""
    s = MagicMock()
    s.nebius_api_key = "mock-nebius-key"
    s.nebius_base_url = "https://api.tokenfactory.nebius.com/v1"
    s.nebius_model = "nvidia/nemotron-3-super-120b-a12b"
    s.model_timeout_seconds = 10.0
    return s


class TestHermesProvider(unittest.IsolatedAsyncioTestCase):
    """
    IsolatedAsyncioTestCase handles async test execution natively.
    HTTP interactions are intercepted via httpx.AsyncClient method patches.
    """

    def _make_provider(self, token: str = "mock-hermes-token-xyz") -> HermesProvider:
        return HermesProvider(_hermes_settings(token))

    async def test_1_correct_url(self):
        """Test 1: target URL is http://127.0.0.1:8642/v1/chat/completions."""
        provider = self._make_provider()
        captured = {}

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            captured["url"] = str(url)
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
            return resp

        with patch.object(httpx.AsyncClient, "post", fake_post):
            await provider.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(
            captured["url"],
            "http://127.0.0.1:8642/v1/chat/completions",
        )

    async def test_2_correct_model_name(self):
        """Test 2: payload contains model=hermes-agent."""
        provider = self._make_provider()
        captured = {}

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
            return resp

        with patch.object(httpx.AsyncClient, "post", fake_post):
            await provider.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(captured["json"]["model"], "hermes-agent")

    async def test_3_authorization_header(self):
        """Test 3: Authorization header contains the Bearer token."""
        token = "secret-mock-token-abc"
        provider = self._make_provider(token=token)
        captured = {}

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            captured["headers"] = headers
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
            return resp

        with patch.object(httpx.AsyncClient, "post", fake_post):
            await provider.chat([{"role": "user", "content": "hi"}])

        self.assertIn("Authorization", captured["headers"])
        self.assertEqual(captured["headers"]["Authorization"], f"Bearer {token}")

    async def test_4_messages_forwarded(self):
        """Test 4: messages list is forwarded unchanged in the payload."""
        provider = self._make_provider()
        msgs = [
            {"role": "system", "content": "You are Orion."},
            {"role": "user", "content": "hello"},
        ]
        captured = {}

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
            return resp

        with patch.object(httpx.AsyncClient, "post", fake_post):
            await provider.chat(msgs)

        self.assertEqual(captured["json"]["messages"], msgs)

    async def test_5_max_tokens_forwarded(self):
        """Test 5: max_tokens is forwarded correctly."""
        provider = self._make_provider()
        captured = {}

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
            return resp

        with patch.object(httpx.AsyncClient, "post", fake_post):
            await provider.chat([{"role": "user", "content": "hi"}], max_tokens=42)

        self.assertEqual(captured["json"]["max_tokens"], 42)

    async def test_6_successful_response_returned_unchanged(self):
        """Test 6: successful JSON response from Hermes is returned as-is."""
        expected = {
            "id": "chatcmpl-xyz",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "PONG"}, "finish_reason": "stop"}],
            "model": "hermes-agent",
        }
        provider = self._make_provider()

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = expected
            return resp

        with patch.object(httpx.AsyncClient, "post", fake_post):
            result = await provider.chat([{"role": "user", "content": "ping"}])

        self.assertEqual(result, expected)

    async def test_7_http_errors_propagate(self):
        """Test 7: HTTP 4xx/5xx errors propagate as httpx.HTTPStatusError."""
        provider = self._make_provider()

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            resp = MagicMock()
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                message="401 Unauthorized",
                request=MagicMock(),
                response=MagicMock(status_code=401),
            )
            return resp

        with patch.object(httpx.AsyncClient, "post", fake_post):
            with self.assertRaises(httpx.HTTPStatusError):
                await provider.chat([{"role": "user", "content": "hi"}])

    async def test_8_token_not_in_errors(self):
        """Test 8: the gateway token must not appear in any raised exception."""
        token = "super-secret-should-not-appear"
        provider = self._make_provider(token=token)

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            resp = MagicMock()
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                message="500 Internal Server Error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )
            return resp

        try:
            with patch.object(httpx.AsyncClient, "post", fake_post):
                await provider.chat([{"role": "user", "content": "hi"}])
        except httpx.HTTPStatusError as exc:
            self.assertNotIn(token, str(exc))
        except Exception as exc:
            self.assertNotIn(token, str(exc))

    async def test_9_missing_token_raises_value_error(self):
        """Test 9: missing/empty token raises ValueError before any HTTP call."""
        provider = self._make_provider(token="")
        call_count = 0

        async def fake_post(client_self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise AssertionError("HTTP call must not be made when token is missing")

        with patch.object(httpx.AsyncClient, "post", fake_post):
            with self.assertRaises(ValueError) as ctx:
                await provider.chat([{"role": "user", "content": "hi"}])

        self.assertEqual(call_count, 0)
        self.assertIn("HERMES_GATEWAY_TOKEN", str(ctx.exception))

    async def test_10_health_endpoint_no_auth(self):
        """Test 10: health() calls /health, not /chat/completions, with no auth."""
        provider = self._make_provider()
        captured = {}

        async def fake_get(client_self, url, **kw):
            captured["url"] = str(url)
            captured["kw"] = kw
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"status": "ok", "platform": "hermes-agent", "version": "0.20.6"}
            return resp

        with patch.object(httpx.AsyncClient, "get", fake_get):
            result = await provider.health()

        self.assertIn("/health", captured["url"])
        self.assertNotIn("/chat/completions", captured["url"])
        self.assertNotIn("Authorization", captured.get("kw", {}).get("headers", {}))
        self.assertEqual(result["status"], "ok")

    async def test_11_nebius_unaffected(self):
        """Test 11: NebiusProvider still works correctly after the changes."""
        settings = _nebius_settings()
        provider = NebiusProvider(settings)
        captured = {}

        async def fake_post(client_self, url, *, headers=None, json=None, **kw):
            captured["url"] = str(url)
            captured["headers"] = headers
            captured["json"] = json
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"choices": [{"message": {"content": "nebius ok"}}]}
            return resp

        with patch.object(httpx.AsyncClient, "post", fake_post):
            result = await provider.chat([{"role": "user", "content": "hello"}])

        self.assertIn("tokenfactory.nebius.com", captured["url"])
        self.assertIn("Bearer", captured["headers"]["Authorization"])
        self.assertEqual(result["choices"][0]["message"]["content"], "nebius ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)
