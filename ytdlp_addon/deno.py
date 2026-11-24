"""Deno, for the JavaScript YouTube's player needs solved: fetched once, the first time it is needed.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

$YTDLP_DENO (a deno executable) wins; otherwise the pinned release (pins.py)
is downloaded into the add-on's folder.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import sys
import zipfile
from pathlib import Path

from ytdlp_addon import fetch, pins

log = logging.getLogger('ytdlp_addon.deno')

# Sites whose videos need JavaScript solved. Any other site works without Deno.
NEEDS_DENO = ('youtube.com', 'youtu.be', 'youtube-nocookie.com')


def needed_for(url: str) -> bool:
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or '').lower()
    return any(host == site or host.endswith('.' + site) for site in NEEDS_DENO)


def target() -> str | None:
    machine = platform.machine().lower()
    arch = {'amd64': 'x86_64', 'x86_64': 'x86_64', 'arm64': 'aarch64', 'aarch64': 'aarch64'}.get(machine)
    if arch is None:
        return None
    if sys.platform == 'win32':
        name = f'{arch}-pc-windows-msvc'
    elif sys.platform == 'darwin':
        name = f'{arch}-apple-darwin'
    else:
        name = f'{arch}-unknown-linux-gnu'
    return name if name in pins.DENO_SHA256 else None


def _executable(folder: Path) -> Path:
    return folder / ('deno.exe' if sys.platform == 'win32' else 'deno')


def find() -> Path | None:
    """Deno if it is here already."""
    override = os.environ.get('YTDLP_DENO', '').strip()
    if override:
        return Path(override) if os.path.isfile(override) else None
    executable = _executable(fetch.data_dir() / f'deno-{pins.DENO_VERSION}')
    return executable if executable.is_file() else None


def ensure(progress=None, cancelled=None) -> Path | None:
    """Deno, downloaded if it isn't here yet (about 40 MB). None where Deno has no build."""
    found = find()
    if found is not None:
        return found
    name = target()
    if name is None:
        log.warning('no Deno build for %s %s', sys.platform, platform.machine())
        return None
    root = fetch.data_dir()
    archive = root / f'deno-{name}.zip'
    url = pins.DENO_URL.format(version=pins.DENO_VERSION, target=name)
    log.info('downloading Deno %s from %s', pins.DENO_VERSION, url)
    fetch.download(url, archive, pins.DENO_SHA256[name], progress, cancelled)
    folder = root / f'deno-{pins.DENO_VERSION}'
    staging = root / f'deno-{pins.DENO_VERSION}.unpacking'
    shutil.rmtree(staging, ignore_errors=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
        executable = _executable(staging)
        os.chmod(executable, os.stat(executable).st_mode | 0o755)
        shutil.rmtree(folder, ignore_errors=True)
        os.replace(staging, folder)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        archive.unlink(missing_ok=True)
    # Older versions this add-on fetched before.
    for old in root.glob('deno-*'):
        if old.is_dir() and old != folder:
            shutil.rmtree(old, ignore_errors=True)
    return _executable(folder)
