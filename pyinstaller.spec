# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Subtitld yt-dlp add-on.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

Produces `dist/ytdlp-addon/` (launcher + `_internal/`). The release step
copies it to `bin/` inside the archive, next to manifest.json.

yt-dlp is NOT frozen in: the add-on runs yt-dlp's official release file (a zip
of its Python code), the one in `_internal/assets/` or a newer one it fetched
(ytdlp_addon/ytdlp.py), and a frozen copy would shadow both. yt-dlp is still
analysed, so the standard modules it imports are in the bundle; only its own
modules are dropped afterwards.

    python tools/fetch_ytdlp.py
    pyinstaller pyinstaller.spec --noconfirm
"""

# ruff: noqa: F821  # PyInstaller injects Analysis/PYZ/EXE/COLLECT at runtime.

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_ROOT = Path(SPECPATH).resolve()
ASSETS = SPEC_ROOT / 'build' / 'assets'

if not (ASSETS / 'yt-dlp').is_file():
    raise SystemExit(f'FATAL: no yt-dlp in {ASSETS}. Run `python tools/fetch_ytdlp.py` first.')

datas = [(str(ASSETS / 'yt-dlp'), 'assets')]

# yt-dlp's own modules: analysed for what they import, then left out.
_YTDLP = ('yt_dlp', 'yt_dlp_ejs')


def _is_ytdlp(name: str) -> bool:
    return any(name == top or name.startswith(top + '.') for top in _YTDLP)


# ---------------------------------------------------------------------------
# libexpat sanity check (from addon-whispercpp).
#
# PyInstaller bundles whatever expat it resolved on the build host, for
# CPython's pyexpat. If that host has an OLD expat shadowing the distro one
# (for example a hand-built 2.5.0 in /usr/local/lib), the frozen binary dies
# before reaching Python:
#     Failed to load libpython3.x.so: undefined symbol: XML_SetReparseDeferralEnabled
# Dropping the bundled copy is not a fix either, because the same stale system
# copy is then used. So verify the bundled copy exports the symbol libpython
# needs, and substitute a known-good system copy if it does not.
# ---------------------------------------------------------------------------
_EXPAT_SYMBOL = 'XML_SetReparseDeferralEnabled'


def _exports_symbol(path: str, symbol: str) -> bool:
    try:
        out = subprocess.run(['nm', '-D', '--defined-only', path],
                             capture_output=True, text=True, timeout=30)
        return symbol in out.stdout
    except Exception:
        return True  # no nm (macOS/Windows): assume fine rather than break the build


def _fix_libexpat(entries):
    if not sys.platform.startswith('linux'):
        return entries
    out = []
    for entry in entries:
        name = entry[0] if entry else ''
        src = entry[1] if len(entry) > 1 else ''
        if not os.path.basename(name).startswith('libexpat.so'):
            out.append(entry)
            continue
        if _exports_symbol(src, _EXPAT_SYMBOL):
            out.append(entry)
            continue
        replacement = None
        for cand in ('/usr/lib/x86_64-linux-gnu/libexpat.so.1',
                     '/usr/lib64/libexpat.so.1',
                     '/lib/x86_64-linux-gnu/libexpat.so.1'):
            if os.path.exists(cand) and _exports_symbol(cand, _EXPAT_SYMBOL):
                replacement = cand
                break
        if replacement:
            print(f'WARNING: build host libexpat at {src} lacks {_EXPAT_SYMBOL}; '
                  f'substituting {replacement}')
            out.append((name, replacement) + tuple(entry[2:]))
        else:
            print(f'ERROR: bundled libexpat lacks {_EXPAT_SYMBOL} and no good '
                  f'system copy was found. The frozen binary will not start. '
                  f'Fix the build host (a stale expat in /usr/local/lib is the '
                  f'usual cause).')
            out.append(entry)
    return out


a = Analysis(
    [str(SPEC_ROOT / 'ytdlp_addon' / '__main__.py')],
    pathex=[str(SPEC_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules('yt_dlp') + collect_submodules('yt_dlp_ejs'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6', 'PyQt6', 'PyQt5', 'tkinter', 'Tkinter', '_tkinter',
        'numpy', 'setuptools', 'pkg_resources', 'unittest', 'pydoc_data', 'pytest',
        # yt-dlp's optional helpers, if the build machine has them: the add-on
        # ships without them (yt-dlp works without each one).
        'curl_cffi', 'Cryptodome', 'Crypto', 'brotli', 'brotlicffi', 'mutagen', 'websockets',
        'requests', 'urllib3', 'secretstorage', 'xattr',
        # Reached by yt-dlp only for reading browsers' cookies and by the REPL,
        # neither of which the add-on does.
        'sqlite3', '_sqlite3', 'readline', 'curses', '_curses',
    ],
    noarchive=False,
)

a.pure = [entry for entry in a.pure if not _is_ytdlp(entry[0])]
a.datas = [entry for entry in a.datas if not _is_ytdlp(entry[0].replace('\\', '/').split('/')[0])]
a.binaries = _fix_libexpat(a.binaries)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ytdlp-addon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # stdio is the protocol channel
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ytdlp-addon',
)
