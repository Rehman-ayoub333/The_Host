import asyncio
import sqlite3

import httpx

import main


def test_records_failure_returns_http_error(monkeypatch):
    def fail_to_read_records(limit):
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(main.data, "get_recent_log", fail_to_read_records)

    async def get_records():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/records")

    response = asyncio.run(get_records())

    assert response.status_code == 503
    assert response.json() == {"detail": "Recent records are unavailable."}
