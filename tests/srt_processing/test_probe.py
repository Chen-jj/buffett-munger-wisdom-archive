"""Source chunking consumes public decoded-frame evidence, never probes media."""
from archive_core.interfaces.bilingual import MediaBoundaryDTO
from srt_processing.domain.chunking import reading_budget


def test_chunking_keeps_two_actual_frames_instead_of_assuming_average_fps():
    media = MediaBoundaryDTO("a" * 64, 2400, (1207500, 1299000, 1300000))
    budget, issues = reading_budget(media, 0, 1000, 1300)
    assert budget.extension_ms == 207
    assert budget.base_units == 9 and budget.maximum_units == 10
    assert not issues


def test_chunking_does_not_borrow_when_frame_evidence_is_unknown():
    media = MediaBoundaryDTO("a" * 64, 2400, None)
    budget, issues = reading_budget(media, 0, 1000, 1300)
    assert budget.extension_ms == 0
    assert budget.base_units == budget.maximum_units == 9
    assert issues == ("timing.frame_gap_unverified",)


def test_one_actual_frame_is_not_misreported_as_two():
    media = MediaBoundaryDTO("a" * 64, 2400, (999000, 1200000, 1300000))
    budget, issues = reading_budget(media, 0, 1000, 1300)
    assert budget.extension_ms == 0
    assert issues == ("timing.short_frame_gap",)
