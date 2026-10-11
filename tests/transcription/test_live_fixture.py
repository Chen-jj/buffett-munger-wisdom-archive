from __future__ import annotations

import pytest

from tests.transcription.live_fixture import (
    PreparationError,
    parse_timestamp,
    select_hls_segments,
    select_hls_variant,
)


def test_parse_timestamp_supports_requested_cnbc_range() -> None:
    assert parse_timestamp("11:48") == 708
    assert parse_timestamp("21:40") == 1300
    assert parse_timestamp("1:02:03.5") == 3723.5


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
