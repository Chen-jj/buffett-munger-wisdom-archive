"""Offline constituency-feature tests; no Stanza model or media assets are loaded."""

import hashlib
import json
import re
from types import SimpleNamespace as NS

import pytest

from archive_core.interfaces.transcription import (
    MatchType, TextSource, TimedWordDTO, TimingSource, reconstruct_sentence_text,
)
from srt_processing.domain.chunking import SyntaxSpan, _split_sentence
from srt_processing.infrastructure import stanza_chunking


def parse_tree(value):
    tokens = re.findall(r"\(|\)|[^\s()]+", value)
    position = 0

    def read():
        nonlocal position
        assert tokens[position] == "("
        label = tokens[position + 1]
        position += 2
        children = []
        while tokens[position] != ")":
            if tokens[position] == "(":
                children.append(read())
            else:
                children.append(NS(label=tokens[position], children=[]))
                position += 1
        position += 1
        return NS(label=label, children=children)

    result = read()
    assert position == len(tokens)
    return result


def fixture(tree_text, canonical=None):
    tree = parse_tree(tree_text)
    tagged = []

    def visit(node):
        if node.children and not node.children[0].children:
            tagged.append((node.children[0].label, node.label))
        else:
            for child in node.children:
                visit(child)

    visit(tree)
    if canonical is None:
        canonical = []
        for value, _ in tagged:
            if value in {",", ".", ";", ":", "?", "!", "%"} and canonical:
                canonical[-1] += value
            else:
                canonical.append(value)
    words = tuple(TimedWordDTO(f"w{index + 1}", value, index * 500, index * 500 + 450,
                              (f"aw{index + 1}",), (), MatchType.ASR_ONLY,
                              TextSource.ASR, TimingSource.ACOUSTIC_ALIGNMENT)
                  for index, value in enumerate(canonical))
    text = reconstruct_sentence_text(words)
    tokens, cursor = [], 0
    for value, tag in tagged:
        first = text.index(value, cursor)
        end = first + len(value)
        tokens.append(NS(text=value, start_char=first, end_char=end,
                         words=[NS(text=value, xpos=tag)]))
        cursor = end
    return words, NS(sentences=[NS(tokens=tokens, constituency=tree)])


def analyze(tree_text, canonical=None):
    words, document = fixture(tree_text, canonical)
    return stanza_chunking.analyze_stanza_sentence(words, document)


def relations(result):
    return {boundary.offset: set(boundary.relations) for boundary in result.boundaries}


def forbidden(result):
    return {offset for span in result.protected_spans
            for offset in range(int(span.first_word_id[1:]), int(span.last_word_id[1:]))}


def test_coordinated_predicates_keep_pp_internal_protection_but_not_all_vb_pp_are_core_dependencies():
    result = analyze("""(ROOT (S (NP (DT The) (NNP Earth)) (VP
        (VP (VBZ revolves) (PP (IN around) (NP (DT the) (NN sun))))
        (CC and) (VP (VBZ circles) (NP (NNS stars))))))""")
    found = relations(result)
    assert found[2] == {"subject.predicate"}
    assert found[3] == {"phrase.preposition"}
    assert found[6] == {"clause.coordinate"}
    assert found[7] == {"connector.after"}
    assert {1, 4, 5} <= forbidden(result)
    assert 3 not in forbidden(result)


def test_vb_pp_adjunct_is_not_claimed_to_be_a_required_complement():
    result = analyze("(ROOT (S (NP (PRP I)) (VP (VBP work) (PP (IN during) (NP (DT the) (NN day))))))")
    assert relations(result)[2] == {"phrase.preposition"}
    assert 2 not in forbidden(result)


@pytest.mark.parametrize("comma", [False, True])
def test_relative_attachment_is_typed_not_hard_protected_and_comma_is_evidence(comma):
    punctuation = "(, ,)" if comma else ""
    result = analyze(f"""(ROOT (S (NP (NP (DT the) (NN number)) {punctuation}
        (SBAR (WHNP (WDT that)) (S (VP (VBD fell))))) (VP (VBZ matters))))""")
    found = relations(result)[2]
    assert "clause.relative" in found
    assert ("evidence.relative.comma" if comma else "evidence.relative.no-comma") in found
    assert ("punctuation" in found) == comma
    assert 2 not in forbidden(result)
    assert SyntaxSpan(2, 4, "relative") in result.spans
    assert [span for span in result.spans if span.kind == "statement"] == [SyntaxSpan(0, 5, "statement")]


def test_clause_complement_retains_punctuation_without_losing_dependency():
    result = analyze("""(ROOT (S (NP (PRP I)) (VP (VBD said) (, ,)
        (SBAR (IN that) (S (NP (PRP they)) (VP (VBD agreed)))))))""")
    assert {"punctuation", "predicate.complement"} <= relations(result)[2]
    assert "connector.after" in relations(result)[3]
    assert [span for span in result.spans if span.kind == "statement"] == [SyntaxSpan(0, 5, "statement")]


def test_noun_infinitive_is_soft_but_to_verb_core_is_protected():
    result = analyze("""(ROOT (S (NP (DT the) (NN ability) (S (VP (TO to)
        (VP (VB keep) (NP (DT the) (NN width)))))) (VP (VBZ matters))))""")
    assert "noun.infinitive" in relations(result)[2]
    assert SyntaxSpan(2, 6, "infinitive") in result.spans
    assert 2 not in forbidden(result) and {1, 3, 5} <= forbidden(result)


def test_statements_exclude_relative_and_complement_s_and_do_not_include_umbrella_s():
    result = analyze("""(ROOT (S
        (S (NP (PRP I)) (VP (VBP know) (SBAR (IN that)
            (S (NP (DT the) (NN number) (SBAR (WHNP (WDT that))
                (S (VP (VBD fell))))) (VP (VBZ matters))))))
        (, ,) (CC and) (S (NP (PRP we)) (VP (VBP agree)))))""")
    statements = [span for span in result.spans if span.kind == "statement"]
    assert statements == [SyntaxSpan(0, 8, "statement"), SyntaxSpan(8, 11, "statement")]
    assert {"clause.coordinate", "punctuation"} <= relations(result)[8]
    assert "connector.after" in relations(result)[9]


@pytest.mark.parametrize("connector,tag", [("so", "RB"), ("however", "ADVP")])
def test_structural_between_statement_connector_belongs_with_following_statement(connector, tag):
    marker = f"(RB {connector})" if tag == "RB" else f"(ADVP (RB {connector}))"
    result = analyze(f"""(ROOT (S (S (NP (PRP I)) (VP (VBP agree))) (, ,)
        {marker} (S (NP (PRP we)) (VP (VBP continue)))))""")
    assert "clause.coordinate" in relations(result)[2]
    assert "connector.after" in relations(result)[3]
    assert 3 not in forbidden(result)


