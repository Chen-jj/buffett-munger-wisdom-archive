"""Pure current-schema data factories shared by isolated contract and layout tests."""
from archive_core.interfaces.bilingual import FinalBilingualDraftDTO, FinalCueDTO, MediaBoundaryDTO


def source_plan(*, sections=True):
    return FinalBilingualDraftDTO(
        "cnbc:2000:sample", "a" * 64, "d" * 64, "b" * 64,
        MediaBoundaryDTO("c" * 64, 3000, tuple(range(0, 3000000, 40000))),
        {"version": "fixture-policy.v1"},
        (FinalCueDTO("c1", ("w1", "w2"), ("s1",), "We agree.", "我们 同意。", 100, 1000, 1216, ("k1",)),
         FinalCueDTO("c2", ("w3",), ("s2",), "Indeed.", "确实。", 1300, 1800, 2134, ("k2",))), (), (),
    )


def populate_current_chain(case, *, export=True):
    """Populate current public artifacts into a supplied fake store writer."""
    from dataclasses import replace
    from pathlib import Path
    from archive_core.interfaces.bilingual import (ArtifactEvidenceDTO, ChunkTranslationDTO, ChunkTranslationResultDTO,
        ReadingBudgetDTO, SourceChunkDTO, SourceChunkPlanDTO, StageManifestDTO)
    from archive_core.interfaces.translation import SectionTitleTranslationDTO
    from archive_core.interfaces.transcription import SourceAlignmentDTO
    from srt_processing.application.workflow import export_report
    from srt_processing.infrastructure.codec import Pysubs2SrtCodec
    import hashlib
    def evidence(name):
        raw = case.store.read_bytes(case.path(name))
        return ArtifactEvidenceDTO(case.path(name), len(raw), hashlib.sha256(raw).hexdigest())
    alignment = SourceAlignmentDTO.from_dict(case.read("source_alignment.json"))
    sha = evidence("source_alignment.json").sha256
    media = MediaBoundaryDTO(evidence("video.mp4").sha256, 3500, tuple(range(0, 3500000, 40000)))
    case.put("media_boundary.json", media.to_dict())
    chunks = SourceChunkPlanDTO(case.asset_id, sha, media, {"version": "fixture-policy.v1"}, {"engine": "fake"}, (
        SourceChunkDTO("k1", ("w1", "w2"), ("s1",), "We agree.", 100, 1000, ReadingBudgetDTO(8, 10, 220), ()),
        SourceChunkDTO("k2", ("w3",), ("s2",), "Indeed.", 1300, 1800, ReadingBudgetDTO(4, 9, 500), ("timing.minimum_duration",))), (), ())
    case.put("source_chunks.json", chunks.to_dict())
    case.put("source_chunking_report.json", {"status": "succeeded"})
    def stage(name, filename, inputs, outputs):
        item = StageManifestDTO(name, case.asset_id, {key: evidence(value) for key, value in inputs.items()},
                                {key: evidence(value) for key, value in outputs.items()}, {"version": "fixture.v1"}, "2026-11-05T00:00:00Z", {})
        case.put(filename, item.to_dict())
    base = {"transcription_manifest": "transcription_manifest.json", "source_alignment": "source_alignment.json", "media_boundary": "media_boundary.json", "video": "video.mp4"}
    stage("source_chunking", "source_chunking_manifest.json", base, {"source_chunks": "source_chunks.json", "report": "source_chunking_report.json"})
    titles = (SectionTitleTranslationDTO("sec1", "问题"),) if alignment.sections else ()
    translation = ChunkTranslationResultDTO(case.asset_id, sha, evidence("source_chunks.json").sha256,
        (ChunkTranslationDTO("k1", "我们 同意。"), ChunkTranslationDTO("k2", "确实。")), titles)
    case.put("translation_result.json", translation.to_dict())
    translated_inputs = {**base, "source_chunks": "source_chunks.json", "source_chunking_manifest": "source_chunking_manifest.json"}
    stage("translation", "translation_manifest.json", translated_inputs, {"translation_result": "translation_result.json"})
    source = replace(source_plan(), asset_id=case.asset_id, source_alignment_sha256=sha,
                     source_chunks_sha256=evidence("source_chunks.json").sha256,
                     translation_result_sha256=evidence("translation_result.json").sha256, media=media, section_titles=titles)
    source.validate_against_inputs(alignment, chunks, translation)
    case.put("final_bilingual_draft.json", source.to_dict())
    case.put("bilingual_postprocessing_report.json", {"status": "succeeded"})
    final_inputs = {**translated_inputs, "translation_result": "translation_result.json", "translation_manifest": "translation_manifest.json"}
    stage("bilingual_postprocessing", "bilingual_postprocessing_manifest.json", final_inputs,
          {"final_bilingual_draft": "final_bilingual_draft.json", "report": "bilingual_postprocessing_report.json"})
    if not export:
        return source
    case.put("srt_processing_report.json", export_report(source))
    codec = Pysubs2SrtCodec()
    for language in ("english", "chinese", "bilingual"):
        case.put(language + ".srt", codec.encode(source, language))
    stage("srt_export", "srt_processing_manifest.json", {**final_inputs, "final_bilingual_draft": "final_bilingual_draft.json", "bilingual_postprocessing_manifest": "bilingual_postprocessing_manifest.json"},
          {"english_srt": "english.srt", "chinese_srt": "chinese.srt", "bilingual_srt": "bilingual.srt", "report": "srt_processing_report.json"})


from archive_core.interfaces.transcription import (SourceAlignmentDTO, SourceSentenceDTO, SourceSectionDTO, TimedWordDTO, MatchType, TextSource, TimingSource, BoundarySource, BoundaryStatus)

def alignment(*, sections: bool = True, last_speaker: str | None = "BUFFETT") -> SourceAlignmentDTO:
    texts = ("We", "agree.", "Indeed.")
    words = tuple(TimedWordDTO(
        id=f"w{i + 1}", text=text, start_ms=start, end_ms=end,
        asr_word_ids=(f"a{i + 1}",), official_token_ids=(f"o{i + 1}",),
        match_type=MatchType.EXACT, text_source=TextSource.OFFICIAL_TRANSCRIPT,
        timing_source=TimingSource.ACOUSTIC_ALIGNMENT,
    ) for i, (text, start, end) in enumerate(zip(texts, (100, 400, 1300), (350, 1000, 1800), strict=True)))
    sentences = (
        SourceSentenceDTO("s1", "w1", "w2", 100, 1000, "We agree.", None,
                          TextSource.OFFICIAL_TRANSCRIPT, BoundarySource.FUSED_PUNCTUATION, BoundaryStatus.VERIFIED),
        SourceSentenceDTO("s2", "w3", "w3", 1300, 1800, "Indeed.", last_speaker,
                          TextSource.OFFICIAL_TRANSCRIPT, BoundarySource.FUSED_PUNCTUATION, BoundaryStatus.VERIFIED),
    )
    return SourceAlignmentDTO("en", 3000, words, sentences,
                              (SourceSectionDTO("sec1", "Question", "s1", "s2"),) if sections else ())



def acoustic_alignment_rows(source: SourceAlignmentDTO) -> list[dict]:
    """Represent the isolated fixture's words before transcript fusion."""
    return [
        {"id": f"aw{index}", "raw_word_id": f"rw{index}", "segment_id": "seg1",
         "text": word.text, "start_ms": word.start_ms, "end_ms": word.end_ms,
         "alignment_score": 0.9, "timing_source": "acoustic_alignment"}
        for index, word in enumerate(source.words, 1)
    ]
