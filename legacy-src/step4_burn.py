"""
Step 4: 字幕样式转换 (SRT -> ASS) + FFmpeg 硬字幕烧录
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import pysubs2
import yaml


def load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def available_ass_font_names():
    names = []
    for path in [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]:
        if Path(path).exists():
            names.append(Path(path).stem)
    return names


def resolve_subtitle_font_name(style_config):
    configured = str(style_config.get("font_name", "")).strip()
    available = available_ass_font_names()
    if configured and configured in available:
        return configured
    if available:
        return available[0]
    return configured or "Arial Unicode MS"


def parse_ass_color(color_str):
    """解析 ASS 颜色字符串 &HAABBGGRR 为 (R, G, B, A)"""
    color_str = color_str.replace("&H", "").replace("&h", "")
    if len(color_str) == 8:
        a = int(color_str[0:2], 16)
        b = int(color_str[2:4], 16)
        g = int(color_str[4:6], 16)
        r = int(color_str[6:8], 16)
        return (r, g, b, a)
    return (255, 255, 255, 0)


def ffmpeg_quote_filter_path(path):
    return str(path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def srt_to_ass(srt_path, ass_path, config, english_srt_path=None):
    """将 SRT 转为带样式的 ASS 格式"""
    style_config = config.get("subtitle_style", {})
    bilingual = config.get("bilingual", {})
    font_name = resolve_subtitle_font_name(style_config)

    subs = pysubs2.load(str(srt_path))

    default_style = subs.styles.get("Default", pysubs2.SSAStyle())
    default_style.fontname = font_name
    default_style.fontsize = style_config.get("font_size", 22)
    default_style.primarycolor = pysubs2.Color(*parse_ass_color(
        style_config.get("primary_color", "&H00FFFFFF")
    ))
    default_style.outlinecolor = pysubs2.Color(*parse_ass_color(
        style_config.get("outline_color", "&H00000000")
    ))
    default_style.outline = style_config.get("outline_width", 2)
    default_style.shadow = style_config.get("shadow", 1)
    default_style.marginv = style_config.get("margin_v", 30)
    default_style.alignment = style_config.get("alignment", 2)
    default_style.bold = True
    subs.styles["Default"] = default_style

    if bilingual.get("enabled") and english_srt_path and Path(english_srt_path).exists():
        en_subs = pysubs2.load(str(english_srt_path))
        en_style = pysubs2.SSAStyle()
        en_style.fontname = font_name
        en_style.fontsize = bilingual.get("secondary_font_size", 16)
        en_style.primarycolor = pysubs2.Color(*parse_ass_color(
            bilingual.get("secondary_color", "&H0000FFFF")
        ))
        en_style.outlinecolor = pysubs2.Color(*parse_ass_color("&H00000000"))
        en_style.outline = 1
        en_style.shadow = 0
        en_style.marginv = style_config.get("margin_v", 30) + 35
        en_style.alignment = 2
        subs.styles["English"] = en_style

        for event in en_subs:
            new_event = event.copy()
            new_event.style = "English"
            subs.append(new_event)
        subs.sort()

    subs.info["PlayResX"] = "1280"
    subs.info["PlayResY"] = "720"
    subs.save(str(ass_path))
    print(f"  ✅ ASS subtitle saved: {ass_path}")
    return ass_path


def burn_subtitles(video_path, subtitle_path, output_path, config):
    """使用 FFmpeg 烧录硬字幕"""
    ffmpeg_config = config.get("ffmpeg", {})
    codec = ffmpeg_config.get("codec", "libx264")
    crf = ffmpeg_config.get("crf", 18)
    preset = ffmpeg_config.get("preset", "medium")

    subtitle_ext = Path(subtitle_path).suffix.lower()
    if subtitle_ext == ".ass":
        vf = f"ass='{ffmpeg_quote_filter_path(Path(subtitle_path))}'"
    else:
        style_config = config.get("subtitle_style", {})
        font = resolve_subtitle_font_name(style_config)
        size = style_config.get("font_size", 22)
        vf = (
            f"subtitles='{ffmpeg_quote_filter_path(Path(subtitle_path))}':"
            f"force_style='FontName={font},FontSize={size},"
            f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            f"Outline=2,Shadow=1'"
        )

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(video_path),
        "-vf",
        vf,
        "-c:v",
        codec,
        "-crf",
        str(crf),
        "-preset",
        preset,
        "-c:a",
        "copy",
        "-y",
        str(output_path),
    ]

    print("  -> Running FFmpeg (this may take a while)...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{result.stderr[-1000:]}")

    print(f"  ✅ Final video: {output_path}")
    return output_path


def burn_year(year, config=None):
    """烧录指定年份的所有视频"""
    if config is None:
        config = load_config()

    output_dir = Path("output") / str(year)
    metadata_path = output_dir / "metadata.json"

    if not metadata_path.exists():
        print(f"❌ No metadata for {year}.")
        return

    with open(metadata_path) as f:
        metadata = json.load(f)

    for session_name in metadata["sessions"]:
        sess_dir = output_dir / session_name
        video_path = sess_dir / "video.mp4"
        chinese_srt = sess_dir / "chinese.srt"
        english_srt = sess_dir / "english.srt"
        output_video = sess_dir / "video_中文字幕.mp4"

        if output_video.exists():
            print(f"  ⏩ Output already exists: {output_video}")
            continue

        if not video_path.exists():
            print(f"  ❌ Video not found: {video_path}")
            continue

        if not chinese_srt.exists():
            print(f"  ❌ Chinese SRT not found: {chinese_srt}. Run step3_translate first.")
            continue

        chinese_text = chinese_srt.read_text(encoding='utf-8', errors='replace')
        if chinese_text.strip() == english_srt.read_text(encoding='utf-8', errors='replace').strip():
            print(f"  ❌ Chinese SRT still matches English source: {chinese_srt}. Skip burn until real translation is ready.")
            continue

        print(f"🔥 Burning subtitles for {year} {session_name}...")

        with tempfile.NamedTemporaryFile(prefix=f"{session_name}_", suffix=".ass", dir=str(sess_dir), delete=False) as tmp_ass:
            chinese_ass = Path(tmp_ass.name)
        try:
            srt_to_ass(chinese_srt, chinese_ass, config, english_srt)
            burn_subtitles(video_path, chinese_ass, output_video, config)
        finally:
            if chinese_ass.exists():
                chinese_ass.unlink()


def main():
    parser = argparse.ArgumentParser(description="Burn Chinese subtitles onto video")
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()

    config = load_config()
    burn_year(args.year, config)


if __name__ == "__main__":
    main()
