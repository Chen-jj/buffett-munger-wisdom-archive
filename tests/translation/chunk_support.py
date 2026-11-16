"""Current batch planning/response tests; all inputs are immutable DTOs."""

from dataclasses import replace


from archive_core.interfaces import SourceAlignmentDTO, SourceSentenceDTO, SourceSectionDTO, TimedWordDTO
from archive_core.interfaces import BoundarySource, BoundaryStatus, MatchType, TextSource, TimingSource
from archive_core.interfaces.bilingual import MediaBoundaryDTO, ReadingBudgetDTO, SourceChunkDTO, SourceChunkPlanDTO
from archive_core.interfaces.bilingual_timing import COUNTING_VERSION
from translation.domain import ProviderResponse, ProviderStatus, TranslationGlossary, GlossaryEntry
from translation.domain import plan_translation_requests, validate_provider_response
from translation.domain.planning import matched_glossary


def source(count=3, *, sections=False, sentence_ids=None):
    words = tuple(TimedWordDTO(f"w{i}", f"Word{i}.", (i-1)*1100, (i-1)*1100+1000,
        (f"aw{i}",), (), MatchType.ASR_ONLY, TextSource.ASR, TimingSource.ACOUSTIC_ALIGNMENT)
        for i in range(1,count+1))
    assignments = sentence_ids or tuple(range(1,count+1))
    sentences = []
    for sid in dict.fromkeys(assignments):
        group = [w for w, owner in zip(words,assignments) if owner==sid]
        sentences.append(SourceSentenceDTO(f"s{sid}", group[0].id, group[-1].id,
            group[0].start_ms, group[-1].end_ms, " ".join(w.text for w in group),
            None, TextSource.ASR, BoundarySource.ASR_PUNCTUATION, BoundaryStatus.VERIFIED))
    alignment = SourceAlignmentDTO("en",count*1100, words,tuple(sentences),
        (SourceSectionDTO("sec1","Title","s1",sentences[-1].id),) if sections else ())
    chunks = tuple(SourceChunkDTO(f"k{i}",(word.id,),(f"s{sid}",),word.text,
        word.start_ms,word.end_ms,ReadingBudgetDTO(9,9,0,counting_version=COUNTING_VERSION),())
        for i,(word,sid) in enumerate(zip(words,assignments),1))
    plan = SourceChunkPlanDTO("synthetic:chunks:test","a"*64,MediaBoundaryDTO("b"*64,count*1100,None),
                              {"version":"test","english_max_characters":42,"english_cps_limit":20,
                               "minimum_duration_ms":834,"maximum_duration_ms":7000,
                               "cross_sentence_merge_gap_limit_ms":500,"maximum_extension_ms":500,
                               "chinese_cps_limit":9,"chinese_line_target_units":16,
                               "chinese_counting":COUNTING_VERSION},{"model":"fake"},chunks,(),())
    return alignment,plan


def output(request):
    return {"section":{"id":request.section.id,"translated_title":"标题"} if request.translate_title else None,
            "items":[{"id":item.id,"translated_text":"完整保留全部信息的长译文"} for item in request.items]}
