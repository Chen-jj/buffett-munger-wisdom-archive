"""Pure official-transcript normalization and fusion artifact contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
import math
import re
import unicodedata
from typing import AbstractSet, Any, Mapping, Sequence

from archive_core.interfaces import (
    MatchType,
    StructuredTranscriptDTO,
    TextSource,
    TimedWordDTO,
    TimingSource,
)
from archive_core.interfaces.transcription import normalize_spoken_text

from .alignment import (
    _LEXICAL_OR_PUNCTUATION_RE,
    AlignedAsrWord,
    AlignmentTimingSource,
    tokenize_surface_text,
)
from .audio_asr import ProviderIdentity, SourceTimeSpan


TRANSCRIPT_FUSION_SCHEMA_VERSION = "transcription.transcript-fusion.v3"

_OFFICIAL_TOKEN_ID_RE = re.compile(r"^ot[1-9][0-9]*$")
_ASR_WORD_ID_RE = re.compile(r"^aw[1-9][0-9]*$")
_INLINE_STAGE_DIRECTION = re.compile(
    r"\((?:laughs|laughter|applause|cheers|inaudible|Buffett laughs)\)"
    r"|\[(?:laughs|laughter|applause|cheers|inaudible|Buffett laughs)\]", re.IGNORECASE
)
_CLOCK_GROUP = re.compile(r"([1-9]|1[0-2]):\s+([0-5]\d)\b")
_CURRENCY_NAMES = {
    "$": ("dollar", "dollars"),
    "£": ("pound", "pounds"),
    "€": ("euro", "euros"),
}
_MAGNITUDES = {"trillion": 10**12, "billion": 10**9, "million": 10**6, "thousand": 1000}
_UNSIGNED_NUMBER_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_NUMBER_PATTERN = rf"[-−]?{_UNSIGNED_NUMBER_PATTERN}"
_FRACTION_PATTERN = r"(?:\d+\s+)?\d+/\s*\d+"
_PERCENT_PATTERN = rf"(?:{_FRACTION_PATTERN}|{_NUMBER_PATTERN})(?:\s*%|\s+percent)"
_AMOUNT_PATTERN = rf"(?:[-−][$£€]|[$£€][-−]?){_UNSIGNED_NUMBER_PATTERN}(?:\s+(?:{'|'.join(_MAGNITUDES)}))?"
_ORDINAL_PATTERN = r"\d{1,4}\s*(?:st|nd|rd|th)"
_DECADE_PATTERN = r"(?:the['’]\s+|['’])(?:\d{2})?\d0\s*s"
_SLASH_DATE_PATTERN = r"(?:9/11|\d{1,2}/\d{1,2}/\d{4})"
_CLOCK_TIME_PATTERN = r"(?:[1-9]|1[0-2]):[0-5]\d"
_QUANTITY_PUNCTUATION = '.,!?;:"“”()[]—–…'
_SPOKEN_CURRENCY_NAMES = {name for names in _CURRENCY_NAMES.values() for name in names}
_CURRENCY_SYMBOL_BY_NAME = {
    name: symbol for symbol, names in _CURRENCY_NAMES.items() for name in names
}
_OFFICIAL_LEXICAL_PATTERN = re.compile(
    rf"(?<!\w)(?:{_PERCENT_PATTERN}|{_AMOUNT_PATTERN}|{_ORDINAL_PATTERN}|"
    rf"{_DECADE_PATTERN}|{_SLASH_DATE_PATTERN}|{_FRACTION_PATTERN})(?![\w/])|"
    rf"{_LEXICAL_OR_PUNCTUATION_RE.pattern}",
    re.IGNORECASE,
)
_CONTRACTIONS = {
    "can't": ("can", "not"),
    "cannot": ("can", "not"),
    "couldn't": ("could", "not"),
    "didn't": ("did", "not"),
    "doesn't": ("does", "not"),
    "don't": ("do", "not"),
    "hadn't": ("had", "not"),
    "hasn't": ("has", "not"),
    "haven't": ("have", "not"),
    "he'll": ("he", "will"),
    "i'll": ("i", "will"),
    "i'm": ("i", "am"),
    "isn't": ("is", "not"),
    "it's": ("it", "is"),
    "shouldn't": ("should", "not"),
    "they'll": ("they", "will"),
    "wasn't": ("was", "not"),
    "we'll": ("we", "will"),
    "we're": ("we", "are"),
    "we've": ("we", "have"),
    "weren't": ("were", "not"),
    "won't": ("will", "not"),
    "wouldn't": ("would", "not"),
    "you'll": ("you", "will"),
    "you're": ("you", "are"),
    "you've": ("you", "have"),
}
_ONES = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)
_TENS = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)
_CARDINALS = dict(zip(_ONES, range(20), strict=True)) | {
    word: decade * 10 for decade, word in enumerate(_TENS) if word
}
_SCALES = {"hundred", *_MAGNITUDES}
_INTRODUCTIONS = {"recognize", "introduce", "welcome", "present"}
_PERSON_TITLE = {
    "miss": "ms", "ms": "ms", "mrs": "mrs", "mr": "mr", "mister": "mr",
    "doctor": "dr", "dr": "dr", "professor": "professor",
}


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _require_int(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _require_sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be an array")
    return value


@dataclass(frozen=True)
class NormalizationPolicy:
    version: str = "english-spoken.v2"

    def __post_init__(self) -> None:
        _require_text(self.version, "version")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NormalizationPolicy":
        return cls(version=data.get("version"))


@dataclass(frozen=True)
class MatchingPolicy:
    version: str = "monotonic-local-dp.v7"
    anchor_ngram_size: int = 2
    max_local_window_words: int = 24
    max_unanchored_conflict_words: int = 4
    max_group_size: int = 4
    max_official_only_words: int = 3
    # Match apostrophized official spellings literally.
    allowed_substitutions: tuple[tuple[str, str], ...] = (("seas", "see's"),)

    def __post_init__(self) -> None:
        _require_text(self.version, "version")
        _require_int(self.anchor_ngram_size, "anchor_ngram_size", minimum=2)
        _require_int(self.max_local_window_words, "max_local_window_words", minimum=1)
        _require_int(
            self.max_unanchored_conflict_words,
            "max_unanchored_conflict_words",
            minimum=1,
        )
        _require_int(self.max_group_size, "max_group_size", minimum=2)
        _require_int(self.max_official_only_words, "max_official_only_words", minimum=1)
        object.__setattr__(
            self,
            "allowed_substitutions",
            tuple(
                tuple(
                    " ".join(value.casefold().split())
                    if isinstance(value, str)
                    else value
                    for value in pair
                )
                for pair in self.allowed_substitutions
            ),
        )
        if not all(
            len(pair) == 2
            and all(isinstance(value, str) and value.strip() for value in pair)
            for pair in self.allowed_substitutions
        ):
            raise ValueError(
                "allowed_substitutions must contain non-empty ASR/official pairs"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "anchor_ngram_size": self.anchor_ngram_size,
            "max_local_window_words": self.max_local_window_words,
            "max_unanchored_conflict_words": self.max_unanchored_conflict_words,
            "max_group_size": self.max_group_size,
            "max_official_only_words": self.max_official_only_words,
            "allowed_substitutions": [
                list(pair) for pair in self.allowed_substitutions
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MatchingPolicy":
        substitutions = _require_sequence(
            data.get("allowed_substitutions", []), "allowed_substitutions"
        )
        return cls(
            version=data.get("version"),
            anchor_ngram_size=data.get("anchor_ngram_size"),
            max_local_window_words=data.get("max_local_window_words"),
            max_unanchored_conflict_words=data.get(
                "max_unanchored_conflict_words"
            ),
            max_group_size=data.get("max_group_size"),
            max_official_only_words=data.get("max_official_only_words"),
            allowed_substitutions=tuple(
                tuple(_require_sequence(pair, "allowed_substitutions item"))
                for pair in substitutions
            ),
        )


@dataclass(frozen=True)
class OfficialAlignmentConfig:
    model: str
    model_version: str
    device: str
    min_alignment_score: float = 0.2
    min_anchor_alignment_score: float = 0.5
    language: str = "en"

    def __post_init__(self) -> None:
        _require_text(self.model, "model")
        _require_text(self.model_version, "model_version")
        _require_text(self.device, "device")
        if self.language != "en":
            raise ValueError("language must be en")
        for name, value in (
            ("min_alignment_score", self.min_alignment_score),
            ("min_anchor_alignment_score", self.min_anchor_alignment_score),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
            ):
                raise ValueError(f"{name} must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_version": self.model_version,
            "device": self.device,
            "min_alignment_score": self.min_alignment_score,
            "min_anchor_alignment_score": self.min_anchor_alignment_score,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfficialAlignmentConfig":
        return cls(
            model=data.get("model"),
            model_version=data.get("model_version"),
            device=data.get("device"),
            min_alignment_score=data.get("min_alignment_score"),
            min_anchor_alignment_score=data.get(
                "min_anchor_alignment_score"
            ),
            language=data.get("language"),
        )


def normalize_token(
    surface: str, policy: NormalizationPolicy | None = None
) -> tuple[str, ...]:
    """Return versioned English matching units while preserving surface elsewhere."""

    selected = policy or NormalizationPolicy()
    if selected.version != "english-spoken.v2":
        raise ValueError(f"unsupported normalization policy: {selected.version}")
    text = unicodedata.normalize("NFKC", _require_text(surface, "surface"))
    text = text.casefold().replace("’", "'").replace("‘", "'")
    quantity = _formatted_quantity(text)
    if quantity is not None:
        return quantity[0]
    numeric_body = text.strip(_QUANTITY_PUNCTUATION)
    if numeric_body.startswith(("-", "−")) and re.fullmatch(_NUMBER_PATTERN, numeric_body):
        return _decimal_words(numeric_body)
    currency = next((symbol for symbol in _CURRENCY_NAMES if symbol in text), None)
    percent = "%" in text
    text = text.replace("–", "-").replace("—", "-")
    for symbol in _CURRENCY_NAMES:
        text = text.replace(symbol, "")
    text = text.replace("%", "").replace("-", " ")
    text = re.sub(r"[^\w'\s.,]", "", text, flags=re.UNICODE)
    units: list[str] = []
    numeric_value: int | None = None
    for raw_part in text.split():
        part = raw_part.strip(".,")
        if part in _CONTRACTIONS:
            units.extend(_CONTRACTIONS[part])
            continue
        numeric_part = part.replace(",", "")
        if re.fullmatch(r"\d+(?:\.\d+)?", numeric_part):
            whole, separator, fraction = numeric_part.partition(".")
            value = int(whole)
            numeric_value = value
            year_style = (
                currency is None
                and not percent
                and "," not in part
                and len(whole) == 4
            )
            units.extend(_integer_words(value, year_style=year_style))
            if separator:
                units.append("point")
                units.extend(_ONES[int(digit)] for digit in fraction)
            continue
        normalized = part.replace("'", "").replace(",", "").replace(".", "")
        if normalized:
            units.append(normalized)
    if currency is not None:
        singular, plural = _CURRENCY_NAMES[currency]
        units.append(singular if numeric_value == 1 else plural)
    if percent:
        units.append("percent")
    if not units:
        raise ValueError("surface must contain spoken lexical content")
    return tuple(units)


def _integer_words(value: int, *, year_style: bool = False) -> tuple[str, ...]:
    if value < 0 or value >= 10**15:
        return (str(value),)
    if year_style and 1100 <= value <= 1999:
        first, second = divmod(value, 100)
        suffix = _under_thousand(second) if second else ("hundred",)
        return _under_thousand(first) + suffix
    if value < 1000:
        return _under_thousand(value)
    result: list[str] = []
    for label, size in _MAGNITUDES.items():
        if value >= size:
            quotient, value = divmod(value, size)
            result.extend(_under_thousand(quotient))
            result.append(label)
    if value:
        result.extend(_under_thousand(value))
    return tuple(result)


def _under_thousand(value: int) -> tuple[str, ...]:
    if value < 20:
        return (_ONES[value],)
    result: list[str] = []
    if value >= 100:
        hundreds, value = divmod(value, 100)
        result.extend((_ONES[hundreds], "hundred"))
    if value >= 20:
        tens, value = divmod(value, 10)
        result.append(_TENS[tens])
    if value:
        result.append(_ONES[value])
    return tuple(result)


def _decimal_words(surface: str) -> tuple[str, ...]:
    surface = surface.replace(",", "").replace("−", "-")
    whole, point, fraction = surface.removeprefix("-").partition(".")
    words = _integer_words(int(whole))
    if point:
        words += ("point",) + tuple(_ONES[int(digit)] for digit in fraction)
    return (("minus",) + words) if surface.startswith("-") else words


def _fraction_value(surface: str) -> Fraction | None:
    whole, _, fraction = surface.rpartition(" ")
    numerator, denominator = map(int, fraction.split("/"))
    return int(whole or 0) + Fraction(numerator, denominator) if denominator else None


def _exact_decimal(value: Fraction) -> str | None:
    denominator = value.denominator
    power = 0
    while denominator > 1 and (denominator % 2 == 0 or denominator % 5 == 0):
        denominator //= 2 if denominator % 2 == 0 else 5
        power += 1
    if denominator != 1:
        return None
    digits = str(value.numerator * 10**power // value.denominator).zfill(power + 1)
    if power:
        return (digits[:-power] + "." + digits[-power:]).rstrip("0").rstrip(".")
    return digits


def _formatted_quantity(surface: str) -> tuple[tuple[str, ...], str] | None:
    text = surface.strip(_QUANTITY_PUNCTUATION)
    if not any(character.isdecimal() for character in text):
        return None
    text = re.sub(r"/\s+", "/", " ".join(text.split()))
    if re.fullmatch(_PERCENT_PATTERN, text):
        number = text.removesuffix("percent").removesuffix("%").rstrip()
        if "/" in number:
            value = _fraction_value(number)
            decimal = _exact_decimal(value) if value is not None else None
            if decimal is None:
                return ((text,), text)
            number = decimal
        return _decimal_words(number) + ("percent",), number + "%"
    if re.fullmatch(_AMOUNT_PATTERN, text):
        money, _, magnitude = text.partition(" ")
        currency = money.lstrip("-−")[0]
        number = money.replace(currency, "")
        units = _decimal_words(number)
        if magnitude:
            units += (magnitude,)
        singular, plural = _CURRENCY_NAMES[currency]
        return units + (singular if number.lstrip("-−") == "1" and not magnitude else plural,), text
    if re.fullmatch(_CLOCK_TIME_PATTERN, text):
        return (f"clock:{text}",), text
    if re.fullmatch(_SLASH_DATE_PATTERN, text):
        return (f"date:{text}",), text
    if re.fullmatch(_FRACTION_PATTERN, text):
        value = _fraction_value(text)
        return (f"fraction:{value}" if value is not None else f"fraction:{text}",), text
    if re.fullmatch(_ORDINAL_PATTERN, text):
        ordinal = text.replace(" ", "")
        return (f"ordinal:{ordinal}",), ordinal
    if re.fullmatch(_DECADE_PATTERN, text):
        number = re.search(r"\d+", text).group()
        decade = (f"decade:{number}",)
        if text.startswith("the"):
            return ("the",) + decade, f"the ’{number}s"
        return decade, f"’{number}s"
    return None


def is_explicit_fusion_quantity(surface: str) -> bool:
    text = surface.casefold().replace("’", "'")
    return (
        _formatted_quantity(text) is not None
        or _spoken_percent(text) is not None
        or re.fullmatch(_NUMBER_PATTERN, text.strip(_QUANTITY_PUNCTUATION)) is not None
    )


def _canonical_number_words(words: Sequence[str]) -> tuple[str, ...]:
    canonical: list[str] = []
    for index, word in enumerate(words):
        next_word = words[index + 1] if index + 1 < len(words) else ""
        if word == "and" and index and words[index - 1] in _SCALES and (
            next_word in _CARDINALS or next_word == "a"
        ):
            continue
        canonical.append("one" if word == "a" and next_word in _SCALES else word)
    return tuple(canonical)


def _spoken_decimal(words: Sequence[str]) -> str | None:
    """Parse a complete cardinal, checking its grammar against the generated reading."""
    negative = bool(words) and words[0] == "minus"
    units = _canonical_number_words(words[1:] if negative else words)
    point = units.index("point") if "point" in units else len(units)
    whole = units[:point]
    total = group = 0
    for word in whole:
        if word in _CARDINALS:
            group += _CARDINALS[word]
        elif word == "hundred":
            group *= 100
        elif word in _MAGNITUDES:
            total += group * _MAGNITUDES[word]
            group = 0
        else:
            return None
    number = total + group
    if whole != _integer_words(number):
        return None
    decimal = ("-" if negative else "") + str(number)
    if point == len(units):
        return decimal
    fraction = units[point + 1:]
    if not fraction or any(digit not in _ONES[:10] for digit in fraction):
        return None
    return decimal + "." + "".join(str(_CARDINALS[digit]) for digit in fraction)


def _spoken_percent(text: str) -> tuple[tuple[str, ...], str] | None:
    number, separator, unit = text.strip(_QUANTITY_PUNCTUATION).rpartition(" ")
    if not separator or unit != "percent":
        return None
    decimal = _spoken_decimal(tuple(number.replace("-", " ").split()))
    return _formatted_quantity(decimal + "%") if decimal is not None else None


@dataclass(frozen=True)
class MoneyAmount:
    currency: str
    value: Fraction
    text: str
    numeral_article: bool


def _money_coefficient(text: str) -> str | None:
    if re.fullmatch(_NUMBER_PATTERN, text):
        return text.replace(",", "").replace("−", "-")
    if re.fullmatch(_FRACTION_PATTERN, text):
        fraction = _fraction_value(text)
        return _exact_decimal(fraction) if fraction is not None else None
    return _spoken_decimal(tuple(text.replace("-", " ").split()))


def parse_money_amount(surfaces: Sequence[str]) -> MoneyAmount | None:
    """Recognize a complete amount with an explicit currency marker."""
    surface = " ".join(surfaces)
    body = surface.strip(_QUANTITY_PUNCTUATION)
    text = re.sub(r"/\s+", "/", " ".join(body.casefold().split()))
    if re.fullmatch(_AMOUNT_PATTERN, text):
        amount, _, scale = text.partition(" ")
        currency = amount.lstrip("-−")[0]
        decimal = _money_coefficient(amount.replace(currency, ""))
    else:
        amount, separator, unit = text.rpartition(" ")
        if not separator or unit not in _CURRENCY_SYMBOL_BY_NAME:
            return None
        currency = _CURRENCY_SYMBOL_BY_NAME[unit]
        coefficient, _, scale = amount.rpartition(" ")
        decimal = _money_coefficient(amount)
        scaled_coefficient = _money_coefficient(coefficient) if scale in _MAGNITUDES and coefficient else None
        if scaled_coefficient is not None and (
            decimal is None or Fraction(scaled_coefficient) * _MAGNITUDES[scale] == Fraction(decimal)
        ):
            decimal = scaled_coefficient
        else:
            scale = ""
    if decimal is None:
        return None
    value = Fraction(decimal) * _MAGNITUDES.get(scale, 1)
    if scale == "thousand":
        decimal = _exact_decimal(abs(value))
        if decimal is None:
            return None
        if value < 0:
            decimal = "-" + decimal
        scale = ""
    whole, dot, fraction = decimal.partition(".")
    number = f"{int(whole):,}"
    if whole.startswith("-") and int(whole) == 0:
        number = "-0"
    display = currency + number + dot + fraction + (f" {scale}" if scale else "")
    return MoneyAmount(currency, value, surface.replace(body, display, 1), text.startswith("a "))


def money_spans(surfaces: Sequence[str]) -> tuple[tuple[int, int, MoneyAmount], ...]:
    """Find complete amount spans without consuming tokens outside their number grammar."""
    spans = []
    for index, surface in enumerate(surfaces):
        body = surface.strip(_QUANTITY_PUNCTUATION).casefold()
        if body in _CURRENCY_SYMBOL_BY_NAME:
            for start in range(max(0, index - 11), index):
                amount = parse_money_amount(surfaces[start:index + 1])
                if amount is not None:
                    spans.append((start, index + 1, amount))
                    break
        elif any(symbol in body for symbol in _CURRENCY_NAMES):
            end = index + 1
            if end < len(surfaces) and surfaces[end].strip(_QUANTITY_PUNCTUATION).casefold() in _MAGNITUDES:
                amount = parse_money_amount(surfaces[index:end + 1])
                if amount is not None:
                    spans.append((index, end + 1, amount))
                    continue
            amount = parse_money_amount((surface,))
            if amount is not None:
                spans.append((index, end, amount))
    return tuple(spans)


def equivalent_fusion_text(
    asr_surfaces: Sequence[str], official_surfaces: Sequence[str]
) -> bool:
    asr_money = parse_money_amount(asr_surfaces)
    official_money = parse_money_amount(official_surfaces)
    if asr_money is not None and official_money is not None:
        return (asr_money.currency, asr_money.value) == (official_money.currency, official_money.value)

    def parse(surfaces: Sequence[str]) -> tuple[tuple[str, ...], str] | None:
        text = " ".join(surfaces).casefold().replace("’", "'")
        return _formatted_quantity(text) or _spoken_percent(text)

    asr, official = parse(asr_surfaces), parse(official_surfaces)
    if asr is not None and official is not None:
        return asr[0] == official[0]
    structured = asr or official
    if structured is None:
        return False
    other_surfaces = official_surfaces if asr is not None else asr_surfaces
    other = " ".join(other_surfaces).casefold().strip(_QUANTITY_PUNCTUATION)
    if structured[0] == ("date:9/11",) and len(other_surfaces) == 2:
        return other == "9- 11"
    if structured[0][-1].startswith("decade:"):
        number = structured[0][-1].removeprefix("decade:")
        article = "the " if structured[0][0] == "the" else ""
        return other == f"{article}{number} s"
    if structured[0][-1] not in _SPOKEN_CURRENCY_NAMES:
        return False
    units = _canonical_number_words(tuple(
        unit for surface in other_surfaces for unit in normalize_token(surface)
    ))
    return units == structured[0]


def fusion_candidate_text(surface: str) -> str:
    """Expand written quantities for the acoustic comparison of whole readings."""
    quantity = _formatted_quantity(surface.casefold().replace("’", "'"))
    if quantity is not None and all(unit.isalpha() for unit in quantity[0]):
        return " ".join(quantity[0])
    number = surface.strip(_QUANTITY_PUNCTUATION)
    if re.fullmatch(_NUMBER_PATTERN, number):
        return " ".join(normalize_token(number))
    return surface


def fusion_candidate_readings(surface: str, *, implicit_currency: bool = False) -> tuple[str, ...]:
    """Return complete lexical variants of a reading, with the same number and currency."""
    canonical = fusion_candidate_text(surface)
    words = tuple(canonical.casefold().strip(_QUANTITY_PUNCTUATION).split())
    if not words or words[-1] not in _SPOKEN_CURRENCY_NAMES:
        return (canonical,)
    number = _canonical_number_words(words[:-1])
    if _spoken_decimal(number) is None:
        return (canonical,)

    with_and = []
    for index, word in enumerate(number):
        with_and.append(word)
        if word == "hundred" and index + 1 < len(number) and number[index + 1] in _CARDINALS:
            with_and.append("and")
    variants: dict[str, None] = {canonical: None}
    for reading in (number, tuple(with_and)):
        forms = (reading, ("a", *reading[1:])) if reading[:1] == ("one",) and (
            len(reading) > 1 and reading[1] in _SCALES
        ) else (reading,)
        for form in forms:
            variants[" ".join((*form, words[-1]))] = None
            if implicit_currency:
                variants[" ".join(form)] = None
    return tuple(variants)


@dataclass(frozen=True)
class OfficialTranscriptToken:
    id: str
    text: str
    normalized: tuple[str, ...]
    chapter_index: int
    chapter_number: int
    paragraph_index: int
    speaker_label: str | None

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        if _OFFICIAL_TOKEN_ID_RE.fullmatch(self.id) is None:
            raise ValueError("official token id must use ot<one-based position>")
        _require_text(self.text, "text")
        object.__setattr__(self, "normalized", tuple(self.normalized))
        if not self.normalized or not all(
            isinstance(unit, str) and unit for unit in self.normalized
        ):
            raise ValueError("normalized must contain lexical units")
        _require_int(self.chapter_index, "chapter_index", minimum=1)
        _require_int(self.chapter_number, "chapter_number")
        _require_int(self.paragraph_index, "paragraph_index", minimum=1)
        if self.speaker_label is not None:
            _require_text(self.speaker_label, "speaker_label")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "normalized": list(self.normalized),
            "chapter_index": self.chapter_index,
            "chapter_number": self.chapter_number,
            "paragraph_index": self.paragraph_index,
            "speaker_label": self.speaker_label,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfficialTranscriptToken":
        normalized = _require_sequence(data.get("normalized", []), "normalized")
        return cls(
            id=data.get("id"),
            text=data.get("text"),
            normalized=tuple(normalized),
            chapter_index=data.get("chapter_index"),
            chapter_number=data.get("chapter_number"),
            paragraph_index=data.get("paragraph_index"),
            speaker_label=data.get("speaker_label"),
        )


def _name_body(surface: str) -> str:
    return surface.strip(_QUANTITY_PUNCTUATION).casefold()


def _surname_sound(surface: str) -> str:
    # The context and a canonical person label establish identity. This coarse
    # consonant check limits corrections to acoustically plausible spellings.
    surface = re.sub(r"c(?=[eiy])", "s", surface)
    surface = surface.translate(str.maketrans("bzqc", "pskk"))
    return re.sub(r"(.)\1+", r"\1", re.sub(r"[^bcdfgjklmnpqrstvxz]", "", surface))


def same_official_person(
    asr_words: Sequence[AlignedAsrWord],
    official_token: OfficialTranscriptToken,
    preceding: Sequence[OfficialTranscriptToken],
    speaker_labels: AbstractSet[str],
) -> bool:
    """Require a locally aligned introduction and a unique canonical person label."""
    if len(asr_words) < 3 or len(preceding) < 3:
        return False
    surname, first_name = asr_words[-1], asr_words[-2]
    official_first = preceding[-1]
    first = _name_body(official_first.text)
    canonical = _name_body(official_token.text)
    original = _name_body(surname.text)
    if first != _name_body(first_name.text) or len(first) < 2 or canonical == original:
        return False
    if not all(re.fullmatch(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", name) for name in (
        first, original, canonical,
    )):
        return False
    if (
        surname.timing_source is not AlignmentTimingSource.ACOUSTIC_ALIGNMENT
        or first_name.end_ms > surname.start_ms
        or surname.start_ms - first_name.end_ms > 1250
    ):
        return False
    same_context = tuple(
        token for token in preceding
        if (token.chapter_index, token.paragraph_index, token.speaker_label) == (
            official_token.chapter_index, official_token.paragraph_index, official_token.speaker_label
        )
    )
    if len(same_context) < 3 or same_context[-1] != official_first:
        return False
    official_intro = tuple(_name_body(token.text) for token in same_context[-5:-1])
    asr_intro = tuple(_name_body(word.text) for word in asr_words[-6:-2])
    if (
        _PERSON_TITLE.get(official_intro[-1]) is None
        or _PERSON_TITLE.get(official_intro[-1]) != _PERSON_TITLE.get(asr_intro[-1])
        or not (_INTRODUCTIONS.intersection(official_intro) & _INTRODUCTIONS.intersection(asr_intro))
    ):
        return False
    matching_labels = {
        " ".join(parts[1:]) for label in speaker_labels
        if (parts := label.casefold().split()) and parts[0] == first
    }
    if matching_labels != {canonical}:
        return False
    consonants = _surname_sound(canonical)
    return len(consonants) >= 3 and _surname_sound(original) == consonants


class IgnoredContentKind(str, Enum):
    CHAPTER_TITLE = "chapter_title"
    STAGE_DIRECTION = "stage_direction"


@dataclass(frozen=True)
class IgnoredOfficialContent:
    kind: IgnoredContentKind
    text: str
    chapter_number: int
    paragraph_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, IgnoredContentKind):
            raise ValueError("kind must be an IgnoredContentKind")
        _require_text(self.text, "text")
        _require_int(self.chapter_number, "chapter_number")
        if self.paragraph_index is not None:
            _require_int(self.paragraph_index, "paragraph_index", minimum=1)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind.value,
            "text": self.text,
            "chapter_number": self.chapter_number,
        }
        if self.paragraph_index is not None:
            data["paragraph_index"] = self.paragraph_index
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IgnoredOfficialContent":
        return cls(
            kind=IgnoredContentKind(data.get("kind")),
            text=data.get("text"),
            chapter_number=data.get("chapter_number"),
            paragraph_index=data.get("paragraph_index"),
        )


def build_official_tokens(
    transcript: StructuredTranscriptDTO,
    policy: NormalizationPolicy,
) -> tuple[tuple[OfficialTranscriptToken, ...], tuple[IgnoredOfficialContent, ...]]:
    """Tokenize only paragraph spoken text from the public structured DTO."""

    if not isinstance(transcript, StructuredTranscriptDTO):
        raise ValueError("transcript must be a StructuredTranscriptDTO")
    tokens: list[OfficialTranscriptToken] = []
    ignored: list[IgnoredOfficialContent] = []
    for chapter_index, chapter in enumerate(transcript.chapters, start=1):
        if chapter.title.strip():
            ignored.append(
                IgnoredOfficialContent(
                    IgnoredContentKind.CHAPTER_TITLE,
                    chapter.title,
                    chapter.number,
                )
            )
        for paragraph_index, paragraph in enumerate(chapter.paragraphs, start=1):
            inline_directions = tuple(match.group() for match in _INLINE_STAGE_DIRECTION.finditer(paragraph.text))
            spoken_text = _INLINE_STAGE_DIRECTION.sub(" ", paragraph.text).strip()
            if spoken_text:
                for surface in tokenize_surface_text(spoken_text, lexical_pattern=_OFFICIAL_LEXICAL_PATTERN):
                    tokens.append(
                        OfficialTranscriptToken(
                            id=f"ot{len(tokens) + 1}",
                            text=surface,
                            normalized=normalize_token(surface, policy),
                            chapter_index=chapter_index,
                            chapter_number=chapter.number,
                            paragraph_index=paragraph_index,
                            speaker_label=paragraph.speaker_label,
                        )
                    )
            ignored.extend(
                IgnoredOfficialContent(
                    IgnoredContentKind.STAGE_DIRECTION,
                    direction,
                    chapter.number,
                    paragraph_index,
                )
                for direction in paragraph.stage_directions + inline_directions
            )
    return tuple(tokens), tuple(ignored)


def official_surface_text(tokens: Sequence[OfficialTranscriptToken]) -> str:
    """Recover display punctuation for official tokens sharing one reading span."""

    surfaces = []
    for token in tokens:
        text = token.text
        body = text.strip(_QUANTITY_PUNCTUATION)
        quantity = _formatted_quantity(body.casefold().replace("’", "'"))
        if quantity is not None and not re.fullmatch(_AMOUNT_PATTERN, body.casefold()):
            formatted = quantity[1]
            if body.startswith(("The ", "The'")):
                formatted = formatted.capitalize()
            text = text.replace(body, formatted, 1)
        surfaces.append(text)
    surface = normalize_spoken_text(" ".join(surfaces))
    body = surface.strip(_QUANTITY_PUNCTUATION)
    percent = _spoken_percent(body.casefold())
    if percent is not None:
        surface = surface.replace(body, percent[1], 1)
    return _CLOCK_GROUP.sub(r"\1:\2", surface)


def numeric_clock_equivalent(
    asr_text: str,
    official: tuple[OfficialTranscriptToken, ...],
    indices: tuple[int, ...],
) -> bool:
    if len(indices) != 2:
        return False
    surface = " ".join(official[index].text for index in indices)
    match = _CLOCK_GROUP.fullmatch(surface.rstrip(",.!?;"))
    return match is not None and asr_text.rstrip(",.!?;") == "".join(match.groups())


@dataclass(frozen=True)
class OfficialAlignmentCandidate:
    official_token_id: str
    text: str
    start_ms: int
    end_ms: int
    alignment_score: float

    def __post_init__(self) -> None:
        _require_text(self.official_token_id, "official_token_id")
        if _OFFICIAL_TOKEN_ID_RE.fullmatch(self.official_token_id) is None:
            raise ValueError("official_token_id must use ot<one-based position>")
        _require_text(self.text, "text")
        SourceTimeSpan(self.start_ms, self.end_ms)
        if (
            isinstance(self.alignment_score, bool)
            or not isinstance(self.alignment_score, (int, float))
            or not math.isfinite(float(self.alignment_score))
            or not 0 <= float(self.alignment_score) <= 1
        ):
            raise ValueError("alignment_score must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_token_id": self.official_token_id,
            "text": self.text,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "alignment_score": self.alignment_score,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfficialAlignmentCandidate":
        return cls(
            official_token_id=data.get("official_token_id"),
            text=data.get("text"),
            start_ms=data.get("start_ms"),
            end_ms=data.get("end_ms"),
            alignment_score=data.get("alignment_score"),
        )


@dataclass(frozen=True)
class ExcludedOfficialTokens:
    official_token_ids: tuple[str, ...]
    reason: str
    left_anchor_id: str | None = None
    right_anchor_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "official_token_ids", tuple(self.official_token_ids))
        if not self.official_token_ids or not all(
            _OFFICIAL_TOKEN_ID_RE.fullmatch(token_id)
            for token_id in self.official_token_ids
        ):
            raise ValueError("official_token_ids must contain stable IDs")
        _require_text(self.reason, "reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_token_ids": list(self.official_token_ids),
            "reason": self.reason,
            "left_anchor_id": self.left_anchor_id,
            "right_anchor_id": self.right_anchor_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExcludedOfficialTokens":
        token_ids = _require_sequence(
            data.get("official_token_ids", []), "official_token_ids"
        )
        return cls(
            official_token_ids=tuple(token_ids),
            reason=data.get("reason"),
            left_anchor_id=data.get("left_anchor_id"),
            right_anchor_id=data.get("right_anchor_id"),
        )


class LocalValidationStatus(str, Enum):
    RECOVERED = "recovered"
    PARTIALLY_RECOVERED = "partially_recovered"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class LocalAlignmentValidation:
    official_token_ids: tuple[str, ...]
    left_anchor_id: str | None
    right_anchor_id: str | None
    status: LocalValidationStatus
    reason: str
    candidates: tuple[OfficialAlignmentCandidate, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "official_token_ids", tuple(self.official_token_ids))
        if not self.official_token_ids:
            raise ValueError("official_token_ids must not be empty")
        if not isinstance(self.status, LocalValidationStatus):
            raise ValueError("status must be a LocalValidationStatus")
        _require_text(self.reason, "reason")
        object.__setattr__(self, "candidates", tuple(self.candidates))
        if not all(
            isinstance(candidate, OfficialAlignmentCandidate)
            for candidate in self.candidates
        ):
            raise ValueError(
                "candidates must contain OfficialAlignmentCandidate values"
            )
        candidate_ids = tuple(
            candidate.official_token_id for candidate in self.candidates
        )
        if self.status is LocalValidationStatus.RECOVERED:
            if candidate_ids != self.official_token_ids:
                raise ValueError(
                    "recovered validation candidates must cover official tokens"
                )
        elif self.status is LocalValidationStatus.PARTIALLY_RECOVERED:
            candidate_set = set(candidate_ids)
            if (not candidate_ids or len(candidate_ids) >= len(self.official_token_ids)
                    or candidate_ids != tuple(token_id for token_id in self.official_token_ids if token_id in candidate_set)):
                raise ValueError("partial validation candidates must be an ordered proper subset")
        elif self.candidates:
            raise ValueError("excluded validation must not contain candidates")

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_token_ids": list(self.official_token_ids),
            "left_anchor_id": self.left_anchor_id,
            "right_anchor_id": self.right_anchor_id,
            "status": self.status.value,
            "reason": self.reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LocalAlignmentValidation":
        token_ids = _require_sequence(
            data.get("official_token_ids", []), "official_token_ids"
        )
        candidates = _require_sequence(data.get("candidates", []), "candidates")
        return cls(
            official_token_ids=tuple(token_ids),
            left_anchor_id=data.get("left_anchor_id"),
            right_anchor_id=data.get("right_anchor_id"),
            status=LocalValidationStatus(data.get("status")),
            reason=data.get("reason"),
            candidates=tuple(
                OfficialAlignmentCandidate.from_dict(candidate)
                for candidate in candidates
            ),
        )


class FusionMode(str, Enum):
    OFFICIAL = "official"
    NO_OFFICIAL = "no_official"


@dataclass(frozen=True)
class OfficialSentenceSpan:
    """Source IDs supporting an official sentence's location on the ASR track."""

    asr_word_ids: tuple[str, ...]
    official_token_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, pattern in (
            ("asr_word_ids", _ASR_WORD_ID_RE), ("official_token_ids", _OFFICIAL_TOKEN_ID_RE),
        ):
            values = tuple(getattr(self, name))
            if not values or not all(isinstance(value, str) and pattern.fullmatch(value) for value in values):
                raise ValueError(f"{name} must contain stable source IDs")
            object.__setattr__(self, name, values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asr_word_ids": list(self.asr_word_ids),
            "official_token_ids": list(self.official_token_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OfficialSentenceSpan":
        return cls(
            asr_word_ids=tuple(_require_sequence(data.get("asr_word_ids"), "asr_word_ids")),
            official_token_ids=tuple(_require_sequence(data.get("official_token_ids"), "official_token_ids")),
        )


@dataclass(frozen=True)
class ExcludedAsrWord:
    asr_word_id: str
    start_ms: int
    end_ms: int
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.asr_word_id, str) or not _ASR_WORD_ID_RE.fullmatch(self.asr_word_id):
            raise ValueError("asr_word_id must use a stable ASR ID")
        _require_int(self.start_ms, "excluded ASR start_ms")
        _require_int(self.end_ms, "excluded ASR end_ms", minimum=self.start_ms + 1)
        _require_text(self.reason, "excluded ASR reason")

    def to_dict(self) -> dict[str, Any]:
        return {"asr_word_id": self.asr_word_id, "start_ms": self.start_ms,
                "end_ms": self.end_ms, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExcludedAsrWord":
        return cls(data.get("asr_word_id"), data.get("start_ms"), data.get("end_ms"), data.get("reason"))


@dataclass(frozen=True)
class TranscriptFusionArtifact:
    audio_duration_ms: int
    aligned_asr_sha256: str
    chapters_sha256: str | None
    mode: FusionMode
    normalization: NormalizationPolicy
    matching: MatchingPolicy
    official_aligner: ProviderIdentity | None
    official_alignment_config: OfficialAlignmentConfig | None
    official_tokens: tuple[OfficialTranscriptToken, ...]
    ignored_content: tuple[IgnoredOfficialContent, ...]
    words: tuple[TimedWordDTO, ...]
    excluded_official: tuple[ExcludedOfficialTokens, ...]
    local_validations: tuple[LocalAlignmentValidation, ...]
    cache_key: str
    official_sentence_spans: tuple[OfficialSentenceSpan, ...] = ()
    excluded_asr: tuple[ExcludedAsrWord, ...] = ()
    schema_version: str = TRANSCRIPT_FUSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TRANSCRIPT_FUSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported transcript fusion schema: {self.schema_version}"
            )
        _require_int(self.audio_duration_ms, "audio_duration_ms", minimum=1)
        _require_text(self.aligned_asr_sha256, "aligned_asr_sha256")
        _require_text(self.cache_key, "cache_key")
        if not isinstance(self.mode, FusionMode):
            raise ValueError("mode must be a FusionMode")
        if not isinstance(self.normalization, NormalizationPolicy):
            raise ValueError("normalization must be a NormalizationPolicy")
        if not isinstance(self.matching, MatchingPolicy):
            raise ValueError("matching must be a MatchingPolicy")
        if (self.official_aligner is None) != (self.official_alignment_config is None):
            raise ValueError(
                "official aligner identity and config must appear together"
            )
        for name in (
            "official_tokens",
            "ignored_content",
            "words",
            "excluded_official",
            "local_validations",
            "official_sentence_spans",
            "excluded_asr",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        self._validate_mode()
        self._validate_words()
        self._validate_official_coverage()
        self._validate_official_sentence_spans()

    def _validate_mode(self) -> None:
        if self.mode is FusionMode.NO_OFFICIAL:
            if self.chapters_sha256 is not None or self.official_tokens:
                raise ValueError("no_official mode must not contain official input")
        else:
            _require_text(self.chapters_sha256, "chapters_sha256")

    def _validate_words(self) -> None:
        previous_end = 0
        all_asr_ids: list[str] = []
        for position, word in enumerate(self.words, start=1):
            if not isinstance(word, TimedWordDTO) or word.id != f"w{position}":
                raise ValueError("fusion words must use stable w1..wN IDs")
            if word.start_ms < previous_end or word.end_ms > self.audio_duration_ms:
                raise ValueError("fusion word timeline must be monotonic and in bounds")
            previous_end = word.end_ms
            all_asr_ids.extend(word.asr_word_ids)
            self._validate_mapping_cardinality(word)
        excluded_ids = [word.asr_word_id for word in self.excluded_asr]
        all_positions = [int(word_id[2:]) for word_id in all_asr_ids]
        excluded_positions = [int(word_id[2:]) for word_id in excluded_ids]
        if (all_positions != sorted(all_positions) or excluded_positions != sorted(excluded_positions)
                or sorted(all_positions + excluded_positions) != list(range(1, len(all_positions) + len(excluded_positions) + 1))
                or any(word.end_ms > self.audio_duration_ms for word in self.excluded_asr)):
            raise ValueError(
                "fusion must cover aligned ASR words exactly once in order"
            )

    def validate_asr_coverage(self, aligned: Sequence[AlignedAsrWord]) -> None:
        """Check the serialized accounting against the complete input, including its tail."""
        referenced = {word_id for word in self.words for word_id in word.asr_word_ids}
        excluded = {word.asr_word_id: (word.start_ms, word.end_ms) for word in self.excluded_asr}
        if (referenced | excluded.keys()) != {word.id for word in aligned} or any(
            word.id in excluded and excluded[word.id] != (word.start_ms, word.end_ms) for word in aligned
        ):
            raise ValueError("fusion source coverage differs from aligned ASR input")

    @staticmethod
    def _validate_mapping_cardinality(word: TimedWordDTO) -> None:
        cardinalities = {
            MatchType.EXACT: (1, 1),
            MatchType.NORMALIZED_EXACT: (1, 1),
            MatchType.SUBSTITUTION: (1, 1),
            MatchType.ONE_TO_MANY: (1, None),
            MatchType.MANY_TO_ONE: (None, 1),
            MatchType.MANY_TO_MANY: (None, None),
            MatchType.ASR_ONLY: (1, 0),
            MatchType.OFFICIAL_ONLY: (0, 1),
        }
        asr_expected, official_expected = cardinalities[word.match_type]
        if word.match_type is MatchType.SUBSTITUTION:
            if (not word.asr_word_ids or not word.official_token_ids
                    or word.text_source is not TextSource.OFFICIAL_TRANSCRIPT
                    or word.timing_source is TimingSource.MERGED_ACOUSTIC_ALIGNMENT):
                raise ValueError("substitution requires provenance from both sources")
            return
        if asr_expected is None:
            valid_asr = len(word.asr_word_ids) > 1
        else:
            valid_asr = len(word.asr_word_ids) == asr_expected
        if official_expected is None:
            valid_official = len(word.official_token_ids) > 1
        else:
            valid_official = len(word.official_token_ids) == official_expected
        if not valid_asr or not valid_official:
            raise ValueError("fusion mapping IDs do not match match_type cardinality")
        expected_text_source = {
            MatchType.EXACT: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.NORMALIZED_EXACT: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.SUBSTITUTION: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.ONE_TO_MANY: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.MANY_TO_ONE: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.MANY_TO_MANY: TextSource.OFFICIAL_TRANSCRIPT,
            MatchType.ASR_ONLY: TextSource.ASR,
            MatchType.OFFICIAL_ONLY: TextSource.OFFICIAL_TRANSCRIPT,
        }[word.match_type]
        if word.text_source is not expected_text_source:
            raise ValueError("fusion text_source does not match match_type")
        merged = word.match_type in {MatchType.MANY_TO_ONE, MatchType.MANY_TO_MANY}
        if merged != (word.timing_source is TimingSource.MERGED_ACOUSTIC_ALIGNMENT):
            raise ValueError("grouping multiple ASR words requires merged acoustic timing")
        if (
            word.match_type is MatchType.OFFICIAL_ONLY
            and word.timing_source is not TimingSource.ACOUSTIC_ALIGNMENT
        ):
            raise ValueError("official_only requires acoustic timing")

    def _validate_official_coverage(self) -> None:
        token_ids = [token.id for token in self.official_tokens]
        if token_ids != [f"ot{position}" for position in range(1, len(token_ids) + 1)]:
            raise ValueError("official tokens must use stable ot1..otN IDs")
        covered = [
            token_id
            for word in self.words
            for token_id in word.official_token_ids
        ]
        covered.extend(
            token_id
            for exclusion in self.excluded_official
            for token_id in exclusion.official_token_ids
        )
        if sorted(covered, key=lambda value: int(value[2:])) != token_ids:
            raise ValueError(
                "every official token must be mapped or explicitly excluded once"
            )

    def _validate_official_sentence_spans(self) -> None:
        tokens = {token.id for token in self.official_tokens}
        published_asr = {word_id for word in self.words for word_id in word.asr_word_ids}
        last_asr = last_official = 0
        for span in self.official_sentence_spans:
            if not set(span.asr_word_ids) <= published_asr or not set(span.official_token_ids) <= tokens:
                raise ValueError("official sentence span references unknown source words")
            asr = [int(value[2:]) for value in span.asr_word_ids]
            official = [int(value[2:]) for value in span.official_token_ids]
            if (asr != sorted(set(asr)) or official != sorted(set(official))
                    or asr[0] <= last_asr or official[0] <= last_official):
                raise ValueError("official sentence spans must follow source order")
            last_asr, last_official = asr[-1], official[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "audio_duration_ms": self.audio_duration_ms,
            "aligned_asr_sha256": self.aligned_asr_sha256,
            "chapters_sha256": self.chapters_sha256,
            "mode": self.mode.value,
            "normalization": self.normalization.to_dict(),
            "matching": self.matching.to_dict(),
            "official_aligner": (
                self.official_aligner.to_dict()
                if self.official_aligner is not None
                else None
            ),
            "official_alignment_config": (
                self.official_alignment_config.to_dict()
                if self.official_alignment_config is not None
                else None
            ),
            "official_tokens": [token.to_dict() for token in self.official_tokens],
            "ignored_content": [item.to_dict() for item in self.ignored_content],
            "words": [word.to_dict() for word in self.words],
            "excluded_official": [item.to_dict() for item in self.excluded_official],
            "local_validations": [item.to_dict() for item in self.local_validations],
            "official_sentence_spans": [item.to_dict() for item in self.official_sentence_spans],
            "excluded_asr": [item.to_dict() for item in self.excluded_asr],
            "cache_key": self.cache_key,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranscriptFusionArtifact":
        if data.get("schema_version") != TRANSCRIPT_FUSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported transcript fusion schema: {data.get('schema_version')}"
            )
        if "review_sentences" in data:
            raise ValueError("fusion contains an unsupported review transcript")
        normalization = data.get("normalization")
        matching = data.get("matching")
        aligner = data.get("official_aligner")
        alignment_config = data.get("official_alignment_config")
        if not isinstance(normalization, Mapping) or not isinstance(matching, Mapping):
            raise ValueError("normalization and matching must be objects")
        sequences = {
            name: _require_sequence(data.get(name), name)
            for name in (
                "official_tokens",
                "ignored_content",
                "words",
                "excluded_official",
                "local_validations",
                "official_sentence_spans",
                "excluded_asr",
            )
        }
        return cls(
            schema_version=data.get("schema_version"),
            audio_duration_ms=data.get("audio_duration_ms"),
            aligned_asr_sha256=data.get("aligned_asr_sha256"),
            chapters_sha256=data.get("chapters_sha256"),
            mode=FusionMode(data.get("mode")),
            normalization=NormalizationPolicy.from_dict(normalization),
            matching=MatchingPolicy.from_dict(matching),
            official_aligner=(
                ProviderIdentity.from_dict(aligner)
                if isinstance(aligner, Mapping)
                else None
            ),
            official_alignment_config=(
                OfficialAlignmentConfig.from_dict(alignment_config)
                if isinstance(alignment_config, Mapping)
                else None
            ),
            official_tokens=tuple(
                OfficialTranscriptToken.from_dict(item)
                for item in sequences["official_tokens"]
            ),
            ignored_content=tuple(
                IgnoredOfficialContent.from_dict(item)
                for item in sequences["ignored_content"]
            ),
            words=tuple(TimedWordDTO.from_dict(item) for item in sequences["words"]),
            excluded_official=tuple(
                ExcludedOfficialTokens.from_dict(item)
                for item in sequences["excluded_official"]
            ),
            local_validations=tuple(
                LocalAlignmentValidation.from_dict(item)
                for item in sequences["local_validations"]
            ),
            cache_key=data.get("cache_key"),
            official_sentence_spans=tuple(
                OfficialSentenceSpan.from_dict(item) for item in sequences["official_sentence_spans"]
            ),
            excluded_asr=tuple(
                ExcludedAsrWord.from_dict(item) for item in sequences["excluded_asr"]
            ),
        )


def aligned_timing_source(source: AlignmentTimingSource) -> TimingSource:
    if source is AlignmentTimingSource.ACOUSTIC_ALIGNMENT:
        return TimingSource.ACOUSTIC_ALIGNMENT
    return TimingSource.INTERPOLATED
