"""Init-sidecar restore of the pinned data release + Runtime Data Identity v1."""

from __future__ import annotations

import gzip
import hashlib
import os
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gencc_link.config import GenCCDataConfigModel, ImmutableDataRequirement
from gencc_link.exceptions import DataUnavailableError
from gencc_link.immutable_data import materialize_immutable_data, verify_runtime_identity
from gencc_link.ingest.builder import build_database

SAMPLE_TSV = Path(__file__).resolve().parent / "fixtures" / "sample.tsv"
TAG = "data-gencc-0123456789abcdef"
URL = f"https://github.com/berntpopp/gencc-link/releases/download/{TAG}/gencc.sqlite.gz"
ASSET_HOST = "https://release-assets.githubusercontent.com/asset/1"


def _release(tmp_path: Path) -> tuple[ImmutableDataRequirement, bytes]:
    cfg = GenCCDataConfigModel(data_dir=tmp_path / "build", db_filename="gencc.sqlite")
    build_database(cfg, tsv_path=SAMPLE_TSV, etag=None, last_modified=None, build_utc="x")
    raw = cfg.db_path.read_bytes()
    bundle = gzip.compress(raw, mtime=0)
    requirement = ImmutableDataRequirement(
        reference_root=tmp_path / "reference",
        release_tag=TAG,
        bundle_url=URL,
        compressed_sha256=hashlib.sha256(bundle).hexdigest(),
        expanded_sha256=hashlib.sha256(raw).hexdigest(),
    )
    return requirement, bundle


def _serve(bundle: bytes) -> None:
    respx.get(URL).mock(return_value=httpx.Response(302, headers={"location": ASSET_HOST}))
    respx.get(ASSET_HOST).mock(return_value=httpx.Response(200, content=bundle))


@respx.mock
def test_materialize_selects_verified_snapshot_and_runtime_proves_it(tmp_path: Path) -> None:
    requirement, bundle = _release(tmp_path)
    _serve(bundle)

    selected = materialize_immutable_data(requirement)

    root = tmp_path / "reference"
    assert selected == root / requirement.compressed_sha256 / "gencc.sqlite"
    assert (root / "current").resolve() == selected.parent
    assert selected.stat().st_mode & 0o777 == 0o444
    assert verify_runtime_identity(root / "current" / "gencc.sqlite", requirement) == {
        "release_tag": TAG,
        "digest": f"sha256:{requirement.compressed_sha256}",
    }
    # A restart re-verifies the existing snapshot without downloading again.
    respx.reset()
    assert materialize_immutable_data(requirement) == selected
    assert not respx.calls


@respx.mock
def test_digest_mismatch_never_replaces_current(tmp_path: Path) -> None:
    requirement, bundle = _release(tmp_path)
    _serve(bundle)
    good = materialize_immutable_data(requirement)
    wrong = requirement.model_copy(update={"compressed_sha256": "f" * 64})

    with pytest.raises(DataUnavailableError, match="digest"):
        materialize_immutable_data(wrong)

    assert (tmp_path / "reference" / "current").resolve() == good.parent
    assert not list((tmp_path / "reference").glob(".*staging*"))


@respx.mock
def test_redirect_off_github_is_refused(tmp_path: Path) -> None:
    requirement, _bundle = _release(tmp_path)
    respx.get(URL).mock(
        return_value=httpx.Response(302, headers={"location": "https://evil.example/x"})
    )

    with pytest.raises(DataUnavailableError, match="allowed hosts"):
        materialize_immutable_data(requirement)


def test_runtime_identity_rejects_a_local_build(tmp_path: Path) -> None:
    requirement, _bundle = _release(tmp_path)

    with pytest.raises(DataUnavailableError):
        verify_runtime_identity(tmp_path / "build" / "gencc.sqlite", requirement)


@respx.mock
def test_runtime_identity_rejects_tampered_bytes(tmp_path: Path) -> None:
    requirement, bundle = _release(tmp_path)
    _serve(bundle)
    selected = materialize_immutable_data(requirement)
    selected.chmod(0o644)
    with selected.open("ab") as handle:
        handle.write(b"x")

    with pytest.raises(DataUnavailableError, match="expanded digest"):
        verify_runtime_identity(selected, requirement)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("release_tag", "latest"),
        ("compressed_sha256", "bad"),
        ("bundle_url", "https://example.org/download/data-gencc-0123456789abcdef/gencc.sqlite.gz"),
        ("bundle_url", URL.replace(TAG, "data-gencc-ffffffffffffffff")),
    ],
)
def test_requirement_rejects_mutable_or_mismatched_pins(field: str, value: str) -> None:
    values = {
        "release_tag": TAG,
        "bundle_url": URL,
        "compressed_sha256": "a" * 64,
        "expanded_sha256": "b" * 64,
        field: value,
    }
    with pytest.raises(ValidationError):
        ImmutableDataRequirement(**values)


@respx.mock
def test_health_reports_runtime_v1_identity_only_for_the_restored_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gencc_link.app as app_mod
    import gencc_link.config as config_mod

    requirement, bundle = _release(tmp_path)
    _serve(bundle)
    materialize_immutable_data(requirement)
    monkeypatch.setattr(app_mod.settings, "immutable_data", requirement)
    served = GenCCDataConfigModel(
        data_dir=tmp_path / "reference", db_filename="current/gencc.sqlite"
    )
    monkeypatch.setattr(config_mod.settings, "data", served)

    body = TestClient(app_mod.create_app()).get("/health").json()
    identity = {"release_tag": TAG, "digest": f"sha256:{requirement.compressed_sha256}"}
    assert body["release_identity"] == {
        "schema_version": 1,
        "data_identity": {"expected": identity, "actual": identity},
    }

    local = GenCCDataConfigModel(data_dir=tmp_path / "build", db_filename="gencc.sqlite")
    monkeypatch.setattr(config_mod.settings, "data", local)
    assert "release_identity" not in TestClient(app_mod.create_app()).get("/health").json()


@respx.mock
def test_runtime_identity_hashes_once_until_the_served_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gencc_link.immutable_data as immutable_data

    requirement, bundle = _release(tmp_path)
    _serve(bundle)
    selected = materialize_immutable_data(requirement)
    hashed: list[Path] = []
    real_sha256 = immutable_data._sha256
    monkeypatch.setattr(
        immutable_data, "_sha256", lambda path: hashed.append(path) or real_sha256(path)
    )

    verify_runtime_identity(selected, requirement)
    verify_runtime_identity(selected, requirement)
    assert len(hashed) == 1  # a repeated /health probe does not re-read the database

    stat = selected.stat()
    os.utime(selected, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
    verify_runtime_identity(selected, requirement)
    assert len(hashed) == 2  # a changed stat (mtime/size/inode) invalidates the cache
