"""Tests for the FastAPI application factory (gencc_link.app)."""

from __future__ import annotations

import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from gencc_link.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["transport"] == "streamable-http-stateless"
    assert body["data"]["status"] in {"ready", "unavailable"}


def test_api_health_alias(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_root(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "GenCC-Link"
    assert body["mcp_endpoint"] == "/mcp"
    assert body["docs"] == "/docs"


def test_create_app_returns_fastapi() -> None:
    from fastapi import FastAPI

    assert isinstance(create_app(), FastAPI)


def _cors_middleware(app: object) -> object:
    from starlette.middleware.cors import CORSMiddleware

    for mw in app.user_middleware:  # type: ignore[attr-defined]
        if mw.cls is CORSMiddleware:
            return mw
    raise AssertionError("CORSMiddleware is not installed")


def test_cors_credentials_disabled(client: TestClient) -> None:
    """Unauthenticated backend: CORS credentials are forced off, and /health still serves."""
    mw = _cors_middleware(create_app())
    assert mw.kwargs["allow_credentials"] is False  # type: ignore[attr-defined]

    resp = client.get("/health")
    assert resp.status_code == 200


def test_cors_methods_preserved() -> None:
    """The existing method list must be preserved (GET /health and root are served)."""
    mw = _cors_middleware(create_app())
    assert mw.kwargs["allow_methods"] == ["GET", "POST", "OPTIONS"]  # type: ignore[attr-defined]


def test_cors_wildcard_with_credentials_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup guard: allow_credentials=True combined with a wildcard origin fails loud."""
    from gencc_link import app as app_module

    monkeypatch.setattr(app_module.settings, "cors_allow_credentials", True)
    monkeypatch.setattr(app_module.settings, "cors_origins", ["*"])
    with pytest.raises(RuntimeError):
        app_module.create_app()
