"""Tests for tools/build_manifest.py.

Builds a synthetic artifacts tree on a tmp_path, runs the manifest
builder, and asserts the resulting manifest is well-formed and
fwHash matches a hand-computed SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

# Importable as a script-style module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_manifest import build_manifest, main, read_flash_args  # noqa: E402


def _write_artifact_tree(root: Path) -> dict[str, bytes]:
    """Create a single (esp32s3, hello_publisher, serial) variant."""
    tx_dir = root / "esp32s3" / "hello_publisher" / "serial"
    tx_dir.mkdir(parents=True)
    files = {
        "bootloader.bin": b"\xaa" * 1024,
        "partition-table.bin": b"\xbb" * 2048,
        "firmware.bin": b"\xcc" * 4096,
    }
    for name, data in files.items():
        (tx_dir / name).write_bytes(data)
    (tx_dir / "flash_args").write_text(
        "--flash-mode dio --flash-freq 80m --flash-size 4MB\n"
        "0x0 bootloader.bin\n"
        "0x8000 partition-table.bin\n"
        "0x10000 firmware.bin\n"
    )
    return files


def test_read_flash_args(tmp_path: Path) -> None:
    (tmp_path / "flash_args").write_text(
        "--flash-mode dio\n"
        "0x0 bootloader.bin\n"
        "0x8000 part.bin\n"
        "0x10000 fw.bin\n"
    )
    pairs = read_flash_args(tmp_path / "flash_args")
    assert pairs == [("0x0", "bootloader.bin"), ("0x8000", "part.bin"), ("0x10000", "fw.bin")]


def test_read_flash_args_rejects_empty(tmp_path: Path) -> None:
    (tmp_path / "flash_args").write_text("--flash-mode dio\n")
    with pytest.raises(ValueError):
        read_flash_args(tmp_path / "flash_args")


def test_build_manifest_single_variant(tmp_path: Path) -> None:
    files = _write_artifact_tree(tmp_path)
    manifest = build_manifest(
        artifacts_root=tmp_path,
        release_tag="v0.2.0",
        commit_sha="abc1234",
        ci_run_url="https://example.test/run/1",
        generated_at="2026-05-13T00:00:00Z",
        url_base="https://example.test/dl",
    )
    assert manifest["wireVersion"] == 1
    assert manifest["releaseTag"] == "v0.2.0"
    assert len(manifest["variants"]) == 1
    v = manifest["variants"][0]
    assert v["board"] == "esp32s3"
    assert v["example"] == "hello_publisher"
    assert v["transport"] == "serial"
    assert len(v["files"]) == 3
    assert v["files"][0]["url"] == \
        "https://example.test/dl/esp32s3/hello_publisher/serial/bootloader.bin"
    assert v["files"][0]["offset"] == "0x0"
    # fwHash matches SHA-256 of the concatenated bins in flash order.
    h = hashlib.sha256()
    for name in ("bootloader.bin", "partition-table.bin", "firmware.bin"):
        h.update(files[name])
    assert v["fwHash"] == h.hexdigest()


def test_build_manifest_multiple_variants(tmp_path: Path) -> None:
    # Two boards, two examples, two transports → four variants.
    for board, example, tx in [
        ("esp32s3", "hello_publisher", "serial"),
        ("esp32s3", "espnow_publisher", "espnow"),
        ("esp32",   "hello_publisher", "serial"),
        ("esp32s3", "espnow_gateway",  "serial"),
    ]:
        d = tmp_path / board / example / tx
        d.mkdir(parents=True)
        (d / "firmware.bin").write_bytes(b"\x00" * 16)
        (d / "flash_args").write_text("0x10000 firmware.bin\n")
    manifest = build_manifest(
        artifacts_root=tmp_path,
        release_tag=None, commit_sha=None,
        ci_run_url=None, generated_at=None,
        url_base="..",
    )
    assert len(manifest["variants"]) == 4
    pairs = {(v["board"], v["example"], v["transport"]) for v in manifest["variants"]}
    assert ("esp32s3", "hello_publisher", "serial") in pairs
    assert ("esp32", "hello_publisher", "serial") in pairs


def test_main_writes_output(tmp_path: Path) -> None:
    _write_artifact_tree(tmp_path)
    out = tmp_path / "manifest.json"
    rc = main([
        "--artifacts", str(tmp_path),
        "--out", str(out),
        "--release-tag", "v0.1.0",
        "--url-base", "https://example.test/dl",
    ])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["releaseTag"] == "v0.1.0"
    assert len(data["variants"]) == 1


def test_main_rejects_missing_dir(tmp_path: Path) -> None:
    rc = main([
        "--artifacts", str(tmp_path / "missing"),
        "--out", str(tmp_path / "m.json"),
    ])
    assert rc == 2


def test_merge_with_preserves_unbuilt_previews(tmp_path: Path) -> None:
    # Set up a prior manifest with two preview entries; the artifact
    # tree only contains one matching variant. After merge, the other
    # preview must survive.
    prior = tmp_path / "manifest.json"
    prior.write_text(json.dumps({
        "wireVersion": 1,
        "variants": [
            {"board": "esp32s3", "example": "hello_publisher",
             "transport": "serial", "preview": True,
             "fwHash": "00" * 32, "files": []},
            {"board": "esp32s3", "example": "espnow_gateway",
             "transport": "serial", "preview": True,
             "fwHash": "00" * 32, "files": []},
        ],
    }))
    artifacts = tmp_path / "artifacts"
    d = artifacts / "esp32s3" / "hello_publisher" / "serial"
    d.mkdir(parents=True)
    (d / "fw.bin").write_bytes(b"X" * 32)
    (d / "flash_args").write_text("0x10000 fw.bin\n")

    manifest = build_manifest(
        artifacts_root=artifacts, release_tag="v1.0.0",
        commit_sha=None, ci_run_url=None, generated_at=None,
        url_base="..", merge_with=prior,
    )

    by_key = {(v["board"], v["example"], v["transport"]): v
              for v in manifest["variants"]}
    # The built one has real files now.
    built = by_key[("esp32s3", "hello_publisher", "serial")]
    assert len(built["files"]) == 1
    assert built["files"][0]["url"].endswith("fw.bin")
    # The other preview survived intact.
    surviving = by_key[("esp32s3", "espnow_gateway", "serial")]
    assert surviving.get("preview") is True
    assert surviving["files"] == []


def test_merge_with_missing_file_is_tolerated(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    d = artifacts / "esp32s3" / "hello_publisher" / "serial"
    d.mkdir(parents=True)
    (d / "fw.bin").write_bytes(b"Y")
    (d / "flash_args").write_text("0x10000 fw.bin\n")
    manifest = build_manifest(
        artifacts_root=artifacts, release_tag=None,
        commit_sha=None, ci_run_url=None, generated_at=None,
        url_base=".", merge_with=tmp_path / "does_not_exist.json",
    )
    assert len(manifest["variants"]) == 1


def test_main_skips_directory_without_flash_args(tmp_path: Path) -> None:
    # A directory tree where one variant has no flash_args is silently
    # skipped — keeps the script tolerant of partial CI uploads.
    good = tmp_path / "esp32s3" / "hello_publisher" / "serial"
    good.mkdir(parents=True)
    (good / "firmware.bin").write_bytes(b"\x00" * 4)
    (good / "flash_args").write_text("0x10000 firmware.bin\n")

    bad = tmp_path / "esp32s3" / "broken" / "serial"
    bad.mkdir(parents=True)
    (bad / "stray.bin").write_bytes(b"\x00")

    out = tmp_path / "m.json"
    assert main(["--artifacts", str(tmp_path), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert len(data["variants"]) == 1
    assert data["variants"][0]["example"] == "hello_publisher"
