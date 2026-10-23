from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import jieba
import pytest

from srt_processing.domain.rules import PROFILE
from srt_processing.infrastructure.segmentation import ChineseSegmentationError, JiebaChineseWordSegmenter


def test_pinned_dictionary_source_identity_and_unseen_sentences(monkeypatch):
    def cache_forbidden(*args, **kwargs):
        raise AssertionError("mutable jieba disk-cache initialization must not run")

    monkeypatch.setattr(jieba.Tokenizer, "initialize", cache_forbidden)
    segmenter = JiebaChineseWordSegmenter()
    path = Path(jieba.__file__).with_name("dict.txt")
    assert jieba.__version__ == "0.42.1"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == PROFILE.parameters["chinese_dictionary_sha256"]
    for text in ("南京市长江大桥欢迎远方旅客。", "我们认为风险值得考虑。", "量子电池与未知术语也有原始范围。"):
        spans = segmenter.spans(text)
        assert "".join(text[start:end] for start, end in spans) == text
        assert spans == segmenter.spans(text)
        assert spans[0][0] == 0 and spans[-1][1] == len(text)
        assert all(left[1] == right[0] for left, right in zip(spans, spans[1:]))
    assert all(segmenter.identity[key] == PROFILE.parameters[key] for key in segmenter.identity)


def test_dictionary_tampering_has_no_fallback(monkeypatch):
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"tampered dictionary")
    with pytest.raises(ChineseSegmentationError, match="fingerprint"):
        JiebaChineseWordSegmenter()


def test_wrong_library_version_has_no_fallback(monkeypatch):
    monkeypatch.setattr(jieba, "__version__", "0.99")
    with pytest.raises(ChineseSegmentationError, match="0.42.1"):
        JiebaChineseWordSegmenter()


def test_missing_library_has_controlled_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "jieba", None)
    with pytest.raises(ChineseSegmentationError, match="pinned"):
        JiebaChineseWordSegmenter()