def test_so_inside_degree_phrase_is_not_a_discourse_connector():
    result = analyze("(ROOT (S (NP (PRP I)) (VP (VBP work) (ADVP (RB so) (RB slowly)))))")
    assert not any("connector.after" in boundary.relations for boundary in result.boundaries)
    assert "attachment.adverbial" in relations(result)[2]


@pytest.mark.parametrize("subtree", [
    "(SBAR (IN if) (S (NP (PRP we)) (VP (VBP live))))",
    "(S (VP (VBG assuming) (SBAR (S (NP (PRP we)) (VP (VBP live))))))",
])
def test_conditional_requires_clause_structure_and_is_not_a_predicate_complement(subtree):
    result = analyze(f"(ROOT (S (NP (PRP I)) (VP (VBP continue) {subtree})))")
    found = relations(result)[2]
    assert "clause.adverbial" in found
    assert "predicate.complement" not in found
    assert any(span.first == 2 and span.kind == "adverbial" for span in result.spans)


def test_marker_word_without_adverbial_clause_is_not_given_a_clause_reward():
    result = analyze("(ROOT (S (NP (PRP I)) (VP (VBP know) (NP (DT the) (NN when)))))")
    assert not any("clause.adverbial" in boundary.relations for boundary in result.boundaries)


def test_umbrella_sentence_starting_with_if_is_not_entirely_an_adverbial_span():
    result = analyze("""(ROOT (S (SBAR (IN if) (S (NP (PRP we)) (VP (VBP live)))) (, ,)
        (S (NP (PRP I)) (VP (VBP continue)))))""")
    assert [span for span in result.spans if span.kind == "adverbial"] == [SyntaxSpan(0, 3, "adverbial")]
    assert [span for span in result.spans if span.kind == "statement"] == [SyntaxSpan(3, 5, "statement")]


@pytest.mark.parametrize("number,number_tree", [
    ("one-half", "(NP (QP (CD one) (HYPH -) (NN half)))"),
    ("three-quarters", "(NP (NN three-quarters))"),
    ("0.5", "(NP (CD 0.5))"),
])
def test_fraction_and_denominator_protection_is_structural_not_sample_specific(number, number_tree):
    result = analyze(f"""(ROOT (PP (IN of) (NP {number_tree}
        (PP (IN of) (NP (CD one) (NN percent))))))""", ["of", number, "of", "one", "percent"])
    assert forbidden(result) == {1, 2, 3, 4}
    assert any(span.reason == "stanza.quantity-core.v1" and span.first_word_id == "w2"
               and span.last_word_id == "w5" for span in result.protected_spans)
    assert all(0 < boundary.offset < 5 for boundary in result.boundaries)


def test_long_pp_protects_only_nominal_head_not_relative_or_another_pp():
    result = analyze("""(ROOT (PP (IN by) (NP (NP (NP (DT the) (NN people))
        (SBAR (WHNP (WP who)) (S (VP (VBP work)))))
        (PP (IN in) (NP (DT the) (NN city))))))""")
    assert {1, 2, 6, 7} <= forbidden(result)
    assert {3, 5}.isdisjoint(forbidden(result))
    assert not any(span.first_word_id == "w1" and span.last_word_id == "w8" for span in result.protected_spans)


def test_whpp_where_complement_is_not_swallowed_by_outer_people_pp():
    result = analyze("""(ROOT (PP (IN by) (NP (NNS people)
        (WHPP (IN for) (SBAR (WHADVP (WRB where))
            (S (NP (DT the) (JJ economic) (NN benefit)) (VP (VBZ comes))))))))""")
    assert 1 in forbidden(result)
    assert {2, 3}.isdisjoint(forbidden(result))


def test_nonquantity_of_modifier_does_not_lock_the_full_noun_phrase():
    result = analyze("""(ROOT (NP (NP (DT a) (NN collection))
        (PP (IN of) (NP (CD three) (NNS coins)))))""")
    assert 2 not in forbidden(result)
    assert not any(span.reason == "stanza.quantity-core.v1" and span.first_word_id == "w1"
                   for span in result.protected_spans)


def test_nominal_core_stops_before_appended_filler_and_coordination():
    result = analyze("""(ROOT (NP (NP (DT the) (NNS activities)) (, ,) (UH uh)
        (CC or) (NP (DT the) (NNS ideas))))""")
    assert 1 in forbidden(result) and 5 in forbidden(result)
    assert {2, 3, 4}.isdisjoint(forbidden(result))


@pytest.mark.parametrize("predicate", [
    "(VP (MD will) (ADVP (RB really)) (RB not) (VP (VB have) (VP (VBN finished))))",
    "(VP (VBZ has) (RB not) (RB really) (VBN finished))",
])
def test_auxiliary_negation_and_intervening_adverbs_are_minimal_verb_core(predicate):
    result = analyze(f"(ROOT (S (NP (PRP She)) {predicate}))")
    assert all(offset in forbidden(result) for offset in range(2, len(result.boundaries) + 1))
    assert 1 not in forbidden(result)  # Subject/predicate stays a soft typed dependency.


def test_lexical_have_object_and_following_adjunct_are_not_an_auxiliary_chain():
    result = analyze("""(ROOT (S (NP (PRP I)) (VP (VBP have) (NP (NNS coins))
        (PP (IN in) (NP (DT the) (NN box))))))""")
    assert 2 not in forbidden(result) and 3 not in forbidden(result)
    assert not any(span.reason == "stanza.auxiliary-negation-verb.v2" for span in result.protected_spans)


def test_overlapping_aux_neg_name_protections_do_not_create_word_internal_boundaries():
    result = analyze("""(ROOT (S (NP (NNP Jane) (NNP Doe))
        (VP (VBP do) (RB n't) (RB really) (VB know))))""", ["Jane", "Doe", "don't", "really", "know"])
    assert {boundary.offset for boundary in result.boundaries} == {1, 2, 3, 4}
    assert forbidden(result) == {1, 3, 4}
    assert len(result.protected_spans) == len(set(result.protected_spans))


def test_numeric_comma_does_not_receive_punctuation_reward():
    result = analyze("(ROOT (NP (CD 1) (, ,) (CD 000) (NNS shares)))", ["1,", "000", "shares"])
    assert 1 in forbidden(result)
    assert "punctuation" not in relations(result)[1]


def test_auxiliary_does_not_swallow_a_coordinated_punctuated_adverbial():
    result = analyze("""(ROOT (S (NP (PRP We)) (VP (VBP do) (RB n't)
        (ADVP (RB intentionally) (, ,) (CC or) (RB willingly) (, ,) (RB voluntarily) (, ,))
        (VP (VB go) (PP (IN into) (NP (NNS situations)))))))""",
        ["We", "don't", "intentionally,", "or", "willingly,", "voluntarily,", "go", "into", "situations"])
    assert {3, 5, 6}.isdisjoint(forbidden(result))
    assert 2 not in forbidden(result)  # No proven compact verb core across this coordinated adjunct.
    assert not any(span.first_word_id == "w2" and span.last_word_id == "w7"
                   for span in result.protected_spans)


