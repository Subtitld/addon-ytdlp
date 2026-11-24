"""Downloads the add-on makes for itself: a newer yt-dlp, Deno.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path

from ytdlp_addon import __version__

USER_AGENT = f'subtitld-addon-ytdlp/{__version__}'
TIMEOUT = 30


class Cancelled(Exception):
    pass


def https_context() -> ssl.SSLContext:
    """certifi's CA bundle: a frozen Python on macOS (and some Linux setups) finds no system one."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 — the system's, then
        return ssl.create_default_context()


def data_dir() -> Path:
    """Where the add-on keeps what it downloads: in Subtitld's model folder when it says where that is."""
    root = os.environ.get('SUBTITLD_MODELS_DIR', '').strip()
    if root:
        path = Path(root) / 'ytdlp'
    elif sys.platform == 'win32':
        path = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'subtitld-ytdlp'
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library' / 'Caches' / 'subtitld-ytdlp'
    else:
        path = Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'subtitld-ytdlp'
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_json(url: str):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=https_context()) as response:
        return json.loads(response.read().decode('utf-8'))


def get_text(url: str) -> str:
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=https_context()) as response:
        return response.read().decode('utf-8', 'replace')


def download(url: str, path: Path, sha256: str, progress=None, cancelled=None) -> Path:
    """`url` to `path`, only if its sha256 is `sha256`: written aside and moved in place once checked."""
    partial = path.with_name(path.name + '.part')
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=https_context()) as response, \
                open(partial, 'wb') as output:
            total = int(response.headers.get('Content-Length') or 0)
            done = 0
            while True:
                if cancelled is not None and cancelled():
                    raise Cancelled()
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None and total:
                    progress(done / total)
        if digest.hexdigest() != sha256.lower():
            raise OSError(f'{url} is not the file expected (sha256 {digest.hexdigest()})')
        os.replace(partial, path)
    finally:
        try:
            partial.unlink()
        except OSError:
            pass
    return path
