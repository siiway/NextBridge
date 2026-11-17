#!/usr/bin/env python3
"""Sync the QQ CQFace GIF set into the data directory.

The GIFs live in a separate repo and are not shipped with NextBridge. The QQ
driver reads them from `<data>/cqface-gif/` first, then from a `db/cqface-gif/`
left in a source checkout, and finally downloads a missing face from the remote
host. Run this to get an offline copy of the full set.

Usage:
    uv run scripts/sync_cqface.py
    uv run scripts/sync_cqface.py --repo wyf9/cqface --ref main
    uv run scripts/sync_cqface.py --dest /srv/nextbridge/data/cqface-gif
    uv run scripts/sync_cqface.py --proxy http://192.168.1.99:11451

Existing files are kept unless --force is given, so a local face added by hand
is not overwritten by the archive.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

DEFAULT_REPO = "wyf9/cqface"
DEFAULT_REF = "main"
ARCHIVE = "https://codeload.github.com/{repo}/tar.gz/refs/heads/{ref}"


def build_opener(proxy: str | None):
    if not proxy:
        return urllib.request.build_opener()
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    return urllib.request.build_opener(handler)


def data_dir() -> Path:
    configured = (os.environ.get("NEXTBRIDGE_DATA_PATH") or "data").strip()
    return Path(configured)


def download_archive(repo: str, ref: str, opener) -> bytes:
    url = ARCHIVE.format(repo=repo, ref=ref)
    with opener.open(url, timeout=120) as resp:
        return resp.read()


def extract_gifs(archive: bytes, dest: Path, force: bool) -> tuple[int, int]:
    written = 0
    skipped = 0
    dest.mkdir(parents=True, exist_ok=True)

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            # Archives nest everything under a single top-level directory.
            parts = member.name.split("/", 1)
            if len(parts) != 2 or not parts[1].startswith("dist/"):
                continue
            name = parts[1][len("dist/") :]
            if not name.endswith(".gif") or "/" in name:
                continue

            target = dest / name
            if target.is_file() and not force:
                skipped += 1
                continue

            source = tar.extractfile(member)
            if source is None:
                continue
            target.write_bytes(source.read())
            written += 1

    return written, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name on GitHub")
    parser.add_argument("--ref", default=DEFAULT_REF, help="branch or tag to read")
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="target directory (defaults to <NEXTBRIDGE_DATA_PATH>/cqface-gif)",
    )
    parser.add_argument("--proxy", default=os.environ.get("SYNC_PROXY"))
    parser.add_argument("--force", action="store_true", help="overwrite existing files")
    args = parser.parse_args()

    dest = args.dest or (data_dir() / "cqface-gif")
    opener = build_opener(args.proxy)

    print(f"downloading {args.repo}@{args.ref}")
    archive = download_archive(args.repo, args.ref, opener)
    written, skipped = extract_gifs(archive, dest, args.force)

    print(f"wrote {written} gif(s) to {dest} ({skipped} already present)")
    if written == 0 and skipped == 0:
        print("no gif found in the archive", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