@pytest.mark.parametrize("tag,modifier,head", [("NML", "(NN razor) (CC and) (NN blade)", "business"),
                                               ("ADJP", "(JJ black) (CC and) (JJ white)", "car")])
def test_coordinated_modifier_right_edge_stays_with_shared_noun_head(tag, modifier, head):
    result = analyze(f"(ROOT (NP (DT the) ({tag} {modifier}) (NN {head})))")
    assert 4 in forbidden(result)
    assert any(span.first_word_id == "w4" and span.last_word_id == "w5"
               and span.reason == "stanza.coordinated-nominal-head.v1" for span in result.protected_spans)
    assert 2 not in forbidden(result)  # Not an indivisible whole coordinated NP.


def test_autonomous_coordinated_nouns_are_not_locked_as_a_shared_head():
    result = analyze("(ROOT (NP (NP (NNP Acme)) (CC and) (NP (NNP Rival))))")
    assert not result.protected_spans


@pytest.mark.parametrize("subject,auxiliary,verb,tag", [
    ("they", "'ve", "had", "VBN"), ("they", "'re", "working", "VBG"),
    ("it", "'s", "grown", "VBN"), ("I", "'d", "finished", "VBN"),
    ("I", "'m", "working", "VBG"), ("they", "\u2019ve", "had", "VBN"),
])
def test_contracted_auxiliary_requires_vp_structure_and_may_cross_simple_adverbs(subject, auxiliary, verb, tag):
    result = analyze(f"""(ROOT (S (NP (PRP {subject})) (VP (VBP {auxiliary})
        (ADVP (RB ever)) (VP ({tag} {verb})))))""", [subject + auxiliary, "ever", verb])
    assert forbidden(result) == {1, 2}


def test_possessive_s_and_copula_before_a_noun_are_not_invented_auxiliary_chains():
    possessive = analyze("(ROOT (S (NP (NNP Jane) (POS 's) (NN company)) (VP (VBZ grows))))",
                         ["Jane's", "company", "grows"])
    copula = analyze("(ROOT (S (NP (PRP it)) (VP (VBZ 's) (NP (DT a) (NN company)))))",
                     ["it's", "a", "company"])
    assert not any(span.reason == "stanza.auxiliary-negation-verb.v2"
                   for result in (possessive, copula) for span in result.protected_spans)


@pytest.mark.parametrize("marker,tag", [("that", "WDT"), ("who", "WP"), ("where", "WRB")])
def test_direct_relative_pos_marker_has_attachment_and_following_clause_relation(marker, tag):
    result = analyze(f"""(ROOT (NP (NP (NNS risks)) (SBAR ({tag} {marker})
        (S (VP (VBP fall))))))""")
    assert {"clause.relative", "evidence.relative.no-comma"} <= relations(result)[1]
    assert "connector.after" in relations(result)[2]
    assert {1, 2}.isdisjoint(forbidden(result))


def test_wh_determiner_without_a_relative_clause_does_not_create_relative_evidence():
    result = analyze("(ROOT (NP (WDT which) (NN business)))")
    assert not any("clause.relative" in b.relations for b in result.boundaries)


def test_numeric_enumeration_keeps_soft_boundaries_and_only_local_last_item_unit_protection():
    result = analyze("""(ROOT (NP (QP (CD five) (, ,) (CD ten) (, ,) (CD fifteen)) (NNS years)))""")
    found = relations(result)
    assert {"punctuation", "attachment.quantity", "evidence.quantity.enumeration"} <= found[1]
    assert {"punctuation", "attachment.quantity"} <= found[2]
    assert {1, 2}.isdisjoint(forbidden(result)) and 3 in forbidden(result)


def test_digit_comma_ambiguity_protection_is_not_silently_overridden_by_enumeration_evidence():
    result = analyze("""(ROOT (NP (QP (CD five) (, ,) (CD 10) (, ,) (CD 15)) (NNS years)))""")
    assert "attachment.quantity" in relations(result)[2]
    assert 1 not in forbidden(result) and {2, 3} <= forbidden(result)
    assert any(span.reason == "canonical.numeric-comma.v1" for span in result.protected_spans)


def test_multiword_numeric_items_are_protected_individually_not_as_a_whole_long_list():
    result = analyze("""(ROOT (NP (QP (CD twenty) (CD five) (, ,) (CD thirty) (CD six)
        (, ,) (CD forty) (CD seven)) (NNS years)))""")
    assert {1, 3, 5, 6} <= forbidden(result)
    assert {2, 4}.isdisjoint(forbidden(result))
    assert all(not (span.first_word_id == "w1" and span.last_word_id == "w7")
               for span in result.protected_spans)


def test_comma_between_independent_numeric_statements_is_not_a_quantity_list():
    result = analyze("""(ROOT (S (S (NP (CD five) (NNS people)) (VP (VBP work))) (, ,)
        (S (NP (CD ten) (NNS people)) (VP (VBP rest)))))""")
    assert "punctuation" in relations(result)[3]
    assert not any("attachment.quantity" in b.relations for b in result.boundaries)


def test_contiguous_subordinate_marker_chain_is_a_local_core_not_the_whole_clause():
    result = analyze("""(ROOT (SBAR (IN so) (IN that) (, ,)
        (S (NP (PRP we)) (VP (VBP benefit)))))""")
    assert 1 in forbidden(result) and 2 not in forbidden(result)
    assert "connector.after" in relations(result)[2]
    assert any(span.reason == "stanza.clause-marker-core.v1" for span in result.protected_spans)


def test_prepositions_outside_a_subordinate_marker_chain_are_not_marker_protections():
    result = analyze("(ROOT (PP (IN from) (PP (IN within) (NP (DT the) (NN company)))))")
    assert not any(span.reason == "stanza.clause-marker-core.v1" for span in result.protected_spans)


def test_time_np_ago_inside_one_adverbial_has_soft_attachment_not_whole_time_protection():
    result = analyze("""(ROOT (S (NP (PRP I)) (VP (VBD wrote)
        (ADVP (NP (DT a) (JJ few) (NNS years)) (RB ago)))))""")
    assert {"attachment.adverbial", "evidence.temporal.ago"} <= relations(result)[5]
    assert 5 not in forbidden(result)


def test_ago_token_without_adverbial_np_attachment_does_not_trigger_time_rule():
    result = analyze("(ROOT (NP (DT the) (NN word) (NN ago)))")
    assert not any("evidence.temporal.ago" in b.relations for b in result.boundaries)


@pytest.mark.parametrize("marker", ["(CC And)", "(RB so)", "(ADVP (RB however))",
                                    "(CC And) (ADVP (RB then))"])
