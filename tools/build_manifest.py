"""Build a web-flasher manifest.json from a directory of firmware bins.

Given a directory layout like::

    artifacts/
      esp32s3/
        hello_publisher/
          serial/
            bootloader.bin  @ 0x0
            partition-table.bin  @ 0x8000
            firmware.bin  @ 0x10000
            flash_args.json   # offsets per file
        espnow_publisher/
          espnow/
            ...
        espnow_gateway/
          serial/
            ...

…produces a single manifest.json with one variant per
(board, example, transport) tuple. ``flash_args.json`` is the
output of ``idf.py build``'s ``flash_args`` extraction; we look it
up to discover the correct flash offsets.

This script has no external deps; it's deliberately runnable from
CI without installing the bridge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VariantFile:
    name: str
    sha256: str
    offset: str  # "0x..." form, matching the manifest schema


@dataclass
class Variant:
    board: str
    example: str
    transport: str
    files: list[VariantFile]
    fw_hash: str
    label: str = ""

    def to_dict(self, url_base: str) -> dict[str, Any]:
        return {
            "board": self.board,
            "example": self.example,
            "transport": self.transport,
            "label": self.label or f"{self.board} · {self.example} · {self.transport}",
            "fwHash": self.fw_hash,
            "files": [
                {
                    "url": f"{url_base}/{self.board}/{self.example}/{self.transport}/{f.name}",
                    "offset": f.offset,
                    "sha256": f.sha256,
                }
                for f in self.files
            ],
        }


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_flash_args(flash_args_path: Path) -> list[tuple[str, str]]:
    """Parse a CMake-style flash_args file.

    The file contains pairs of ``<offset> <filename>``, possibly with
    leading per-line ``--flash-mode`` etc. that we ignore.
    Returns a list of ``(offset_hex, filename)`` in flash order.
    """
    out: list[tuple[str, str]] = []
    text = flash_args_path.read_text()
    tokens = text.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            # skip "--flag value" pairs
            i += 2
            continue
        if tok.startswith("0x") and i + 1 < len(tokens):
            out.append((tok, tokens[i + 1]))
            i += 2
            continue
        i += 1
    if not out:
        raise ValueError(f"no offset/filename pairs found in {flash_args_path}")
    return out


def scan_artifacts(root: Path) -> list[Variant]:
    """Scan ``root/<board>/<example>/<transport>/`` directories."""
    variants: list[Variant] = []
    for board_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for example_dir in sorted(p for p in board_dir.iterdir() if p.is_dir()):
            for tx_dir in sorted(p for p in example_dir.iterdir() if p.is_dir()):
                flash_args = tx_dir / "flash_args"
                if not flash_args.exists():
                    flash_args = tx_dir / "flash_args.txt"
                if not flash_args.exists():
                    continue
                files: list[VariantFile] = []
                concat = bytearray()
                for offset, name in read_flash_args(flash_args):
                    path = tx_dir / name
                    if not path.exists():
                        raise FileNotFoundError(path)
                    data = path.read_bytes()
                    files.append(VariantFile(
                        name=path.name,
                        sha256=sha256_hex(data),
                        offset=offset,
                    ))
                    concat.extend(data)
                fw_hash = sha256_hex(bytes(concat))
                variants.append(Variant(
                    board=board_dir.name,
                    example=example_dir.name,
                    transport=tx_dir.name,
                    files=files,
                    fw_hash=fw_hash,
                ))
    return variants


def build_manifest(
    artifacts_root: Path,
    release_tag: str | None,
    commit_sha: str | None,
    ci_run_url: str | None,
    generated_at: str | None,
    url_base: str,
    merge_with: Path | None = None,
) -> dict[str, Any]:
    variants = scan_artifacts(artifacts_root)
    built = [v.to_dict(url_base) for v in variants]

    # If an existing manifest is passed via merge_with, keep any of its
    # entries that do NOT collide with a freshly built (board, example,
    # transport) tuple. This lets a partial CI build (e.g. only one
    # board succeeded) preserve preview placeholders for the rest.
    keep: list[dict[str, Any]] = []
    if merge_with is not None and merge_with.exists():
        try:
            prev = json.loads(merge_with.read_text())
            built_keys = {(v["board"], v["example"], v["transport"]) for v in built}
            for v in prev.get("variants", []):
                key = (v.get("board"), v.get("example"), v.get("transport"))
                if key not in built_keys:
                    keep.append(v)
        except (OSError, json.JSONDecodeError):
            # Ignore a missing or malformed prior manifest; CI runs
            # with --merge-with on the checked-in file should always
            # find it valid, but we don't fail the whole release if
            # someone hand-edited it.
            pass

    merged = built + keep
    return {
        "$schema": "./manifest.schema.json",
        "wireVersion": 1,
        "generatedAt": generated_at,
        "releaseTag": release_tag,
        "commitSha": commit_sha,
        "ciRunUrl": ci_run_url,
        "variants": merged,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="build-manifest")
    p.add_argument("--artifacts", type=Path, required=True,
                   help="root directory of <board>/<example>/<transport>/...")
    p.add_argument("--release-tag", default=None)
    p.add_argument("--commit-sha", default=None)
    p.add_argument("--ci-run-url", default=None)
    p.add_argument("--generated-at", default=None,
                   help="ISO-8601 timestamp; CI fills this in")
    p.add_argument("--url-base", default=".",
                   help="URL prefix for firmware files in the manifest")
    p.add_argument("--out", type=Path, required=True,
                   help="output path (typically web-flasher/manifest.json)")
    p.add_argument("--merge-with", type=Path, default=None,
                   help="if given, preserve any variants from this prior "
                        "manifest that weren't rebuilt (preview placeholders)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    if not args.artifacts.is_dir():
        print(f"artifacts dir not found: {args.artifacts}", file=sys.stderr)
        return 2
    manifest = build_manifest(
        artifacts_root=args.artifacts,
        release_tag=args.release_tag,
        commit_sha=args.commit_sha,
        ci_run_url=args.ci_run_url,
        generated_at=args.generated_at,
        url_base=args.url_base.rstrip("/"),
        merge_with=args.merge_with,
    )
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out} with {len(manifest['variants'])} variant(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
