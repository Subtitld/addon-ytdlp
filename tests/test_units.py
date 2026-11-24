"""The add-on's own logic, without the network.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from ytdlp_addon import deno, downloader, pins, ytdlp
from ytdlp_addon.__main__ import _height


def test_format_prefers_h264_within_the_height():
    choice = downloader.format_for('720')
    assert choice.split('/')[0] == 'bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]'
    assert choice.endswith('/bv*+ba/b')  # anything at all, last
    assert '[height' not in downloader.format_for('best')
    assert '+' not in downloader.format_for('720', can_merge=False)


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
