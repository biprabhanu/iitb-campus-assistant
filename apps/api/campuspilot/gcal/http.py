"""One place that turns httpx failures into ConnectorErrors (never echoing URLs or bodies)."""

from __future__ import annotations

import httpx

from campuspilot.connectors.errors import ConnectorError

TIMEOUT = httpx.Timeout(15.0)


async def send(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            return await client.request(method, url, **kwargs)
    except httpx.TimeoutException:
        raise ConnectorError("timeout", "Google took too long to answer. Try again.") from None
    except httpx.HTTPError:
        raise ConnectorError(
            "unreachable", "Could not reach Google. Check your internet connection."
        ) from None


def json_body(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
