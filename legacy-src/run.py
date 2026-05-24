#!/usr/bin/env python3
"""
伯克希尔股东大会中文字幕自动化工具 - 一键运行入口

用法:
    python run.py --year 1994              # 处理指定年份
    python run.py --year-range 1994 2000   # 处理年份范围
    python run.py --all                    # 处理所有年份
    python run.py --year 1994 --step 3     # 从第 3 步开始
    python run.py --year 1994 --srt en.srt # 使用已有 SRT
"""

import argparse
import json
from pathlib import Path

import yaml

from src.step0_crawl import crawl_year, get_all_years, get_session, load_config
from src.step1_download import download_year
from src.step2_align import align_year
from src.step3_translate import translate_year
from src.step4_burn import burn_year


STEPS = {
    0: ("爬取 CNBC 页面", crawl_year),
    1: ("下载视频 (yt-dlp)", download_year),
    2: ("时间轴对齐 (WhisperX)", align_year),
    3: ("翻译字幕 (LLM)", translate_year),
    4: ("烧录硬字幕 (FFmpeg)", burn_year),
}


def process_year(year, config, start_step=0, srt_path=None, video_path=None):
    """处理单个年份的完整流程"""
    print(f"\n{'='*60}")
    print(f"🎬 Processing {year} Berkshire Hathaway Annual Meeting")
    print(f"{'='*60}")

    output_dir = Path("output") / str(year)

    # 如果提供了自定义 SRT，跳到翻译步骤
    if srt_path:
        srt_path = Path(srt_path)
        if not srt_path.exists():
            print(f"❌ SRT file not found: {srt_path}")
            return

        # 需要先有 metadata
        if not (output_dir / "metadata.json").exists():
            crawl_year(year, config)

        # 复制 SRT 到各 session 目录
        with open(output_dir / "metadata.json") as f:
            metadata = json.load(f)
        for session_name in metadata["sessions"]:
            sess_dir = output_dir / session_name
            sess_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(srt_path, sess_dir / "english.srt")

        start_step = max(start_step, 3)

    # 如果提供了自定义视频路径
    if video_path:
        video_path = Path(video_path)
        if not video_path.exists():
            print(f"❌ Video file not found: {video_path}")
            return

        if not (output_dir / "metadata.json").exists():
            crawl_year(year, config)

        with open(output_dir / "metadata.json") as f:
            metadata = json.load(f)
        for session_name in metadata["sessions"]:
            sess_dir = output_dir / session_name
            sess_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(video_path, sess_dir / "video.mp4")

    # 执行流程
    for step_num, (step_name, step_func) in STEPS.items():
        if step_num < start_step:
            print(f"\n⏩ Skipping Step {step_num}: {step_name}")
            continue

        print(f"\n📌 Step {step_num}: {step_name}")
        print(f"{'─'*40}")

        try:
            step_func(year, config)
        except Exception as e:
            print(f"❌ Step {step_num} failed: {e}")
            print(f"   You can retry from this step with: python run.py --year {year} --step {step_num}")
            return False

    print(f"\n🎉 {year} processing complete!")
    print(f"   Output: output/{year}/*/video_中文字幕.mp4")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="伯克希尔股东大会中文字幕自动化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run.py --year 1994              # 处理 1994 年
  python run.py --year 1994 --step 3     # 从翻译步骤开始
  python run.py --year-range 1994 2000   # 处理 1994-2000 年
  python run.py --all                    # 处理所有年份
  python run.py --year 1994 --srt en.srt # 使用已有 SRT 文件
        """
    )
    parser.add_argument("--year", type=int, help="处理指定年份")
    parser.add_argument("--year-range", type=int, nargs=2, metavar=("START", "END"),
                        help="处理年份范围")
    parser.add_argument("--all", action="store_true", help="处理所有年份 (1994-2025)")
    parser.add_argument("--step", type=int, default=0, choices=[0,1,2,3,4],
                        help="从第 N 步开始 (0=爬取, 1=下载, 2=对齐, 3=翻译, 4=烧录)")
    parser.add_argument("--srt", type=str, help="使用已有的英语 SRT 文件")
    parser.add_argument("--video", type=str, help="使用已有的视频文件")

    args = parser.parse_args()
    config = load_config()

    if args.year:
        process_year(args.year, config, args.step, args.srt, args.video)

    elif args.year_range:
        start, end = args.year_range
        for y in range(start, end + 1):
            success = process_year(y, config, args.step, args.srt, args.video)
            if not success:
                print(f"\n⚠️  Stopped at {y} due to error. Fix and retry with --year {y}")
                break

    elif args.all:
        session = get_session(config)
        years = get_all_years(session)
        for y in years:
            process_year(y, config, args.step, args.srt, args.video)

    else:
        parser.print_help()
        print("\n💡 快速开始: python run.py --year 1994")


if __name__ == "__main__":
    main()