def test_independent_statement_includes_its_structurally_attached_marker(marker):
    result = analyze(f"""(ROOT (S {marker} (S (NP (DT the) (NN company))
        (VP (MD will) (VP (VB grow))))))""")
    statement = next(span for span in result.spans if span.kind == "statement")
    assert statement.first == 0
    marker_words = 2 if "then" in marker else 1
    assert "connector.after" in relations(result)[marker_words]


def test_external_marker_passes_through_a_pure_s_wrapper_without_losing_ownership():
    result = analyze("""(ROOT (S (RB so) (S (S (NP (DT the) (NN company))
        (VP (MD will) (VP (VB grow)))))))""")
    assert [span for span in result.spans if span.kind == "statement"] == [SyntaxSpan(0, 5, "statement")]
    assert "connector.after" in relations(result)[1]


def test_coordinate_marker_does_not_swallow_the_preceding_complete_statement():
    result = analyze("""(ROOT (S (S (NP (PRP I)) (VP (VBP agree))) (, ,) (RB so)
        (S (NP (PRP we)) (VP (VBP continue)))))""")
    assert [span for span in result.spans if span.kind == "statement"] == [
        SyntaxSpan(0, 2, "statement"), SyntaxSpan(2, 5, "statement")]
    assert "connector.after" in relations(result)[3]


def test_statement_marker_does_not_extend_back_across_a_conditional_clause():
    result = analyze("""(ROOT (S (CC And) (S
        (SBAR (IN if) (S (NP (PRP we)) (VP (VBP live)))) (, ,)
        (ADVP (RB however)) (S (NP (PRP I)) (VP (VBP continue))))))""")
    assert [span for span in result.spans if span.kind == "statement"] == [SyntaxSpan(4, 7, "statement")]
    assert SyntaxSpan(1, 4, "adverbial") in result.spans


def test_adverbial_containing_another_clause_is_not_a_statement_marker():
    result = analyze("""(ROOT (S (ADVP (S (NP (PRP we)) (VP (VBP agree)))) (, ,)
        (S (NP (PRP I)) (VP (VBP continue)))))""")
    assert [span for span in result.spans if span.kind == "statement"] == [SyntaxSpan(2, 4, "statement")]


@pytest.mark.parametrize("clause", [
    "(SQ (MD would) (NP (PRP you)) (VP (VB give) (NP (NNS answers))))",
    "(SQ (VBP do) (NP (PRP you)) (VP (VP (VB have) (NP (NNS answers)))))",
    "(SINV (VBP have) (NP (PRP we)) (ADVP (RB ever)) (VP (VBN seen) (NP (NNS results))))",
])
def test_inverted_auxiliary_pronoun_and_first_verb_form_only_a_local_core(clause):
    result = analyze(f"(ROOT {clause})")
    assert "subject.predicate" in relations(result)[1]
    assert "evidence.inversion.aux-subject" in relations(result)[1]
    assert {1, 2} <= forbidden(result)
    assert any(span.reason == "stanza.inverted-pronoun-core.v1" for span in result.protected_spans)
    assert max(int(span.last_word_id[1:]) for span in result.protected_spans
               if span.reason == "stanza.inverted-pronoun-core.v1") < len(result.boundaries) + 1


def test_inverted_negative_contraction_still_maps_to_whole_canonical_words():
    result = analyze("(ROOT (SQ (VBP do) (RB n't) (NP (PRP you)) (VP (VB know))))",
                     ["don't", "you", "know"])
    assert forbidden(result) == {1, 2}
    assert {b.offset for b in result.boundaries} == {1, 2}


def test_inversion_long_nominal_subject_is_typed_but_not_one_hard_auxiliary_span():
    result = analyze("""(ROOT (SQ (MD would) (NP (DT the) (JJ entire) (NN board))
        (VP (VB give) (NP (NNS answers)))))""")
    assert "subject.predicate" in relations(result)[1]
    assert "subject.predicate" in relations(result)[4]
    assert 1 not in forbidden(result) and 4 not in forbidden(result)
    assert not any(span.reason == "stanza.inverted-pronoun-core.v1" for span in result.protected_spans)


def test_inversion_does_not_bridge_a_comma_or_coordinated_adverbial_to_the_verb():
    result = analyze("""(ROOT (SQ (MD would) (NP (PRP you))
        (ADVP (RB willingly) (, ,) (CC or) (RB voluntarily) (, ,))
        (VP (VB give) (NP (NNS answers)))))""")
    assert 1 in forbidden(result) and {2, 3, 4, 5}.isdisjoint(forbidden(result))
    assert not any(span.first_word_id == "w1" and span.last_word_id == "w6"
                   for span in result.protected_spans)


def test_inversion_does_not_treat_a_nonauxiliary_lexical_verb_as_an_auxiliary():
    result = analyze("(ROOT (SINV (VBD sang) (NP (PRP he)) (ADVP (RB softly))))")
    assert not any(span.reason == "stanza.inverted-pronoun-core.v1" for span in result.protected_spans)


@pytest.mark.parametrize("question", [
    "(SQ (MD would) (NP (PRP you)) (VP (VB give) (NP (NNS answers))))",
    "(SBARQ (WHNP (WP what)) (SQ (VBP do) (NP (PRP you)) (VP (VB have))))",
    "(SBARQ (WHNP (WP who)) (SQ (VBD arrived)))",
])
def test_punctuated_complete_question_intro_is_not_a_predicate_complement(question):
    result = analyze(f"(ROOT (S (NP (DT The) (NN question)) (VP (VBZ is) (, ,) {question})))")
    assert "clause.interrogative" in relations(result)[3]
    assert "predicate.complement" not in relations(result)[3]


@pytest.mark.parametrize("question", [
    "(SQ (MD would) (NP (PRP you)))",
    "(SBARQ (WHNP (WP what)))",
    "(SBARQ (WHNP (WP what)) (SQ (MD would) (NP (PRP you))))",
    "(SBARQ (WHNP (WP who)) (SQ (MD would)))",
])
def test_punctuation_alone_does_not_make_an_incomplete_question_an_independent_intro(question):
    result = analyze(f"(ROOT (S (NP (DT The) (NN question)) (VP (VBZ is) (, ,) {question})))")
    assert "clause.interrogative" not in relations(result)[3]
    assert "predicate.complement" in relations(result)[3]


def test_unpunctuated_embedded_question_is_not_relabelled_as_a_question_intro():
    result = analyze("""(ROOT (S (NP (PRP I)) (VP (VBP wonder)
        (SBARQ (WHNP (WP what)) (SQ (VBP do) (NP (PRP you)) (VP (VB have)))))))""")
    assert "clause.interrogative" not in relations(result)[2]
    assert "predicate.complement" in relations(result)[2]


def test_direct_wh_pos_with_its_own_subject_predicate_is_uncertain_nominal_clause():
    result = analyze("""(ROOT (NP (NNS risks) (SBAR (WDT that)
        (S (NP (DT the) (NN business)) (VP (VBZ changes))))))""")
    assert "noun.clause" in relations(result)[1]
    assert "clause.relative" not in relations(result)[1]
    assert "evidence.relative.no-comma" not in relations(result)[1]
    assert "connector.after" in relations(result)[2]
    assert 1 not in forbidden(result)


