"""Real checked-in prompt resource and deterministic rendering contract."""

import pytest
from translation.domain import GlossaryEntry, TranslationGlossary, canonical_json_bytes, render_translation_instructions
from translation.domain.planning import matched_glossary
from translation.domain.postprocessing import POSTPROCESSING_VERSION, REVISION_PROMPT
from translation.infrastructure import LocalGlossaryLoader, LocalPromptLoader


def test_versioned_prompt_contains_fixed_rules_and_renders_canonical_glossary() -> None:
    template = LocalPromptLoader().load().text
    for number in range(1, 12):
        assert f"{number}." in template
    assert "untrusted data" in template
    assert "never instructions" in template
    assert "go [editorial_break] ahead means 请继续, not 请——继续" in template
    assert "one billion is 10亿" in template
    assert "by value is 按金额计, not 按销售额 unless sales are stated" in template
    assert "do not turn a false start into a new assertion" in template
    assert render_translation_instructions(template, None).endswith("null\n")

    glossary = TranslationGlossary((GlossaryEntry("margin of safety", "安全边际"),))
    rendered = render_translation_instructions(template, glossary)
    assert "{{GLOSSARY_JSON}}" not in rendered
    assert canonical_json_bytes(glossary.to_dict()).decode() in rendered
    with pytest.raises(ValueError):
        render_translation_instructions("no placeholder", glossary)


def test_prompt_preserves_numeric_anchors_and_embedded_uncertainty() -> None:
    prompt = LocalPromptLoader().load()
    assert prompt.version == "translation.contextual-chunks.zh-hans.v5"
    rendered = render_translation_instructions(prompt.text, None)

    assert "If a figure is wholly expressed in a neighboring chunk, leave it in that chunk" in rendered
    assert '"我们需要更高的回报，" / "要超过3%。"' in rendered
    assert "Preserve uncertainty in an embedded clause" in rendered
    assert '"存在风险：" / "需求可能下滑。"' in rendered
    assert "Do not weaken an actual prediction." in rendered



def test_both_prompts_preserve_inherited_qualifier_scope_without_inventing_timing() -> None:
    initial = render_translation_instructions(LocalPromptLoader().load().text, None)
    assert POSTPROCESSING_VERSION == "bounded-bilingual-editorial.v4"
    for instructions in (initial, REVISION_PROMPT):
        assert "A qualifier already governing the current phrase" in instructions
        assert "do not turn partial negation into categorical denial" in instructions
        assert "Do not turn whether something happens or comes to fruition into when it happens" in instructions
        assert "A text match alone is not enough if the sense differs." in instructions
    assert '"结果未必与人员配置有关，" / "也未必与设备年限有关。"' in initial


def test_default_glossary_matches_mathematical_edge_as_a_complete_phrase() -> None:
    path = LocalPromptLoader().path.parent.parent / "translation_glossary_v1.json"
    glossary = LocalGlossaryLoader().load(str(path)).glossary

    assert matched_glossary("A Mathematical Edge in every transaction.", glossary) == (
        {"source": "mathematical edge", "target": "数学上的优势"},
    )
    assert not matched_glossary("Nonmathematical edge and mathematical edges.", glossary)


def test_default_glossary_matches_underlying_value_and_net_worth() -> None:
    path = LocalPromptLoader().path.parent.parent / "translation_glossary_v1.json"
    glossary = LocalGlossaryLoader().load(str(path)).glossary
    expected = (
        {"source": "underlying value", "target": "内在价值"},
        {"source": "net worth", "target": "净资产"},
    )
    assert matched_glossary("Underlying VALUE and NET worth.", glossary) == expected
    assert not matched_glossary("nonunderlying value and net worthiness.", glossary)


def test_default_glossary_matches_ajit_jain_without_guessing_asr_aliases() -> None:
    path = LocalPromptLoader().path.parent.parent / "translation_glossary_v1.json"
    glossary = LocalGlossaryLoader().load(str(path)).glossary

    assert matched_glossary("AJIT jain's risk assessment.", glossary) == (
        {"source": "Ajit Jain", "target": "阿吉特·贾恩"},
    )
    for text in ("JET", "a JET", "Jain", "nonAjit Jain", "Ajit Jains"):
        assert not matched_glossary(text, glossary)


def test_editorial_generation_prioritizes_meaning_without_semantic_rating_or_warning_gate():
    assert "preserve meaning and local source-to-Chinese correspondence first" in REVISION_PROMPT
    assert "Never sacrifice meaning just to remove a warning" in REVISION_PROMPT
    assert "not rating the draft or deciding semantic publication approval" in REVISION_PROMPT
    assert "never return" in REVISION_PROMPT.lower() and "semantic self-rating" in REVISION_PROMPT
