"""The manifest says what Subtitld needs to know, and agrees with the package.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ytdlp_addon import ADDON_ID, __version__

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))


def test_identity():
    assert MANIFEST['id'] == ADDON_ID
    assert MANIFEST['version'] == __version__
    pyproject = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    assert re.search(rf'^version = "{re.escape(__version__)}"$', pyproject, re.MULTILINE)


def test_task_and_executable():
    assert MANIFEST['tasks'] == ['media.download']
    assert MANIFEST['executable'] == 'bin/ytdlp-addon'
    assert MANIFEST['protocol'] == 1
    assert set(MANIFEST['platforms']) == {'linux', 'macos', 'windows'}


def test_settings():
    fields = {field['key']: field for field in MANIFEST['config_schema']['fields']}
    heights = [option['value'] for option in fields['max_height']['options']]
    from ytdlp_addon.downloader import DEFAULT_HEIGHT, HEIGHTS
    assert heights == list(HEIGHTS)
    assert fields['max_height']['default'] == DEFAULT_HEIGHT
    assert fields['auto_update']['type'] == 'bool'
    from ytdlp_addon.downloader import (AUDIO_CODECS, CONTAINERS, DEFAULT_AUDIO_CODEC, DEFAULT_CONTAINER,
                                        DEFAULT_VIDEO_CODEC, VIDEO_CODECS)
    for key, allowed, default in (('container', CONTAINERS, DEFAULT_CONTAINER),
                                  ('video_codec', VIDEO_CODECS, DEFAULT_VIDEO_CODEC),
                                  ('audio_codec', AUDIO_CODECS, DEFAULT_AUDIO_CODEC)):
        assert [option['value'] for option in fields[key]['options']] == list(allowed), key
        assert fields[key]['default'] == default, key
