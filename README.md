# buffett-munger-wisdom-archive

Local media pipeline for collecting Buffett and Munger archive videos, generating subtitles, rendering review videos, and serving review assets.

## Quick Start

### 1. Install System Dependencies

Use Python 3.11 or 3.12 for this project. The ASR stack used by `legacy-src/step2_align.py` depends on PyTorch/WhisperX packages that do not currently support Python 3.13+ reliably.

On macOS with Homebrew:

```bash
brew install python@3.11 ffmpeg-full
```

`ffmpeg-full` is required instead of Homebrew's regular `ffmpeg` formula because subtitle burn-in needs the `ass` or `subtitles` video filter backed by `libass`.

`ffmpeg-full` is keg-only, so put it before the regular Homebrew `ffmpeg` in your shell:

```bash
export PATH="/opt/homebrew/opt/ffmpeg-full/bin:$PATH"
```

Verify the external tools:

```bash
python3.11 --version
ffmpeg -version
ffprobe -version
yt-dlp --version
ffmpeg -hide_banner -filters | awk '$2 == "ass" || $2 == "subtitles"'
```

Expected filter output includes both:

```text
ass               V->V       Render ASS subtitles onto input video using the libass library.
subtitles         V->V       Render text subtitles onto input video using the libass library.
```

### 2. Install Python Dependencies

Create a project virtual environment with Python 3.11:

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

### 3. Smoke Test

Run the legacy CLI help command:

```bash
python legacy-src/tools_project_cli.py -h
python legacy-src/run.py --help
```

For ASR/alignment workflows, `faster-whisper` and `whisperx` may download model files on first real use.
