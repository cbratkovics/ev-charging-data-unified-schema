"""Shared fixtures. Everything runs offline: the landed fixture under tests/fixtures/ is the
only input (it is hand-built and labelled as such in tests/fixtures/README.md)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ev_charging_data_unified_schema.config import FIXTURES_DIR


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def raw_frame() -> pd.DataFrame:
    """A small raw frame with mixed types, nulls and a duplicate row, as a source parser
    would hand it over before landing."""
    return pd.DataFrame(
        {
            "Station Name": ["A 1", "A 1", "B 2", None],
            "Start Date": ["2020-01-01 08:00", "2020-01-01 08:00", "01/02/2020 09:30", "x"],
            "Energy (kWh)": [1.5, 1.5, None, 0],
            "Port": [1, 1, 2, 2],
        }
    )


class StubResponse:
    """The slice of ``requests.Response`` the fetcher uses, as a context manager."""

    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    def __enter__(self) -> StubResponse:
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def iter_content(self, chunk: int):
        for i in range(0, len(self._body), chunk):
            yield self._body[i : i + chunk]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


class StubSession:
    """Answers every GET with the same response and records the calls."""

    def __init__(self, response: StubResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs) -> StubResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


@pytest.fixture
def stub_http(monkeypatch):
    """``stub_http(status, body, headers)`` returns a stub session answering every request the
    same way and installs it as ``requests.Session`` for code that builds its own."""
    from ev_charging_data_unified_schema import acquire

    def serve(status: int, body: bytes = b"", headers: dict | None = None) -> StubSession:
        sess = StubSession(StubResponse(status, body, headers))
        monkeypatch.setattr(acquire.requests, "Session", lambda: sess)
        return sess

    return serve
