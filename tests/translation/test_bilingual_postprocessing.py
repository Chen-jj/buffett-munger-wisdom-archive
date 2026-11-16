"""Editorial batching/source integrity and real anchored timing, never provider or I/O."""

from dataclasses import replace

import pytest

from archive_core.interfaces import reconstruct_sentence_text, SourceSectionDTO

from archive_core.interfaces.bilingual import MediaBoundaryDTO, ProtectedSpanDTO

from tests.translation.chunk_support import source

from translation.domain.postprocessing import Group, editorial_batches, final_cues, merge_allowed, parse_revision, trial



def case(texts=("First.","Second."),times=((0,1000),(1200,2200)),chinese=("甲","乙"),
         *, owners=None,speakers=None,frames=None,duration=3000):
    alignment,chunks=source(len(texts),sentence_ids=owners)
    words=tuple(replace(word,text=text,start_ms=start,end_ms=end) for word,text,(start,end) in zip(alignment.words,texts,times))
    sentences=[]
    for i,sentence in enumerate(alignment.sentences):
        selected=words[int(sentence.first_word_id[1:])-1:int(sentence.last_word_id[1:])]
        sentences.append(replace(sentence,text=reconstruct_sentence_text(selected),start_ms=selected[0].start_ms,
            end_ms=selected[-1].end_ms,speaker_label=speakers[i] if speakers else None))
    alignment=replace(alignment,words=words,sentences=tuple(sentences),audio_duration_ms=duration)
    media=MediaBoundaryDTO("b"*64,duration,tuple(frames) if frames is not None else None)
    chunks=replace(chunks,media=media,chunks=tuple(replace(chunk,english_text=word.text,start_ms=word.start_ms,base_end_ms=word.end_ms)
            for chunk,word in zip(chunks.chunks,words)))
    groups=tuple(Group(chunk.word_ids,text,(chunk.id,)) for chunk,text in zip(chunks.chunks,chinese))
    return alignment,chunks,groups



@pytest.mark.parametrize("base,expected",[(833,834),(834,834),(1000,1334),(6999,6999),(7000,7000),(7001,7001)])
def test_required_extension_is_once_only_and_total_seven_second_cap(base,expected):
    text="甲"*12 if base==1000 else "甲"
    a,k,g=case(("Spoken.",),((0,base),),(text,),duration=max(8000,base+500))
    result=trial(g,a,k.media,k.policy)[0]
    assert result["final_end_ms"]==expected
    assert final_cues(g,a,k.media,k.policy)[0].base_end_ms==base



def test_chinese_need_borrows_only_needed_334_not_full_500():
    a,k,g=case(("Spoken.",),((0,1000),),("甲"*12,),duration=5000)
    assert trial(g,a,k.media,k.policy)[0]["final_end_ms"]==1334



def test_media_tail_and_five_hundred_cap_are_binding():
    a,k,g=case(("Spoken.",),((0,1000),),("甲"*30,),duration=1300)
    assert trial(g,a,k.media,k.policy)[0]["final_end_ms"]==1300
    a,k,g=case(("Spoken.",),((0,1000),),("甲"*30,),duration=5000)
    assert trial(g,a,k.media,k.policy)[0]["final_end_ms"]==1500



def test_missing_frames_for_neighbor_gap_never_borrows_or_claims_pass():
    a,k,g=case(chinese=("甲"*12,"乙"))
    row=trial(g,a,k.media,k.policy)[0]
    assert row["final_end_ms"]==1000 and "frame_gap_unknown" in row["issues"]



def test_exact_frame_budget_retains_two_actual_pts_not_average_fps():
    a,k,g=case(chinese=("甲"*12,"乙"),frames=(0,1000000,1030000,1080000,1160000,1200000,1300000,2200000))
    row=trial(g,a,k.media,k.policy)[0]
    assert row["final_end_ms"]==1080
    assert "short_gap" not in row["issues"]



def test_overlap_is_not_short_gap_warning():
    a,k,g=case()
    # Invalid source times are rejected by the authority DTO, before processing.
    with pytest.raises(ValueError):replace(a,words=(a.words[0],replace(a.words[1],start_ms=900)))



