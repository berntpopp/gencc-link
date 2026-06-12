"""Tests for configuration models (gencc_link.config)."""

from __future__ import annotations

from pathlib import Path

from gencc_link.config import (
    GenCCDataConfigModel,
    ServerSettings,
    get_data_config,
)


class TestServerSettings:
    def test_defaults(self) -> None:
        s = ServerSettings(_env_file=None)
        assert s.host == "127.0.0.1"
        assert s.port == 8000
        assert s.transport == "unified"
        assert s.mcp_path == "/mcp"
        assert s.log_level == "INFO"
        assert isinstance(s.data, GenCCDataConfigModel)

    def test_mcp_path_leading_slash_normalization(self) -> None:
        s = ServerSettings(_env_file=None, mcp_path="custom")
        assert s.mcp_path == "/custom"

    def test_mcp_path_already_slashed(self) -> None:
        s = ServerSettings(_env_file=None, mcp_path="/already")
        assert s.mcp_path == "/already"

    def test_cors_origins_from_comma_string(self) -> None:
        s = ServerSettings(_env_file=None, cors_origins="http://a.com, http://b.com ,")
        assert s.cors_origins == ["http://a.com", "http://b.com"]

    def test_cors_origins_from_list(self) -> None:
        s = ServerSettings(_env_file=None, cors_origins=["http://x"])
        assert s.cors_origins == ["http://x"]

    def test_cors_origins_empty(self) -> None:
        s = ServerSettings(_env_file=None, cors_origins="")
        assert s.cors_origins == []

    def test_env_prefix(self, monkeypatch) -> None:
        monkeypatch.setenv("GENCC_LINK_PORT", "9999")
        s = ServerSettings(_env_file=None)
        assert s.port == 9999

    def test_nested_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GENCC_LINK_DATA__DB_FILENAME", "custom.sqlite")
        s = ServerSettings(_env_file=None)
        assert s.data.db_filename == "custom.sqlite"


class TestGenCCDataConfigModel:
    def test_db_path(self) -> None:
        base = Path("/var/data/gencc-data")
        cfg = GenCCDataConfigModel(data_dir=base, db_filename="db.sqlite")
        assert cfg.db_path == base / "db.sqlite"

    def test_data_dir_expanduser(self) -> None:
        cfg = GenCCDataConfigModel(data_dir=Path("~/gencc"))
        assert "~" not in str(cfg.data_dir)

    def test_defaults(self) -> None:
        cfg = GenCCDataConfigModel()
        assert cfg.source_format == "new"
        assert cfg.db_filename == "gencc.sqlite"
        assert cfg.auto_bootstrap is True
        assert cfg.cache_size == 512


class TestGetDataConfig:
    def test_returns_data_config(self) -> None:
        cfg = get_data_config()
        assert isinstance(cfg, GenCCDataConfigModel)
