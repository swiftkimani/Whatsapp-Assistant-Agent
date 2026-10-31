"""The one place that talks to the WhatsApp bridge.

Two callers with different needs: FastAPI routes await it, while the agent runs
inside a threadpool and cannot. Both share the url, the shared token and the
same "the bridge is down" message, so there is one thing to change.
"""
import os

import httpx

UNREACHABLE = "Can't reach the WhatsApp bridge. Is it running?"


def _url(path: str) -> str:
    return f"{os.getenv('BRIDGE_API_URL', 'http://127.0.0.1:3001')}{path}"


def _headers() -> dict[str, str]:
    return {"x-bridge-token": os.getenv("BRIDGE_API_TOKEN", "")}


async def post(path: str, payload: dict, timeout: float) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(_url(path), json=payload, headers=_headers())


def post_sync(path: str, payload: dict, timeout: float) -> httpx.Response:
    """For code already off the event loop, such as the agent pipeline."""
    with httpx.Client(timeout=timeout) as client:
        return client.post(_url(path), json=payload, headers=_headers())
