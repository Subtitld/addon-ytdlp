"""Shared fixtures: a local website, and the add-on run through its protocol.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent / 'data'
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='session')
def site():
    """tests/data/ served on 127.0.0.1: a page with a <video>, one without."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DATA))
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()


class Addon:
    """The add-on as Subtitld runs it: the frozen binary named by $YTDLP_TEST_BINARY, else from source."""

    def __init__(self, models: Path):
        binary = os.environ.get('YTDLP_TEST_BINARY')
        command = [binary] if binary else [sys.executable, '-m', 'ytdlp_addon']
        env = dict(os.environ, SUBTITLD_MODELS_DIR=str(models), YTDLP_AUTO_UPDATE='0')
        self.process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=None)
        self.hello = self.read()
        self.send({'type': 'ready', 'host': 'tests', 'host_version': '0', 'protocol': 1})

    def send(self, frame: dict) -> None:
        self.process.stdin.write((json.dumps(frame) + '\n').encode('utf-8'))
        self.process.stdin.flush()

    def read(self) -> dict:
        line = self.process.stdout.readline()
        assert line, 'the add-on closed its stdout'
        return json.loads(line)

    def request(self, req_id: str, params: dict, on_progress=None) -> dict:
        """Send a media.download request; its terminal frame."""
        self.send({'id': req_id, 'type': 'media.download', 'params': params})
        while True:
            frame = self.read()
            assert frame.get('id') == req_id, frame
            if frame['type'] == 'progress':
                if on_progress is not None:
                    on_progress(frame)
                continue
            return frame

    def close(self) -> int:
        try:
            self.send({'type': 'shutdown'})
        except (BrokenPipeError, OSError):
            pass
        return self.process.wait(15)


@pytest.fixture
def addon(tmp_path):
    running = Addon(tmp_path / 'models')
    yield running
    running.close()
