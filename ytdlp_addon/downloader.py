"""Getting the video a web page shows, with yt-dlp.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

One video per link (a link to a playlist or a channel is refused: open one of
its videos), at most as tall as the setting says, H.264 preferred so every
player and editor reads it, as MP4 (MKV when its streams don't fit in one).
yt-dlp puts separate video and audio together with the ffmpeg Subtitld ships.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

log = logging.getLogger('ytdlp_addon.downloader')

HEIGHTS = ('480', '720', '1080', '1440', '2160', 'best')
DEFAULT_HEIGHT = '1080'


class DownloadError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Cancelled(Exception):
    pass


def format_for(height: str, can_merge: bool = True) -> str:
    """yt-dlp's format choice: H.264 video with AAC audio when there is one this tall, else the best there is
    this tall, else anything. Without ffmpeg, only files that have both already (nothing to put together)."""
    if height not in HEIGHTS or height == 'best':
        limit = ''
    else:
        limit = f'[height<={int(height)}]'
    choices = [
        f'bv*{limit}[vcodec^=avc1]+ba[ext=m4a]',
        f'b{limit}[vcodec^=avc1][acodec!=none]',
        f'bv*{limit}+ba',
        f'b{limit}',
        'bv*+ba',
        'b',
    ]
    return '/'.join(c for c in choices if can_merge or '+' not in c)


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def clean_message(text: str) -> str:
    """yt-dlp's message, for the person: without its colour codes and the command-line options it suggests."""
    text = _ANSI.sub('', str(text or '')).strip()
    text = re.sub(r'^ERROR:\s*', '', text)
    text = re.split(r'\s+(?:Use|Pass|Try|See)\s+(?:--|https?://)|;?\s+please report this issue', text,
                    maxsplit=1, flags=re.IGNORECASE)[0]
    return text.strip()


# What yt-dlp says when it can't go on without the person's account, in their words.
_SIGN_IN = ('logged-in', 'log in', 'login', 'sign in', 'signed in', '--cookies', 'account credentials')


def needs_sign_in(text: str) -> bool:
    text = str(text or '').lower()
    return any(phrase in text for phrase in _SIGN_IN)


class _Logger:
    """yt-dlp's messages, to the log (stderr): never to stdout, which is the protocol's."""

    def debug(self, message):
        if not message.startswith('[debug] '):
            log.info('%s', _ANSI.sub('', message))

    def info(self, message):
        log.info('%s', _ANSI.sub('', message))

    def warning(self, message):
        log.warning('%s', _ANSI.sub('', message))

    def error(self, message):
        log.error('%s', _ANSI.sub('', message))


def _is_unsupported(yt_dlp, exc) -> bool:
    utils = yt_dlp.utils
    if isinstance(exc, getattr(utils, 'UnsupportedError', ())):
        return True
    original = getattr(exc, 'exc_info', None)
    if original and isinstance(original[1], getattr(utils, 'UnsupportedError', ())):
        return True
    return 'Unsupported URL' in str(exc)


