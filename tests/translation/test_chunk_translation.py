"""Current batch planning/response tests; all inputs are immutable DTOs."""

from dataclasses import replace

import pytest

from archive_core.interfaces import SourceAlignmentDTO, SourceSentenceDTO, SourceSectionDTO, TimedWordDTO
from archive_core.interfaces import BoundarySource, BoundaryStatus, MatchType, TextSource, TimingSource
from archive_core.interfaces.bilingual import MediaBoundaryDTO, ReadingBudgetDTO, SourceChunkDTO, SourceChunkPlanDTO
from archive_core.interfaces.bilingual_timing import COUNTING_VERSION
from translation.domain import ProviderResponse, ProviderStatus, TranslationGlossary, GlossaryEntry
from translation.domain import plan_translation_requests, validate_provider_response
from translation.domain.planning import matched_glossary


from tests.translation.chunk_support import source, output


def test_fifty_limit_never_splits_a_complete_sentence_group():
    alignment,chunks=source(51,sentence_ids=tuple(range(1,49))+(49,49,49))
    requests=plan_translation_requests(alignment,chunks)
    assert [len(r.items) for r in requests]==[48,3]
    assert [r.items[0].id for r in requests]==["k1","k49"]


def test_cross_sentence_chunk_closure_and_over_fifty_group_are_indivisible():
    alignment,chunks=source(53,sentence_ids=(1,)*51+(2,3))
    requests=plan_translation_requests(alignment,chunks)
    assert [len(r.items) for r in requests]==[51,2]
    alignment,chunks=source(4)
    first,second=chunks.chunks[:2]
    merged=replace(first,word_ids=first.word_ids+second.word_ids,sentence_ids=("s1","s2"),
        english_text=first.english_text+" "+second.english_text,base_end_ms=second.base_end_ms)
    chunks=replace(chunks,chunks=tuple(replace(c,id=f"k{i}") for i,c in enumerate((merged,)+chunks.chunks[2:],1)))
    assert len(plan_translation_requests(alignment,chunks)[0].items)==3


def test_section_context_is_complete_title_task_only_first_batch_and_budgets_unchanged():
    alignment,chunks=source(51,sections=True)
    requests=plan_translation_requests(alignment,chunks)
    assert [len(r.items) for r in requests]==[50,1]
    assert [r.translate_title for r in requests]==[True,False]
    assert len(requests[1].readonly_context)==51
    assert requests[0].items[0].to_dict()["budget"]==chunks.chunks[0].budget.to_dict()
    assert validate_provider_response(requests[0],ProviderResponse(ProviderStatus.COMPLETED,output(requests[0]),1))
    assert validate_provider_response(requests[1],ProviderResponse(ProviderStatus.COMPLETED,output(requests[1]),1))


def test_unsectioned_context_has_three_previous_and_two_following_sentences():
    alignment,chunks=source(55)
    requests=plan_translation_requests(alignment,chunks)
    assert [v["id"] for v in requests[0].readonly_context][-1]=="s52"
    assert [v["id"] for v in requests[1].readonly_context][0]=="s48"


def test_terms_match_only_target_text_case_insensitive_whole_word():
    glossary=TranslationGlossary((GlossaryEntry("word51","目标"),GlossaryEntry("Word5","五")))
    alignment,chunks=source(51)
    requests=plan_translation_requests(alignment,chunks,glossary)
    assert requests[0].glossary==({"source":"Word5","target":"五"},)
    assert requests[1].glossary==({"source":"word51","target":"目标"},)
    assert not matched_glossary("foreword51",TranslationGlossary((GlossaryEntry("word51","目标"),)))


def test_terms_prefer_full_names_but_keep_separate_short_alias_occurrences():
    glossary = TranslationGlossary((
        GlossaryEntry("Berkshire", "伯克希尔"),
        GlossaryEntry("Berkshire Hathaway", "伯克希尔·哈撒韦"),
        GlossaryEntry("Buffett", "巴菲特"),
        GlossaryEntry("Buffett Limited Partnership", "巴菲特有限合伙公司"),
        GlossaryEntry("Gillette", "吉列"),
    ))
    assert matched_glossary(
        "BERKSHIRE HATHAWAY’s stake and Buffett Limited Partnership.", glossary
    ) == (glossary.entries[1].to_dict(), glossary.entries[3].to_dict())
    assert matched_glossary(
        "Berkshire Hathaway, Berkshire, and Gillette's shares.", glossary
    ) == tuple(glossary.entries[i].to_dict() for i in (0, 1, 4))


def test_terms_match_apostrophe_variants_but_do_not_infer_misrecognized_names():
    entry = GlossaryEntry("See's Candy", "喜诗糖果")
    glossary = TranslationGlossary((entry,))
    assert matched_glossary("See’s Candy has a moat.", glossary) == (entry.to_dict(),)
    assert not matched_glossary("Seas Candy has a moat.", glossary)


@pytest.mark.parametrize("damage", ["missing","duplicate","order","extra","blank","title"])
def test_responses_reject_missing_duplicate_order_extra_blank_or_unrequested_title(damage):
    alignment,chunks=source()
    request=plan_translation_requests(alignment,chunks)[0]
    response=output(request)
    if damage=="missing":response["items"].pop()
    elif damage=="duplicate":response["items"][1]["id"]="k1"
    elif damage=="order":response["items"].reverse()
    elif damage=="extra":response["items"][0]["english"]="Word1."
    elif damage=="blank":response["items"][0]["translated_text"]=" "
    elif damage=="title":response["section"]={"id":"sec1","translated_title":"标题"}
    with pytest.raises(ValueError):
        validate_provider_response(request,ProviderResponse(ProviderStatus.COMPLETED,response,1))


def test_long_translation_is_not_rejected_for_budget():
    alignment,chunks=source()
    request=plan_translation_requests(alignment,chunks)[0]
    response=output(request)
    assert len(validate_provider_response(request,ProviderResponse(ProviderStatus.COMPLETED,response,1)).items)==3
