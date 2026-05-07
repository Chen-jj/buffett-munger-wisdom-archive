#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import pysubs2
import yaml
from PIL import Image, ImageDraw, ImageFont

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CONFIG = ROOT / "config.yaml"
WEBAPP = ROOT / "webapp"
WEB_DB = WEBAPP / "app.db"
DEFAULT_SYNC_OFFSET_MS = 0


def load_config():
    if not CONFIG.exists():
        return {}
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def ensure_parent(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def sanitize_slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "item"


def parse_clock_or_seconds(value: str | None) -> float:
    if value is None:
        return 0.0
    value = str(value).strip()
    if not value:
        return 0.0
    if ":" not in value:
        return float(value)
    parts = value.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    else:
        raise ValueError(f"Unsupported time value: {value}")
    return int(h) * 3600 + int(m) * 60 + float(s)


def list_assets(year: int | None = None):
    base = OUTPUT if year is None else OUTPUT / str(year)
    if not base.exists():
        return {"exists": False, "base": str(base)}
    result = {}
    years = [base] if year is not None else sorted([p for p in OUTPUT.iterdir() if p.is_dir()])
    for ydir in years:
        sessions = {}
        for sdir in sorted([p for p in ydir.iterdir() if p.is_dir()]):
            sessions[sdir.name] = sorted(p.name for p in sdir.iterdir() if p.is_file())
        result[ydir.name] = sessions
    return result


def read_text(path: Path, max_chars: int | None = None):
    text = path.read_text(encoding="utf-8", errors="replace")
    return text if not max_chars else text[:max_chars]


def parse_srt(path: Path):
    content = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\n+", content.strip())
    entries = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) >= 3:
            entries.append({
                "index": lines[0].strip(),
                "timestamp": lines[1].strip(),
                "text": "\n".join(lines[2:]).strip(),
            })
    return entries


def write_srt_entries(entries: list[dict], path: Path):
    blocks = []
    for e in entries:
        blocks.append(f"{e['index']}\n{e['timestamp']}\n{e['text']}")
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def build_bilingual_srt(chinese_srt: Path, english_srt: Path, output_srt: Path):
    zh_entries = parse_srt(chinese_srt)
    en_entries = parse_srt(english_srt)
    merged = []
    total = min(len(zh_entries), len(en_entries))
    for idx in range(total):
        zh = zh_entries[idx]
        en = en_entries[idx]
        zh_text = clean_text(zh["text"]).replace("\r", "").strip()
        en_text = clean_text(en["text"]).replace("\r", "").strip()
        merged.append({
            "index": str(idx + 1),
            "timestamp": zh["timestamp"],
            "text": zh_text + ("\n" + en_text if en_text else ""),
        })
    write_srt_entries(merged, output_srt)
    return output_srt


def interleave_bilingual_text(zh_text: str, en_text: str) -> str:
    zh_lines = [clean_text(line).replace("\r", "").strip() for line in zh_text.splitlines() if clean_text(line).strip()]
    en_lines = [clean_text(line).replace("\r", "").strip() for line in en_text.splitlines() if clean_text(line).strip()]
    if not zh_lines:
        return "\n".join(en_lines)
    if not en_lines:
        return "\n".join(zh_lines)

    if len(zh_lines) == len(en_lines):
        merged = []
        for zh_line, en_line in zip(zh_lines, en_lines):
            merged.append(zh_line)
            merged.append(en_line)
        return "\n".join(merged)

    return "\n".join(zh_lines + en_lines)


def build_interleaved_bilingual_srt(chinese_srt: Path, english_srt: Path, output_srt: Path):
    zh_entries = parse_srt(chinese_srt)
    en_entries = parse_srt(english_srt)
    merged = []
    total = min(len(zh_entries), len(en_entries))
    for idx in range(total):
        zh = zh_entries[idx]
        en = en_entries[idx]
        merged.append({
            "index": str(idx + 1),
            "timestamp": zh["timestamp"],
            "text": interleave_bilingual_text(zh["text"], en["text"]),
        })
    write_srt_entries(merged, output_srt)
    return output_srt


def clean_text(text: str) -> str:
    fixes = {
        "â\x80\x94": "—",
        "â\x80\x99": "’",
        "â\x80\x9c": "“",
        "â\x80\x9d": "”",
        "â\x80\xa6": "…",
        "â\x80\x93": "–",
        "Â": "",
    }
    for bad, good in fixes.items():
        text = text.replace(bad, good)
    return text


def clean_srt_file(src: Path, dst: Path):
    entries = parse_srt(src)
    for e in entries:
        e["text"] = clean_text(e["text"])
    write_srt_entries(entries, dst)


SYSTEM_PROMPT = """你是一名专业中英字幕翻译，擅长伯克希尔股东大会、投资、保险、消费品、会计和资本配置语境。
要求：
1. 仅翻译文本，不改序号和时间轴
2. 保留说话人标识，如 WARREN BUFFETT: → 沃伦·巴菲特：
3. 翻译自然、口语化、忠实
4. 每条字幕尽量简洁，必要时保留换行
5. (Laughter) → （笑声），(Applause) → （掌声）
6. 常见人名：Warren Buffett=沃伦·巴菲特，Charlie Munger=查理·芒格，Berkshire Hathaway=伯克希尔·哈撒韦
7. 不要解释，不要补充说明，不要遗漏任何条目
"""

USER_TMPL = """请把以下 SRT 片段翻译成中文。严格保持序号与时间轴完全不变，只翻译文本行：

{srt}
"""


def get_client():
    cfg = load_config().get("translation", {}).get("openai", {})
    api_key = cfg.get("api_key")
    if not api_key or api_key == "sk-xxx" or OpenAI is None:
        return None, cfg
    kwargs = {"api_key": api_key}
    if cfg.get("base_url"):
        kwargs["base_url"] = cfg["base_url"]
    return OpenAI(**kwargs), cfg


def batched(it: list, size: int) -> Iterable[list]:
    for i in range(0, len(it), size):
        yield it[i:i + size]


def translate_entries(entries: list[dict], batch_size: int = 12) -> str:
    client, cfg = get_client()
    if client is None:
        raise RuntimeError("No usable OpenAI-compatible client configured in config.yaml")
    model = cfg.get("model", "gpt-4o")
    temp = cfg.get("temperature", 0.1)
    outputs = []
    for batch in batched(entries, batch_size):
        srt = "\n\n".join(
            f"{e['index']}\n{e['timestamp']}\n{clean_text(e['text'])}" for e in batch
        )
        resp = client.chat.completions.create(
            model=model,
            temperature=temp,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_TMPL.format(srt=srt)},
            ],
        )
        outputs.append(resp.choices[0].message.content.strip())
    return "\n\n".join(outputs) + "\n"


def translate_preview(path: Path, start: int = 1, count: int = 12):
    entries = parse_srt(path)
    chosen = [e for e in entries if start <= int(e["index"]) < start + count]
    srt = "\n\n".join(
        f"{e['index']}\n{e['timestamp']}\n{clean_text(e['text'])}" for e in chosen
    )
    print(USER_TMPL.format(srt=srt))