def download(yt_dlp, url: str, output_dir: str, height: str, ffmpeg: str | None, deno: str | None,
             progress, cancelled) -> dict:
    """Get the video at `url` into `output_dir`: {'path', 'title'}. `progress(value, message)`, value -1 while
    the size isn't known; `cancelled()` True stops it (Cancelled, what it wrote removed)."""
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    before = {entry.name for entry in folder.iterdir()}
    sizes = {'parts': [], 'index': 0}
    written = {'id': None}   # the video's id: every file this download writes has it in its name

    def on_progress(status):
        if cancelled():
            raise Cancelled()
        if status.get('status') != 'downloading':
            return
        done = status.get('downloaded_bytes') or 0
        total = status.get('total_bytes') or status.get('total_bytes_estimate') or 0
        parts, index = sizes['parts'], sizes['index']
        # Video and audio come as two files: one bar for both, each weighed by its size.
        if parts and all(parts) and index < len(parts):
            whole = sum(parts)
            value = (sum(parts[:index]) + min(done, parts[index])) / whole
        elif total:
            value = done / total
        else:
            value = -1.0
        progress(min(value, 0.99), '')

    def on_finished_part(status):
        if status.get('status') == 'finished':
            sizes['index'] += 1

    def on_postprocess(status):
        if cancelled():
            raise Cancelled()
        if status.get('status') == 'started' and status.get('postprocessor') in ('Merger', 'FFmpegMerger'):
            progress(-1.0, 'Putting the video and its sound together...')

    options = {
        'format': format_for(height, can_merge=bool(ffmpeg)),
        'merge_output_format': 'mp4/mkv',
        'outtmpl': {'default': str(folder / '%(title).120B [%(id)s].%(ext)s')},
        'windowsfilenames': True,
        'noplaylist': True,
        'noprogress': True,
        'quiet': True,
        'logger': _Logger(),
        'progress_hooks': [on_progress, on_finished_part],
        'postprocessor_hooks': [on_postprocess],
        'retries': 5,
        'fragment_retries': 5,
        'socket_timeout': 30,
        'overwrites': False,
    }
    if ffmpeg:
        options['ffmpeg_location'] = ffmpeg
    if deno:
        options['js_runtimes'] = {'deno': {'path': deno}}

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            progress(-1.0, 'Looking at the page...')
            info = ydl.extract_info(url, download=False, process=False)
            if cancelled():
                raise Cancelled()
            if info.get('_type') in ('playlist', 'multi_video'):
                raise DownloadError('bad_params', 'This link is a list of videos. Open one of its videos instead.')
            info = ydl.process_ie_result(info, download=False)
            written['id'] = info.get('id')
            if info.get('is_live'):
                raise DownloadError('bad_params', 'This video is live. It can be opened once the live stream ends.')
            formats = info.get('requested_formats') or [info]
            sizes['parts'] = [f.get('filesize') or f.get('filesize_approx') or 0 for f in formats]
            ydl.process_info(info)
            if cancelled():
                raise Cancelled()
            requested = info.get('requested_downloads') or []
            path = (requested[0].get('filepath') if requested else None) or info.get('filepath') \
                or ydl.prepare_filename(info)
    except (Cancelled, KeyboardInterrupt):
        _remove_new(folder, before, written['id'])
        raise Cancelled()
    except DownloadError:
        _remove_new(folder, before, written['id'])
        raise
    except Exception as exc:  # noqa: BLE001 — yt-dlp's errors, said to the person
        _remove_new(folder, before, written['id'])
        original = (getattr(exc, 'exc_info', None) or (None, None))[1]
        if isinstance(original, Cancelled) or isinstance(exc.__context__, Cancelled):
            raise Cancelled()
        if _is_unsupported(yt_dlp, exc):
            raise DownloadError('unsupported_url', clean_message(exc)) from exc
        if needs_sign_in(exc):
            raise DownloadError('bad_params', 'The website only shows this video to someone signed in, which this '
                                f'add-on cannot do. ({clean_message(exc)})') from exc
        log.exception('download of %s failed', url)
        raise DownloadError('internal', clean_message(exc)) from exc
    if not path or not os.path.isfile(path):
        raise DownloadError('internal', f'yt-dlp reported {path!r}, which is not there')
    return {'path': str(path), 'title': str(info.get('title') or '')}


def _remove_new(folder: Path, before: set[str], video_id: str | None) -> None:
    """What this download wrote (parts, pieces), so a stopped one leaves nothing behind: the files new since
    it started with the video's id in their name, as the name template puts it."""
    if not video_id:
        return
    mark = f'[{video_id}]'
    for entry in folder.iterdir():
        if entry.name not in before and mark in entry.name and entry.is_file():
            try:
                entry.unlink()
            except OSError as exc:
                log.warning('could not remove %s: %s', entry, exc)
