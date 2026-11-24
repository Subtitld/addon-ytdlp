#!/usr/bin/env python3
"""Put the yt-dlp the add-on ships into build/assets/: the official release file, checked against its pin.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

    python tools/fetch_ytdlp.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ytdlp_addon import fetch, pins  # noqa: E402


def main() -> int:
    assets = ROOT / 'build' / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    target = assets / 'yt-dlp'
    if target.is_file():
        import hashlib
        if hashlib.sha256(target.read_bytes()).hexdigest() == pins.YTDLP_SHA256:
            print(f'{target}: yt-dlp {pins.YTDLP_VERSION}, already here')
            return 0
    fetch.download(pins.YTDLP_URL, target, pins.YTDLP_SHA256)
    print(f'{target}: yt-dlp {pins.YTDLP_VERSION}, {target.stat().st_size:,} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
