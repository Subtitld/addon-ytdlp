# yt-dlp add-on for Subtitld

Opens the video of a web page from its link, so you can subtitle it: YouTube, Vimeo and the [many other websites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) [yt-dlp](https://github.com/yt-dlp/yt-dlp) knows. In Subtitld, choose **Open a link** on the start screen and paste the link. A link straight to a video file needs no add-on: Subtitld downloads it itself.

**Use it only for videos you have the right to work on**: your own, your client's, or ones whose licence allows it. Many websites' terms forbid downloading their videos otherwise.

- **One video per link.** A link to a playlist or a channel is refused: open one of its videos. A live stream can be opened once it ends.
- **Made for editing, or as you like it.** By default H.264 video with AAC sound when the website has it (every player and editor reads it), up to 1080p, saved as MP4 in the folder Subtitld shows (your Videos folder at first). The settings choose another file type (MKV, WebM) and other codecs, or the best there is whatever its codec.
- **Keeps itself working.** Websites change often, and yt-dlp follows them. Once a day at most, when you use it, the add-on fetches yt-dlp's latest release (about 3 MB, checked against the sums published with it). It keeps the yt-dlp it shipped with to fall back on.
- **YouTube needs Deno.** YouTube's player hides its videos behind JavaScript, which yt-dlp solves with [Deno](https://deno.com). The first YouTube link downloads Deno once (about 40 MB, checked against a pinned sha256) into Subtitld's model folder. Other websites don't need it. On Haiku, where Deno has no build, yt-dlp uses Node instead, from the `nodejs24` package Subtitld installs with the add-on.
- **No account.** The add-on never signs in anywhere, and reads no browser's cookies: a video only shown to signed-in people can't be opened with it.

## Settings

| Setting | Default | |
|---|---|---|
| Largest video | 1080p | The tallest video to get. Subtitling rarely needs more; a smaller video downloads faster. |
| File type | MP4 | MP4, MKV or WebM. MKV takes any video and sound; when they don't fit in MP4 or WebM, the video is saved as MKV. |
| Video codec | H.264 | H.264, AV1, VP9 or H.265 preferred, or Any, the best there is. When the website has none in the codec, the best video is taken. |
| Audio codec | AAC | AAC or Opus preferred, or Any, the best there is. |
| Keep yt-dlp up to date | on | Fetch yt-dlp's latest release, at most once a day. |

## How it is built

The add-on is a small Python program that speaks Subtitld's add-on protocol (task `media.download`) and runs yt-dlp's official release file, a zip of its Python code: `tools/fetch_ytdlp.py` puts the pinned one in the bundle, `ytdlp_addon/ytdlp.py` picks the newest at hand. yt-dlp is analysed by PyInstaller, so the standard modules it needs are frozen in, but not frozen itself, or the frozen copy would shadow the release files. yt-dlp puts separate video and audio together with the ffmpeg Subtitld ships.

```bash
pip install -e '.[build,dev]'
python tools/fetch_ytdlp.py
pytest
pyinstaller pyinstaller.spec --noconfirm
YTDLP_TEST_BINARY=$PWD/dist/ytdlp-addon/ytdlp-addon pytest tests/test_installed.py
```

The tests serve a page with a video from the machine they run on, so they don't depend on a website; one goes to YouTube to prove Deno is fetched and runs. The release workflow builds every platform's archive, installs it the way Subtitld does, and runs those tests against it before publishing.

## Licence

Apache-2.0. yt-dlp is in the public domain (Unlicense), Deno is MIT; every archive carries `THIRD_PARTY_LICENSES/` with the notices of everything in it.