def test_whnp_relative_is_not_downgraded_even_with_an_explicit_subject():
    result = analyze("""(ROOT (NP (DT the) (NN book) (SBAR (WHNP (WDT that))
        (S (NP (PRP we)) (VP (VBD bought))))))""")
    assert {"clause.relative", "evidence.relative.no-comma"} <= relations(result)[2]
    assert "noun.clause" not in relations(result)[2]
    assert "connector.after" in relations(result)[3]


@pytest.mark.parametrize("content", ["(NP (NN value))", "(PP (IN at) (NP (NN work)))"])
def test_comma_participial_supplement_requires_an_already_completed_predicate_content(content):
    result = analyze(f"""(ROOT (S (NP (PRP We)) (VP (VBD gained) {content} (, ,)
        (S (VP (VBG producing) (NP (NNS returns)))))))""")
    entry = next(b for b in result.boundaries if "evidence.participial.supplement" in b.relations)
    assert "clause.adverbial" in entry.relations and "predicate.complement" not in entry.relations


def test_bare_kept_comma_running_is_not_proven_to_be_a_free_supplement():
    result = analyze("(ROOT (S (NP (PRP We)) (VP (VBD kept) (, ,) (S (VP (VBG running))))))")
    assert "predicate.complement" in relations(result)[2]
    assert "evidence.participial.supplement" not in relations(result)[2]


def test_nonfinite_complement_without_comma_keeps_the_original_dependency():
    result = analyze("""(ROOT (S (NP (PRP We)) (VP (VBD kept) (NP (NNS machines))
        (S (VP (VBG running))))))""")
    assert "predicate.complement" in relations(result)[3]
    assert "evidence.participial.supplement" not in relations(result)[3]


def test_finite_clause_after_comma_is_not_a_participial_supplement():
    result = analyze("""(ROOT (S (NP (PRP We)) (VP (VBD saw) (NP (NNS results)) (, ,)
        (S (NP (PRP they)) (VP (VBD improved))))))""")
    assert "predicate.complement" in relations(result)[3]
    assert "evidence.participial.supplement" not in relations(result)[3]


@pytest.mark.parametrize("nominal", [
    "(NP (NP (DT a) (NN rate)) (PP (IN of) (NP (NN return))))",
    "(NP (NP (QP (RB over) (CD 70)) (NN %)) (PP (IN of) (NP (DT the) (NN market))))",
    "(WHNP (WHNP (WDT what) (NN kind)) (PP (IN of) (NP (DT a) (NN moat))))",
    "(NP (NP (NNS millions)) (PP (IN of) (NP (NNS people))))",
    "(NP (NNS terms) (PP (IN of) (NP (DT that) (NN moat))))",
    "(NML (NN director) (PP (IN of) (NP (DT the) (NN company))))",
    "(QP (CD one) (PP (IN of) (NP (DT the) (NNS companies))))",
])
def test_nominal_of_attachment_has_a_visible_head_and_remains_soft(nominal):
    words, document = fixture(f"(ROOT {nominal})")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    offset = next(index for index, word in enumerate(words) if word.text == "of")
    assert {"attachment.nominal-of", "phrase.preposition"} <= relations(result)[offset]
    assert offset not in forbidden(result)


@pytest.mark.parametrize("quantifier", ["all", "most", "some"])
def test_nonarticle_partitive_heads_are_accepted_without_inventing_a_noun(quantifier):
    result = analyze(f"(ROOT (NP (NP (DT {quantifier})) (PP (IN of) (NP (PRP$ our) (NNS businesses)))))")
    assert "attachment.nominal-of" in relations(result)[1]
    assert 1 not in forbidden(result)


@pytest.mark.parametrize("article", ["the", "a", "an"])
def test_article_only_damaged_nominal_does_not_supply_a_partitive_head(article):
    result = analyze(f"(ROOT (NP (NP (DT {article})) (PP (IN of) (NP (DT the) (NN company)))))")
    assert not any("attachment.nominal-of" in b.relations for b in result.boundaries)


@pytest.mark.parametrize("tree", [
    "(ROOT (VP (VBP think) (PP (IN of) (NP (NNS ideas)))))",
    "(ROOT (NP (PP (IN of) (NP (DT the) (NN company)))))",
    "(ROOT (PP (IN of) (NP (DT the) (NN company))))",
    "(ROOT (NP (PP (IN near) (NP (DT the) (NN company))) (PP (IN of) (NP (NN value)))))",
    "(ROOT (NP (SBAR (IN that) (S (NP (DT the) (NN company)) (VP (VBZ grows)))) (PP (IN of) (NP (NN value)))))",
])
def test_nominal_of_does_not_borrow_a_head_from_verbs_prepositions_or_unrelated_clauses(tree):
    result = analyze(tree)
    assert not any("attachment.nominal-of" in b.relations for b in result.boundaries)


@pytest.mark.parametrize("preposition", ["in", "from", "around"])
def test_non_of_nominal_pp_is_not_reclassified(preposition):
    result = analyze(f"(ROOT (NP (NN value) (PP (IN {preposition}) (NP (DT the) (NN company)))))")
    assert relations(result)[1] == {"phrase.preposition"}


def test_repeated_nominal_of_modifiers_do_not_lock_the_entire_chain():
    result = analyze("""(ROOT (NP (NP (NN rate)) (PP (IN of) (NP (NN return)))
        (PP (IN of) (NP (NN investment)))))""")
    assert "attachment.nominal-of" in relations(result)[1]
    assert "attachment.nominal-of" in relations(result)[3]
    assert {1, 3}.isdisjoint(forbidden(result))


