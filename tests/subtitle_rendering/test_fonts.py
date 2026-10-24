"""Exact font gates use byte/table/measurement fakes, never system fonts."""

from dataclasses import replace
import hashlib
from types import SimpleNamespace

import pytest

from archive_core.interfaces import RenderFontSpecDTO, RenderLineMetricsDTO
from subtitle_rendering.domain.layout import UNICODE_CLASSIFICATION_VERSION
from subtitle_rendering.infrastructure import fonts
from subtitle_rendering.infrastructure.fonts import (
    ExactFontAdapter, FontValidationError, RegexGraphemeSegmenter, validate_libass_font_selection,
)


DATA = b"ttcf-test-font-bytes"


def face(family="Hiragino Sans GB", style="W3", postscript="HiraginoSansGB-W3"):
    names = [SimpleNamespace(nameID=index, toUnicode=lambda value=value: value)
             for index, value in ((16, family), (17, style), (6, postscript))]
    cmap = {code: f"glyph{code}" for code in (*range(32, 127), ord("中"), ord("文"))}
    return {"name": SimpleNamespace(names=names),
            "cmap": SimpleNamespace(tables=[SimpleNamespace(isUnicode=lambda: True, cmap=cmap)])}


class FakeMeasurementFont:
    def __init__(self, size, name=("Hiragino Sans GB", "W3")):
        self.size, self.name = size, name

    def getname(self):
        return self.name

    def getbbox(self, text):
        return -2, -3, len(text) * self.size, self.size + 2

    def getlength(self, text):
        return len(text) * self.size - 1

    def getmetrics(self):
        return self.size, 4


@pytest.fixture
def setup_font(monkeypatch):
    state = SimpleNamespace(faces=[face(), face(style="W6", postscript="HiraginoSansGB-W6")],
                            measurement_name=("Hiragino Sans GB", "W3"), calls=[])
    monkeypatch.setattr(fonts.Path, "read_bytes", lambda self: DATA)
    monkeypatch.setattr(fonts, "TTCollection", lambda stream: SimpleNamespace(fonts=state.faces, close=lambda: None))
    monkeypatch.setattr(fonts.features, "check_feature", lambda name: True)
    monkeypatch.setattr(fonts.features, "version", lambda name: "test-" + name)

    def truetype(stream, size, *, index, layout_engine):
        state.calls.append((stream.getvalue(), size, index, layout_engine))
        return FakeMeasurementFont(size, state.measurement_name)

    monkeypatch.setattr(fonts.ImageFont, "truetype", truetype)
    state.spec = replace(RenderFontSpecDTO(), path="/tmp/exact-font.ttc", sha256=hashlib.sha256(DATA).hexdigest())
    return state


def test_exact_font_identity_and_measurement_are_bound_to_bytes_face_and_all_engines(setup_font):
    adapter = ExactFontAdapter(setup_font.spec, ("中文 Hello",))
    identity = adapter.identity
    assert identity.spec == setup_font.spec
    assert identity.size_bytes == len(DATA)
    assert identity.postscript_name == "HiraginoSansGB-W3"
    tokens = identity.measurement_adapter_version.split(";")
    assert RegexGraphemeSegmenter.version in tokens
    assert UNICODE_CLASSIFICATION_VERSION in tokens
    assert f"Pillow={fonts.PIL.__version__}" in tokens
    assert f"fontTools={fonts.fontTools.__version__}" in tokens
    assert "freetype2=test-freetype2" in tokens and "harfbuzz=test-harfbuzz" in tokens
    assert adapter.measure("中文", 30, 2, 1) == RenderLineMetricsDTO(67, 40)
    assert all(call[0] == DATA and call[2] == 0 for call in setup_font.calls)
    adapter.measure("中文", 30, 2, 1)
    assert [call[1] for call in setup_font.calls] == [1, 30]


@pytest.mark.parametrize("mutation", (
    lambda state: setattr(state, "spec", replace(state.spec, sha256="0" * 64)),
    lambda state: setattr(state, "spec", replace(state.spec, face_index=2)),
    lambda state: setattr(state, "spec", replace(state.spec, family="Other")),
    lambda state: setattr(state, "spec", replace(state.spec, style="W6")),
    lambda state: state.faces.append(face(style="W9")),
    lambda state: setattr(state, "measurement_name", ("Hiragino Sans GB", "W6")),
    lambda state: state.faces[0]["name"].names.pop(),
    lambda state: state.faces[0]["name"].names.append(SimpleNamespace(nameID=6, toUnicode=lambda: "OtherPS")),
    lambda state: state.faces[0]["cmap"].tables[0].cmap.update({ord("中"): ".notdef"}),
))
def test_font_fingerprint_family_style_face_uniqueness_and_glyph_failures(setup_font, mutation):
    mutation(setup_font)
    with pytest.raises(FontValidationError):
        ExactFontAdapter(setup_font.spec, ("中文",))


