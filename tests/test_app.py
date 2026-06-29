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