def export_batch(path: Path, out_dir: Path, batch_size: int = 50, prefix: str = "batch"):
    entries = parse_srt(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for idx, batch in enumerate(batched(entries, batch_size), start=1):
        seq_start = (idx - 1) * batch_size + 1
        seq_end = seq_start + len(batch) - 1
        batch_path = out_dir / f"{prefix}_{idx:03d}_{seq_start}_{seq_end}.srt"
        cleaned = []
        for offset, e in enumerate(batch, start=seq_start):
            cleaned.append({"index": str(offset), "timestamp": e["timestamp"], "text": clean_text(e["text"])})
        write_srt_entries(cleaned, batch_path)
        manifest.append({"file": batch_path.name, "start": seq_start, "end": seq_end, "count": len(batch)})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_batches(src_dir: Path, out_path: Path):
    manifest_path = src_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = [src_dir / item["file"] for item in manifest]
    else:
        files = sorted(src_dir.glob("*.srt"))
    entries = []
    next_index = 1
    for f in files:
        for e in parse_srt(f):
            entries.append({"index": str(next_index), "timestamp": e["timestamp"], "text": e["text"]})
            next_index += 1
    write_srt_entries(entries, out_path)


def translate_srt_heuristic(src: Path, dst: Path):
    speaker_map = {
        "WARREN BUFFETT:": "沃伦·巴菲特：",
        "CHARLIE MUNGER:": "查理·芒格：",
        "AUDIENCE:": "观众：",
        "AUDIENCE MEMBER:": "观众提问：",
        "QUESTIONER:": "提问者：",
        "VOICES:": "众人：",
        "VOICE:": "声音：",
        "WALTER SCOTT:": "沃尔特·斯科特：",
        "FORREST KRUTTER:": "福雷斯特·克鲁特：",
        "ROBERT FITZSIMMONS:": "罗伯特·菲茨西蒙斯：",
    }
    fixed_sentences = {
        "Put this over here.": "把这个放这边。",
        "Am I live yet? Yeah.": "已经开始了吗？开始了。",
        "Morning.": "早上好。",
        "Good morning.": "大家早上好。",
        "Thank you.": "谢谢。",
        "Thanks.": "谢谢。",
        "Yeah.": "是的。",
        "Yes.": "是。",
        "No.": "不是。",
        "Okay.": "好。",
        "All right.": "好。",
        "(Laughter)": "（笑声）",
        "(Applause)": "（掌声）",
        "(laughs)": "（笑）",
    }

    def split_speaker(text: str):
        for en, zh in speaker_map.items():
            if text.startswith(en):
                return zh, text[len(en):].strip()
        return "", text

    def short_translate(line: str) -> str:
        line = clean_text(line).strip()
        if not line:
            return line
        speaker, body = split_speaker(line)
        body = fixed_sentences.get(body, body)
        if body in fixed_sentences.values():
            return (speaker + body).strip()
        return (speaker + body).strip()

    entries = parse_srt(src)
    for e in entries:
        e["text"] = "\n".join(short_translate(x) for x in e["text"].splitlines())
    write_srt_entries(entries, dst)


def available_ass_font_names() -> list[str]:
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


def resolve_subtitle_font_name(style: dict | None = None) -> str:
    style = style or {}
    configured = str(style.get("font_name", "")).strip()
    available = available_ass_font_names()
    if configured and configured in available:
        return configured
    if available:
        return available[0]
    return configured or "Arial Unicode MS"




def build_bilingual_ass(chinese_srt: Path, english_srt: Path, output_ass: Path):
    cfg = load_config()
    style = cfg.get("subtitle_style", {})
    bilingual = cfg.get("bilingual", {})
    font_name = resolve_subtitle_font_name(style)

    zh_entries = parse_srt(chinese_srt)
    en_entries = parse_srt(english_srt)
    total = min(len(zh_entries), len(en_entries))

    subs = pysubs2.SSAFile()
    base_style = pysubs2.SSAStyle()
    base_style.fontname = font_name
    base_style.fontsize = style.get("font_size", 26)
    base_style.primarycolor = pysubs2.Color(*parse_ass_color(style.get("primary_color", "&H00FFFFFF")))
    base_style.outlinecolor = pysubs2.Color(*parse_ass_color(style.get("outline_color", "&H00000000")))
    base_style.outline = style.get("outline_width", 2)
    base_style.shadow = style.get("shadow", 1)
    base_style.marginv = style.get("margin_v", 42)
    base_style.alignment = 2
    base_style.bold = True
    subs.styles["Default"] = base_style
    subs.info["PlayResX"] = "1280"
    subs.info["PlayResY"] = "720"

    en_size = int(bilingual.get("secondary_font_size", 20))

    def ms_from_ts(ts: str):
        start_sec, end_sec = parse_timestamp_to_seconds(ts)
        return int(round(start_sec * 1000)), int(round(end_sec * 1000))

    def clean(value: str) -> str:
        return clean_text(value).replace("\r", "").replace("{", "(").replace("}", ")").strip()

    for i in range(total):
        zh = zh_entries[i]
        en = en_entries[i]
        zh_text = clean(zh["text"])
        en_text = clean(en["text"])
        if not zh_text:
            continue
        start_ms, end_ms = ms_from_ts(zh["timestamp"])
        event = pysubs2.SSAEvent(start=start_ms, end=end_ms, style="Default")
        if en_text:
            en_color = bilingual.get("secondary_color", "&H0060E6FF").replace("&H", "")
            event.text = r'{\fs%d}%s\N{\fs%d\c&H%s&}%s' % (base_style.fontsize, zh_text, en_size, en_color, en_text)
        else:
            event.text = r'{\fs%d}%s' % (base_style.fontsize, zh_text)
        subs.events.append(event)

    output_ass.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(output_ass), format_="ass")
    return output_ass
def parse_ass_color(color_str: str) -> tuple[int, int, int, int]:
    color_str = str(color_str).replace("&H", "").replace("&h", "")
    if len(color_str) == 8:
        a = int(color_str[0:2], 16)
        b = int(color_str[2:4], 16)
        g = int(color_str[4:6], 16)
        r = int(color_str[6:8], 16)
        return (r, g, b, a)
    return (255, 255, 255, 0)


def srt_to_ass(srt_path: Path, ass_path: Path, english_srt_path: Path | None = None):
    cfg = load_config()
    style = cfg.get("subtitle_style", {})
    font_name = resolve_subtitle_font_name(style)
    subs = pysubs2.load(str(srt_path))
    default_style = subs.styles.get("Default", pysubs2.SSAStyle())
    default_style.fontname = font_name
    default_style.fontsize = style.get("font_size", 26)
    default_style.primarycolor = pysubs2.Color(*parse_ass_color(
        style.get("primary_color", "&H00FFFFFF")
    ))
    default_style.outlinecolor = pysubs2.Color(*parse_ass_color(
        style.get("outline_color", "&H00000000")
    ))
    default_style.outline = style.get("outline_width", 2)
    default_style.shadow = style.get("shadow", 1)
    default_style.marginv = style.get("margin_v", 42)
    default_style.alignment = 2
    default_style.bold = True
    subs.styles["Default"] = default_style
    subs.info["PlayResX"] = "1280"
    subs.info["PlayResY"] = "720"
    subs.save(str(ass_path), format_="ass")


def ffmpeg_supports_filter(filter_name: str) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=True,
    )
    pattern = re.compile(rf"\b{re.escape(filter_name)}\b")
    return any(pattern.search(line) for line in result.stdout.splitlines())


def ffmpeg_quote_filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def parse_timestamp_to_seconds(ts: str) -> tuple[float, float]:
    start_str, end_str = [x.strip() for x in ts.split("-->")]

    def parse_one(part: str) -> float:
        hms, ms = part.split(",")
        h, m, s = [int(x) for x in hms.split(":")]
        return h * 3600 + m * 60 + s + int(ms) / 1000.0

    return parse_one(start_str), parse_one(end_str)


