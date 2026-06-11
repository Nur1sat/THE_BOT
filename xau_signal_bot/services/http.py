from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import requests


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; XauSignalBot/1.0; +https://example.local)",
    "Accept": "*/*",
}
FETCH_RETRIES = 2
FETCH_RETRY_SLEEP_SECONDS = 0.15
REQUESTS_FALLBACK_TIMEOUT_SECONDS = 4


async def fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    request_headers = {**DEFAULT_HEADERS, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(FETCH_RETRIES):
        try:
            async with session.get(url, headers=request_headers, params=params) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < FETCH_RETRIES - 1:
                await asyncio.sleep(FETCH_RETRY_SLEEP_SECONDS)
    if last_error:
        return await asyncio.to_thread(_fetch_json_with_requests, url, request_headers, params)
    raise RuntimeError("request failed")


async def fetch_text(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> str:
    request_headers = {**DEFAULT_HEADERS, **(headers or {})}
    last_error: Exception | None = None
    for attempt in range(FETCH_RETRIES):
        try:
            async with session.get(url, headers=request_headers, params=params) as response:
                response.raise_for_status()
                return await response.text()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < FETCH_RETRIES - 1:
                await asyncio.sleep(FETCH_RETRY_SLEEP_SECONDS)
    if last_error:
        return await asyncio.to_thread(_fetch_text_with_requests, url, request_headers, params)
    raise RuntimeError("request failed")


def _fetch_json_with_requests(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
) -> Any:
    response = requests.get(url, headers=headers, params=params, timeout=REQUESTS_FALLBACK_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _fetch_text_with_requests(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
) -> str:
    response = requests.get(url, headers=headers, params=params, timeout=REQUESTS_FALLBACK_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.text
