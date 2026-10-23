from dataclasses import replace

import pytest

from archive_core.interfaces import (
    SubtitleCueDTO, SubtitleFragmentDTO, SubtitleMediaDTO, SubtitlePlanDTO,
    SubtitleRulesDTO, SubtitleTimingAdjustmentDTO,
)
from srt_processing.application.ports import SrtCue
from srt_processing.domain.rules import english_characters, wrap_english_text
from srt_processing.infrastructure.codec import Pysubs2SrtCodec, SubtitleCodecError


def _plan(english="We agree: 10% < 20%.", chinese="我们同意：10%。"):
    cues = tuple(
        SubtitleCueDTO(
            f"c{i}", None, start, end, end, text, translated,
            (SubtitleFragmentDTO(f"s{i}", f"w{i}", f"w{i}", 0, len(translated), None),),
            SubtitleTimingAdjustmentDTO(0, (), gap, gap_class),
            ("english_sentence", "chinese_sentence"),
        )
        for i, (start, end, text, translated, gap, gap_class) in enumerate((
            (100, 800, english, chinese, 1200, "long_gap"),
            (2000, 3000, "Indeed.", "确实。", None, "last_cue"),
        ), 1)
    )
    return SubtitlePlanDTO(
        "a" * 64, "b" * 64, "c" * 64, "en", "zh-Hans",
        SubtitleMediaDTO(5000, 5000, 5000, 24, 1, 84),
        SubtitleRulesDTO("test-profile.v1", "v1", "d" * 64, "test-algorithm.v1",
                         "text.v1", "count.v1", "boundaries.v1", "cost.v1"),
        cues,
    )


def test_fixed_projections_have_exact_bytes_and_shared_cue_times() -> None:
    codec = Pysubs2SrtCodec()
    plan = _plan()
    bodies = {
        "english": (plan.cues[0].english_text, "Indeed."),
        "chinese": (plan.cues[0].chinese_text, "确实。"),
        "bilingual": (plan.cues[0].chinese_text + "\n" + plan.cues[0].english_text, "确实。\nIndeed."),
    }
    for language, texts in bodies.items():
        data = codec.encode(plan, language)
        assert data == (
            f"1\n00:00:00,100 --> 00:00:00,800\n{texts[0]}\n\n"
            f"2\n00:00:02,000 --> 00:00:03,000\n{texts[1]}\n\n"
        ).encode("utf-8")
        assert not data.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in data and data.endswith(b"\n")
        assert codec.decode(data) == (
            SrtCue(1, 100, 800, texts[0]), SrtCue(2, 2000, 3000, texts[1]),
        )
        assert codec.encode(plan, language) == data


def test_codec_identity_matches_the_exact_installed_library() -> None:
    identity = Pysubs2SrtCodec().identity
    assert identity.library_name == "pysubs2"
    assert identity.library_version == "1.8.1"
    assert identity.encoding == "utf-8" and identity.newline == "\n"
    assert identity.bom is False and identity.terminal_newline is True
    assert identity.bilingual_order == ("zh-Hans", "en")
    assert identity.serialization_version == "word-wrap-english-2x42.v2"


@pytest.mark.parametrize("language", ["english", "chinese", "bilingual"])
@pytest.mark.parametrize("english", [
    "Berkshire Hathaway's shareholders value long-term capital growth.",
    "Warren Buffett and Charlie Munger discuss Coca-Cola's gains, 12.5%.",
])
def test_real_codec_projects_word_wrapped_english_without_changing_logical_plan(language, english) -> None:
    plan = _plan(english=english)
    before = plan.to_dict()
    wrapped = wrap_english_text(english)
    assert len(wrapped.split("\n")) == 2
    assert all(english_characters(line) <= 42 for line in wrapped.split("\n"))
    assert wrapped.replace("\n", " ") == english
    assert wrapped.split() == english.split()
    expected = {"english": wrapped, "chinese": plan.cues[0].chinese_text,
                "bilingual": plan.cues[0].chinese_text + "\n" + wrapped}[language]
    codec = Pysubs2SrtCodec()
    raw = codec.encode(plan, language)
    assert codec.decode(raw)[0].text == expected
    assert expected.encode("utf-8") in raw
    assert plan.to_dict() == before


@pytest.mark.parametrize("english", ["a" * 43, " ".join(["a" * 28] * 3)])
@pytest.mark.parametrize("language", ["english", "chinese", "bilingual"])
def test_codec_refuses_long_word_or_total_84_that_needs_three_word_lines(english, language) -> None:
    assert english_characters(english) <= 84
    with pytest.raises(SubtitleCodecError, match="cannot fit"):
        Pysubs2SrtCodec().encode(_plan(english=english), language)


def test_codec_refuses_a_different_installed_library_version(monkeypatch) -> None:
    import srt_processing.infrastructure.codec as module

    monkeypatch.setattr(module.pysubs2, "__version__", "1.9.0")
    with pytest.raises(SubtitleCodecError, match="requires pysubs2 1.8.1"):
        Pysubs2SrtCodec()


@pytest.mark.parametrize("text", [
    "Buffett's & Munger's 12.5% / $1,000.", "A &lt;b&gt;literal&lt;/b&gt; entity.",
    r"A literal \q and \t remain.", "Café e\u0301 中文 👩\u200d💻.",
])
@pytest.mark.parametrize("language", ["english", "chinese", "bilingual"])
def test_punctuation_entities_safe_escapes_and_unicode_round_trip(text, language) -> None:
    codec = Pysubs2SrtCodec()
    p = _plan(english=text, chinese=text)
    assert codec.decode(codec.encode(p, language))[0].text == (
        text + "\n" + text if language == "bilingual" else text
    )