def seconds_to_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    h = total_ms // 3600000
    total_ms %= 3600000
    m = total_ms // 60000
    total_ms %= 60000
    s = total_ms // 1000
    ms = total_ms % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def clip_srt(src: Path, dst: Path, start_sec: float = 0.0, duration_sec: float | None = None):
    entries = parse_srt(src)
    end_limit = None if duration_sec is None else start_sec + duration_sec
    clipped = []
    next_index = 1
    for entry in entries:
        start, end = parse_timestamp_to_seconds(entry["timestamp"])
        if end <= start_sec:
            continue
        if end_limit is not None and start >= end_limit:
            break
        new_start = max(0.0, start - start_sec)
        new_end = end - start_sec
        if end_limit is not None:
            new_end = min(new_end, duration_sec)
        if new_end <= new_start:
            continue
        clipped.append({
            "index": str(next_index),
            "timestamp": f"{seconds_to_srt_timestamp(new_start)} --> {seconds_to_srt_timestamp(new_end)}",
            "text": entry["text"],
        })
        next_index += 1
    write_srt_entries(clipped, dst)


def wrap_text(text: str, max_chars: int = 28) -> list[str]:
    lines = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        if len(raw) <= max_chars:
            lines.append(raw)
            continue
        current = []
        current_len = 0
        for token in re.split(r"(\s+)", raw):
            if not token:
                continue
            token_len = len(token)
            if current and current_len + token_len > max_chars:
                lines.append("".join(current).strip())
                current = [token]
                current_len = token_len
            else:
                current.append(token)
                current_len += token_len
        if current:
            lines.append("".join(current).strip())
    return lines or [""]


def get_font(font_size: int):
    font_candidates = [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    font_path = next((p for p in font_candidates if Path(p).exists()), font_candidates[0])
    return ImageFont.truetype(font_path, font_size)


def render_subtitle_pngs(srt_path: Path, out_dir: Path, width: int = 1280, sync_offset_ms: int = 0):
    cfg = load_config()
    style = cfg.get("subtitle_style", {})
    font_size = int(style.get("font_size", 22) * 2)
    font = get_font(font_size)
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = parse_srt(srt_path)
    concat_lines = []
    blank_path = out_dir / "blank.png"
    Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(blank_path)
    safe_blank_path = blank_path.resolve().as_posix().replace("'", "'\\''")

    shift_sec = sync_offset_ms / 1000.0
    shifted = []
    for entry in entries:
        start_sec, end_sec = parse_timestamp_to_seconds(entry["timestamp"])
        start_sec = max(0.0, start_sec + shift_sec)
        end_sec = max(start_sec + 0.05, end_sec + shift_sec)
        shifted.append((start_sec, end_sec, entry))

    cursor = 0.0
    for idx, (start_sec, end_sec, entry) in enumerate(shifted, start=1):
        gap = start_sec - cursor
        if gap > 0.001:
            concat_lines.append(f"file '{safe_blank_path}'\n")
            concat_lines.append(f"duration {gap:.3f}\n")

        lines = wrap_text(clean_text(entry["text"]), max_chars=30)
        line_spacing = 10
        stroke_width = 3
        bbox_heights = []
        max_line_w = 0
        for line in lines:
            bbox = font.getbbox(line or " ")
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            bbox_heights.append(h)
            max_line_w = max(max_line_w, w)
        total_h = sum(bbox_heights) + line_spacing * max(0, len(lines) - 1)
        img_h = total_h + 24
        img_w = min(width, max_line_w + 80)
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        y = 12
        for line, line_h in zip(lines, bbox_heights):
            bbox = font.getbbox(line or " ")
            line_w = bbox[2] - bbox[0]
            x = (img_w - line_w) // 2
            draw.text(
                (x, y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, 255),
            )
            y += line_h + line_spacing
        img_name = f"sub_{idx:05d}.png"
        img_path = out_dir / img_name
        img.save(img_path)
        safe_path = img_path.resolve().as_posix().replace("'", "'\\''")
        concat_lines.append(f"file '{safe_path}'\n")
        concat_lines.append(f"duration {max(0.05, end_sec - start_sec):.3f}\n")
        cursor = end_sec

    if concat_lines:
        last_path = safe_blank_path if not shifted else (out_dir / f"sub_{len(shifted):05d}.png").resolve().as_posix().replace("'", "'\\''")
        concat_lines.append(f"file '{last_path}'\n")
    concat_path = out_dir / "subtitles.concat"
    concat_path.write_text("".join(concat_lines), encoding="utf-8")
    return concat_path


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def burn_from_srt(video_path: Path, srt_path: Path, out_path: Path, start_time: str | None = None, duration: str | None = None, keep_frames: bool = False, sync_offset_ms: int = DEFAULT_SYNC_OFFSET_MS):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    ffmpeg_cfg = cfg.get("ffmpeg", {})
    work_srt = srt_path
    generated_clip = False
    if start_time or duration:
        start_sec = parse_clock_or_seconds(start_time)
        duration_sec = parse_clock_or_seconds(duration) if duration else None
        work_srt = out_path.parent / f"{out_path.stem}.clipped.srt"
        clip_srt(srt_path, work_srt, start_sec=start_sec, duration_sec=duration_sec)
        generated_clip = True

    review_srt = work_srt
    if sync_offset_ms:
        shifted_entries = []
        shift_sec = sync_offset_ms / 1000.0
        for entry in parse_srt(work_srt):
            start_sec, end_sec = parse_timestamp_to_seconds(entry["timestamp"])
            start_sec = max(0.0, start_sec + shift_sec)
            end_sec = max(start_sec + 0.05, end_sec + shift_sec)
            shifted_entries.append({
                "index": entry["index"],
                "timestamp": f"{seconds_to_srt_timestamp(start_sec)} --> {seconds_to_srt_timestamp(end_sec)}",
                "text": entry["text"],
            })
        review_srt = out_path.parent / f"{out_path.stem}.shifted.srt"
        write_srt_entries(shifted_entries, review_srt)

    video_duration = probe_duration(video_path)
    limit_duration = video_duration
    if start_time:
        start_sec = parse_clock_or_seconds(start_time)
        limit_duration = max(0.0, video_duration - start_sec)
    if duration:
        duration_sec = parse_clock_or_seconds(duration)
        limit_duration = min(limit_duration, duration_sec)

    codec = ffmpeg_cfg.get("codec", "libx264")
    crf = str(ffmpeg_cfg.get("crf", 18))
    preset = ffmpeg_cfg.get("preset", "medium")
    image_dir = out_path.parent / f"{out_path.stem}_subtitle_frames"
    concat_path = image_dir / "subtitles.concat"
    burn_mode = "subtitle_filter"
    temp_paths: list[Path] = []

    if image_dir.exists():
        shutil.rmtree(image_dir)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]
    if start_time:
        cmd.extend(["-ss", start_time])
    cmd.extend(["-i", str(video_path)])

    try:
        if ffmpeg_supports_filter("ass"):
            with tempfile.NamedTemporaryFile(prefix=f"{out_path.stem}_", suffix=".burn.ass", dir=str(out_path.parent), delete=False) as tmp_ass:
                ass_path = Path(tmp_ass.name)
            temp_paths.append(ass_path)
            english_candidate = srt_path.parent / "english_15min.srt"
            english_srt_for_burn = None
            if generated_clip and english_candidate.exists():
                english_srt_for_burn = out_path.parent / f"{out_path.stem}.english.clipped.srt"
                clip_srt(english_candidate, english_srt_for_burn, start_sec=start_sec, duration_sec=duration_sec)
                temp_paths.append(english_srt_for_burn)
            elif english_candidate.exists():
                english_srt_for_burn = english_candidate

            bilingual_ass_path = None
            if load_config().get("bilingual", {}).get("enabled") and english_srt_for_burn is not None:
                bilingual_ass_path = out_path.parent / f"{out_path.stem}.bilingual.ass"
                build_bilingual_ass(review_srt, english_srt_for_burn, bilingual_ass_path)
                srt_to_ass(review_srt, ass_path)
                ass_path = bilingual_ass_path
            else:
                srt_to_ass(review_srt, ass_path)
            cmd.extend([
                "-vf", f"ass='{ffmpeg_quote_filter_path(ass_path)}'",
                "-map", "0:v:0",
                "-map", "0:a?",
            ])
        else:
            burn_mode = "png_overlay_fallback"
            concat_path = render_subtitle_pngs(review_srt, image_dir, sync_offset_ms=0)
            cmd.extend([
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_path),
                "-filter_complex", "[1:v]format=rgba,fps=30[subs];[0:v][subs]overlay=(main_w-overlay_w)/2:main_h-overlay_h-30:shortest=1:repeatlast=1[v]",
                "-map", "[v]",
                "-map", "0:a?",
            ])

        cmd.extend([
            "-t", f"{limit_duration:.3f}",
            "-c:v", codec,
            "-crf", crf,
            "-preset", preset,
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", str(out_path),
        ])
        subprocess.run(cmd, check=True)

        ass_path = temp_paths[0] if temp_paths else None
        return {
            "output": out_path,
            "review_srt": review_srt,
            "generated_clip": generated_clip,
            "subtitle_frames_dir": image_dir,
            "ass_path": ass_path,
            "concat_path": concat_path,
            "burn_mode": burn_mode,
        }
    finally:
        for temp_path in temp_paths:
            if temp_path.exists():
                temp_path.unlink()
        if not keep_frames and image_dir.exists():
            shutil.rmtree(image_dir)

