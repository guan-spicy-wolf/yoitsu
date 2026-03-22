"""Thin httpx wrappers for pasloe and trenni HTTP APIs."""
from __future__ import annotations

from typing import Any

import httpx


class PasloeClient:
    def __init__(self, url: str, api_key: str) -> None:
        self._url = url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._http = httpx.AsyncClient(
            base_url=self._url, headers=self._headers, timeout=10.0
        )

    async def check_ready(self) -> bool:
        """Return True if pasloe responds with HTTP 200."""
        try:
            r = await self._http.get("/events", params={"limit": "1"})
            return r.status_code == 200
        except Exception:
            return False

    async def get_stats(self) -> dict[str, Any] | None:
        """Return pasloe stats (total_events + by_type) or None on error."""
        try:
            r = await self._http.get("/events/stats")
            r.raise_for_status()
            raw = r.json()
            return {"total_events": raw["total_events"], "by_type": raw["by_type"]}
        except Exception:
            return None

    async def post_event(self, *, type_: str, data: dict) -> str | None:
        """POST a single event; return event id or None on failure."""
        try:
            r = await self._http.post("/events", json={
                "source_id": "yoitsu-cli",
                "type": type_,
                "data": data,
            })
            r.raise_for_status()
            return r.json().get("id")
        except Exception:
            return None

    async def aclose(self) -> None:
        await self._http.aclose()


class TrenniClient:
    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._url, timeout=10.0)

    async def check_ready(self) -> bool:
        """Return True if trenni control API responds with HTTP 200."""
        try:
            r = await self._http.get("/control/status")
            return r.status_code == 200
        except Exception:
            return False

    async def get_status(self) -> dict[str, Any] | None:
        """Return trenni status dict or None on error."""
        try:
            r = await self._http.get("/control/status")
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def post_control(self, endpoint: str) -> str | None:
        """POST to /control/<endpoint>. Returns None on success, error string on failure."""
        try:
            r = await self._http.post(f"/control/{endpoint}")
            if r.status_code == 200:
                return None
            return f"trenni returned {r.status_code}: {r.text}"
        except httpx.ConnectError:
            return "trenni unreachable"
        except Exception as exc:
            return str(exc)

    async def aclose(self) -> None:
        await self._http.aclose()
