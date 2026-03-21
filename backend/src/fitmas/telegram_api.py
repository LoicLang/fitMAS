from __future__ import annotations

import os

import httpx


def get_api_base() -> str:
    return os.getenv("FITMAS_API_URL", "http://127.0.0.1:8000")


async def api_get(path: str, *, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{get_api_base()}{path}", timeout=30)
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError:
            if attempt < retries - 1:
                import asyncio

                await asyncio.sleep(2)
            else:
                raise


async def api_post(path: str, data: dict, *, retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{get_api_base()}{path}", json=data, timeout=60)
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError:
            if attempt < retries - 1:
                import asyncio

                await asyncio.sleep(2)
            else:
                raise
