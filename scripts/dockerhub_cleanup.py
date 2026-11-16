#!/usr/bin/env python3
"""Delete redundant Docker Hub tags for siiwayteam/nextbridge.

Keeps: latest, main, dev, unstable (+ their -amd64/-arm64 variants).
Deletes: everything else (sha-tracking tags like main-<sha>, dev-<sha>).

Usage:
    DOCKERHUB_TOKEN=dckr_pat_xxx DOCKERHUB_USER=siiwayteam python3 dockerhub_cleanup.py
    # add --dry-run to only list what would be deleted
"""

import json
import os
import sys
import urllib.error
import urllib.request

REPO = "siiwayteam/nextbridge"
KEEP_BASES = {"latest", "main", "dev", "unstable"}

PROXY = os.environ.get("DH_PROXY")  # e.g. http://192.168.1.99:11451
TOKEN = os.environ["DOCKERHUB_TOKEN"]
USER = os.environ.get("DOCKERHUB_USER", "siiwayteam")

DRY_RUN = "--dry-run" in sys.argv


def opener():
    if PROXY:
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
        )
    return urllib.request.build_opener()


op = opener()


def req(url, method="GET", data=None, token=None):
    r = urllib.request.Request(url, method=method, data=data)
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    if data:
        r.add_header("Content-Type", "application/json")
    try:
        with op.open(r, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} on {method} {url}: {e.read()[:200]!r}")
        raise
    return json.loads(body) if body else {}


# 1. Login to get a JWT
jwt = req(
    "https://hub.docker.com/v2/users/login",
    data=json.dumps({"username": USER, "password": TOKEN}).encode(),
    method="POST",
)["token"]
print("login OK")

# 2. List all tags
tags = []
url = f"https://hub.docker.com/v2/repositories/{REPO}/tags?page_size=100"
while url:
    d = req(url, token=jwt)
    tags += [t["name"] for t in d.get("results", [])]
    url = d.get("next")
print(f"total tags: {len(tags)}")

# 3. Pick the redundant ones
to_delete = []
for name in tags:
    base = name.rsplit("-", 1)[0] if name.endswith(("-amd64", "-arm64")) else name
    if base not in KEEP_BASES:
        to_delete.append(name)
print(f"to delete: {len(to_delete)}")
for n in to_delete:
    print("  -", n)

if DRY_RUN:
    sys.exit(0)

# 4. Delete them one by one
failed = []
for name in to_delete:
    try:
        req(
            f"https://hub.docker.com/v2/repositories/{REPO}/tags/{name}/",
            method="DELETE",
            token=jwt,
        )
        print("deleted", name)
    except Exception as e:
        print("FAIL", name, e)
        failed.append(name)

print(f"\ndone. failed: {len(failed)}")
for n in failed:
    print("  retry:", n)
