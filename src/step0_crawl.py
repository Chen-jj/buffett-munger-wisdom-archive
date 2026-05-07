"""
Step 0: 爬取 CNBC Buffett Archive
- 从年会列表页获取所有年份
- 从年会页面获取 morning/afternoon session 视频页面链接
- 从视频页面提取英文逐字稿 + 章节信息
"""

import re
import json
import time
import argparse
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import yaml


def load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_session(config):
    s = requests.Session()
    s.headers.update({
        "User-Agent": config.get("crawl", {}).get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
    })
    return s


def get_all_years(session):
    """从列表页获取所有年份 URL"""
    url = "https://buffett.cnbc.com/annual-meetings/"
    resp = session.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    years = {}
    for link in soup.find_all("a", href=True):
        href = link["href"]
        m = re.search(r"/(\d{4})-berkshire-hathaway-annual-meeting/?", href)
        if m:
            year = int(m.group(1))
            full_url = href if href.startswith("http") else f"https://buffett.cnbc.com{href}"
            years[year] = full_url

    return dict(sorted(years.items()))


def get_session_pages(session, year_url, delay=1.0):
    """从年会页面获取 morning/afternoon session 的视频页面链接"""
    resp = session.get(year_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    sessions = {}
    for link in soup.find_all("a", href=True):
        href = link["href"]
        full_url = href if href.startswith("http") else f"https://buffett.cnbc.com{href}"

        # 只匹配视频页面（/video/ 路径）
        if "/video/" not in href:
            continue

        href_lower = href.lower()
        link_text = link.get_text(strip=True).lower()

        # 判断 session 类型（URL 或链接文本中包含关键词）
        is_morning = "morning" in href_lower or "morning" in link_text
        is_afternoon = "afternoon" in href_lower or "afternoon" in link_text
        is_highlight = "highlight" in href_lower or "highlight" in link_text

        if is_morning:
            sessions["morning"] = full_url
        elif is_afternoon:
            sessions["afternoon"] = full_url
        elif is_highlight:
            if "highlight" not in sessions:
                sessions["highlight"] = full_url

    time.sleep(delay)
    return sessions


def extract_transcript(session, video_page_url, delay=1.0):
    """
    从视频页面提取英文逐字稿和章节信息。

    CNBC 页面 HTML 结构：
    - div.Transcript-transcriptBody
      - div.Transcript-transcriptChaptersWrapper
        - div.Chapter-chapter (每个章节)
          - div.Chapter-chapterTitle  →  "N.Title"
          - div.Chapter-chapterContent
            - div.ChapterParagraph-chapterParagraph (每段)
              - p (speaker + text content)
              - div.ChapterParagraph-chapterParagraphToolTip (Sync button, skip)
    """
    resp = session.get(video_page_url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 提取 __CNBC_META_DATA
    meta = {}
    for script in soup.find_all("script"):
        text = script.string or ""
        if "__CNBC_META_DATA" in text:
            m = re.search(r"__CNBC_META_DATA\s*=\s*(\{.+?\})\s*;", text, re.DOTALL)
            if m:
                try:
                    meta = json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
            break

    # 提取逐字稿
    body = soup.find("div", class_="Transcript-transcriptBody")
    if not body:
        print(f"    ⚠️  No transcript body found on page")
        return {
            "meta": meta,
            "chapters": [],
            "full_transcript": "",
            "video_page_url": video_page_url
        }

    chapters = []
    chapter_divs = body.find_all("div", class_="Chapter-chapter")

    for ch_div in chapter_divs:
        # 提取章节标题
        title_div = ch_div.find("div", class_="Chapter-chapterTitle")
        title_text = title_div.get_text(strip=True) if title_div else ""

        # 解析章节编号和标题
        ch_match = re.match(r"^(\d+)\.\s*(.+)$", title_text)
        if ch_match:
            ch_number = int(ch_match.group(1))
            ch_title = ch_match.group(2).strip()
        else:
            ch_number = 0
            ch_title = title_text

        # 提取段落
        paragraphs = []
        para_divs = ch_div.find_all("div", class_="ChapterParagraph-chapterParagraph")

        for para_div in para_divs:
            # 文本在 <p> 标签中，跳过 Sync Video to Paragraph 按钮
            p_tag = para_div.find("p")
            if p_tag:
                text = p_tag.get_text(strip=True)
                if text:
                    paragraphs.append(text)

        chapters.append({
            "number": ch_number,
            "title": ch_title,
            "paragraphs": paragraphs
        })

    # 生成完整逐字稿文本
    full_transcript_lines = []
    for ch in chapters:
        full_transcript_lines.append(f"\n=== Chapter {ch['number']}: {ch['title']} ===\n")
        for p in ch["paragraphs"]:
            full_transcript_lines.append(p)
            full_transcript_lines.append("")

    time.sleep(delay)
    return {
        "meta": meta,
        "chapters": chapters,
        "full_transcript": "\n".join(full_transcript_lines),
        "video_page_url": video_page_url
    }


def crawl_year(year, config=None):
    """爬取指定年份的所有数据"""
    if config is None:
        config = load_config()

    delay = config.get("crawl", {}).get("delay", 1.0)
    session = get_session(config)
    output_dir = Path("output") / str(year)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"📡 Crawling {year} Berkshire Hathaway Annual Meeting...")

    # 获取年会页面
    year_url = f"https://buffett.cnbc.com/{year}-berkshire-hathaway-annual-meeting/"
    print(f"  → Fetching year page: {year_url}")

    # 获取 session 页面链接
    session_pages = get_session_pages(session, year_url, delay)
    print(f"  → Found sessions: {list(session_pages.keys())}")

    # 如果有 morning/afternoon，跳过 highlight
    has_full_session = "morning" in session_pages or "afternoon" in session_pages

    metadata = {
        "year": year,
        "year_url": year_url,
        "sessions": {}
    }

    for session_name, video_url in session_pages.items():
        # 跳过 highlight reel（如果有完整 session）
        if session_name == "highlight" and has_full_session:
            continue

        print(f"  → Extracting transcript for {session_name}: {video_url}")
        sess_dir = output_dir / session_name
        sess_dir.mkdir(parents=True, exist_ok=True)

        result = extract_transcript(session, video_url, delay)

        # 保存逐字稿
        transcript_path = sess_dir / "transcript.txt"
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(result["full_transcript"])

        # 保存章节信息
        chapters_path = sess_dir / "chapters.json"
        with open(chapters_path, "w", encoding="utf-8") as f:
            json.dump(result["chapters"], f, indent=2, ensure_ascii=False)

        # 保存元信息
        meta_path = sess_dir / "meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(result["meta"], f, indent=2, ensure_ascii=False)

        metadata["sessions"][session_name] = {
            "video_page_url": video_url,
            "video_id": result["meta"].get("id"),
            "title": result["meta"].get("title"),
            "chapter_count": len(result["chapters"]),
            "transcript_length": len(result["full_transcript"])
        }

        print(f"    ✅ {len(result['chapters'])} chapters, "
              f"{len(result['full_transcript'])} chars transcript saved")

    # 保存年份元信息
    with open(output_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"✅ {year} crawl complete → {output_dir}/")
    return metadata


def main():
    parser = argparse.ArgumentParser(description="Crawl CNBC Buffett Archive")
    parser.add_argument("--year", type=int, help="Specific year to crawl")
    parser.add_argument("--all", action="store_true", help="Crawl all years")
    parser.add_argument("--year-range", type=int, nargs=2, help="Year range (start end)")
    parser.add_argument("--list-years", action="store_true", help="List all available years")
    args = parser.parse_args()

    config = load_config()

    if args.list_years:
        session = get_session(config)
        years = get_all_years(session)
        print(f"Available years ({len(years)}):")
        for y, url in years.items():
            print(f"  {y}: {url}")
        return

    if args.year:
        crawl_year(args.year, config)
    elif args.year_range:
        for y in range(args.year_range[0], args.year_range[1] + 1):
            try:
                crawl_year(y, config)
            except Exception as e:
                print(f"❌ Error crawling {y}: {e}")
    elif args.all:
        session = get_session(config)
        years = get_all_years(session)
        for y in years:
            try:
                crawl_year(y, config)
            except Exception as e:
                print(f"❌ Error crawling {y}: {e}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
