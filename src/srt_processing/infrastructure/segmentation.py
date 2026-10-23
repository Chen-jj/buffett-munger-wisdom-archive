"""Pinned local jieba dictionary, without global mutation or disk caches."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from types import MappingProxyType

from srt_processing.domain.rules import PROFILE


class ChineseSegmentationError(ValueError):
    category = "segmentation_invalid"


class JiebaChineseWordSegmenter:
    def __init__(self) -> None:
        try:
            import jieba
        except ImportError as error:
            raise ChineseSegmentationError("Chinese segmentation requires pinned jieba 0.42.1") from error

        if jieba.__version__ != "0.42.1":
            raise ChineseSegmentationError("Chinese segmentation requires jieba 0.42.1")
        try:
            data = Path(jieba.__file__).with_name("dict.txt").read_bytes()
        except OSError as error:
            raise ChineseSegmentationError("Chinese segmentation dictionary is unavailable") from error
        expected = PROFILE.parameters["chinese_dictionary_sha256"]
        if hashlib.sha256(data).hexdigest() != expected:
            raise ChineseSegmentationError("Chinese segmentation dictionary fingerprint mismatch")
        self._tokenizer = jieba.Tokenizer()
        # The pinned loader consumes verified bytes. Never trust jieba's mutable
        # default /tmp marshal cache or load external/user dictionaries.
        self._tokenizer.FREQ, self._tokenizer.total = self._tokenizer.gen_pfdict(BytesIO(data))
        self._tokenizer.initialized = True
        self._identity = MappingProxyType({key: PROFILE.parameters[key] for key in (
            "chinese_segmentation_engine", "chinese_dictionary_sha256", "chinese_segmentation_mode",
        )})

    @property
    def identity(self):
        return self._identity

    def spans(self, text: str) -> tuple[tuple[int, int], ...]:
        if not isinstance(text, str):
            raise ValueError("Chinese segmentation input must be text")
        return tuple((start, end) for _, start, end in self._tokenizer.tokenize(text, mode="default", HMM=False))
