"""Which yt-dlp the add-on runs: the one it ships, or a newer one it fetched.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

Video websites change often, and a yt-dlp a few weeks old may no longer get
their videos. So, unless the setting is off, the add-on asks GitHub at most
once a day for yt-dlp's latest release, the first time it is used in a
session. A newer one is downloaded (about 3 MB), checked against the sums
published with it, and used from then on; the add-on keeps the one it ships
to fall back on.

yt-dlp's release file `yt-dlp` is a zip of its Python code: put on sys.path,
`import yt_dlp` reads it. The frozen bundle deliberately does not freeze
yt_dlp itself (pyinstaller.spec), or the frozen copy would always win.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from ytdlp_addon import fetch, pins

log = logging.getLogger('ytdlp_addon.ytdlp')

LATEST_URL = 'https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest'
FILE_URL = 'https://github.com/yt-dlp/yt-dlp/releases/download/{tag}/{name}'
CHECK_EVERY_SEC = 24 * 3600
KEEP = 2   # downloaded versions kept: the newest and the one before

_loaded = None   # (module, version, path) once imported


def version_key(text: str) -> tuple[int, ...]:
    """'2026.11.23' -> (2026, 11, 23); () when it isn't a version."""
    if not re.fullmatch(r'\d+(\.\d+)*', text or ''):
        return ()
    return tuple(int(part) for part in text.split('.'))


def bundled() -> Path:
    """The yt-dlp the add-on ships. Source runs use build/assets/ (tools/fetch_ytdlp.py)."""
    override = os.environ.get('YTDLP_ADDON_ASSETS', '').strip()
    if override:
        root = Path(override)
    elif getattr(sys, '_MEIPASS', None):
        root = Path(sys._MEIPASS) / 'assets'
    else:
        root = Path(__file__).resolve().parent.parent / 'build' / 'assets'
    return root / 'yt-dlp'


def _downloaded() -> list[tuple[tuple[int, ...], Path]]:
    found = []
    for path in fetch.data_dir().glob('yt-dlp-*'):
        key = version_key(path.name[len('yt-dlp-'):])
        if key and path.is_file():
            found.append((key, path))
    return sorted(found, reverse=True)


def candidates() -> list[tuple[str, Path]]:
    """Every yt-dlp at hand, newest first, as (version, path)."""
    found = [(key, path) for key, path in _downloaded()]
    ship = bundled()
    if ship.is_file():
        found.append((version_key(pins.YTDLP_VERSION), ship))
    found.sort(key=lambda item: item[0], reverse=True)
    return [('.'.join(map(str, key)), path) for key, path in found]


def _state_path() -> Path:
    return fetch.data_dir() / 'update-check.json'


def _due() -> bool:
    try:
        last = float(json.loads(_state_path().read_text(encoding='utf-8')).get('checked', 0))
    except (OSError, ValueError, AttributeError):
        last = 0.0
    return time.time() - last >= CHECK_EVERY_SEC


def update(cancelled=None) -> str | None:
    """Fetch yt-dlp's latest release if it is newer than every one here. Its version when it fetched one.
    A failure is logged, never raised: the yt-dlp here still works for most links."""
    try:
        release = fetch.get_json(LATEST_URL)
        tag = str(release.get('tag_name') or '')
        _state_path().write_text(json.dumps({'checked': time.time(), 'latest': tag}), encoding='utf-8')
        newest = candidates()[0][0] if candidates() else ''
        if not version_key(tag) or version_key(tag) <= version_key(newest):
            log.info('yt-dlp %s is the latest', newest)
            return None
        sums = fetch.get_text(FILE_URL.format(tag=tag, name='SHA2-256SUMS'))
        match = re.search(r'^([0-9a-fA-F]{64})\s+\*?yt-dlp$', sums, re.MULTILINE)
        if match is None:
            log.warning('yt-dlp %s: no sum for the yt-dlp file', tag)
            return None
        target = fetch.data_dir() / f'yt-dlp-{tag}'
        fetch.download(FILE_URL.format(tag=tag, name='yt-dlp'), target, match.group(1), cancelled=cancelled)
        log.info('yt-dlp %s downloaded', tag)
        for _key, old in _downloaded()[KEEP:]:
            old.unlink(missing_ok=True)
        return tag
    except fetch.Cancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning('checking for a newer yt-dlp failed: %s', exc)
        return None


def _import(path: Path):
    for name in [n for n in sys.modules if n == 'yt_dlp' or n.startswith(('yt_dlp.', 'yt_dlp_ejs'))]:
        del sys.modules[name]
    sys.path.insert(0, str(path))
    try:
        import yt_dlp
        from yt_dlp.version import __version__ as version
        if not str(getattr(yt_dlp, '__file__', '')).startswith(str(path)):
            raise ImportError(f'yt_dlp came from {yt_dlp.__file__}, not {path}')
        return yt_dlp, version
    except BaseException:
        sys.path.remove(str(path))
        raise


def load(auto_update: bool, cancelled=None):
    """yt_dlp, imported once per process: the newest at hand, after fetching a newer one when due."""
    global _loaded
    if _loaded is not None:
        return _loaded
    if auto_update and _due():
        update(cancelled)
    problems = []
    for version, path in candidates():
        try:
            module, actual = _import(path)
        except Exception as exc:  # noqa: BLE001 — a broken download: the next one
            log.warning('yt-dlp %s at %s does not load: %s', version, path, exc)
            problems.append(f'{path.name}: {exc}')
            if path != bundled():
                path.unlink(missing_ok=True)
            continue
        log.info('using yt-dlp %s from %s', actual, path)
        _loaded = (module, actual, path)
        return _loaded
    raise RuntimeError('no yt-dlp that loads: ' + ('; '.join(problems) or 'none found'))