def test_nominal_of_capacity_can_still_use_the_soft_boundary():
    head, object_ = "x" * 50, "y" * 34
    words, document = fixture(f"(ROOT (NP (NN {head}) (PP (IN of) (NP (NN {object_})))))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    parts = _split_sentence(words, result, ())
    assert parts is not None and [tuple(word.id for word in part) for part in parts] == [("w1",), ("w2", "w3")]
    assert "attachment.nominal-of" in relations(result)[1]


@pytest.mark.parametrize("body", [
    "(SBAR (WHNP (WDT what)) (S (NP (PRP we)) (VP (VBP choose))))",
    "(WHADVP (WRB how)) (S (NP (PRP we)) (VP (VBP proceed)))",
])
def test_concessive_prefix_protects_only_no_matter_and_the_wh_marker(body):
    result = analyze(f"(ROOT (ADVP (DT no) (NN matter) {body}))")
    cores = [span for span in result.protected_spans if span.reason == "stanza.concessive-prefix.v1"]
    assert [(span.first_word_id, span.last_word_id) for span in cores] == [("w1", "w3")]
    assert {1, 2} <= forbidden(result)
    assert 3 not in forbidden(result)
    assert "connector.after" in relations(result)[3]
    assert not any(span.first_word_id == "w1" and span.last_word_id != "w3" for span in result.protected_spans)


def test_concessive_prefix_does_not_lock_a_long_wh_phrase_or_put_connector_inside_it():
    result = analyze("""(ROOT (ADVP (DT no) (NN matter) (SBAR
        (WHNP (WDT which) (JJ complicated) (NN proposal))
        (S (NP (PRP we)) (VP (VBP choose) (PP (IN after) (NP (DT the) (NN discussion))))))))""")
    core = next(span for span in result.protected_spans if span.reason == "stanza.concessive-prefix.v1")
    assert (core.first_word_id, core.last_word_id) == ("w1", "w3")
    assert "connector.after" not in relations(result)[3]
    assert "connector.after" in relations(result)[5]
    assert {3, 5, 7}.isdisjoint(forbidden(result))


@pytest.mark.parametrize("tree", [
    "(ROOT (NP (DT no) (NN matter) (SBAR (WHNP (WDT what)) (S (NP (PRP we)) (VP (VBP choose))))))",
    "(ROOT (ADVP (DT no) (NN matter) (NP (DT the) (NN choice))))",
    "(ROOT (ADVP (DT no) (NN matter)) (SBARQ (WHNP (WP what)) (SQ (VBD happened))))",
    "(ROOT (ADVP (DT no) (NN matter) (WHNP (DT the) (NN choice))))",
])
def test_unrelated_matter_or_missing_wh_is_not_a_concessive_core(tree):
    result = analyze(tree)
    assert not any(span.reason == "stanza.concessive-prefix.v1" for span in result.protected_spans)


def test_concessive_connector_does_not_cross_a_comma_after_a_complete_wh_prefix():
    result = analyze("""(ROOT (ADVP (DT no) (NN matter) (WHNP (WP what)) (, ,)
        (S (NP (PRP we)) (VP (VBP continue)))))""")
    assert "connector.after" not in relations(result)[3]
    assert "punctuation" in relations(result)[3]
    assert 3 not in forbidden(result)


@pytest.mark.parametrize("left,right", [("RP", "RB"), ("RB", "RP"), ("RB", "RB")])
def test_three_item_nonclausal_adverb_coordination_is_soft_before_cc(left, right):
    result = analyze(f"(ROOT (VP (VBP move) (ADVP ({left} up) (CC and) ({right} down))))")
    assert "attachment.coordination" in relations(result)[2]
    assert "connector.after" in relations(result)[3]
    assert 2 not in forbidden(result)


@pytest.mark.parametrize("adverbs", [
    "(RB intentionally) (, ,) (CC or) (RB willingly) (, ,) (RB voluntarily)",
    "(RB up) (CC and) (RB down) (CC and) (RB sideways)",
    "(ADVP (RB up)) (CC and) (ADVP (RB down))",
    "(RB up) (CC and) (S (NP (PRP we)) (VP (VBP continue)))",
])
def test_long_interrupted_or_clausal_adverb_lists_do_not_get_the_local_coordination_rule(adverbs):
    result = analyze(f"(ROOT (VP (VBP move) (ADVP {adverbs})))")
    assert not any("attachment.coordination" in boundary.relations for boundary in result.boundaries)
    assert not any(span.first_word_id == "w2" for span in result.protected_spans)


def test_three_item_adverb_coordination_capacity_can_use_its_soft_boundary():
    left, right = "x" * 80, "y" * 80
    words, document = fixture(f"(ROOT (ADVP (RB {left}) (CC and) (RB {right})))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    parts = _split_sentence(words, result, ())
    assert parts is not None and [tuple(word.id for word in part) for part in parts] == [("w1",), ("w2", "w3")]
    assert "attachment.coordination" in relations(result)[1]


@pytest.mark.parametrize("parent,degree_tag,quantifier", [
    ("NP", "RB", "all"), ("NP", "RBR", "most"), ("QP", "RBS", "some"),
])
def test_degree_scope_before_local_partitive_quantifier_is_soft(parent, degree_tag, quantifier):
    result = analyze(f"(ROOT ({parent} ({degree_tag} virtually) (DT {quantifier})))")
    assert "attachment.scope" in relations(result)[1]
    assert 1 not in forbidden(result)


@pytest.mark.parametrize("tree", [
    "(ROOT (NP (RB virtually) (DT the)))",
    "(ROOT (NP (RB virtually) (, ,) (DT all)))",
    "(ROOT (S (RB actually) (NP (DT all) (NNS businesses)) (VP (VBP grow))))",
    "(ROOT (ADVP (RB almost) (DT all)))",
])
def test_scope_rule_does_not_cross_punctuation_or_guess_from_a_sentence_initial_adverb(tree):
    assert not any("attachment.scope" in boundary.relations for boundary in analyze(tree).boundaries)


@pytest.mark.parametrize("quantity", ["(CD three)", "(DT a) (JJ few)", "(JJ several)", "(JJ many)", "(DT some)"])
def test_quantified_times_np_directly_attached_to_vp_is_frequency(quantity):
    words, document = fixture(f"(ROOT (VP (VBP fluctuate) (NP {quantity} (NNS times))))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    assert "attachment.frequency" in relations(result)[1]
    assert 1 not in forbidden(result)


@pytest.mark.parametrize("tree", [
    "(ROOT (VP (VBP remember) (NP (DT those) (NNS times))))",
    "(ROOT (VP (VBP read) (NP (CD three) (NNP Times))))",
    "(ROOT (VP (VBP count) (NP (CD three) (NNS businesses))))",
    "(ROOT (NP (CD three) (NNS times)))",
    "(ROOT (VP (VBP recall) (NP (NP (NNS times)) (PP (IN with) (NP (CD three) (NNS friends))))))",
    "(ROOT (VP (VBP recall) (NP (SBAR (IN when) (S (NP (CD three) (NNS people)) (VP (VBD arrived)))) (NNS times))))",
])
def test_frequency_is_not_inferred_from_demonstrative_times_proper_names_or_unrelated_quantity(tree):
    assert not any("attachment.frequency" in boundary.relations for boundary in analyze(tree).boundaries)


@pytest.mark.parametrize("head", [
    "(NP (CD five) (NNS years))", "(NP (DT a) (JJ few) (NNS months))",
    "(NP (QP (CD five) (, ,) (CD ten) (, ,) (CD fifteen)) (NNS years))",
])
def test_quantified_time_plus_from_now_has_two_soft_local_attachments(head):
    words, document = fixture(f"(ROOT (NP {head} (PP (IN from) (ADVP (RB now)))))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    offset = next(index for index, word in enumerate(words) if word.text == "from")
    assert "attachment.temporal" in relations(result)[offset]
    assert "attachment.temporal" in relations(result)[offset + 1]
    assert {offset, offset + 1}.isdisjoint(forbidden(result))
    assert not any(span.last_word_id == words[-1].id for span in result.protected_spans)


@pytest.mark.parametrize("tree", [
    "(ROOT (NP (NP (CD five) (NNS years)) (PP (IN from) (NP (NNP London)))))",
    "(ROOT (NP (NP (CD five) (NNS years)) (PP (IN from) (ADVP (RB overseas)))))",
    "(ROOT (NP (NP (NN income)) (PP (IN from) (ADVP (RB now)))))",
    "(ROOT (NP (NP (CD five) (NNS companies)) (PP (IN from) (ADVP (RB now)))))",
    "(ROOT (NP (NP (DT those) (NNS years)) (PP (IN from) (ADVP (RB now)))))",
    "(ROOT (NP (NP (SBAR (IN when) (S (NP (CD three) (NNS people)) (VP (VBD arrived)))) (NNS years)) (PP (IN from) (ADVP (RB now)))))",
])
def test_temporal_attachment_requires_a_local_quantity_time_unit_and_exact_from_now(tree):
    assert not any("attachment.temporal" in boundary.relations for boundary in analyze(tree).boundaries)


@pytest.mark.parametrize("verb,tag", [
    ("am", "VBP"), ("is", "VBZ"), ("are", "VBP"), ("was", "VBD"), ("were", "VBD"),
    ("be", "VB"), ("been", "VBN"), ("being", "VBG"),
])
def test_copular_be_with_adjective_protects_only_the_minimal_predicate_core(verb, tag):
    result = analyze(f"""(ROOT (VP ({tag} {verb}) (RB not) (ADJP (JJ related)
        (PP (IN to) (NP (JJ intrinsic) (NN value))))))""")
    core = next(span for span in result.protected_spans if span.reason == "stanza.copular-adjective-core.v1")
    assert (core.first_word_id, core.last_word_id) == ("w1", "w3")
    assert {1, 2} <= forbidden(result)
    assert 3 not in forbidden(result)


@pytest.mark.parametrize("prefix", [
    "", "(RB very)", "(RBR more)", "(RBS most)", "(RB not) (RB particularly)", "(ADVP (RB rather) (RB unusually))",
])
def test_copular_adjp_direct_pure_adverb_prefix_is_part_of_the_minimal_core(prefix):
    words, document = fixture(f"(ROOT (VP (VBZ is) (ADJP {prefix} (JJ clear) (PP (IN about) (NP (DT the) (NN issue))))))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    core = next(span for span in result.protected_spans if span.reason == "stanza.copular-adjective-core.v1")
    last = next(word.id for word in words if word.text == "clear")
    assert (core.first_word_id, core.last_word_id) == ("w1", last)
    assert int(last[1:]) not in forbidden(result)


def test_copular_vp_simple_adverb_phrase_does_not_extend_protection_past_first_adjective():
    result = analyze("""(ROOT (VP (VBP are) (ADVP (RB not) (RB particularly))
        (ADJP (JJ clear) (PP (IN about) (NP (DT the) (NN issue))))))""")
    core = next(span for span in result.protected_spans if span.reason == "stanza.copular-adjective-core.v1")
    assert (core.first_word_id, core.last_word_id) == ("w1", "w4")
    assert 4 not in forbidden(result)


@pytest.mark.parametrize("clitic,subject", [("'m", "I"), ("'re", "We"), ("'s", "It")])
def test_contracted_be_needs_vp_and_adjective_evidence_and_keeps_exact_canonical_mapping(clitic, subject):
    result = analyze(f"(ROOT (S (NP (PRP {subject})) (VP (VBP {clitic}) (RB not) (ADJP (JJ certain)))))",
                     [subject + clitic, "not", "certain"])
    core = next(span for span in result.protected_spans if span.reason == "stanza.copular-adjective-core.v1")
    assert (core.first_word_id, core.last_word_id) == ("w1", "w3")


@pytest.mark.parametrize("tree", [
    "(ROOT (VP (VBZ has) (RB not) (ADJP (JJ related))))",
    "(ROOT (VP (VBP keep) (RB not) (ADJP (JJ related))))",
    "(ROOT (VP (MD be) (ADJP (JJ related))))",
    "(ROOT (NP (NN be) (ADJP (JJ related))))",
    "(ROOT (NP (NN company) (POS 's) (ADJP (JJ related))))",
    "(ROOT (VP (VBP are) (, ,) (RB not) (ADJP (JJ related))))",
    "(ROOT (VP (VBP are) (ADVP (RB intentionally) (, ,) (CC or) (RB willingly)) (ADJP (JJ related))))",
    "(ROOT (VP (VBP are) (ADJP (ADJP (JJ related)))))",
    "(ROOT (VP (VBP are) (ADJP (PP (IN in) (NP (NN part))) (JJ related))))",
    "(ROOT (VP (VBP are) (ADJP (RB not) (, ,) (JJ related))))",
    "(ROOT (VP (VBP are) (ADJP (RB not) (CC or) (JJ related))))",
    "(ROOT (VP (VBP are) (ADJP (ADVP (RB almost) (S (NP (PRP we)) (VP (VBP agree)))) (JJ related))))",
])
def test_copular_core_does_not_guess_from_other_verbs_or_cross_nonpure_prefixes(tree):
    assert not any(span.reason == "stanza.copular-adjective-core.v1" for span in analyze(tree).protected_spans)


def test_long_copular_adjective_complement_still_has_a_legal_capacity_cut_after_its_head():
    object_ = "x" * 66
    words, document = fixture(f"(ROOT (VP (VBP are) (RB not) (ADJP (JJ related) (PP (IN to) (NP (NN {object_}))))))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    parts = _split_sentence(words, result, ())
    assert parts is not None and [tuple(word.id for word in part) for part in parts] == [("w1", "w2", "w3"), ("w4", "w5")]


@pytest.mark.parametrize("wrapper", [
    "{body}", "(SBAR {body})", "(SBAR (S (SBAR {body})))",
])
@pytest.mark.parametrize("adverb,tag", [("currently", "RB"), ("often", "RB"), ("better", "RBR")])
def test_bare_vp_complement_wrapper_attaches_its_single_adverb_to_first_direct_verb(wrapper, adverb, tag):
    body = f"(S (ADVP ({tag} {adverb})) (VP (VBP exist) (PP (IN in) (NP (DT a) (NN business)))))"
    result = analyze(f"(ROOT (VP (VBP perceive) {wrapper.format(body=body)}))")
    core = next(span for span in result.protected_spans if span.reason == "stanza.complement-adverb-verb-core.v1")
    assert (core.first_word_id, core.last_word_id) == ("w2", "w3")
    assert "predicate.complement" in relations(result)[1]
    assert 1 not in forbidden(result) and 2 in forbidden(result) and 3 not in forbidden(result)


@pytest.mark.parametrize("tree", [
    "(ROOT (S (ADVP (RB currently)) (VP (VBP exist))))",
    "(ROOT (VP (VBP perceive) (SBAR (IN if) (S (ADVP (RB currently)) (VP (VBP exist))))))",
    "(ROOT (VP (VBP perceive) (SBAR (WHADVP (WRB when)) (S (ADVP (RB currently)) (VP (VBP exist))))))",
    "(ROOT (VP (VBP perceive) (S (NP (NNS companies)) (ADVP (RB currently)) (VP (VBP exist)))))",
    "(ROOT (VP (VBP perceive) (S (ADVP (RB almost) (RB always)) (VP (VBP exist)))))",
    "(ROOT (VP (VBP perceive) (S (ADVP (RB currently) (, ,) (RB really)) (VP (VBP exist)))))",
    "(ROOT (VP (VBP perceive) (S (ADVP (RB currently)) (, ,) (VP (VBP exist)))))",
    "(ROOT (VP (VBP perceive) (S (ADVP (RB currently)) (VP (MD can) (VP (VB exist))))))",
    "(ROOT (VP (VBP perceive) (S (ADVP (RB currently)) (VP (VP (VBP exist))))))",
    "(ROOT (VP (VBP perceive) (SBARQ (WHNP (WP what)) (S (ADVP (RB currently)) (VP (VBP exist))))))",
    "(ROOT (VP (VBP saw) (NP (NNS results)) (, ,) (S (ADVP (RB currently)) (VP (VBG improving)))))",
    "(ROOT (VP (VBP perceive) (S (S (NP (PRP we)) (VP (VBP know))) (S (ADVP (RB currently)) (VP (VBP exist))))))",
])
def test_complement_adverb_core_does_not_consume_markers_statements_or_interrupted_prefixes(tree):
    assert not any(span.reason == "stanza.complement-adverb-verb-core.v1" for span in analyze(tree).protected_spans)


def test_long_bare_complement_keeps_a_capacity_cut_after_the_two_word_core():
    object_ = "x" * 65
    words, document = fixture(f"(ROOT (VP (VBP perceive) (SBAR (S (ADVP (RB currently)) (VP (VBP exist) (PP (IN in) (NP (NN {object_}))))))))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    parts = _split_sentence(words, result, ())
    assert parts is not None and [tuple(word.id for word in part) for part in parts] == [("w1", "w2", "w3"), ("w4", "w5")]


@pytest.mark.parametrize("head,preposition", [
    ("(JJ related)", "to"), ("(RB very) (JJ good)", "at"),
    ("(ADVP (RB quite)) (JJ ready)", "for"), ("(JJR better)", "than"), ("(JJS best)", "in"),
])
def test_direct_adjective_head_owned_pp_gets_only_a_soft_attachment(head, preposition):
    words, document = fixture(f"(ROOT (ADJP {head} (PP (IN {preposition}) (NP (DT the) (NN business)))))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    offset = next(index for index, word in enumerate(words) if word.text == preposition)
    assert {"phrase.preposition", "attachment.adjectival"} <= relations(result)[offset]
    assert offset not in forbidden(result)
    assert not any(span.reason.startswith("stanza.adjectiv") for span in result.protected_spans)


@pytest.mark.parametrize("tree", [
    "(ROOT (VP (VBN related) (PP (IN to) (NP (NN value)))))",
    "(ROOT (NP (JJ related) (NN value) (PP (IN to) (NP (NN business)))))",
    "(ROOT (ADJP (RB currently) (PP (IN in) (NP (NN business)))))",
    "(ROOT (ADJP (ADJP (JJ related)) (PP (IN to) (NP (NN value)))))",
    "(ROOT (ADJP (ADJP (ADVP (IN at) (JJS least)) (RB as) (JJ important)) (PP (IN as) (NP (DT an) (NN ability)))))",
    "(ROOT (ADJP (JJ related) (, ,) (PP (IN to) (NP (NN value)))))",
    "(ROOT (ADJP (JJ related) (CC and) (PP (IN to) (NP (NN value)))))",
    "(ROOT (ADJP (JJ related) (PRN (RB arguably)) (PP (IN to) (NP (NN value)))))",
    "(ROOT (ADJP (JJ related) (S (NP (PRP we)) (VP (VBP agree))) (PP (IN to) (NP (NN value)))))",
    "(ROOT (ADJP (JJ related) (ADVP (RB actually)) (PP (IN to) (NP (NN value)))))",
])
def test_adjectival_pp_attachment_does_not_borrow_a_head_or_cross_intervening_material(tree):
    result = analyze(tree)
    assert not any("attachment.adjectival" in boundary.relations for boundary in result.boundaries)


def test_adjectival_pp_capacity_can_still_use_the_soft_boundary():
    head, object_ = "x" * 50, "y" * 34
    words, document = fixture(f"(ROOT (ADJP (JJ {head}) (PP (IN to) (NP (NN {object_})))))")
    result = stanza_chunking.analyze_stanza_sentence(words, document)
    parts = _split_sentence(words, result, ())
    assert parts is not None and [tuple(word.id for word in part) for part in parts] == [("w1",), ("w2", "w3")]
    assert "attachment.adjectival" in relations(result)[1]


@pytest.mark.parametrize("damage", ["token-span", "tree-leaf", "expanded-word", "multiple-sentences"])
def test_exact_mapping_still_fails_closed(damage):
    words, document = fixture("(ROOT (S (NP (PRP I)) (VP (VBP agree))))")
    if damage == "token-span":
        document.sentences[0].tokens[0].end_char = 2
    elif damage == "tree-leaf":
        document.sentences[0].constituency.children[0].children[0].children[0].children[0].label = "you"
    elif damage == "expanded-word":
        document.sentences[0].tokens[1].words[0].text = "agreed"
    else:
        document.sentences.append(document.sentences[0])
    with pytest.raises(ValueError):
        stanza_chunking.analyze_stanza_sentence(words, document)


def test_identity_versions_features_and_protection_without_changing_the_model(tmp_path, monkeypatch):
    weights = tmp_path / "weights"
    weights.write_bytes(b"fixed-offline-model")
    lock = {"stanza_version": stanza_chunking.STANZA_VERSION, "processors": {"constituency": "fixed"},
            "files": {"weights": hashlib.sha256(weights.read_bytes()).hexdigest()}, "transformer_path": "transformer"}
    lock_path = tmp_path / "model_identity.json"
    lock_path.write_text(json.dumps(lock))
    monkeypatch.setattr(stanza_chunking, "MODEL_LOCK_PATH", lock_path)
    monkeypatch.setattr(stanza_chunking, "version", lambda _: stanza_chunking.STANZA_VERSION)
    analyzer = stanza_chunking.StanzaConstituencyAnalyzer(str(tmp_path))
    assert analyzer.identity["mapping"] == "exact-char-spans.v1"
    assert analyzer.identity["protection"] == "minimal-np-pp-quantity-aux-marker-inversion-scope-predicate.v6"
    assert analyzer.identity["ranking"] == "typed-constituency-relations.v10"
    assert analyzer._pipeline is None
