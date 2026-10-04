"""
HermesProvider — ModelProvider implementation for the Hermes Agent running
inside the NemoClaw/OpenShell "orion" sandbox.

Communication path:
  Orion (host Python)
    └── HTTP POST http://127.0.0.1:8642/v1/chat/completions
          Bearer: <hermes_gateway_token>
            └── [openshell forward service tunnel over gRPC]
                  └── sandbox:8642  (Hermes Agent OpenAI-compatible API)

The token is received via dependency injection (Settings.hermes_gateway_token),
loaded from the .env file at startup. It is NEVER:
  - printed or logged
  - included in error messages
  - written to the audit log
  - returned in API responses

The provider communicates exclusively through HTTP — no subprocess, no shell,
no NemoClaw/OpenShell CLI invocation.
"""
from typing import Any

import httpx

from ..config import Settings
from .base import ModelProvider

# The exact model name Hermes exposes on its /v1/models endpoint.
_HERMES_MODEL = "hermes-agent"

# Health endpoint does not require authentication — safe for startup probing.
_HEALTH_PATH = "/health"


class HermesProvider(ModelProvider):
    """
    ModelProvider that delegates to the local Hermes Agent via its
    OpenAI-compatible REST API, tunnelled through the OpenShell gateway.

    Parameters
    ----------
    settings:
        Application settings. ``settings.hermes_gateway_token`` is used as
        the Bearer token. ``settings.hermes_base_url`` and
        ``settings.hermes_model`` are also respected so they can be overridden
        without code changes.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------------
    # Health probe (no auth required — safe for startup / liveness checks)
    # ------------------------------------------------------------------

    async def health(self) -> dict[str, Any]:
        """
        Probe the Hermes /v1/health endpoint.

        Returns the parsed JSON body on success; raises ``httpx.HTTPError``
        on transport or HTTP-level failure.
        """
        url = f"{self.settings.hermes_base_url.rstrip('/')}{_HEALTH_PATH}"
        timeout = httpx.Timeout(self.settings.model_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # ModelProvider interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 800,
    ) -> dict[str, Any]:
        """
        Send a chat-completion request to the Hermes Agent.

        Raises
        ------
        ValueError
            If the gateway token has not been configured.
        httpx.HTTPStatusError
            If Hermes returns a non-2xx response (propagated to caller).
        """
        token = self.settings.hermes_gateway_token

        if not token:
            raise ValueError(
                "Hermes gateway token is not configured. "
                "Set HERMES_GATEWAY_TOKEN in .env "
                "(obtain with: nemoclaw orion gateway-token --quiet)."
            )

        url = f"{self.settings.hermes_base_url.rstrip('/')}/chat/completions"

        headers = {
            # Token is passed only in this header; never logged or surfaced.
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.settings.hermes_model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        timeout = httpx.Timeout(self.settings.model_timeout_seconds)

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload,
            )

        # Raises httpx.HTTPStatusError on 4xx / 5xx.
        # The exception message from httpx does NOT include request headers,
        # so the Bearer token is not leaked through the exception chain.
        response.raise_for_status()
        return response.json()
