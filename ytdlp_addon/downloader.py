"""Getting the video a web page shows, with yt-dlp.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

One video per link (a link to a playlist or a channel is refused: open one of
its videos), at most as tall as the setting says, in the file type and with
the codecs the settings prefer: by default H.264 and AAC in an MP4, which
every player and editor reads. A codec is a preference: when the website has
none in it, the best it has is taken. A file type the streams don't fit in
gives an MKV, which takes any. yt-dlp puts separate video and audio together,
and changes the file type of a single file, with the ffmpeg Subtitld ships.
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


CONTAINERS = ('mp4', 'mkv', 'webm')
DEFAULT_CONTAINER = 'mp4'
# The setting's value -> yt-dlp's filter on a format's codec ('any': no filter, the best there is).
VIDEO_CODECS = {
    'h264': "[vcodec^=avc1]",
    'any': '',
    'av1': "[vcodec^=av01]",
    'vp9': "[vcodec^=vp09]",
    'h265': "[vcodec~='^(hev|hvc)1']",
}
DEFAULT_VIDEO_CODEC = 'h264'
AUDIO_CODECS = {
    'aac': "[acodec^=mp4a]",
    'any': '',
    'opus': "[acodec=opus]",
}
DEFAULT_AUDIO_CODEC = 'aac'


def format_for(height: str, can_merge: bool = True, video_codec: str = DEFAULT_VIDEO_CODEC,
               audio_codec: str = DEFAULT_AUDIO_CODEC) -> str:
    """yt-dlp's format choice: the best video and audio this tall in the codecs asked for, else in the video
    codec with any audio, else the best there is this tall, else anything. Without ffmpeg, only files that
    have both already (nothing to put together)."""
    if height not in HEIGHTS or height == 'best':
        limit = ''
    else:
        limit = f'[height<={int(height)}]'
    vc = VIDEO_CODECS.get(video_codec, VIDEO_CODECS[DEFAULT_VIDEO_CODEC])
    ac = AUDIO_CODECS.get(audio_codec, AUDIO_CODECS[DEFAULT_AUDIO_CODEC])
    choices = [
        f'bv*{limit}{vc}+ba{ac}',
        f'b{limit}{vc}{ac}[acodec!=none]',
        f'bv*{limit}{vc}+ba',
        f'b{limit}{vc}[acodec!=none]',
        f'bv*{limit}+ba',
        f'b{limit}',
        'bv*+ba',
        'b',
    ]
    unique = []
    for choice in choices:
        if (can_merge or '+' not in choice) and choice not in unique:
            unique.append(choice)
    return '/'.join(unique)


def containers_for(container: str) -> tuple[str, str]:
    """(merge_output_format, remux rule) for the file type asked for. yt-dlp takes the first container the
    streams fit in, so MKV, which takes any, comes last; a single file already in WebM goes to MKV, not MP4,
    for the same reason."""
    if container == 'mkv':
        return 'mkv', 'mkv'
    if container == 'webm':
        return 'webm/mkv', 'webm>webm/mkv'
    return 'mp4/mkv', 'webm>mkv/mp4'


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
             progress, cancelled, container: str = DEFAULT_CONTAINER, video_codec: str = DEFAULT_VIDEO_CODEC,
             audio_codec: str = DEFAULT_AUDIO_CODEC) -> dict:
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
        elif status.get('status') == 'started' and status.get('postprocessor') in ('VideoRemuxer', 'FFmpegVideoRemuxer'):
            progress(-1.0, 'Changing the file type...')

    options = {
        'format': format_for(height, bool(ffmpeg), video_codec, audio_codec),
        'merge_output_format': containers_for(container)[0],
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
        # A single file (nothing to merge) in the file type asked for too.
        options['postprocessors'] = [{'key': 'FFmpegVideoRemuxer', 'preferedformat': containers_for(container)[1]}]
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
            path = _written(info, folder, before)
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


def _written(info: dict, folder: Path, before: set[str]) -> str | None:
    """The file the download ended in. What yt-dlp says, when it is there; after a merge or a change of file
    type that can be a name it no longer uses, so else the file new in the folder with the video's id in its
    name (pieces and parts aside)."""
    requested = info.get('requested_downloads') or []
    for path in (info.get('filepath'), requested[0].get('filepath') if requested else None):
        if path and os.path.isfile(path):
            return str(path)
    mark = f"[{info.get('id')}]"
    found = [entry for entry in folder.iterdir()
             if entry.name not in before and mark in entry.name and entry.is_file()
             and not re.search(r'\.(part|ytdl|temp)$|\.f[0-9a-z-]+\.\w+$', entry.name)]
    return str(max(found, key=lambda entry: entry.stat().st_size)) if found else None


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
