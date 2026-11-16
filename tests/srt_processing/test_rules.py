"""Current bilingual counting and exact frame-gap timing rules."""
import pytest
from archive_core.interfaces.bilingual import MediaBoundaryDTO
from archive_core.interfaces.bilingual_timing import chinese_half_units, english_characters, empty_frame_count, maximum_extension_ms
from srt_processing.domain.chunking import chunk_issues


@pytest.mark.parametrize("text,chinese", [
    ("中文。",6), ("A 1,%",5), ("Ａ１，",6), ("café",2), ("cafe\u0301",2),
    ("\U00020000",2), ("\u0661\u0662",2), ("ｶﾀｶﾅ",4), ("\u03a9",2),
    ("👩🏽\u200d💻",4), ("✈️",2), ("\U0010ffff",2), ("\t\n\u00a0\u3000",0),
    ("\uffbf",2), ("",0),
])
def test_fixed_counts_and_independent_english_capacity(text,chinese):
    assert chinese_half_units(text) == chinese
    assert english_characters(text) == len(text)


@pytest.mark.parametrize("end,next_start,expected", [(1000,1100,2),(1001,1100,1),(1001,1080,0),(1000,1000,0)])
def test_empty_frames_are_actual_half_open_pts(end,next_start,expected):
    media = MediaBoundaryDTO("a"*64,2000,(1000000,1080000,1100000))
    assert empty_frame_count(media,end,next_start) == expected


@pytest.mark.parametrize("start,end,next_start,frames,expected", [
    (0,1000,1600,(1490000,1550000),490),
    (0,1000,1600,(1510000,1550000),500),
    (0,1000,1600,None,0),
    (0,6900,None,None,100),
    (1000,7800,None,None,200),
    (1000,7800,7900,(7820000,7870000),20),
])
def test_budget_is_bounded_by_real_frames_total_time_and_media(start,end,next_start,frames,expected):
    media = MediaBoundaryDTO("a"*64,8000,frames)
    assert maximum_extension_ms(media,start,end,next_start) == expected


def test_english_cps_threshold_uses_unrounded_integer_comparison():
    assert "reading.english_cps" not in chunk_issues("x"*20,1000)
    assert "reading.english_cps" in chunk_issues("x"*20,999)
