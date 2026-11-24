"""What the add-on downloads, pinned: the yt-dlp it ships and the Deno it gets.

Copyright 2026 Subtitld contributors
SPDX-License-Identifier: Apache-2.0

yt-dlp is the official release's `yt-dlp` file: a zip of its Python code that
any Python 3.10+ runs. The add-on carries this one (tools/fetch_ytdlp.py puts
it in the bundle) and may later fetch a newer one (ytdlp_addon/ytdlp.py).

Deno runs the JavaScript YouTube's player needs solved before it hands out a
video; yt-dlp has no JavaScript of its own. Fetched the first time a YouTube
link is opened, from Deno's GitHub release, checked against these sums.
"""

YTDLP_VERSION = '2026.11.23'
YTDLP_SHA256 = 'e8665ed64d6b9172773e812f891fb707a0cb1ee8d9ef4fc1acb00cabee4c5256'
YTDLP_URL = f'https://github.com/yt-dlp/yt-dlp/releases/download/{YTDLP_VERSION}/yt-dlp'

DENO_VERSION = '2.9.8'
DENO_URL = 'https://github.com/denoland/deno/releases/download/v{version}/deno-{target}.zip'
# Deno's target name -> sha256 of deno-<target>.zip.
DENO_SHA256 = {
    'x86_64-unknown-linux-gnu': 'e890975bc2549807bbcc0b584ffafda72cc7c93349dd99c80483dd784f6c4609',
    'aarch64-unknown-linux-gnu': 'd49596c20b9788cf8f5d8ddf644103d4bde56ed239753f0bdb92ba9361d51905',
    'aarch64-apple-darwin': '9f0bf660393da2eaff044cdc7444cb08c73f235849b61d224d825a194ce7c98e',
    'x86_64-apple-darwin': '4b2f5edd2639b7470f034238b321d7002d8dfb4726d8558f52c17afac370eb2c',
    'x86_64-pc-windows-msvc': 'cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf',
}