def analyze_sync(video_path: Path, srt_path: Path, sample_count: int = 12, sync_offset_ms: int = DEFAULT_SYNC_OFFSET_MS):
    entries = parse_srt(srt_path)
    if not entries:
        return {
            "video": str(video_path),
            "srt": str(srt_path),
            "sample_count": 0,
            "status": "empty",
            "recommended_sync_offset_ms": sync_offset_ms,
        }

    chosen = entries[: min(sample_count, len(entries))]
    starts = []
    gaps = []
    shifted_starts = []
    shifted_gaps = []
    prev_end = 0.0
    prev_shifted_end = 0.0
    shift_sec = sync_offset_ms / 1000.0

    for entry in chosen:
        start_sec, end_sec = parse_timestamp_to_seconds(entry["timestamp"])
        shifted_start = max(0.0, start_sec + shift_sec)
        shifted_end = max(shifted_start + 0.05, end_sec + shift_sec)
        starts.append(start_sec)
        gaps.append(max(0.0, start_sec - prev_end))
        shifted_starts.append(shifted_start)
        shifted_gaps.append(max(0.0, shifted_start - prev_shifted_end))
        prev_end = end_sec
        prev_shifted_end = shifted_end

    avg_start = sum(starts) / len(starts)
    avg_gap = sum(gaps) / len(gaps)
    avg_shifted_gap = sum(shifted_gaps) / len(shifted_gaps)
    min_shifted_gap = min(shifted_gaps) if shifted_gaps else 0.0

    return {
        "video": str(video_path),
        "srt": str(srt_path),
        "sample_count": len(chosen),
        "subtitle_start_min": round(min(starts), 3),
        "subtitle_start_max": round(max(starts), 3),
        "subtitle_start_avg": round(avg_start, 3),
        "avg_inter_gap": round(avg_gap, 3),
        "shifted_start_min": round(min(shifted_starts), 3),
        "shifted_start_max": round(max(shifted_starts), 3),
        "avg_shifted_gap": round(avg_shifted_gap, 3),
        "min_shifted_gap": round(min_shifted_gap, 3),
        "gap_preserved_after_shift": min_shifted_gap >= 0.0,
        "applied_sync_offset_ms": sync_offset_ms,
        "recommended_sync_offset_ms": sync_offset_ms,
        "status": "ok",
        "note": "review 流程会校验字幕空隙是否保留，并记录当前烧录是否使用了额外时间偏移。默认偏移为 0ms。",
    }


def review_burn(video_path: Path, srt_path: Path, output_path: Path, review_path: Path | None = None, sync_offset_ms: int = DEFAULT_SYNC_OFFSET_MS):
    report = analyze_sync(video_path, srt_path, sync_offset_ms=sync_offset_ms)
    report["output"] = str(output_path)
    report["output_exists"] = output_path.exists()
    if output_path.exists():
        report["output_duration"] = round(probe_duration(output_path), 3)
        report["output_size"] = output_path.stat().st_size
    if review_path is None:
        review_path = output_path.with_suffix(output_path.suffix + ".review.json")
    ensure_parent(review_path)
    review_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return review_path, report


def os_common_prefix(a: str, b: str) -> str:
    size = min(len(a), len(b))
    i = 0
    while i < size and a[i] == b[i]:
        i += 1
    return a[:i]


def chapter_to_seconds(chapter: dict, english_entries: list[dict]) -> float:
    paragraphs = [clean_text(p).strip() for p in chapter.get("paragraphs", []) if clean_text(p).strip()]
    if not paragraphs:
        return 0.0
    first = paragraphs[0]
    best = None
    best_score = -1.0
    first_lower = first.lower()
    first_words = [w for w in re.findall(r"[a-z0-9']+", first_lower) if len(w) >= 3]
    for entry in english_entries:
        text = clean_text(entry["text"]).replace("\n", " ").strip()
        if not text:
            continue
        text_lower = text.lower()
        score = 0.0
        if first_lower == text_lower:
            score = 1_000_000.0
        elif first_lower in text_lower or text_lower in first_lower:
            score = 100_000.0 + min(len(first_lower), len(text_lower))
        else:
            prefix_score = len(os_common_prefix(first_lower, text_lower))
            word_hits = sum(1 for w in first_words if w in text_lower)
            score = word_hits * 100.0 + prefix_score
        if score > best_score:
            best_score = score
            best = entry
    if best is None:
        return 0.0
    start, _ = parse_timestamp_to_seconds(best["timestamp"])
    return round(start, 3)


def collect_chapter_transcript(chapter: dict, chinese_entries: list[dict], english_entries: list[dict], all_chapters: list[dict]) -> list[dict]:
    start = chapter_to_seconds(chapter, english_entries)
    next_start = None
    for idx, current in enumerate(all_chapters):
        if current.get("number") == chapter.get("number") and idx + 1 < len(all_chapters):
            next_start = chapter_to_seconds(all_chapters[idx + 1], english_entries)
            break
    paired = []
    total = min(len(chinese_entries), len(english_entries))
    for i in range(total):
        zh_entry = chinese_entries[i]
        en_entry = english_entries[i]
        e_start, e_end = parse_timestamp_to_seconds(en_entry["timestamp"])
        if e_end + 0.001 < start:
            continue
        if next_start is not None and e_start >= next_start:
            break
        zh_text = clean_text(zh_entry["text"]).replace("\n", " ").strip()
        en_text = clean_text(en_entry["text"]).replace("\n", " ").strip()
        if not zh_text and not en_text:
            continue
        paired.append({
            "start": round(e_start, 3),
            "end": round(e_end, 3),
            "zh": zh_text,
            "en": en_text,
        })
    return paired


