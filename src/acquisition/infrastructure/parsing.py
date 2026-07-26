"""Shared parser building blocks for acquisition crawlers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from acquisition.domain import Chapter, SourceMetadata, Transcript


@dataclass(frozen=True)
class HtmlParseKit:
    """Small BeautifulSoup boundary kept out of crawler orchestration."""

    def soup(self, html: str):
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "beautifulsoup4 is required for acquisition HTML parsing"
            ) from exc
        return BeautifulSoup(html, "html.parser")


@dataclass(frozen=True)
class TranscriptNormalizer:
    """Normalize CNBC-style transcript DOM into source-neutral chapters."""

    def from_cnbc_soup(self, soup) -> Transcript:
        body = soup.find("div", class_="Transcript-transcriptBody")
        if body is None:
            return Transcript()

        chapters: list[Chapter] = []
        for chapter_div in body.find_all("div", class_="Chapter-chapter"):
            title_div = chapter_div.find("div", class_="Chapter-chapterTitle")
            title_text = title_div.get_text(" ", strip=True) if title_div else ""
            number, title = _parse_chapter_title(title_text)
            paragraphs = []
            for paragraph_div in chapter_div.find_all(
                "div", class_="ChapterParagraph-chapterParagraph"
            ):
                paragraph = paragraph_div.find("p")
                if paragraph is None:
                    continue
                text = paragraph.get_text(" ", strip=True)
                if text:
                    paragraphs.append(text)
            chapters.append(
                Chapter(number=number, title=title, paragraphs=tuple(paragraphs))
            )
        return Transcript(chapters=tuple(chapters))


@dataclass(frozen=True)
class MetadataExtractor:
    """Extract source metadata without exposing provider page structures."""

    schema_version: str = "acquisition.source-metadata.v1"

    def cnbc(self, soup) -> SourceMetadata:
        raw_metadata = self._cnbc_raw_metadata(soup)
        return SourceMetadata(
            schema_version=self.schema_version,
            title=_string_or_none(raw_metadata.get("title")),
            video_id=_string_or_none(raw_metadata.get("id")),
            raw_metadata=raw_metadata,
        )

    def html_title(self, soup, *, video_id: str | None = None) -> SourceMetadata:
        title = soup.find("title")
        title_text = title.get_text(" ", strip=True) if title else None
        return SourceMetadata(
            schema_version=self.schema_version,
            title=title_text,
            video_id=video_id,
            raw_metadata={},
        )

    def _cnbc_raw_metadata(self, soup) -> dict[str, Any]:
        decoder = json.JSONDecoder()
        for script in soup.find_all("script"):
            text = script.string or script.get_text() or ""
            marker_index = text.find("__CNBC_META_DATA")
            if marker_index < 0:
                continue
            equals_index = text.find("=", marker_index)
            if equals_index < 0:
                continue
            payload = text[equals_index + 1 :].lstrip()
            try:
                data, _ = decoder.raw_decode(payload)
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}
        return {}


def _parse_chapter_title(title_text: str) -> tuple[int, str]:
    match = re.match(r"^(\d+)\s*\.\s*(.+)$", title_text)
    if not match:
        return 0, title_text
    return int(match.group(1)), match.group(2).strip()


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
