"""The add-on end to end, through its protocol: from source, or the release's frozen binary installed the
way Subtitld installs it ($YTDLP_TEST_BINARY).

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

The pages are served from tests/data/ on this computer, so the outcome does not
depend on a website. One test goes to YouTube, which proves Deno is fetched
and runs on this platform; YouTube may refuse a data centre's address
("confirm you're not a bot"), which counts as reaching it.
"""

from __future__ import annotations

import os
import subprocess


def test_hello(addon):
    assert addon.hello['type'] == 'hello'
    assert addon.hello['addon'] == 'ytdlp'
    assert addon.hello['capabilities'] == [{'task': 'media.download'}]


def test_gets_the_video_of_a_page(addon, site, tmp_path):
    out = tmp_path / 'videos'
    seen = []
    frame = addon.request('a', {'url': f'{site}/page.html', 'output_dir': str(out)}, seen.append)
    assert frame['type'] == 'result', frame
    path = frame['data']['path']
    assert os.path.dirname(path) == str(out)
    assert os.path.getsize(path) == os.path.getsize(os.path.join(os.path.dirname(__file__), 'data', 'clip.mp4'))
    assert frame['data']['engine'].startswith('yt-dlp ')
    assert seen and all(-1.0 <= f['value'] <= 1.0 for f in seen)
    assert sorted(os.listdir(out)) == [os.path.basename(path)]  # nothing else left


def test_a_page_with_no_video(addon, site, tmp_path):
    frame = addon.request('b', {'url': f'{site}/novideo.html', 'output_dir': str(tmp_path)})
    assert frame['type'] == 'error'
    assert frame['code'] == 'unsupported_url', frame


def test_bad_params(addon, tmp_path):
    frame = addon.request('c', {'url': 'file:///etc/passwd', 'output_dir': str(tmp_path)})
    assert (frame['type'], frame['code']) == ('error', 'bad_params')
    frame = addon.request('d', {'url': 'https://example.com/'})
    assert (frame['type'], frame['code']) == ('error', 'bad_params')


def test_cancel_before_anything(addon, site, tmp_path):
    addon.send({'id': 'e', 'type': 'media.download', 'params': {'url': f'{site}/page.html',
                                                                'output_dir': str(tmp_path / 'v')}})
    addon.send({'id': 'x', 'type': 'cancel', 'target': 'e'})
    while True:
        frame = addon.read()
        if frame['type'] != 'progress':
            break
    # Either it was quicker than the cancel, or it stopped and left nothing.
    if frame['type'] == 'error':
        assert frame['code'] == 'cancelled', frame
        assert not (tmp_path / 'v').exists() or not os.listdir(tmp_path / 'v')
    else:
        assert frame['type'] == 'result'


def test_youtube_with_deno(addon, tmp_path):
    frame = addon.request('f', {'url': 'https://www.youtube.com/watch?v=jNQXAC9IVRw', 'output_dir': str(tmp_path),
                                'options': {'max_height': '480'}})
    deno_folder = tmp_path / 'models' / 'ytdlp'  # the addon fixture's
    if frame['type'] == 'result':
        assert os.path.getsize(frame['data']['path']) > 100_000
    else:
        assert 'bot' in frame['message'].lower() or 'sign' in frame['message'].lower(), frame
    executables = [p for p in deno_folder.rglob('deno*') if p.is_file() and p.suffix in ('', '.exe')]
    assert executables, 'Deno was not fetched'
    version = subprocess.run([str(executables[0]), '--version'], capture_output=True, text=True, timeout=60)
    assert version.returncode == 0 and version.stdout.startswith('deno '), version