@pytest.mark.parametrize("damage",["missing","duplicate","outside","time","blank","protection"])
def test_model_proposal_must_keep_exact_word_coverage_fields_and_protections(damage):
    a,k,g=case(owners=(1,1))
    response={"status":"proposed","cues":[{"first_word_id":"w1","last_word_id":"w1","translated_text":"甲"},
                                            {"first_word_id":"w2","last_word_id":"w2","translated_text":"乙"}]}
    if damage=="missing":response["cues"].pop()
    elif damage=="duplicate":response["cues"][1]["first_word_id"]="w1"
    elif damage=="outside":response["cues"][1]["last_word_id"]="w3"
    elif damage=="time":response["cues"][0]["start_ms"]=0
    elif damage=="blank":response["cues"][0]["translated_text"]=" "
    elif damage=="protection":k=replace(k,protected_spans=(ProtectedSpanDTO("w1","w2","proper_name"),))
    with pytest.raises(ValueError):parse_revision(response,g,alignment=a,chunks=k)



def test_coverage_feedback_contains_only_a_bounded_preview_of_missing_source_ids():
    a,k=source(8)
    groups=tuple(Group(c.word_ids,"译",(c.id,)) for c in k.chunks)
    response={"status":"proposed","cues":[{"first_word_id":"w8","last_word_id":"w8",
                                          "translated_text":"不应出现在错误中的内容"}]}
    with pytest.raises(ValueError,match=r"; missing \(7\): w1, w2, w3$"):
        parse_revision(response,groups,alignment=a,chunks=k)



@pytest.mark.parametrize("gap,allowed",[(499,True),(500,False)])
def test_cross_original_sentence_merge_gap_is_strict(gap,allowed):
    from translation.domain.postprocessing import merge_allowed
    a,k,g=case(times=((0,1000),(1000+gap,2000+gap)))
    merged=Group(("w1","w2"),"甲乙",("k1","k2"))
    assert merge_allowed(merged,a,k.policy)==allowed



@pytest.mark.parametrize("ranges,allowed",[
    ((("w1","w1"),("w2","w3"),("w4","w4")),False),
    ((("w1","w3"),("w4","w4")),False),
    ((("w1","w1"),("w2","w4")),False),
    ((("w1","w4"),),True),
])
def test_recut_requires_complete_crossed_source_sentences(ranges,allowed):
    a,k,g=case(("One","two.","Three","four."),((0,1000),(1200,2200),(2210,3210),(3400,4400)),
        ("甲","乙","丙","丁"),owners=(1,1,2,2),duration=5000)
    response={"status":"proposed","cues":[
        {"first_word_id":first,"last_word_id":last,"translated_text":"译"} for first,last in ranges]}
    if allowed:
        proposal=parse_revision(response,g,alignment=a,chunks=k)
        assert [cue.word_ids for cue in proposal]==[("w1","w2","w3","w4")]
    else:
        with pytest.raises(ValueError,match="incomplete original sentence"):
            parse_revision(response,g,alignment=a,chunks=k)



def test_known_null_different_known_speakers_cannot_be_bridged():
    from translation.domain.postprocessing import merge_allowed
    a,k,g=case(("One.","Two.","Three."),((0,1000),(1100,2100),(2200,3200)),("甲","乙","丙"),
        speakers=("BUFFETT",None,"MUNGER"),duration=4000)
    assert not merge_allowed(Group(("w1","w2","w3"),"甲乙丙",("k1","k2","k3")),a,k.policy)



def compact_sentences(alignment,chunks):
    result=[]
    for sentence in alignment.sentences:
        words=alignment.words[int(sentence.first_word_id[1:])-1:int(sentence.last_word_id[1:])]
        result.append(replace(chunks.chunks[0],id=f"k{len(result)+1}",word_ids=tuple(w.id for w in words),
            sentence_ids=(sentence.id,),english_text=reconstruct_sentence_text(words),
            start_ms=words[0].start_ms,base_end_ms=words[-1].end_ms))
    return replace(chunks,chunks=tuple(result))


def test_editorial_generation_always_covers_even_warning_free_input_without_merging_first():
    a,k,g=case()
    assert not any(row["issues"] for row in trial(g,a,k.media,k.policy) if row["issues"]!=("frame_gap_unknown",))
    batch,=editorial_batches(k,a)
    assert (batch.first,batch.last)==(0,1)
    assert [group.word_ids for group in g]==[("w1",),("w2",)]


def test_editorial_batches_limit_fifty_initial_cues_without_cutting_sentence_groups():
    a,k=source(51)
    assert [(b.first,b.last) for b in editorial_batches(k,a)]==[(0,49),(50,50)]
    a,k=source(53,sentence_ids=(1,)*51+(2,3))
    assert [(b.first,b.last) for b in editorial_batches(k,a)]==[(0,50),(51,52)]


