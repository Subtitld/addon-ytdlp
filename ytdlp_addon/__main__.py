"""yt-dlp add-on for Subtitld — JSON-line protocol entry point.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy of
the License at http://www.apache.org/licenses/LICENSE-2.0. Unless required by
applicable law or agreed to in writing, software distributed under the License
is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.

What this add-on is
-------------------
Gets the video a web page shows (YouTube, Vimeo and the many other websites
yt-dlp knows), so Subtitld can open it from a link. Serves `media.download`.
A link straight to a video file needs no add-on: Subtitld downloads it itself.

Wire format
-----------
One JSON object per line on stdin/stdout. Stderr is free-form logging, which
the host prefixes with `[addon:ytdlp]` and surfaces.

`media.download` params:
    url         the page's link
    output_dir  the folder to save the video in
    options     {"max_height": "1080", "container": "mp4", "video_codec": "h264",
                 "audio_codec": "aac", "auto_update": bool}
Frames: `progress` {value (-1 while the size is unknown), message}; then
`result` {"path", "title", "engine": "yt-dlp <version>"}, or `error` with code
`unsupported_url` (no video it can get there), `bad_params` (a playlist, a
live stream), `cancelled`, `network_unavailable` or `internal`.

Options
-------
`max_height`, or $YTDLP_MAX_HEIGHT (default 1080): the tallest video to get,
or "best".
`container`, or $YTDLP_CONTAINER (default mp4): the file type, mp4, mkv or
webm; MKV when the streams don't fit in the one asked for.
`video_codec`, or $YTDLP_VIDEO_CODEC (default h264): h264, any, av1, vp9 or
h265. `audio_codec`, or $YTDLP_AUDIO_CODEC (default aac): aac, any or opus.
Preferences: without one, the best there is.
`auto_update`, or $YTDLP_AUTO_UPDATE (default on): fetch yt-dlp's latest
release, at most once a day (ytdlp.py).
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import sys
import threading
import time
import traceback

from ytdlp_addon import ADDON_ID, PROTOCOL_VERSION, __version__
from ytdlp_addon import deno, downloader, fetch, ytdlp

ADDON_VERSION = __version__
TASK = 'media.download'

ERR_BAD_PARAMS = 'bad_params'
ERR_INTERNAL = 'internal'
ERR_CANCELLED = 'cancelled'
ERR_NETWORK = 'network_unavailable'

log = logging.getLogger('ytdlp_addon')


# ---------------------------------------------------------------------------
# stdio ownership + protocol frames
# ---------------------------------------------------------------------------
_PROTO_IN = None   # binary reader for host frames
_PROTO_OUT = None  # binary writer for our frames
_proto_lock = threading.Lock()


def _claim_protocol_stdio() -> None:
    """Give the protocol exclusive use of the real stdin/stdout.

    fd-level, not just `sys.stdout = sys.stderr`: ffmpeg, which yt-dlp runs,
    could write to an inherited fd 1. Falls back to the Python-level swap if
    the fd dance fails.
    """
    global _PROTO_IN, _PROTO_OUT
    try:
        sys.stdout.flush()
        in_fd = os.dup(0)
        out_fd = os.dup(1)
        devnull = os.open(os.devnull, os.O_RDONLY)
        try:
            os.dup2(devnull, 0)
        finally:
            os.close(devnull)
        os.dup2(2, 1)
        _PROTO_IN = os.fdopen(in_fd, 'rb')
        _PROTO_OUT = os.fdopen(out_fd, 'wb')
    except (OSError, ValueError, AttributeError):
        _PROTO_IN = sys.stdin.buffer
        _PROTO_OUT = sys.stdout.buffer
    sys.stdin = open(os.devnull, encoding='utf-8')  # stray input() -> EOFError
    sys.stdout = sys.stderr                        # stray print() -> the log


def _emit(frame: dict) -> None:
    data = (json.dumps(frame, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    out = _PROTO_OUT if _PROTO_OUT is not None else sys.stdout.buffer
    with _proto_lock:
        try:
            out.write(data)
            out.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass  # host went away; the frame loop exits on the next empty read


def _emit_progress(req_id: str, value: float, message: str = '') -> None:
    value = float(value)
    _emit({'id': req_id, 'type': 'progress',
           'value': -1.0 if value < 0 else min(1.0, value), 'message': message})


def _emit_result(req_id: str, data: dict) -> None:
    _emit({'id': req_id, 'type': 'result', 'data': data})


def _emit_error(req_id: str, code: str, message: str, retryable: bool = False) -> None:
    _emit({'id': req_id, 'type': 'error', 'code': code,
           'message': message, 'retryable': retryable})


# ---------------------------------------------------------------------------
# Options and environment
# ---------------------------------------------------------------------------
def _env(*names: str) -> str:
    """First non-empty value among `names`, stripped. '' when none are set."""
    for name in names:
        value = (os.environ.get(name) or '').strip()
        if value:
            return value
    return ''


def _flag(options: dict, key: str, env: str, default: bool) -> bool:
    value = options.get(key)
    if value is None or value == '':
        value = _env(env)
    if value is None or value == '':
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ('0', 'false', 'no', 'off')
    return bool(value)


def _height(options: dict) -> str:
    value = str(options.get('max_height') or _env('YTDLP_MAX_HEIGHT') or downloader.DEFAULT_HEIGHT).strip().lower()
    return value if value in downloader.HEIGHTS else downloader.DEFAULT_HEIGHT


def _choice(options: dict, key: str, env: str, allowed, default: str) -> str:
    value = str(options.get(key) or _env(env) or default).strip().lower()
    return value if value in allowed else default


def _ffmpeg() -> str | None:
    """The ffmpeg Subtitld ships (it says where), else one on PATH."""
    given = _env('SUBTITLD_FFMPEG_EXECUTABLE')
    if given and os.path.isfile(given):
        return given
    return shutil.which('ffmpeg')


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class _Request:
    def __init__(self, req_id: str):
        self.id = req_id
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None


_active: dict[str, _Request] = {}
_active_lock = threading.Lock()
# yt-dlp is imported once and Deno fetched once: one request at a time does either.
_setup_lock = threading.Lock()


def _handle_download(state: _Request, params: dict) -> None:
    req_id = state.id
    url = str(params.get('url') or '').strip()
    output_dir = str(params.get('output_dir') or '').strip()
    options = params.get('options') if isinstance(params.get('options'), dict) else {}
    if not url.lower().startswith(('http://', 'https://')):
        _emit_error(req_id, ERR_BAD_PARAMS, 'url must be an http(s) link')
        return
    if not output_dir:
        _emit_error(req_id, ERR_BAD_PARAMS, 'output_dir is required')
        return

    cancelled = state.cancel.is_set
    try:
        with _setup_lock:
            _emit_progress(req_id, -1.0, 'Starting yt-dlp...')
            module, version, _path = ytdlp.load(_flag(options, 'auto_update', 'YTDLP_AUTO_UPDATE', True), cancelled)
            runtime = None
            if deno.needed_for(url) and deno.find() is None and deno.target() is None:
                node = deno.node()
                runtime = ('node', node) if node else None
            elif deno.needed_for(url):
                if deno.find() is None:
                    _emit_progress(req_id, 0.0, 'Getting Deno, once (about 40 MB)...')
                path = deno.ensure(_every_percent(lambda value: _emit_progress(
                    req_id, value, 'Getting Deno, once (about 40 MB)...')), cancelled)
                runtime = ('deno', str(path)) if path else None
        if cancelled():
            raise downloader.Cancelled()
        started = time.monotonic()
        result = downloader.download(
            module, url, output_dir, _height(options), _ffmpeg(), runtime,
            lambda value, message: _emit_progress(req_id, value, message), cancelled,
            container=_choice(options, 'container', 'YTDLP_CONTAINER', downloader.CONTAINERS,
                              downloader.DEFAULT_CONTAINER),
            video_codec=_choice(options, 'video_codec', 'YTDLP_VIDEO_CODEC', downloader.VIDEO_CODECS,
                                downloader.DEFAULT_VIDEO_CODEC),
            audio_codec=_choice(options, 'audio_codec', 'YTDLP_AUDIO_CODEC', downloader.AUDIO_CODECS,
                                downloader.DEFAULT_AUDIO_CODEC))
        log.info('download %s: %s in %.1fs', req_id, result['path'], time.monotonic() - started)
        result['engine'] = f'yt-dlp {version}'
        _emit_progress(req_id, 1.0, '')
        _emit_result(req_id, result)
    except (downloader.Cancelled, fetch.Cancelled):
        log.info('download %s: cancelled', req_id)
        _emit_error(req_id, ERR_CANCELLED, 'cancelled')
    except downloader.DownloadError as exc:
        log.warning('download %s failed: [%s] %s', req_id, exc.code, exc.message)
        _emit_error(req_id, exc.code, exc.message)
    except OSError as exc:
        log.warning('download %s failed: %s', req_id, exc)
        _emit_error(req_id, ERR_NETWORK, f'{exc}', retryable=True)
    except Exception as exc:  # noqa: BLE001 — every path must end in one terminal frame
        log.exception('download %s failed', req_id)
        _emit_error(req_id, ERR_INTERNAL, f'{type(exc).__name__}: {exc}')


def _every_percent(report):
    """`report`, called again only once the value has moved by a percent."""
    last = [-1.0]

    def moved(value: float) -> None:
        if value >= 1.0 or value - last[0] >= 0.01:
            last[0] = value
            report(value)
    return moved


def _spawn(req_id: str, target, *args) -> None:
    state = _Request(req_id)
    with _active_lock:
        _active[req_id] = state

    def _run():
        try:
            target(state, *args)
        except BaseException:  # noqa: BLE001
            log.exception('worker crashed')
            tail = traceback.format_exc().strip().splitlines()[-1]
            _emit_error(req_id, ERR_INTERNAL, f'worker crashed: {tail}')
        finally:
            with _active_lock:
                _active.pop(req_id, None)

    thread = threading.Thread(target=_run, name=f'ytdlp-{req_id}', daemon=True)
    state.thread = thread
    thread.start()


# ---------------------------------------------------------------------------
# Handshake + frame loop
# ---------------------------------------------------------------------------
def _send_hello() -> None:
    _emit({
        'type': 'hello',
        'protocol': PROTOCOL_VERSION,
        'addon': ADDON_ID,
        'version': ADDON_VERSION,
        'capabilities': [{'task': TASK}],
    })


def _read_frame() -> dict | None:
    source = _PROTO_IN if _PROTO_IN is not None else sys.stdin.buffer
    line = source.readline()
    if not line:
        return None  # stdin closed: the host went away
    text = line.decode('utf-8', errors='replace').strip().lstrip('﻿')
    if not text:
        return {}
    try:
        frame = json.loads(text)
    except ValueError as exc:
        log.warning('malformed frame %r: %s', line[:200], exc)
        return {}
    return frame if isinstance(frame, dict) else {}


def _main_loop() -> int:
    while True:
        frame = _read_frame()
        if frame is None:
            log.info('stdin closed; exiting')
            return 0
        if not frame:
            continue
        ftype = frame.get('type')

        if ftype == 'shutdown':
            log.info('shutdown requested')
            return 0

        if ftype == 'ready':
            log.info('handshake complete; host=%s host_version=%s',
                     frame.get('host'), frame.get('host_version'))
            continue

        if ftype == 'cancel':
            target = frame.get('target')
            with _active_lock:
                state = _active.get(target) if isinstance(target, str) else None
            if state is not None:
                log.info('cancel %s', target)
                state.cancel.set()
            continue

        if ftype == TASK:
            req_id = frame.get('id')
            params = frame.get('params')
            if not isinstance(req_id, str) or not req_id:
                log.warning('%s without id', TASK)
                continue
            if params is None:
                params = {}
            if not isinstance(params, dict):
                _emit_error(req_id, ERR_BAD_PARAMS, 'params must be an object')
                continue
            _spawn(req_id, _handle_download, params)
            continue

        # Unknown task: still answer, so the host's future resolves instead of
        # hanging until its timeout.
        req_id = frame.get('id')
        if isinstance(req_id, str) and req_id:
            _emit_error(req_id, ERR_BAD_PARAMS, f'unsupported frame type {ftype!r}')


def _stop_workers(budget_sec: float = 3.5) -> None:
    """Cancel every download and give it a moment to remove what it wrote.

    The host allows 5 s between `shutdown` and SIGTERM, so stay under it.
    """
    with _active_lock:
        states = list(_active.values())
    for state in states:
        state.cancel.set()
    deadline = time.monotonic() + budget_sec
    for state in states:
        if state.thread is not None:
            state.thread.join(timeout=max(0.0, deadline - time.monotonic()))


def main() -> int:
    _claim_protocol_stdio()
    logging.basicConfig(
        level=(_env('YTDLP_ADDON_LOG_LEVEL') or 'INFO').upper(),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        stream=sys.stderr,
    )
    log.info('ytdlp-addon %s on %s %s, python %s',
             ADDON_VERSION, platform.system(), platform.machine(), platform.python_version())
    _send_hello()
    rc = 1
    try:
        rc = _main_loop()
    except KeyboardInterrupt:
        rc = 130
    except Exception:  # noqa: BLE001
        log.exception('main loop crashed')
        rc = 1
    finally:
        _stop_workers()
    # A download thread may still be inside a socket read: leave without waiting for it.
    try:
        sys.stderr.flush()
    finally:
        os._exit(rc)


if __name__ == '__main__':
    sys.exit(main())
