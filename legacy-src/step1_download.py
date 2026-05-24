"""
Step 1: 使用 yt-dlp 下载 CNBC 视频。

当前 CNBC Buffett Archive 页面 URL 不能再直接被 yt-dlp 识别，
需要先从页面 HTML 中提取 playbackURL（通常是 m3u8），
再把真实媒体地址交给 yt-dlp 下载。
"""

import json
import re
import subprocess
import argparse
from pathlib import Path

import requests
import yaml


def load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_media_url(video_url, config=None):
    """从 CNBC 视频页面中提取真实媒体地址（优先 playbackURL）。"""
    if config is None:
        config = load_config()

    headers = {
        "User-Agent": config.get("crawl", {}).get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
    }

    resp = requests.get(video_url, headers=headers, timeout=30)
    resp.raise_for_status()
    html = resp.text

    match = re.search(r'playbackURL":"(.*?)"', html)
    if not match:
        return video_url

    media_url = match.group(1).encode("utf-8").decode("unicode_escape")
    media_url = media_url.replace("\\/", "/")
    if media_url.startswith("//"):
        media_url = f"https:{media_url}"
    return media_url


def download_video(video_url, output_path, config=None):
    """使用 yt-dlp 下载视频"""
    if config is None:
        config = load_config()

    dl_config = config.get("download", {})
    fmt = dl_config.get("format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best")
    retries = dl_config.get("retries", 3)
    rate_limit = dl_config.get("rate_limit")

    media_url = get_media_url(video_url, config)
    print(f"  → Resolved media URL: {media_url}")

    ytdlp_bin = str(Path(__file__).parent.parent / ".venv" / "bin" / "yt-dlp")
    if not Path(ytdlp_bin).exists():
        ytdlp_bin = "yt-dlp"

    cmd = [
        ytdlp_bin,
        "-f", fmt,
        "--merge-output-format", "mp4",
        "--retries", str(retries),
        "--continue",
        "-o", str(output_path),
        "--no-check-certificates",
    ]

    if rate_limit:
        cmd.extend(["--limit-rate", rate_limit])

    cmd.append(media_url)

    print(f"  → Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print("  ❌ yt-dlp failed with primary format")
        # 尝试备用格式
        cmd_fallback = [
            ytdlp_bin,
            "-f", "best",
            "--merge-output-format", "mp4",
            "--retries", str(retries),
            "--continue",
            "-o", str(output_path),
            "--no-check-certificates",
            media_url
        ]
        print(f"  → Retrying with fallback format...")
        result = subprocess.run(cmd_fallback)
        if result.returncode != 0:
            raise RuntimeError("yt-dlp download failed")

    print(f"  ✅ Video downloaded: {output_path}")
    return output_path


def download_year(year, config=None):
    """下载指定年份的所有视频"""
    if config is None:
        config = load_config()

    output_dir = Path("output") / str(year)
    metadata_path = output_dir / "metadata.json"

    if not metadata_path.exists():
        print(f"❌ No metadata found for {year}. Run step0_crawl first.")
        return

    with open(metadata_path) as f:
        metadata = json.load(f)

    for session_name, session_info in metadata["sessions"].items():
        video_url = session_info["video_page_url"]
        sess_dir = output_dir / session_name
        video_path = sess_dir / "video.mp4"

        if video_path.exists():
            print(f"  ⏩ Video already exists: {video_path}")
            continue

        print(f"📥 Downloading {year} {session_name} from {video_url}")
        try:
            download_video(video_url, video_path, config)
        except Exception as e:
            print(f"  ❌ Download failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Download CNBC Buffett videos")
    parser.add_argument("--year", type=int, required=True, help="Year to download")
    args = parser.parse_args()

    config = load_config()
    download_year(args.year, config)


if __name__ == "__main__":
    main()