def load_chapter_title_translations(session_dir: Path) -> dict[str, str]:
    candidates = [
        session_dir / "chapter_titles_zh.json",
        session_dir / "chapters.zh.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return {clean_text(str(k)): clean_text(str(v)) for k, v in data.items() if str(k).strip() and str(v).strip()}
    return {}


def build_catalog(output_root: Path = OUTPUT):
    catalog = {"years": []}
    years = sorted([p for p in output_root.iterdir() if p.is_dir() and p.name.isdigit()], key=lambda p: int(p.name))
    for year_dir in years:
        year_item = {"year": int(year_dir.name), "sessions": []}
        for session_dir in sorted([p for p in year_dir.iterdir() if p.is_dir()]):
            render_dir = session_dir / "render2"
            source_video = session_dir / "video_中文字幕.mp4"
            videos = []
            if source_video.exists():
                videos.append(source_video)
            if render_dir.exists():
                videos.extend(sorted(p for p in render_dir.glob("*.mp4") if p not in videos))
            raw_video = session_dir / "video.mp4"
            if raw_video.exists() and raw_video not in videos:
                videos.append(raw_video)
            if not videos:
                continue
            meta = {}
            meta_path = session_dir / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            english_path = session_dir / "english.srt"
            chinese_candidates = [
                session_dir / "chinese.srt",
                render_dir / "chinese_15min_full.srt",
                render_dir / "chinese.srt",
            ]
            chinese_path = next((p for p in chinese_candidates if p.exists()), None)
            english_entries = parse_srt(english_path) if english_path.exists() else []
            chinese_entries = parse_srt(chinese_path) if chinese_path and chinese_path.exists() else []
            title_translations = load_chapter_title_translations(session_dir)
            chapter_path = session_dir / "chapters.json"
            raw_chapters = json.loads(chapter_path.read_text(encoding="utf-8")) if chapter_path.exists() else []
            chapters = []
            for chapter in raw_chapters:
                transcript_lines = collect_chapter_transcript(chapter, chinese_entries, english_entries, raw_chapters)
                title_en = clean_text(chapter.get("title", ""))
                title_zh = clean_text(
                    chapter.get("title_zh")
                    or chapter.get("title_cn")
                    or title_translations.get(title_en)
                    or title_en
                )
                chapters.append({
                    "number": chapter.get("number"),
                    "title_en": title_en,
                    "title_zh": title_zh,
                    "start": chapter_to_seconds(chapter, english_entries),
                    "transcript_zh": "\n".join([line["zh"] for line in transcript_lines if line["zh"]]),
                    "transcript_en": "\n".join([line["en"] for line in transcript_lines if line["en"]]),
                    "transcript_lines": transcript_lines,
                    "end": round(transcript_lines[-1]["end"], 3) if transcript_lines else None,
                })
            year_item["sessions"].append({
                "slug": f"{year_dir.name}-{sanitize_slug(session_dir.name)}",
                "year": int(year_dir.name),
                "session": session_dir.name,
                "title": meta.get("title") or session_dir.name,
                "headline": meta.get("headline") or meta.get("title") or session_dir.name,
                "video_options": [
                    {"label": p.name, "path": str(p.relative_to(ROOT)).replace('\\', '/')}
                    for p in videos
                ],
                "default_video": str(videos[-1].relative_to(ROOT)).replace('\\', '/'),
                "chapters": chapters,
            })
        if year_item["sessions"]:
            catalog["years"].append(year_item)
    return catalog


def ensure_web_db(db_path: Path = WEB_DB):
    ensure_parent(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_slug TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            title TEXT NOT NULL,
            start REAL NOT NULL,
            transcript_zh TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_slug, chapter_number)
        )
        """
    )
    conn.commit()
    return conn



def write_webapp_assets(web_root: Path, catalog: dict):
    web_root.mkdir(parents=True, exist_ok=True)
    assets_dir = web_root / "assets"
    assets_dir.mkdir(exist_ok=True)
    (web_root / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Buffett & Munger Wisdom Archive Review</title>
  <link rel="stylesheet" href="/webapp/assets/style.css" />
</head>
<body>
  <div id="app"></div>
  <script src="/webapp/assets/app.js"></script>
</body>
</html>
"""
    css = """*{box-sizing:border-box}html,body{height:100%;overflow:hidden}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Helvetica Neue',sans-serif;background:linear-gradient(180deg,#0b1020,#11192c 45%,#0f172a);color:#eef2ff}#app{display:grid;grid-template-columns:300px 320px minmax(0,1fr);height:100vh}.column{padding:20px;min-height:0;overflow:hidden}.scroll-pane{height:100%;overflow:auto;padding-right:6px}.panel{background:rgba(15,23,42,.72);backdrop-filter:blur(18px);border:1px solid rgba(255,255,255,.08);box-shadow:0 20px 60px rgba(0,0,0,.28)}.left{border-right:1px solid rgba(255,255,255,.06)}.mid{border-right:1px solid rgba(255,255,255,.06)}h1{font-size:18px;margin:0 0 16px}.year{margin-bottom:12px;border-radius:16px;overflow:hidden}.year button,.session-btn,.chapter-btn,.fav-btn,.toolbar button,.time-btn{cursor:pointer;border:none}.year-header{width:100%;text-align:left;padding:14px 16px;background:rgba(255,255,255,.05);color:#fff;font-weight:700;display:flex;justify-content:space-between}.session-list{padding:8px}.session-btn{width:100%;text-align:left;padding:12px 14px;margin:6px 0;border-radius:14px;background:rgba(255,255,255,.03);color:#dbeafe}.session-btn.active,.chapter-btn.active{background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff}.chapter-btn{width:100%;text-align:left;padding:12px;border-radius:14px;background:rgba(255,255,255,.03);color:#cbd5e1;margin-bottom:8px}.chapter-time{display:flex;justify-content:space-between;gap:12px;align-items:center}.main-wrap{padding:24px;min-height:0;overflow:auto}.toolbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;position:sticky;top:0;z-index:5;background:linear-gradient(180deg,rgba(11,16,32,.96),rgba(11,16,32,.8));padding-bottom:12px}.toolbar .actions{display:flex;gap:10px}.toolbar button,.fav-btn,.time-btn{padding:10px 14px;border-radius:12px;background:rgba(255,255,255,.08);color:#fff}.hero{padding:20px;border-radius:24px}.video-shell{display:grid;gap:16px}.video-card{padding:18px;border-radius:24px}.video-card video,.floating-player video{width:100%;border-radius:18px;background:#000;box-shadow:0 12px 40px rgba(0,0,0,.35)}.chapter-meta{display:flex;justify-content:space-between;align-items:center;gap:12px;margin:16px 0}.transcript{white-space:pre-wrap;line-height:1.8;background:rgba(255,255,255,.04);padding:18px;border-radius:18px;min-height:180px}.bilingual{display:grid;gap:14px}.transcript-block{background:rgba(255,255,255,.03);padding:16px;border-radius:16px}.transcript-line-zh{margin-bottom:6px}.transcript-line-en{color:#cbd5e1}.muted{color:#94a3b8;font-size:13px}.badge{padding:6px 10px;border-radius:999px;background:rgba(37,99,235,.18);color:#bfdbfe}.fav-list{display:grid;gap:10px;padding-top:10px}.fav-item{padding:14px;border-radius:16px;background:rgba(255,255,255,.05)}.floating-player{position:fixed;right:20px;bottom:20px;width:320px;z-index:30;background:rgba(15,23,42,.92);padding:12px;border-radius:16px;border:1px solid rgba(255,255,255,.1);box-shadow:0 20px 60px rgba(0,0,0,.4)}.floating-player.hidden{display:none}.floating-meta{display:flex;justify-content:space-between;align-items:center;margin-top:8px;gap:8px}.floating-meta .label{font-size:12px;color:#cbd5e1}.video-tabs{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}.video-tab{padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.06);color:#dbeafe;border:none;cursor:pointer}.video-tab.active{background:linear-gradient(135deg,#2563eb,#7c3aed);color:#fff}@media (max-width:1200px){#app{grid-template-columns:260px 280px minmax(0,1fr)}.floating-player{width:280px}}"""
    js = """const state={catalog:null,currentSession:null,currentChapter:null,currentVideoPath:'',collapsed:JSON.parse(localStorage.getItem('collapsedYears')||'{}'),favorites:[],player:null,mainWrap:null,videoCard:null,floatingVisible:false,activePane:'chapters',suppressAutoChapterSync:false,restoreScrollTop:null,isSyncingFromFloating:false};
const app=document.getElementById('app');
function persist(){localStorage.setItem('collapsedYears',JSON.stringify(state.collapsed))}
function findSession(slug){for(const year of state.catalog.years){for(const session of year.sessions){if(session.slug===slug)return session}}return null}
function formatTime(sec){sec=Math.max(0,Number(sec||0));const h=Math.floor(sec/3600);const m=Math.floor((sec%3600)/60);const s=Math.floor(sec%60);return h?`${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`:`${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`}
function escapeHtml(s){return String(s??'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]||m))}
async function load(){state.catalog=await fetch('/webapp/catalog.json').then(r=>r.json());state.favorites=await fetch('/api/favorites').then(r=>r.json());const firstYear=state.catalog.years[0];if(firstYear){if(state.collapsed[firstYear.year]===undefined)state.collapsed[firstYear.year]=false;const firstSession=firstYear.sessions[0];if(firstSession){state.currentSession=findSession(firstSession.slug);state.currentChapter=state.currentSession.chapters[0]||null;state.currentVideoPath='/' + state.currentSession.default_video}}renderLayout();bindDom();renderLeft();renderMid();renderMain(true)}
function renderLayout(){app.innerHTML='<aside class="left column"><div class="scroll-pane" id="left-pane"></div></aside><aside class="mid column"><div class="scroll-pane" id="mid-pane"></div></aside><main class="main-wrap" id="main-wrap"></main><div class="floating-player hidden panel" id="floating-player"><video id="floating-video" controls playsinline muted></video><div class="floating-meta"><div class="label" id="floating-label"></div><button class="time-btn" onclick="window.backToMainVideo()">回到主视频</button></div></div>'}
function bindDom(){state.mainWrap=document.getElementById('main-wrap');state.mainWrap.addEventListener('scroll',updateFloatingPlayer,{passive:true})}
function preserveMainScroll(){if(state.mainWrap)state.restoreScrollTop=state.mainWrap.scrollTop}
function restoreMainScroll(){if(state.mainWrap&&state.restoreScrollTop!==null){state.mainWrap.scrollTop=state.restoreScrollTop;state.restoreScrollTop=null}}
function mainVideo(){return document.getElementById('main-video')}
function floatingVideo(){return document.getElementById('floating-video')}
function bindMainPlayer(){const video=mainVideo();if(!video||video===state.player)return;state.player=video;video.addEventListener('timeupdate',()=>{if(!state.suppressAutoChapterSync)syncCurrentChapterFromVideo();syncFloatingFromMain()});video.addEventListener('seeked',()=>{if(!state.suppressAutoChapterSync)syncCurrentChapterFromVideo(true);syncFloatingFromMain()});video.addEventListener('play',syncFloatingFromMain);video.addEventListener('pause',syncFloatingFromMain);video.addEventListener('loadedmetadata',()=>{syncFloatingFromMain()});video.addEventListener('volumechange',syncFloatingFromMain)}
function bindFloatingPlayer(){const video=floatingVideo();if(!video||video.dataset.bound)return;video.dataset.bound='1';video.addEventListener('timeupdate',syncMainFromFloating);video.addEventListener('seeked',syncMainFromFloating);video.addEventListener('play',()=>{const main=mainVideo();if(main&&main.paused)main.play().catch(()=>{});syncMainFromFloating()});video.addEventListener('pause',()=>{const main=mainVideo();if(main&&!main.paused)main.pause()});video.addEventListener('volumechange',()=>{const main=mainVideo();if(main){main.muted=video.muted;main.volume=video.volume}})}
function ensurePlayers(){bindMainPlayer();bindFloatingPlayer()}
function renderLeft(){const node=document.getElementById('left-pane');if(!node)return;node.innerHTML=`<h1>烧录视频目录</h1><div class="muted">左栏独立滚动，按年份折叠</div>${state.catalog.years.map((year,idx)=>{const collapsed=state.collapsed[year.year]??(idx!==0);return `<div class="year panel"><button class="year-header" onclick="window.toggleYear(${year.year})"><span>${year.year}</span><span>${collapsed?'＋':'－'}</span></button>${collapsed?'':`<div class="session-list">${year.sessions.map(session=>`<button class="session-btn ${state.currentSession&&state.currentSession.slug===session.slug?'active':''}" onclick="window.pickSession('${session.slug}')"><div>${escapeHtml(session.session)}</div><div class="muted">${escapeHtml(session.headline)}</div></button>`).join('')}</div>`}</div>`}).join('')}`}
function renderMid(){const node=document.getElementById('mid-pane');if(!node)return;if(state.activePane==='favorites'){node.innerHTML=`<h1>我的收藏</h1><div class="muted">保存在本地 web 数据库</div><div class="fav-list">${state.favorites.map(f=>`<div class="fav-item"><div><strong>${escapeHtml(f.title)}</strong></div><div class="muted">${escapeHtml(f.session_slug)} · ${formatTime(f.start)}</div><button class="session-btn" style="margin-top:8px" onclick="window.jumpFavorite('${f.session_slug}',${f.chapter_number})">打开</button></div>`).join('')||'<div class="muted">暂无收藏</div>'}</div>`;return}if(!state.currentSession){node.innerHTML='<h1>议题导航</h1><div class="muted">请选择一个视频</div>';return}node.innerHTML=`<h1>${escapeHtml(state.currentSession.session)} 议题</h1><div class="muted">点击议题可直接跳到视频对应时间</div>${state.currentSession.chapters.map(ch=>`<button class="chapter-btn ${state.currentChapter&&state.currentChapter.number===ch.number?'active':''}" onclick="window.pickChapter(${ch.number})"><div class="chapter-time"><div>${ch.number}. ${escapeHtml(ch.title_zh||ch.title_en)}</div><span class="muted">${formatTime(ch.start)}</span></div><div class="muted">${escapeHtml(ch.title_en||'')}</div></button>`).join('')}`}
function renderMain(forceVideo=false){const node=document.getElementById('main-wrap');if(!node)return;if(!state.currentSession){node.innerHTML='<div class="hero panel"><h1>Buffett & Munger Wisdom Archive Review</h1><div class="muted">请先选择左侧视频。</div></div>';return}const chapter=state.currentChapter||state.currentSession.chapters[0];if(forceVideo||!mainVideo()){node.innerHTML=`<div class="toolbar"><div><div class="badge">${escapeHtml(state.currentSession.headline)}</div><h1 style="margin-top:10px">${escapeHtml(state.currentSession.title)}</h1></div><div class="actions"><button onclick="window.showFavorites()">收藏夹</button><button onclick="window.showChapters()">议题</button></div></div><div class="video-shell"><div class="video-card panel" id="video-card"><video id="main-video" controls playsinline preload="metadata" src="${escapeHtml(state.currentVideoPath)}"></video><div class="video-tabs">${state.currentSession.video_options.map(v=>`<button class="video-tab ${('/'+v.path)===state.currentVideoPath?'active':''}" onclick="window.pickVideo('${v.path}')">${escapeHtml(v.label)}</button>`).join('')}</div><div class="chapter-meta" id="chapter-meta"></div><div class="transcript bilingual" id="transcript-panel"></div></div></div>`;state.videoCard=document.getElementById('video-card');ensurePlayers();restoreMainScroll()}else{const tabs=node.querySelector('.video-tabs');if(tabs){tabs.innerHTML=state.currentSession.video_options.map(v=>`<button class="video-tab ${('/'+v.path)===state.currentVideoPath?'active':''}" onclick="window.pickVideo('${v.path}')">${escapeHtml(v.label)}</button>`).join('')}}renderPlayerMeta();renderTranscript();updateFloatingPlayer()}
function renderPlayerMeta(){const node=document.getElementById('chapter-meta');if(!node)return;const chapter=state.currentChapter;node.innerHTML=`<div><div><strong>${chapter?chapter.number+'. '+escapeHtml(chapter.title_zh||chapter.title_en):'未选择议题'}</strong></div><div class="muted">${chapter?escapeHtml(chapter.title_en||''):''}</div><div class="muted">跳转时间 ${chapter?formatTime(chapter.start):'--:--'}</div></div><div style="display:flex;gap:8px"><button class="time-btn" onclick="window.seekCurrentChapter()">跳到本节</button><button class="fav-btn" onclick="window.toggleFavoriteItem()">${favExists()?'取消收藏':'收藏此轮'}</button></div>`;const label=document.getElementById('floating-label');if(label)label.textContent=chapter?`${chapter.number}. ${chapter.title_zh||chapter.title_en}`:''}
function renderTranscript(){const node=document.getElementById('transcript-panel');if(!node)return;const chapter=state.currentChapter;if(!chapter){node.innerHTML='当前议题暂无内容';return}const lines=(chapter.transcript_lines||[]).filter(line=>line.zh||line.en);node.innerHTML=lines.length?lines.map(line=>`<div class="transcript-block"><div class="transcript-line-zh">${escapeHtml(line.zh||'')}</div>${line.en?`<div class="transcript-line-en">${escapeHtml(line.en)}</div>`:''}</div>`).join(''):`<div class="transcript-block"><div class="transcript-line-zh">${escapeHtml(chapter.transcript_zh||'当前议题暂无中文内容')}</div>${chapter.transcript_en?`<div class="transcript-line-en">${escapeHtml(chapter.transcript_en)}</div>`:'<div class="muted" style="margin-top:8px">No English transcript for this chapter.</div>'}</div>`}
function selectSession(slug){state.currentSession=findSession(slug);state.currentChapter=state.currentSession?state.currentSession.chapters[0]||null:null;state.currentVideoPath=state.currentSession?'/' + state.currentSession.default_video:'';state.activePane='chapters';renderLeft();renderMid();renderMain(true);seekMainToChapter(state.currentChapter,false)}
function seekMainToChapter(chapter,autoplay){const video=mainVideo();if(!video||!chapter)return;state.suppressAutoChapterSync=true;const apply=()=>{video.currentTime=chapter.start||0;if(autoplay)video.play().catch(()=>{});setTimeout(()=>{state.suppressAutoChapterSync=false;syncCurrentChapterFromVideo(true);syncFloatingFromMain()},150)};if(video.readyState>=1)apply();else video.addEventListener('loadedmetadata',apply,{once:true})}
function isWithinChapter(time,chapter){if(!chapter)return false;const start=Number(chapter.start||0);const end=Number(chapter.end||Number.POSITIVE_INFINITY);return time>=Math.max(0,start-0.15)&&time<end-0.05}
function jumpToChapter(num,autoplay=true){if(!state.currentSession)return;state.currentChapter=state.currentSession.chapters.find(c=>c.number===num)||state.currentSession.chapters[0]||null;renderMid();renderPlayerMeta();renderTranscript();seekMainToChapter(state.currentChapter,autoplay)}
function findChapterByTime(t){if(!state.currentSession)return null;let active=state.currentSession.chapters[0]||null;for(const ch of state.currentSession.chapters){if(ch.start<=t+0.05)active=ch;else break}return active}
function syncCurrentChapterFromVideo(force=false){const video=mainVideo();if(!video||!state.currentSession)return;const currentTime=video.currentTime||0;if(!force&&isWithinChapter(currentTime,state.currentChapter))return;const active=findChapterByTime(currentTime);if(active&&(!state.currentChapter||active.number!==state.currentChapter.number||force)){state.currentChapter=active;renderMid();renderPlayerMeta();renderTranscript()}}
async function toggleFavorite(){if(!state.currentSession||!state.currentChapter)return;const payload={session_slug:state.currentSession.slug,chapter_number:state.currentChapter.number,title:state.currentChapter.title_zh||state.currentChapter.title_en,start:state.currentChapter.start,transcript_zh:state.currentChapter.transcript_zh||''};const exists=state.favorites.find(f=>f.session_slug===payload.session_slug&&f.chapter_number===payload.chapter_number);await fetch('/api/favorites',{method:exists?'DELETE':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});state.favorites=await fetch('/api/favorites').then(r=>r.json());if(state.activePane==='favorites')renderMid();renderPlayerMeta()}
function favExists(){return !!(state.currentSession&&state.currentChapter&&state.favorites.some(f=>f.session_slug===state.currentSession.slug&&f.chapter_number===state.currentChapter.number))}
function syncFloatingFromMain(){const main=mainVideo(), floating=floatingVideo();if(!main||!floating||state.isSyncingFromFloating)return;const source=main.currentSrc||main.src;if(source&&floating.src!==source)floating.src=source;if(Math.abs((floating.currentTime||0)-(main.currentTime||0))>0.4){try{floating.currentTime=main.currentTime||0}catch(e){}}floating.muted=main.muted;floating.volume=main.volume;if(state.floatingVisible){if(main.paused){floating.pause()}else{floating.play().catch(()=>{})}}}
function syncMainFromFloating(){const main=mainVideo(), floating=floatingVideo();if(!main||!floating||!state.floatingVisible)return;state.isSyncingFromFloating=true;if(Math.abs((main.currentTime||0)-(floating.currentTime||0))>0.4){try{main.currentTime=floating.currentTime||0}catch(e){}}syncCurrentChapterFromVideo(true);setTimeout(()=>{state.isSyncingFromFloating=false},0)}
function updateFloatingPlayer(){const floating=document.getElementById('floating-player');const main=mainVideo(), mini=floatingVideo();if(!floating||!mini||!main||!state.videoCard||!state.mainWrap)return;const hostRect=state.mainWrap.getBoundingClientRect();const rect=state.videoCard.getBoundingClientRect();const offscreen=rect.bottom<hostRect.top+80||rect.top<hostRect.top-40;if(offscreen&&!state.floatingVisible){syncFloatingFromMain();floating.classList.remove('hidden');state.floatingVisible=true;if(!main.paused)mini.play().catch(()=>{})}else if(!offscreen&&state.floatingVisible){if(Math.abs((main.currentTime||0)-(mini.currentTime||0))>0.4){try{main.currentTime=mini.currentTime||0}catch(e){}}if(!mini.paused&&main.paused)main.play().catch(()=>{});floating.classList.add('hidden');state.floatingVisible=false}if(state.floatingVisible)syncFloatingFromMain()}
window.toggleYear=year=>{preserveMainScroll();state.collapsed[year]=!(state.collapsed[year]??false);persist();renderLeft();restoreMainScroll();updateFloatingPlayer()};
window.pickSession=slug=>selectSession(slug);
window.pickChapter=num=>jumpToChapter(num,true);
window.showFavorites=()=>{state.activePane='favorites';renderMid()};
window.showChapters=()=>{state.activePane='chapters';renderMid()};
window.jumpFavorite=(slug,num)=>{selectSession(slug);setTimeout(()=>jumpToChapter(num,true),0)};
window.toggleFavoriteItem=()=>toggleFavorite();
window.seekCurrentChapter=()=>{if(state.currentChapter)jumpToChapter(state.currentChapter.number,true)};
window.pickVideo=path=>{const next='/' + path;if(next===state.currentVideoPath)return;const main=mainVideo();const currentTime=main?main.currentTime||0:(state.currentChapter?.start||0);const shouldPlay=!!(main&&!main.paused);state.currentVideoPath=next;renderMain(true);const video=mainVideo();if(video){const apply=()=>{video.currentTime=currentTime;if(shouldPlay)video.play().catch(()=>{});syncCurrentChapterFromVideo(true)};if(video.readyState>=1)apply();else video.addEventListener('loadedmetadata',apply,{once:true})}};
window.backToMainVideo=()=>{document.getElementById('main-video')?.scrollIntoView({behavior:'smooth',block:'center'})};
load();
"""
    (assets_dir / "style.css").write_text(css, encoding="utf-8")
    (assets_dir / "app.js").write_text(js, encoding="utf-8")
    (web_root / "index.html").write_text(html, encoding="utf-8")


class ReviewRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, db_path=None, **kwargs):
        self.db_path = db_path
        super().__init__(*args, directory=directory, **kwargs)

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/favorites":
            conn = ensure_web_db(Path(self.db_path))
            rows = conn.execute("SELECT session_slug, chapter_number, title, start, transcript_zh, created_at FROM favorites ORDER BY created_at DESC").fetchall()
            conn.close()
            self._json([
                {
                    "session_slug": r[0],
                    "chapter_number": r[1],
                    "title": r[2],
                    "start": r[3],
                    "transcript_zh": r[4],
                    "created_at": r[5],
                }
                for r in rows
            ])
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/favorites":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        conn = ensure_web_db(Path(self.db_path))
        conn.execute(
            "INSERT OR REPLACE INTO favorites(session_slug, chapter_number, title, start, transcript_zh) VALUES (?, ?, ?, ?, ?)",
            (payload["session_slug"], payload["chapter_number"], payload["title"], payload["start"], payload.get("transcript_zh", "")),
        )
        conn.commit()
        conn.close()
        self._json({"ok": True})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/favorites":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        conn = ensure_web_db(Path(self.db_path))
        conn.execute("DELETE FROM favorites WHERE session_slug = ? AND chapter_number = ?", (payload["session_slug"], payload["chapter_number"]))
        conn.commit()
        conn.close()
        self._json({"ok": True})