@pytest.mark.parametrize("text", [
    "<b>literal</b>", "<i>literal</i>", "<term>literal</term>",
    r"{\i1}literal", "{profit}", r"Literal\Ntext", r"Literal\ntext",
    r"Literal\htext", r"{\p1}m 0 0 l 1 1",
])
@pytest.mark.parametrize("language", ["english", "chinese", "bilingual"])
def test_codec_never_silently_strips_tags_changes_escapes_or_filters_events(text, language) -> None:
    codec = Pysubs2SrtCodec()
    p = _plan(english=text, chinese=text)
    original = p.to_dict()
    with pytest.raises(SubtitleCodecError):
        codec.encode(p, language)
    assert p.to_dict() == original


@pytest.mark.parametrize("language", ["English", "zh-Hans", "", None])
def test_codec_rejects_non_fixed_projection_languages(language) -> None:
    with pytest.raises(SubtitleCodecError):
        Pysubs2SrtCodec().encode(_plan(), language)


def test_codec_rejects_non_plan_input() -> None:
    with pytest.raises(SubtitleCodecError):
        Pysubs2SrtCodec().encode({}, "english")


@pytest.mark.parametrize("data", [
    b"", b"\xff", b"\xef\xbb\xbf1\n00:00:00,000 --> 00:00:01,000\nText\n",
    b"1\r\n00:00:00,000 --> 00:00:01,000\r\nText\r\n",
    b"1\n00:00:00,000 --> 00:00:01,000\nText", b"2\n00:00:00,000 --> 00:00:01,000\nText\n",
    b"01\n00:00:00,000 --> 00:00:01,000\nText\n", b"1\nnot a timestamp\nText\n",
    b"1\n00:99:00,000 --> 00:99:01,000\nText\n", b"1\n0:00:00.000 --> 0:00:01.000\nText\n",
    b"1\n00:00:01,000 --> 00:00:00,000\nText\n", b"1\n00:00:00,000 --> 00:00:01,000\n\n",
    b"1\n00:00:00,000 --> 00:00:01,000\n<b>Text</b>\n",
    b"1\n00:00:00,000 --> 00:00:01,000\n<unknown>Text</unknown>\n",
    b"1\n00:00:00,000 --> 00:00:01,000\n{\\i1}Text\n",
    b"1\n00:00:00,000 --> 00:00:01,000\nLiteral\\Ntext\n",
    b"1\n00:00:00,000 --> 00:00:02,000\nText\n\n2\n00:00:01,000 --> 00:00:03,000\nOverlap\n",
    "not bytes",
])
def test_decode_rejects_invalid_bytes_structure_timing_and_lossy_text(data) -> None:
    with pytest.raises(SubtitleCodecError):
        Pysubs2SrtCodec().decode(data)


def test_decode_checks_real_indices_instead_of_library_synthetic_order() -> None:
    codec = Pysubs2SrtCodec()
    data = codec.encode(_plan(), "english")
    for replacement in (b"1", b"3", b"0"):
        corrupted = data.replace(b"\n\n2\n", b"\n\n" + replacement + b"\n")
        with pytest.raises(SubtitleCodecError):
            codec.decode(corrupted)


@pytest.mark.parametrize("offset", [10 * 60 * 60 * 1000, 99 * 60 * 60 * 1000])
def test_long_supported_hour_timestamps_preserve_integer_milliseconds(offset) -> None:
    p = _plan()
    p = replace(p, media=SubtitleMediaDTO(offset + 5000, offset + 5000, offset + 5000, 24, 1, 84),
                cues=tuple(replace(cue, start_ms=cue.start_ms + offset,
                                   base_end_ms=cue.base_end_ms + offset, end_ms=cue.end_ms + offset)
                           for cue in p.cues))
    codec = Pysubs2SrtCodec()
    decoded = codec.decode(codec.encode(p, "bilingual"))
    assert decoded[0].start_ms == offset + 100
    assert decoded[1].end_ms == offset + 3000


def test_timestamp_overflow_cannot_be_silently_clamped_by_library() -> None:
    p = _plan()
    offset = 100 * 60 * 60 * 1000
    p = replace(p, media=SubtitleMediaDTO(offset + 5000, offset + 5000, offset + 5000, 24, 1, 84),
                cues=tuple(replace(cue, start_ms=cue.start_ms + offset,
                                   base_end_ms=cue.base_end_ms + offset, end_ms=cue.end_ms + offset)
                           for cue in p.cues))
    with pytest.raises(SubtitleCodecError, match="could not serialize"):
        Pysubs2SrtCodec().encode(p, "english")


def test_bilingual_numeric_last_line_is_rejected_if_library_confuses_it_with_index() -> None:
    p = _plan()
    p = replace(p, cues=(p.cues[0], replace(p.cues[1], english_text="123")))
    with pytest.raises(SubtitleCodecError):
        Pysubs2SrtCodec().encode(p, "bilingual")


def test_timestamp_like_body_cannot_be_misparsed_as_an_extra_event() -> None:
    with pytest.raises(SubtitleCodecError):
        Pysubs2SrtCodec().encode(_plan(english="00:00:01,000 --> 00:00:02,000"), "english")


def test_library_empty_event_filtering_cannot_produce_a_successful_projection(monkeypatch) -> None:
    import srt_processing.infrastructure.codec as module

    monkeypatch.setattr(module.pysubs2.SSAFile, "to_string", lambda *args, **kwargs: "")
    with pytest.raises(SubtitleCodecError):
        Pysubs2SrtCodec().encode(_plan(), "english")