def test_editorial_word_budget_is_180_with_equality_and_oversize_whole_group_preserved():
    a,k=source(181,sentence_ids=(1,)*90+(2,)*90+(3,))
    k=compact_sentences(a,k)
    assert [(b.first,b.last) for b in editorial_batches(k,a)]==[(0,1),(2,2)]
    a,k=source(181,sentence_ids=(1,)*181)
    assert [(b.first,b.last) for b in editorial_batches(compact_sentences(a,k),a)]==[(0,0)]


def test_editorial_batches_keep_sections_separate_and_connected_sentence_group_atomic(monkeypatch):
    import translation.domain.postprocessing as module
    a,k=source(4)
    a=replace(a,sections=(SourceSectionDTO("sec1","First","s1","s2"),SourceSectionDTO("sec2","Second","s3","s4")))
    assert [(b.first,b.last) for b in editorial_batches(k,a)]==[(0,1),(2,3)]
    a,k=source(4,sentence_ids=(1,2,2,3))
    first=replace(k.chunks[0],word_ids=("w1","w2"),sentence_ids=("s1","s2"),
        english_text=reconstruct_sentence_text(a.words[:2]),base_end_ms=a.words[1].end_ms)
    k=replace(k,chunks=(first,replace(k.chunks[2],id="k2"),replace(k.chunks[3],id="k3")))
    monkeypatch.setattr(module,"EDITORIAL_WORD_LIMIT",2)
    assert [(b.first,b.last) for b in editorial_batches(k,a)]==[(0,1),(2,2)]


def test_editorial_input_group_crossing_section_is_rejected_not_split():
    a,k=source(2)
    a=replace(a,sections=(SourceSectionDTO("sec1","First","s1","s1"),SourceSectionDTO("sec2","Second","s2","s2")))
    merged=replace(k.chunks[0],word_ids=("w1","w2"),sentence_ids=("s1","s2"),
        english_text=reconstruct_sentence_text(a.words),base_end_ms=a.words[-1].end_ms)
    with pytest.raises(ValueError,match="crosses a section"):
        editorial_batches(replace(k,chunks=(merged,)),a)


def test_editorial_candidate_keeps_truthful_even_worse_reading_warnings_instead_of_rejection():
    a,k,g=case(("x"*81,),((0,7001),),("甲",),duration=8000)
    proposed=parse_revision({"status":"proposed","cues":[{
        "first_word_id":"w1","last_word_id":"w1","translated_text":"甲"*80}]},g,alignment=a,chunks=k)
    rows=trial(proposed,a,k.media,k.policy)
    assert {"english_length","base_duration","display_duration","chinese_length","chinese_cps"}<=set(rows[0]["issues"])
    assert final_cues(proposed,a,k.media,k.policy)[0].chinese_text=="甲"*80


def test_editorial_merge_over_english_cps_and_retained_short_gap_are_warnings_not_gates():
    a,k,g=case(("a"*36,"b"*31,"Third."),((0,1000),(1010,2010),(2020,3020)),
        ("甲","乙","丙"),frames=range(0,4000000,40000),duration=4000)
    proposal=parse_revision({"status":"proposed","cues":[
        {"first_word_id":"w1","last_word_id":"w2","translated_text":"甲乙"},
        {"first_word_id":"w3","last_word_id":"w3","translated_text":"丙"}]},g,alignment=a,chunks=k)
    assert {"english_cps","short_gap"}<=set(trial(proposal,a,k.media,k.policy)[0]["issues"])


def test_editorial_recut_can_choose_any_unprotected_boundary_and_whole_cue_source_anchors():
    a,k,g=case(("First","second."),((0,1000),(1200,2200)),owners=(1,1))
    proposal=parse_revision({"status":"proposed","cues":[
        {"first_word_id":"w1","last_word_id":"w2","translated_text":"完整意思"}]},g,alignment=a,chunks=k)
    cue,=final_cues(proposal,a,k.media,k.policy)
    assert (cue.start_ms,cue.base_end_ms,cue.english_text)==(0,2200,"First second.")
    assert cue.initial_chunk_ids==("k1","k2")



def test_english_cps_is_reported_without_creating_extension():
    a,k,g=case(("x"*40,),((0,1000),),("对",),duration=3000)
    row,=trial(g,a,k.media,k.policy)
    assert row["issues"]==("english_cps",) and row["final_end_ms"]==1000
    assert len(editorial_batches(k,a))==1