def serve_review_app(port: int = 8765, open_browser: bool = False):
    catalog = build_catalog()
    write_webapp_assets(WEBAPP, catalog)
    ensure_web_db(WEB_DB).close()

    def handler(*args, **kwargs):
        return ReviewRequestHandler(*args, directory=str(ROOT), db_path=str(WEB_DB), **kwargs)

    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/webapp/index.html"
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    print(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def cleanup_outputs(output_root: Path = OUTPUT, dry_run: bool = False):
    removable_dirs = []
    removable_files = []

    legacy_render = output_root / "1994" / "morning" / "render"
    if legacy_render.exists():
        removable_dirs.append(legacy_render)

    for year_dir in sorted([p for p in output_root.iterdir() if p.is_dir() and p.name.isdigit()]):
        for session_dir in sorted([p for p in year_dir.iterdir() if p.is_dir()]):
            render_dir = session_dir / "render2"
            if not render_dir.exists():
                continue
            for path in render_dir.iterdir():
                name = path.name
                if path.is_dir() and name.endswith("_subtitle_frames"):
                    removable_dirs.append(path)
                    continue
                if not path.is_file():
                    continue
                if name.endswith('.burn.ass') or '.burn.ass.' in name:
                    removable_files.append(path)
                elif name.endswith('.shifted.srt'):
                    removable_files.append(path)
                elif name in {'video_cn_clip.mp4', 'chinese_60s_v2.srt', 'chinese.srt'}:
                    removable_files.append(path)

    removed = []
    seen = set()
    for path in removable_files + removable_dirs:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        removed.append(str(path))
        if dry_run:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    return removed


def main():
    ap = argparse.ArgumentParser(description="Helper CLI for Buffett & Munger Wisdom Archive repo")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list")
    p.add_argument("--year", type=int)

    p = sub.add_parser("read")
    p.add_argument("path")
    p.add_argument("--max-chars", type=int)

    p = sub.add_parser("srt2json")
    p.add_argument("path")

    p = sub.add_parser("clean-srt")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("translate-srt")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--batch-size", type=int, default=12)

    p = sub.add_parser("translate-srt-heuristic")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("translate-preview")
    p.add_argument("input")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--count", type=int, default=12)

    p = sub.add_parser("export-batch")
    p.add_argument("input")
    p.add_argument("out_dir")
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--prefix", default="batch")

    p = sub.add_parser("merge-batch")
    p.add_argument("src_dir")
    p.add_argument("output")

    p = sub.add_parser("clip-srt")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--start-sec", type=float, default=0.0)
    p.add_argument("--duration-sec", type=float)

    p = sub.add_parser("burn-from-srt")
    p.add_argument("video")
    p.add_argument("srt")
    p.add_argument("output")
    p.add_argument("--start")
    p.add_argument("--duration")
    p.add_argument("--keep-frames", action="store_true")
    p.add_argument("--sync-offset-ms", type=int, default=DEFAULT_SYNC_OFFSET_MS)
    p.add_argument("--review", action="store_true", help="兼容旧参数；现在 burn-from-srt 默认总会生成 review")

    p = sub.add_parser("review-burn")
    p.add_argument("video")
    p.add_argument("srt")
    p.add_argument("output")
    p.add_argument("--sync-offset-ms", type=int, default=DEFAULT_SYNC_OFFSET_MS)
    p.add_argument("--review-path")

    p = sub.add_parser("serve-review")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true")

    p = sub.add_parser("cleanup-output")
    p.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()

    if args.cmd == "list":
        print(json.dumps(list_assets(args.year), ensure_ascii=False, indent=2))
    elif args.cmd == "read":
        print(read_text(Path(args.path), args.max_chars))
    elif args.cmd == "srt2json":
        print(json.dumps(parse_srt(Path(args.path)), ensure_ascii=False, indent=2))
    elif args.cmd == "clean-srt":
        clean_srt_file(Path(args.input), Path(args.output))
        print(args.output)
    elif args.cmd == "translate-srt":
        src = Path(args.input)
        dst = Path(args.output)
        entries = parse_srt(src)
        translated = translate_entries(entries, batch_size=args.batch_size)
        dst.write_text(translated, encoding="utf-8")
        print(dst)
    elif args.cmd == "translate-srt-heuristic":
        translate_srt_heuristic(Path(args.input), Path(args.output))
        print(args.output)
    elif args.cmd == "translate-preview":
        translate_preview(Path(args.input), args.start, args.count)
    elif args.cmd == "export-batch":
        export_batch(Path(args.input), Path(args.out_dir), args.batch_size, args.prefix)
        print(args.out_dir)
    elif args.cmd == "merge-batch":
        merge_batches(Path(args.src_dir), Path(args.output))
        print(args.output)
    elif args.cmd == "clip-srt":
        clip_srt(Path(args.input), Path(args.output), start_sec=args.start_sec, duration_sec=args.duration_sec)
        print(args.output)
    elif args.cmd == "burn-from-srt":
        result = burn_from_srt(Path(args.video), Path(args.srt), Path(args.output), args.start, args.duration, keep_frames=args.keep_frames, sync_offset_ms=args.sync_offset_ms)
        review_path, report = review_burn(Path(args.video), Path(result["review_srt"]), Path(args.output), sync_offset_ms=args.sync_offset_ms)
        report["burn_mode"] = result["burn_mode"]
        Path(review_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(review_path)
        print(args.output)
    elif args.cmd == "review-burn":
        review_path, report = review_burn(Path(args.video), Path(args.srt), Path(args.output), Path(args.review_path) if args.review_path else None, sync_offset_ms=args.sync_offset_ms)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(review_path)
    elif args.cmd == "serve-review":
        serve_review_app(port=args.port, open_browser=args.open)
    elif args.cmd == "cleanup-output":
        removed = cleanup_outputs(dry_run=args.dry_run)
        print(json.dumps({"dry_run": args.dry_run, "removed": removed}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
