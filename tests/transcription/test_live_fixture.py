from __future__ import annotations

import pytest

from acquisition.domain import Chapter, Transcript
from tests.transcription.live_fixture import (
    PreparationError,
    parse_timestamp,
    select_hls_segments,
    select_hls_variant,
    select_transcript_chapters,
)


def test_parse_timestamp_supports_requested_cnbc_range() -> None:
    assert parse_timestamp("35:01") == 2101
    assert parse_timestamp("45:24") == 2724
    assert parse_timestamp("1:02:03.5") == 3723.5


def test_select_transcript_chapters_returns_exact_requested_order() -> None:
    transcript = Transcript(
        chapters=(
            Chapter(number=5, title="Before"),
            Chapter(number=6, title='"There\'s nothing magic about a one-year period"'),
            Chapter(
                number=7,
                title='We want a "mathematical edge in every transaction"',
            ),
            Chapter(number=8, title="After"),
        )
    )

    selected = select_transcript_chapters(transcript, (6, 7))

    assert [chapter.number for chapter in selected] == [6, 7]
    assert [chapter.title for chapter in selected] == [
        '"There\'s nothing magic about a one-year period"',
        'We want a "mathematical edge in every transaction"',
    ]


@pytest.mark.parametrize("chapter_numbers", [(7, 6), (6, 8)])
def test_select_transcript_chapters_rejects_non_exact_order_or_gap(
    chapter_numbers: tuple[int, int],
) -> None:
    transcript = Transcript(
        chapters=(
            Chapter(number=6, title="Six"),
            Chapter(number=7, title="Seven"),
        )
    )

    with pytest.raises(PreparationError, match="exact ordered"):
        select_transcript_chapters(transcript, chapter_numbers)


def test_select_hls_variant_uses_highest_bandwidth_at_height_limit() -> None:
    master = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=300000,RESOLUTION=400x224
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=700000,RESOLUTION=640x360
medium.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=900000,RESOLUTION=640x360
better.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1800000,RESOLUTION=1280x720
high.m3u8
"""

    selected = select_hls_variant(master, "https://media.example/master.m3u8", 360)

    assert selected == "https://media.example/better.m3u8"


def test_select_hls_segments_includes_only_intersecting_range() -> None:
    playlist = """#EXTM3U
#EXTINF:3.0,
segment-0.ts
#EXTINF:3.0,
segment-1.ts
#EXTINF:3.0,
segment-2.ts
#EXTINF:3.0,
segment-3.ts
"""

    start, urls = select_hls_segments(
        playlist,
        "https://media.example/path/playlist.m3u8",
        4,
        10,
    )

    assert start == 3
    assert urls == (
        "https://media.example/path/segment-1.ts",
        "https://media.example/path/segment-2.ts",
        "https://media.example/path/segment-3.ts",
    )


def test_select_hls_segments_rejects_range_past_playlist() -> None:
    with pytest.raises(PreparationError, match="exceeds"):
        select_hls_segments(
            "#EXTM3U\n#EXTINF:3.0,\nsegment.ts\n",
            "https://media.example/playlist.m3u8",
            2,
            4,
        )
