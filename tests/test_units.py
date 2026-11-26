"""The add-on's own logic, without the network.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ytdlp_addon import deno, downloader, pins, ytdlp
from ytdlp_addon.__main__ import _height


def test_format_prefers_h264_within_the_height():
    choice = downloader.format_for('720')
    assert choice.split('/')[0] == 'bv*[height<=720][vcodec^=avc1]+ba[acodec^=mp4a]'
    assert choice.endswith('/bv*+ba/b')  # anything at all, last
    assert '[height' not in downloader.format_for('best')
    assert '+' not in downloader.format_for('720', can_merge=False)


def test_codecs_are_preferences():
    choice = downloader.format_for('best', True, 'any', 'any').split('/')
    assert choice[0] == 'bv*+ba'  # the best, whatever its codec
    assert len(choice) == len(set(choice))
    av1 = downloader.format_for('1080', True, 'av1', 'opus').split('/')
    assert av1[0] == 'bv*[height<=1080][vcodec^=av01]+ba[acodec=opus]'
    assert 'bv*[height<=1080]+ba' in av1 and av1[-1] == 'b'  # falls back to any codec
    assert downloader.format_for('720', True, 'nonsense') == downloader.format_for('720')


def test_file_types():
    assert downloader.containers_for('mkv') == ('mkv', 'mkv')
    assert downloader.containers_for('mp4')[0] == 'mp4/mkv'
    assert downloader.containers_for('webm') == ('webm/mkv', 'webm>webm/mkv')


def test_heights():
    assert _height({'max_height': '480'}) == '480'
    assert _height({'max_height': 'best'}) == 'best'
    assert _height({'max_height': '999'}) == downloader.DEFAULT_HEIGHT
    assert _height({}) == downloader.DEFAULT_HEIGHT


def test_messages_lose_command_line_advice():
    message = ('ERROR: [vimeo] 1: The web client only works when logged-in. Use --cookies, '
               '--cookies-from-browser. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ for how')
    assert downloader.clean_message(message) == '[vimeo] 1: The web client only works when logged-in.'
    assert downloader.clean_message('\x1b[0;31mERROR:\x1b[0m x; please report this issue on  https://a') == 'x'
    assert downloader.needs_sign_in(message)
    assert downloader.needs_sign_in("Sign in to confirm you're not a bot")
    assert not downloader.needs_sign_in('Unable to download webpage: HTTP Error 404')


def test_deno_only_for_youtube():
    assert deno.needed_for('https://www.youtube.com/watch?v=x')
    assert deno.needed_for('https://youtu.be/x')
    assert deno.needed_for('https://music.youtube.com/watch?v=x')
    assert not deno.needed_for('https://vimeo.com/1')
    assert not deno.needed_for('https://notyoutube.com/x')


def test_deno_has_a_pin_for_this_computer():
    name = deno.target()
    assert name is None or name in pins.DENO_SHA256


def test_no_deno_on_haiku_node_instead(monkeypatch, tmp_path):
    monkeypatch.setattr(deno.sys, 'platform', 'haiku')
    assert deno.target() is None
    node = tmp_path / 'node'
    node.write_text('')
    monkeypatch.setenv('YTDLP_NODE', str(node))
    assert deno.node() == str(node)
    monkeypatch.setenv('YTDLP_NODE', str(tmp_path / 'missing'))
    assert deno.node() is None


def test_js_runtime_reaches_yt_dlp(monkeypatch):
    seen = {}

    class FakeYDL:
        def __init__(self, options):
            seen.update(options)

        def __enter__(self):
            raise downloader.Cancelled()

        def __exit__(self, *exc):
            return False

    fake = type('yt_dlp', (), {'YoutubeDL': FakeYDL, 'utils': None})
    try:
        downloader.download(fake, 'https://youtu.be/x', str(Path(tempfile.mkdtemp())), 'best', None,
                            ('node', '/bin/node'), lambda *a: None, lambda: False)
    except downloader.Cancelled:
        pass
    assert seen['js_runtimes'] == {'node': {'path': '/bin/node'}}


def test_version_order():
    assert ytdlp.version_key('2026.11.23') == (2026, 11, 23)
    assert ytdlp.version_key('2026.11.23.1') > ytdlp.version_key('2026.11.23')
    assert ytdlp.version_key('nightly') == ()


def test_newest_yt_dlp_first(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBTITLD_MODELS_DIR', str(tmp_path))
    folder = tmp_path / 'ytdlp'
    folder.mkdir()
    (folder / 'yt-dlp-2099.1.1').write_bytes(b'')
    (folder / 'yt-dlp-2000.1.1').write_bytes(b'')
    (folder / 'yt-dlp-garbage').write_bytes(b'')
    found = [version for version, _path in ytdlp.candidates()]
    assert found[0] == '2099.1.1'
    assert 'garbage' not in ' '.join(found)
    assert found == sorted(found, key=ytdlp.version_key, reverse=True)
