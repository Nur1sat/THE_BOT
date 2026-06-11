from __future__ import annotations

import socket

from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver
from aiogram.client.session.aiohttp import AiohttpSession

from xau_signal_bot.bot.config import Settings


class TelegramFallbackResolver(AbstractResolver):
    def __init__(self, telegram_ips: list[str]) -> None:
        self._default = DefaultResolver()
        self._telegram_ips = telegram_ips

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[dict]:
        try:
            return await self._default.resolve(host, port, family)
        except OSError:
            if host != "api.telegram.org" or not self._telegram_ips:
                raise
            return [
                {
                    "hostname": host,
                    "host": ip,
                    "port": port,
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": socket.AI_NUMERICHOST,
                }
                for ip in self._telegram_ips
            ]

    async def close(self) -> None:
        await self._default.close()


class TelegramAiohttpSession(AiohttpSession):
    def __init__(self, telegram_ips: list[str]) -> None:
        super().__init__()
        self._connector_init["resolver"] = TelegramFallbackResolver(telegram_ips)
        self._connector_init["ttl_dns_cache"] = 300


def build_telegram_session(settings: Settings) -> AiohttpSession:
    return TelegramAiohttpSession(settings.telegram_api_ips)
