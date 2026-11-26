from itertools import groupby, product
import math
from types import SimpleNamespace

import pytest

from archive_core.interfaces import (
    StructuredTranscriptDTO,
    TranscriptChapterDTO,
    TranscriptParagraphDTO,
)
from transcription.domain import (
    NormalizationPolicy,
    OfficialAlignmentConfig,
    build_official_tokens,
)
from transcription.domain.fusion_acoustics import AcousticCandidateEvidence, AcousticWordEvidence
from transcription.infrastructure import WhisperXOfficialTranscriptAligner
from transcription.infrastructure import audio_asr


class _EmissionBackend:
    def __init__(self, torch, frame_probabilities):
        self.logits = torch.tensor(frame_probabilities).log().unsqueeze(0)
        self.inference_calls = 0
        self.load_calls = 0

    def load_align_model(self, **kwargs):
        self.load_calls += 1
        return self, {
            "type": "huggingface",
            "dictionary": {"<pad>": 0, "a": 1, "b": 2, "|": 3},
        }

    def __call__(self, waveform):
        self.inference_calls += 1
        return SimpleNamespace(logits=self.logits)


def test_one_window_scores_exact_ctc_likelihood_and_distinct_repeat_frames(monkeypatch):
    torch = pytest.importorskip("torch")
    probabilities = [
        (0.05, 0.90, 0.04, 0.01),
        (0.88, 0.10, 0.01, 0.01),
        (0.04, 0.91, 0.03, 0.02),
    ]
    backend = _EmissionBackend(torch, probabilities)
    windows = []

    def read(audio_path, start_ms, end_ms):
        windows.append((audio_path, start_ms, end_ms))
        return torch.ones((1, (end_ms - start_ms) * 16))

    monkeypatch.setattr(audio_asr, "_read_pcm_window", read)
    adapter = WhisperXOfficialTranscriptAligner(
        whisperx_version="test", backend=backend, model_resolver=lambda *_: "model"
    )
    config = OfficialAlignmentConfig("test", "test", "cpu")

    repeated, single, empty, unsupported = adapter.score_candidates(
        "audio.wav", 100, 160, ("AA", "a", "", "99"), config
    )

    assert windows == [("audio.wav", 100, 160)]
    assert backend.inference_calls == backend.load_calls == 1
    assert repeated.ctc_log_likelihood == pytest.approx(math.log(0.90 * 0.88 * 0.91))
    single_paths = sum(
        math.prod(probabilities[frame][state] for frame, state in enumerate(path))
        for path in product((0, 1), repeat=len(probabilities))
        if tuple(state for state, _ in groupby(path) if state != 0) == (1,)
    )
    assert single.ctc_log_likelihood == pytest.approx(math.log(single_paths))
    assert (repeated.start_ms, repeated.end_ms) == (100, 160)
    assert repeated.mean_character_score == pytest.approx((0.90 + 0.91) / 2)
    assert repeated.energy_coverage == pytest.approx(1.0)
    assert empty.ctc_log_likelihood == pytest.approx(math.log(0.05 * 0.88 * 0.04))
    assert empty.start_ms is None and empty.word_evidence == ()
    assert unsupported.ctc_log_likelihood is None


def test_align_official_window_preserves_word_identity_and_source_timeline(monkeypatch):
    torch = pytest.importorskip("torch")
    backend = _EmissionBackend(torch, [
        (0.98, 0.01, 0.005, 0.005),
        (0.01, 0.96, 0.02, 0.01),
        (0.01, 0.02, 0.01, 0.96),
        (0.01, 0.02, 0.96, 0.01),
        (0.98, 0.01, 0.005, 0.005),
    ])
    monkeypatch.setattr(audio_asr, "_read_pcm_window", lambda *_: torch.ones((1, 1600)))
    adapter = WhisperXOfficialTranscriptAligner(
        whisperx_version="test", backend=backend, model_resolver=lambda *_: "model"
    )
    config = OfficialAlignmentConfig("test", "test", "cpu")
    transcript = StructuredTranscriptDTO(
        "en", (TranscriptChapterDTO(1, "", (TranscriptParagraphDTO("A B!"),)),)
    )
    tokens, _ = build_official_tokens(transcript, NormalizationPolicy())

    first, second = adapter.align_official_window("audio.wav", tokens, 1000, 1100, config)

    assert (first.official_token_id, first.text, first.start_ms, first.end_ms) == ("ot1", "A", 1020, 1040)
    assert (second.official_token_id, second.text, second.start_ms, second.end_ms) == ("ot2", "B!", 1060, 1080)
    assert first.alignment_score == pytest.approx(0.96)
    assert second.alignment_score == pytest.approx(0.96)


@pytest.mark.parametrize(
    ("currency_score", "shorthand_likelihood", "expected_end", "expected_score"),
    ((0.14, -15.0, 1400, 0.98), (0.78, -15.0, 1600, 0.78), (0.14, -25.0, 1600, 0.14)),
)
def test_interrupted_currency_uses_actual_spoken_components(
    monkeypatch, currency_score, shorthand_likelihood, expected_end, expected_score
):
    adapter = WhisperXOfficialTranscriptAligner(whisperx_version="test")
    config = OfficialAlignmentConfig("test", "test", "cpu", min_alignment_score=0.20)
    transcript = StructuredTranscriptDTO(
        "en", (TranscriptChapterDTO(1, "", (TranscriptParagraphDTO("on $10—"),)),)
    )
    tokens, _ = build_official_tokens(transcript, NormalizationPolicy())
    shared_words = (AcousticWordEvidence("on", 1020, 1080, 0.49),
                    AcousticWordEvidence("ten", 1200, 1400, 0.98))

    def score(audio_path, start_ms, end_ms, readings, config):
        assert readings == ("on ten dollars", "on ten")
        return (
            AcousticCandidateEvidence(-20.0, word_evidence=(*shared_words,
                AcousticWordEvidence("dollars", 1420, 1600, currency_score))),
            AcousticCandidateEvidence(shorthand_likelihood, word_evidence=shared_words),
        )

    monkeypatch.setattr(adapter, "score_candidates", score)
    on, amount = adapter.align_official_window("audio.wav", tokens, 1000, 1700, config)

    assert (on.official_token_id, on.text, on.start_ms, on.end_ms) == ("ot1", "on", 1020, 1080)
    assert (amount.official_token_id, amount.text, amount.start_ms, amount.end_ms) == (
        "ot2", "$10—", 1200, expected_end,
    )
    assert amount.alignment_score == expected_score