def test_font_missing_file_is_controlled(setup_font, monkeypatch):
    def missing(path):
        raise FileNotFoundError()

    monkeypatch.setattr(fonts.Path, "read_bytes", missing)
    with pytest.raises(FontValidationError, match="could not be verified"):
        ExactFontAdapter(setup_font.spec, ("中文",))


def test_invalid_font_binary_is_controlled(setup_font, monkeypatch):
    def invalid(stream):
        raise fonts.TTLibError("bad font")

    monkeypatch.setattr(fonts, "TTCollection", invalid)
    with pytest.raises(FontValidationError):
        ExactFontAdapter(setup_font.spec, ("中文",))


def test_missing_shaper_cannot_silently_select_a_different_measurement_engine(setup_font, monkeypatch):
    monkeypatch.setattr(fonts.features, "check_feature", lambda name: False)
    with pytest.raises(FontValidationError, match="shaping"):
        ExactFontAdapter(setup_font.spec, ("中文",))


@pytest.mark.parametrize("text", ("emoji😀", "e\u0301", "\u2060", "\u200d", "缺"))
def test_authoritative_missing_codepoints_including_ignorable_controls_are_not_exempt(setup_font, text):
    with pytest.raises(FontValidationError, match="glyph"):
        ExactFontAdapter(setup_font.spec, (text,))


@pytest.mark.parametrize("args", (("中", True, 2, 1), ("中", 30, -1, 1), ("中", 30, 2, 1.5), ("", 30, 2, 1)))
def test_measurement_parameters_are_strict(setup_font, args):
    adapter = ExactFontAdapter(setup_font.spec, ("中",))
    with pytest.raises(FontValidationError):
        adapter.measure(*args)


def selection(identity, index=-1):
    return (f"[Parsed_ass_0 @ 0x123] fontselect: ({identity.spec.family}, 400, 0) -> "
            f"{identity.spec.path}, {index}, {identity.postscript_name}")


@pytest.mark.parametrize("index", (-1, 0))
def test_libass_exact_file_and_unique_postscript_face_mapping(setup_font, index):
    adapter = ExactFontAdapter(setup_font.spec, ("中文",))
    validate_libass_font_selection(selection(adapter.identity, index), adapter.identity)


def test_merely_loading_a_font_named_fallback_does_not_mean_it_was_selected(setup_font):
    identity = ExactFontAdapter(setup_font.spec, ("中文",)).identity
    validate_libass_font_selection("Loading font file '/font/CJKSymbolsFallback.ttc'\n" + selection(identity), identity)


@pytest.mark.parametrize("mutation", (
    lambda text: "", lambda text: text.replace("400", "700"), lambda text: text.replace(", 400, 0)", ", 400, 1)"),
    lambda text: text.replace("exact-font.ttc", "other-font.ttc"),
    lambda text: text.replace("-1, HiraginoSansGB-W3", "1, HiraginoSansGB-W3"),
    lambda text: text.replace("HiraginoSansGB-W3", "HiraginoSansGB-W6"),
    lambda text: text.replace("fontselect:", "fontselect: unknown dialect"),
    lambda text: text + "\nGlyph 0x123 not found, selecting one more font",
    lambda text: text + "\nfailed to find any fallback with glyph 0x123",
    lambda text: text + "\nfontselect: unknown",
))
def test_actual_missing_unknown_or_different_font_evidence_is_rejected(setup_font, mutation):
    identity = ExactFontAdapter(setup_font.spec, ("中文",)).identity
    with pytest.raises(FontValidationError):
        validate_libass_font_selection(mutation(selection(identity)), identity)


@pytest.mark.parametrize("token", ("A\u0301", "👩\u200d💻", "✈\ufe0f", "🇨🇳", "👍🏽", "क्\u200dष", "각"))
def test_regex_adapter_emits_complete_grapheme_boundaries(token):
    assert RegexGraphemeSegmenter().boundaries("甲" + token + "乙") == (0, 1, len(token) + 1, len(token) + 2)
    assert RegexGraphemeSegmenter().boundaries("") == (0,)
