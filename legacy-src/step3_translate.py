"""
Step 3: 使用 LLM 将英文 SRT 翻译为中文 SRT
支持 OpenAI API 及任何兼容接口（Ollama、vLLM 等）。
"""

import re
import json
import argparse
from pathlib import Path

import yaml
import pysubs2
from openai import OpenAI


def load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_client(config):
    """创建 OpenAI 兼容客户端"""
    trans_config = config["translation"]["openai"]
    kwargs = {"api_key": trans_config["api_key"]}
    if trans_config.get("base_url"):
        kwargs["base_url"] = trans_config["base_url"]
    return OpenAI(**kwargs)


TRANSLATE_SYSTEM_PROMPT = """你是一名专业的中英翻译专家，专注于巴菲特和芒格在伯克希尔·哈撒韦股东大会上的发言翻译。

翻译要求：
1. 翻译成自然流畅的中文，保持口语化风格
2. 保留说话人标记（如 "WARREN BUFFETT:" → "沃伦·巴菲特："）
3. 金融/投资术语使用标准中文译法
4. 单行字幕不超过 20 个汉字，必要时拆行
5. 保持原文的幽默感和语气
6. "(Laughter)" → "（笑声）"，"(Applause)" → "（掌声）"

常见人名对照：
- Warren Buffett → 沃伦·巴菲特
- Charlie Munger → 查理·芒格
- Greg Abel → 格雷格·阿贝尔
- Ajit Jain → 阿吉特·贾因
- Berkshire Hathaway → 伯克希尔·哈撒韦"""

TRANSLATE_USER_PROMPT = """请将以下 SRT 字幕翻译为中文。严格保持序号和时间轴不变，只翻译文本行。

{srt_content}"""


def translate_batch(client, model, srt_entries, temperature=0.1):
    """翻译一批 SRT 条目"""
    # 构造待翻译的 SRT 文本
    srt_text = ""
    for entry in srt_entries:
        srt_text += f"{entry['index']}\n"
        srt_text += f"{entry['timestamp']}\n"
        srt_text += f"{entry['text']}\n\n"

    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": TRANSLATE_USER_PROMPT.format(srt_content=srt_text.strip())}
        ]
    )

    translated = response.choices[0].message.content.strip()
    return translated


def parse_srt(srt_path):
    """解析 SRT 文件为条目列表"""
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()

    entries = []
    # SRT 格式: index\ntimestamp\ntext\n\n
    blocks = re.split(r"\n\n+", content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) >= 3:
            entries.append({
                "index": lines[0].strip(),
                "timestamp": lines[1].strip(),
                "text": "\n".join(lines[2:]).strip()
            })

    return entries


def write_srt(entries_text, output_path):
    """将翻译后的文本写入 SRT 文件"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(entries_text)


def translate_srt(srt_path, output_path, config):
    """翻译整个 SRT 文件"""
    trans_config = config["translation"]["openai"]
    model = trans_config.get("model", "gpt-4o")
    temperature = trans_config.get("temperature", 0.1)
    batch_size = trans_config.get("batch_size", 15)

    client = get_client(config)
    entries = parse_srt(srt_path)

    if not entries:
        print("  ❌ No SRT entries found")
        return None

    print(f"  → Translating {len(entries)} entries in batches of {batch_size}...")

    all_translated = []
    translated_any = False
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(entries) + batch_size - 1) // batch_size
        print(f"    Batch {batch_num}/{total_batches} ({len(batch)} entries)...")

        try:
            translated = translate_batch(client, model, batch, temperature)
            all_translated.append(translated)
            translated_any = True
        except Exception as e:
            print(f"    ❌ Translation error: {e}")
            # 保留原文作为 fallback
            fallback = ""
            for entry in batch:
                fallback += f"{entry['index']}\n{entry['timestamp']}\n{entry['text']}\n\n"
            all_translated.append(fallback)

    if not translated_any:
        print("  ❌ All translation batches failed; not writing fallback-only chinese.srt")
        return None

    # 合并所有翻译结果
    final_text = "\n\n".join(all_translated)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_text)

    print(f"  ✅ Translation complete: {output_path}")
    return output_path


def translate_year(year, config=None):
    """翻译指定年份的所有 SRT"""
    if config is None:
        config = load_config()

    output_dir = Path("output") / str(year)
    metadata_path = output_dir / "metadata.json"

    if not metadata_path.exists():
        print(f"❌ No metadata for {year}. Run step0_crawl first.")
        return

    with open(metadata_path) as f:
        metadata = json.load(f)

    for session_name in metadata["sessions"]:
        sess_dir = output_dir / session_name
        english_srt = sess_dir / "english.srt"
        chinese_srt = sess_dir / "chinese.srt"

        if chinese_srt.exists():
            print(f"  ⏩ Chinese SRT already exists: {chinese_srt}")
            continue

        if not english_srt.exists():
            print(f"  ❌ English SRT not found: {english_srt}. Run step2_align first.")
            continue

        print(f"🌐 Translating {year} {session_name}...")
        translate_srt(english_srt, chinese_srt, config)


def main():
    parser = argparse.ArgumentParser(description="Translate English SRT to Chinese")
    parser.add_argument("--year", type=int, required=True)
    args = parser.parse_args()

    config = load_config()
    translate_year(args.year, config)


if __name__ == "__main__":
    main()
