"""Pinned, offline-only Stanza constituency analysis with exact source mapping."""

from __future__ import annotations

from importlib.metadata import version
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable

from archive_core.interfaces.bilingual import ProtectedSpanDTO
from archive_core.interfaces.transcription import TimedWordDTO, reconstruct_sentence_text
from srt_processing.domain.chunking import SyntaxAnalysis, SyntaxBoundary, SyntaxSpan


STANZA_VERSION = "1.11.0"
MODEL_LOCK_PATH = Path(__file__).with_name("stanza_model_lock.json")
_PT_ESCAPE = {"-LRB-": "(", "-RRB-": ")", "-LSB-": "[", "-RSB-": "]",
              "-LCB-": "{", "-RCB-": "}"}
_CLAUSES = {"S", "SBAR", "SINV", "SQ"}
_NOMINALS = {"NP", "NML", "NX", "QP"}
_NOMINAL_OF_PARENTS = {"NP", "NML", "WHNP", "QP"}
_PARTITIVE_HEADS = {"all", "most", "some"}
_LOCAL_COUNT_WORDS = {"few", "several", "many", "some"}
_DURATION_UNITS = {unit + suffix for unit in ("second", "minute", "hour", "day", "week", "month", "year")
                   for suffix in ("", "s")}
_ADVERBIAL_MARKERS = {
    "after", "although", "assuming", "because", "before", "if", "once", "provided",
    "since", "though", "unless", "until", "when", "whenever", "whereas", "while",
}
_AUXILIARIES = {"am", "are", "be", "been", "being", "did", "do", "does", "had", "has", "have", "is", "was", "were",
                "'m", "'re", "'s", "'ve", "'d"}
_COPULAR_BE = {"am", "are", "be", "been", "being", "is", "was", "were", "'m", "'re", "'s"}
_ADVERB_TAGS = {"RB", "RBR", "RBS"}
_FINITE_TAGS = {"MD", "VBD", "VBP", "VBZ"}
_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "trillion", "half", "halves", "quarter", "quarters", "third",
    "thirds", "fourth", "fourths", "fifth", "fifths", "sixth", "sixths",
    "seventh", "sevenths", "eighth", "eighths", "ninth", "ninths", "tenth", "tenths",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_spans(words: tuple[TimedWordDTO, ...], text: str):
    cursor = 0
    spans = []
    for word in words:
        position = text.find(word.text, cursor)
        if position < 0 or text[cursor:position].strip():
            raise ValueError("canonical word cannot be mapped by exact character span")
        end = position + len(word.text)
        spans.append((position, end))
        cursor = end
    if text[cursor:].strip():
        raise ValueError("canonical word mapping leaves unmatched text")
    return spans


def analyze_stanza_sentence(words: tuple[TimedWordDTO, ...], document) -> SyntaxAnalysis:
    """Separate model execution from deterministic span/tree interpretation."""
    text = reconstruct_sentence_text(words)
    word_spans = _canonical_spans(words, text)
    if len(document.sentences) != 1:
        raise ValueError("Stanza must preserve the complete canonical sentence")
    sentence = document.sentences[0]
    leaves = []
    cursor = 0
    for token in sentence.tokens:
        first, last = token.start_char, token.end_char
        if (type(first) is not int or type(last) is not int or first < cursor
                or first >= last or text[first:last] != token.text
                or text[cursor:first].strip()):
            raise ValueError("Stanza token character spans do not reconstruct source")
        token_words = tuple(token.words)
        if not token_words or "".join(word.text for word in token_words) != token.text:
            raise ValueError("Stanza expanded words cannot be mapped exactly")
        offset = first
        for word in token_words:
            end = offset + len(word.text)
            leaves.append((word.text, offset, end, word.xpos))
            offset = end
        cursor = last
    if text[cursor:].strip():
        raise ValueError("Stanza token mapping omits source text")
    tree = sentence.constituency
    tree_leaves = []
    nodes = []
    ranges = {}
    parents = {}

    def visit(node, parent=None):
        first = len(tree_leaves)
        parents[id(node)] = parent
        if not node.children:
            tree_leaves.append(_PT_ESCAPE.get(node.label, node.label))
        else:
            for child in node.children:
                visit(child, node)
            nodes.append((node.label, first, len(tree_leaves), node))
        ranges[id(node)] = (first, len(tree_leaves))

    visit(tree)
    if tuple(tree_leaves) != tuple(leaf[0] for leaf in leaves):
        raise ValueError("Stanza constituency leaves differ from exact token projection")
    if not leaves:
        raise ValueError("Stanza returned no source tokens")

    # A candidate boundary may only fall between complete canonical timed words.
    boundaries = {index: set() for index in range(1, len(words))}
    ends = {end: index + 1 for index, (_, end) in enumerate(word_spans[:-1])}
    starts = {start: index for index, (start, _) in enumerate(word_spans[1:], 1)}
    protected = []
    spans = []

    def project(first_leaf, last_leaf):
        start, end = leaves[first_leaf][1], leaves[last_leaf - 1][2]
        covered = [index for index, (a, b) in enumerate(word_spans) if a < end and b > start]
        return covered[0], covered[-1] + 1

    def protect(first_leaf, last_leaf, reason):
        first, last = project(first_leaf, last_leaf)
        if last - first > 1:
            protected.append(ProtectedSpanDTO(words[first].id, words[last - 1].id, reason))

    def expression(first_leaf, last_leaf, kind):
        first, last = project(first_leaf, last_leaf)
        spans.append(SyntaxSpan(first, last, kind))

    def before(first_leaf, relation):
        offset = starts.get(leaves[first_leaf][1])
        if offset is not None:
            boundaries[offset].add(relation)

    def after(last_leaf, relation):
        offset = ends.get(leaves[last_leaf - 1][2])
        if offset is not None:
            boundaries[offset].add(relation)

    def descendants(node):
        return (node.label,) + tuple(label for child in node.children for label in descendants(child))

    def adverbial(node):
        first, _ = ranges[id(node)]
        return (node.label in {"S", "SBAR", "PP"} and leaves[first][0].lower() in _ADVERBIAL_MARKERS
                and (node.label != "S" or node.children[0].label == "VP")
                and any(item in {"S", "SINV", "SQ"}
                        for child in node.children for item in descendants(child)))

    def simple_adverb(node):
        first, last = ranges[id(node)]
        return (node.label in _ADVERB_TAGS | {"ADVP"}
                and all(leaf[3] in _ADVERB_TAGS for leaf in leaves[first:last]))

    def own_subject_predicate(node):
        labels = tuple(child.label for child in node.children)
        return "NP" in labels and ("VP" in labels or bool(_FINITE_TAGS.intersection(labels)))

    def nominal_of_head(node):
        first, _ = ranges[id(node)]
        if node.label in _NOMINAL_OF_PARENTS:
            return any(nominal_of_head(child) for child in node.children)
        if node.children and not node.children[0].children:
            return (node.label.startswith("NN") or node.label in {"CD", "WP", "WP$", "WDT"}
                    or (node.label in {"DT", "PDT", "JJ", "JJS", "RB", "RBS"}
                        and leaves[first][0].lower() in _PARTITIVE_HEADS))
        return False  # Do not borrow a head from a PP, relative clause or unrelated S.

    def has_local_quantity(children):
        if any(item in _CLAUSES | {"SBARQ", "VP", "PP", "WHPP"}
               for child in children for item in descendants(child)):
            return False
        return any(leaf[3] == "CD" or (leaf[3] in {"DT", "PDT", "JJ", "JJR", "JJS"}
                   and leaf[0].lower() in _LOCAL_COUNT_WORDS)
                   for child in children for leaf in leaves[slice(*ranges[id(child)])])

    def question_intro(node):
        first, _ = ranges[id(node)]
        parent = parents[id(node)]
        if (parent is None or parent.label != "VP" or not first
                or leaves[first - 1][0] not in {",", ":"}):
            return False
        if node.label in {"SQ", "SINV"}:
            labels = tuple(child.label for child in node.children)
            return (own_subject_predicate(node) and bool(_FINITE_TAGS.intersection(labels))
                    and (any(label in {"VP", "ADJP", "PP"} for label in labels) or labels.count("NP") > 1))
        if node.label == "SBARQ" and any(child.label.startswith("WH") for child in node.children):
            for child in node.children:
                if child.label not in {"SQ", "SINV"}:
                    continue
                labels = tuple(item.label for item in child.children)
                if not _FINITE_TAGS.intersection(labels):
                    continue
                if "NP" in labels:
                    if any(label in {"VP", "ADJP", "PP"} for label in labels) or labels.count("NP") > 1:
                        return True
                elif any(item.label in {"VBD", "VBP", "VBZ"} and leaves[ranges[id(item)][0]][0].lower().replace("\u2019", "'") not in _AUXILIARIES
                         for item in child.children):
                    return True  # The WH constituent may itself supply the subject.
        return False

    def completed_vp_content(node):
        return (node.label in {"NP", "PP"}
                or (node.label == "VP" and any(completed_vp_content(child) for child in node.children)))

    def supplement(node):
        first, _ = ranges[id(node)]
        parent = parents[id(node)]
        if (node.label != "S" or parent is None or parent.label != "VP"
                or leaves[first][3] != "VBG" or any(child.label == "NP" for child in node.children)
                or not any(child.label == "VP" for child in node.children)):
            return False
        position = next(index for index, child in enumerate(parent.children) if child is node)
        return (position > 0 and parent.children[position - 1].label == ","
                and any(completed_vp_content(child) for child in parent.children[:position - 1]))

    def first_core_verb(node):
        if node.label.startswith("VB"):
            return ranges[id(node)][0]
        if node.label == "VP":
            for child in node.children:
                if not simple_adverb(child):
                    return first_core_verb(child)
        return None

    def numeric_leaf(leaf):
        value, _, _, tag = leaf
        pieces = value.lower().split("-")
        return (tag == "CD" or all(piece in _NUMBER_WORDS for piece in pieces)
                or re.fullmatch(r"[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:[/\u2044]\d+)?%?", value) is not None)

    def quantity(node):
        first, last = ranges[id(node)]
        if not node.children or not node.children[0].children:
            return numeric_leaf(leaves[first])
        if node.label not in _NOMINALS:
            return False
        labels = tuple(child.label for child in node.children)
        if not any(label in _CLAUSES | {"PP", "CC"} for label in descendants(node)):
            significant = [leaf for leaf in leaves[first:last] if leaf[3] not in {"DT", "RB", "$", "SYM"}]
            return bool(significant and numeric_leaf(significant[0])
                        and all(leaf[3] in {"CD", "JJ", "JJR", "JJS", "NN", "NNS", "NNP", "NNPS", "DT", "RB", "$", "SYM", "IN", "HYPH"}
                                for leaf in leaves[first:last]))
        # A fraction/ratio is a quantity core, not an arbitrary noun plus an of-PP.
        if not node.children or not quantity(node.children[0]):
            return False
        for child in node.children[1:]:
            child_first, _ = ranges[id(child)]
            if child.label == "PP":
                if (len(child.children) != 2 or leaves[child_first][0].lower() != "of"
                        or not quantity(child.children[1])):
                    return False
            elif child.label not in {"NN", "NNS"}:
                return False
        return "PP" in labels

    def nominal_core(node):
        first, last = ranges[id(node)]
        if quantity(node):
            return first, last
        if node.label not in _NOMINALS:
            return None
        stop = last
        postmodifiers = _CLAUSES | {"PP", "WHPP", "CC", "PRN", "UH", ",", ":", "."}
        for child in node.children:
            child_first, _ = ranges[id(child)]
            if child.label in postmodifiers:
                stop = child_first
                break
            if any(item in postmodifiers for item in descendants(child)):
                core = nominal_core(child)
                stop = core[1] if core is not None else child_first
                break
        if stop <= first:
            return None
        tags = tuple(leaf[3] for leaf in leaves[first:stop])
        if any(tag and (tag.startswith("NN") or tag == "CD") for tag in tags):
            return first, stop
        return None

    def statement_marker(node):
        return (node.label in _ADVERB_TAGS | {"CC"}
                or (node.label == "ADVP" and not any(
                    item in _CLAUSES | {"SBARQ"} for item in descendants(node))))

    def statement(node, prefix_first=None):
        if node.label in {"ROOT", "S", "SINV", "SQ"}:
            labels = tuple(child.label for child in node.children)
            clauses = [child for child in node.children if child.label in {"S", "SINV", "SQ"}]
            if clauses:
                for position, child in enumerate(node.children):
                    if child.label not in {"S", "SINV", "SQ"}:
                        continue
                    marker_first = None
                    previous = position - 1
                    while previous >= 0 and (statement_marker(node.children[previous])
                                             or node.children[previous].label in {",", ":"}):
                        if statement_marker(node.children[previous]):
                            marker_first = ranges[id(node.children[previous])][0]
                        previous -= 1
                    # A pure S wrapper may carry an already attached external marker.
                    if prefix_first is not None and previous < 0:
                        marker_first = prefix_first
                    if marker_first is not None:
                        before(ranges[id(child)][0], "connector.after")
                    statement(child, marker_first)
            elif node.label != "ROOT" and "NP" in labels and (
                    "VP" in labels or any(label.startswith("VB") or label == "MD" for label in labels)):
                first, last = ranges[id(node)]
                first = prefix_first if prefix_first is not None else first
                expression(first, last, "statement")
                before(first, "clause.independent")
                after(last, "clause.independent")

    statement(tree)
    for label, first, last, node in nodes:
        child_labels = tuple(child.label for child in node.children)
        parent = parents[id(node)]
        parent_label = parent.label if parent is not None else None
        if label == "SBAR" and parent_label in {"NP", "NML"} and any(
                child.label.startswith("WH") or child.label in {"WDT", "WP", "WP$", "WRB"}
                for child in node.children):
            body = next((child for child in node.children if child.label in {"S", "SINV", "SQ"}), None)
            relative = (any(child.label.startswith("WH") for child in node.children)
                        or (body is not None and not own_subject_predicate(body)
                            and any(child.label == "VP" for child in body.children)))
            if relative:
                before(first, "clause.relative")
                comma = first > 0 and leaves[first - 1][0] == ","
                before(first, "evidence.relative.comma" if comma else "evidence.relative.no-comma")
                expression(first, last, "relative")
            else:
                # A direct WH POS plus a complete S does not prove a restrictive RC.
                before(first, "noun.clause")
                expression(first, last, "complement")
        elif label in {"S", "VP"} and parent_label in {"NP", "NML"} and leaves[first][3] == "TO":
            before(first, "noun.infinitive")
            expression(first, last, "infinitive")
        elif question_intro(node):
            before(first, "clause.interrogative")
        elif adverbial(node) or supplement(node):
            before(first, "clause.adverbial")
            after(last, "clause.adverbial")
            if supplement(node):
                before(first, "evidence.participial.supplement")
            expression(first, last, "adverbial")
        elif label in _CLAUSES | {"SBARQ"} and parent_label == "VP":
            before(first, "predicate.complement")
            expression(first, last, "complement")
        if (label == "S" and child_labels == ("ADVP", "VP") and simple_adverb(node.children[0])
                and ranges[id(node.children[0])][1] - first == 1
                and node.children[1].children and node.children[1].children[0].label.startswith("VB")):
            entry, ancestor = node, parent
            while (ancestor is not None and ancestor.label in {"S", "SBAR"}
                   and len(ancestor.children) == 1):
                entry, ancestor = ancestor, parents[id(ancestor)]
            if (ancestor is not None and ancestor.label == "VP"
                    and not adverbial(entry) and not supplement(entry) and not question_intro(entry)
                    and (first == 0 or leaves[first - 1][0] not in {",", ";", ":", ".", "?", "!"})):
                verb_first, _ = ranges[id(node.children[1].children[0])]
                protect(first, verb_first + 1, "stanza.complement-adverb-verb-core.v1")
        if label == "PP":
            before(first, "phrase.preposition")
            if parent_label == "ADJP":
                position = next(index for index, child in enumerate(parent.children) if child is node)
                if position > 0 and parent.children[position - 1].label in {"JJ", "JJR", "JJS"}:
                    before(first, "attachment.adjectival")
            if parent_label in _NOMINAL_OF_PARENTS and leaves[first][3] == "IN" and leaves[first][0].lower() == "of":
                position = next(index for index, child in enumerate(parent.children) if child is node)
                previous = position - 1
                while previous >= 0 and parent.children[previous].label == "PP":
                    previous -= 1  # Earlier nominal modifiers do not supply a new head.
                if previous >= 0 and nominal_of_head(parent.children[previous]):
                    before(first, "attachment.nominal-of")
            if (parent_label in {"NP", "NML", "QP"} and len(node.children) == 2
                    and child_labels == ("IN", "ADVP") and leaves[first][0].lower() == "from"
                    and last - first == 2 and leaves[first + 1][0].lower() == "now"
                    and leaves[first + 1][3] == "RB"):
                position = next(index for index, child in enumerate(parent.children) if child is node)
                preceding = parent.children[:position]
                if (preceding and leaves[first - 1][0].lower() in _DURATION_UNITS
                        and leaves[first - 1][3] in {"NN", "NNS"} and has_local_quantity(preceding)):
                    before(first, "attachment.temporal")
                    before(first + 1, "attachment.temporal")
        if label == "ADVP" and parent_label in {"VP", "ADJP"}:
            before(first, "attachment.adverbial")
        if (label == "ADVP" and len(node.children) == 3 and child_labels[1] == "CC"
                and child_labels[0] in {"RP", "RB"} and child_labels[2] in {"RP", "RB"}
                and all(ranges[id(child)][1] - ranges[id(child)][0] == 1 for child in node.children)):
            before(ranges[id(node.children[1])][0], "attachment.coordination")
        if (label == "NP" and parent_label == "VP" and leaves[last - 1][0].lower() == "times"
                and leaves[last - 1][3] == "NNS" and has_local_quantity(node.children)):
            before(first, "attachment.frequency")
        if (label in {"ADVP", "SBAR"} and len(node.children) >= 3
                and ranges[id(node.children[0])] == (first, first + 1)
                and ranges[id(node.children[1])] == (first + 1, first + 2)
                and leaves[first][0].lower() == "no" and leaves[first + 1][0].lower() == "matter"):
            marker = node.children[2]
            if marker.label == "SBAR" and marker.children:
                marker = marker.children[0]
            marker_first, marker_last = ranges[id(marker)]
            if (marker.label.startswith("WH") and marker_first == first + 2
                    and leaves[marker_first][3] in {"WDT", "WP", "WP$", "WRB"}):
                protect(first, marker_first + 1, "stanza.concessive-prefix.v1")
                if marker_last < last and leaves[marker_last][0] not in {",", ";", ":", ".", "?", "!"}:
                    before(marker_last, "connector.after")
        if label == "SBAR":
            marker_end = 0
            while marker_end < len(node.children) and node.children[marker_end].label == "IN":
                marker_end += 1
            if marker_end > 1 and marker_end < len(node.children):
                _, marker_last = ranges[id(node.children[marker_end - 1])]
                protect(first, marker_last, "stanza.clause-marker-core.v1")
                following = marker_end
                while following < len(node.children) and node.children[following].label in {",", ":"}:
                    following += 1
                if following < len(node.children):
                    before(ranges[id(node.children[following])][0], "connector.after")
        if label == "QP":
            # Lists may be split, but punctuation does not make each number a new statement.
            items, item_first, item_last = [], None, None
            for child in node.children:
                child_first, child_last = ranges[id(child)]
                if child.label in {",", "CC", ":"}:
                    if item_first is not None:
                        items.append((item_first, item_last))
                        item_first, item_last = None, None
                    continue
                if all(numeric_leaf(leaf) or leaf[3] in {"HYPH", "$", "SYM"}
                       for leaf in leaves[child_first:child_last]):
                    item_first = child_first if item_first is None else item_first
                    item_last = child_last
                else:
                    items = []
                    item_first = None
                    break
            if item_first is not None:
                items.append((item_first, item_last))
            if (len(items) > 1 and any(item in {",", "CC"} for item in child_labels)
                    and all(any(numeric_leaf(leaf) for leaf in leaves[a:b]) for a, b in items)):
                for item_first, item_last in items:
                    protect(item_first, item_last, "stanza.quantity-item.v1")
                for item_first, _ in items[1:]:
                    before(item_first, "attachment.quantity")
                    before(item_first, "evidence.quantity.enumeration")
                if parent is not None and parent_label in _NOMINALS:
                    position = next(index for index, child in enumerate(parent.children) if child is node)
                    following = position + 1
                    while following < len(parent.children) and parent.children[following].label in {"NN", "NNS"}:
                        following += 1
                    if following > position + 1:
                        protect(items[-1][0], ranges[id(parent.children[following - 1])][1],
                                "stanza.quantity-unit.v1")
        for position, child in enumerate(node.children):
            if child.label not in {"CC", "RB", "ADVP"}:
                continue
            previous = [item for item in child_labels[:position] if item not in {",", ":"}]
            following = [item for item in child_labels[position + 1:] if item not in {",", ":"}]
            if previous and following and previous[-1] in {"S", "SINV", "SQ"} and following[0] in {"S", "SINV", "SQ"}:
                child_first, child_last = ranges[id(child)]
                before(child_first, "clause.coordinate")
                after(child_last, "connector.after")
        for position, (left, right) in enumerate(zip(child_labels, child_labels[1:]), 1):
            right_first, right_last = ranges[id(node.children[position])]
            if right == "CC" and left in {"S", "SINV", "SQ", "VP"} and any(
                    item in {"S", "SINV", "SQ", "VP"} for item in child_labels[position + 1:]):
                before(right_first, "clause.coordinate")
            if left == "CC":
                before(right_first, "connector.after")
            if label == "ADVP" and left == "NP" and right in _ADVERB_TAGS and leaves[right_first][0].lower() == "ago":
                before(right_first, "attachment.adverbial")
                before(right_first, "evidence.temporal.ago")
            if (label in {"NP", "QP"} and left in _ADVERB_TAGS
                    and right in {"DT", "PDT", "JJ", "JJS", "RB", "RBS"}
                    and leaves[right_first][0].lower() in _PARTITIVE_HEADS):
                before(right_first, "attachment.scope")
            if label == "S" and left == "NP" and right == "VP":
                before(right_first, "subject.predicate")
            if label == "SBAR" and left in {"IN", "WHNP", "WHADVP", "WDT", "WP", "WP$", "WRB"} and right in _CLAUSES:
                before(right_first, "connector.after")
            if (label == "VP" and left.startswith("VB") and right in {"NP", "ADJP", "S", "SBAR", "SQ", "SINV", "SBARQ", "VP"}
                    and not adverbial(node.children[position]) and not supplement(node.children[position])
                    and not question_intro(node.children[position])):
                before(right_first, "predicate.complement")
                expression(right_first, right_last, "complement")
            if (label == "VP" and left == "ADVP" and right == "VP"
                    and "CC" in child_labels[:position - 1]):
                before(right_first, "connector.after")
            if (label in {"NP", "NML"} and left in {"NML", "ADJP"} and right.startswith("NN")
                    and "CC" in descendants(node.children[position - 1])):
                _, modifier_last = ranges[id(node.children[position - 1])]
                if leaves[modifier_last - 1][3] and leaves[modifier_last - 1][3].startswith(("NN", "JJ")):
                    protect(modifier_last - 1, right_last, "stanza.coordinated-nominal-head.v1")
        # Stop the noun core before postmodifiers, clauses or coordinated items.
        if label in {"NP", "NML", "NX"}:
            core = nominal_core(node)
            tags = tuple(leaf[3] for leaf in leaves[core[0]:core[1]]) if core is not None else ()
            if any(tag and tag.startswith("NN") for tag in tags):
                protect(core[0], core[1], "stanza.base-noun-phrase.v2")
        if label in _NOMINALS and quantity(node):
            protect(first, last, "stanza.quantity-core.v1")
        if label == "PP" and len(child_labels) >= 2 and child_labels[0] in {"IN", "TO"}:
            core = nominal_core(node.children[1])
            if core is not None:
                protect(first, core[1], "stanza.preposition-object-core.v2")
        if label == "VP":
            for position, child in enumerate(node.children[:-1]):
                child_first, _ = ranges[id(child)]
                if child.label not in {"MD", "TO"} and not (
                        child.label.startswith("VB") and leaves[child_first][0].lower().replace("\u2019", "'") in _AUXILIARIES):
                    continue
                following = position + 1
                while following < len(node.children) and simple_adverb(node.children[following]):
                    following += 1
                if (child.label.startswith("VB")
                        and leaves[child_first][0].lower().replace("\u2019", "'") in _COPULAR_BE
                        and following < len(node.children) and node.children[following].label == "ADJP"):
                    adjective = node.children[following]
                    head = 0
                    while head < len(adjective.children) and simple_adverb(adjective.children[head]):
                        head += 1
                    if head < len(adjective.children) and adjective.children[head].label in {"JJ", "JJR", "JJS"}:
                        adjective_first, _ = ranges[id(adjective.children[head])]
                        protect(child_first, adjective_first + 1, "stanza.copular-adjective-core.v1")
                if following < len(node.children) and (
                        node.children[following].label == "VP" or node.children[following].label.startswith("VB")):
                    verb_first, _ = ranges[id(node.children[following])]
                    if leaves[verb_first][3] and leaves[verb_first][3].startswith("VB"):
                        protect(child_first, verb_first + 1, "stanza.auxiliary-negation-verb.v2")
        if label in {"SQ", "SINV"}:
            for position, child in enumerate(node.children[:-1]):
                child_first, _ = ranges[id(child)]
                if child.label != "MD" and not (
                        child.label in _FINITE_TAGS and leaves[child_first][0].lower().replace("\u2019", "'") in _AUXILIARIES):
                    continue
                subject = position + 1
                while subject < len(node.children) and simple_adverb(node.children[subject]):
                    subject += 1
                if subject >= len(node.children) or node.children[subject].label != "NP":
                    continue
                subject_first, subject_last = ranges[id(node.children[subject])]
                before(subject_first, "subject.predicate")
                before(subject_first, "evidence.inversion.aux-subject")
                following = subject + 1
                while following < len(node.children) and simple_adverb(node.children[following]):
                    following += 1
                if following < len(node.children) and node.children[following].label in {"VP", "ADJP", "PP", "NP"}:
                    before(ranges[id(node.children[subject + 1])][0], "subject.predicate")
                    before(ranges[id(node.children[subject + 1])][0], "evidence.inversion.subject-predicate")
                if subject_last - subject_first == 1 and leaves[subject_first][3] == "PRP":
                    protect(child_first, subject_last, "stanza.inverted-pronoun-core.v1")
                    if following < len(node.children):
                        verb_first = first_core_verb(node.children[following])
                        if verb_first is not None:
                            protect(child_first, verb_first + 1, "stanza.inverted-pronoun-core.v1")
    for index, (value, start, end, tag) in enumerate(leaves[:-1]):
        numeric_comma = (value == "," and index > 0 and leaves[index - 1][0][-1:].isdecimal()
                         and leaves[index + 1][0][:1].isdecimal())
        if numeric_comma:
            protect(index - 1, index + 2, "canonical.numeric-comma.v1")
        elif value in {",", ";", ":", ".", "?", "!"}:
            after(index + 1, "punctuation")
        following = leaves[index + 1]
        if tag in {"MD", "TO"} or value.lower() in {"not", "n't"}:
            next_verb = index + 1
            while next_verb < len(leaves) and leaves[next_verb][3] in _ADVERB_TAGS:
                next_verb += 1
            if next_verb < len(leaves) and leaves[next_verb][3] and leaves[next_verb][3].startswith("VB"):
                protect(index, next_verb + 1, "stanza.auxiliary-negation-verb.v2")
        if tag and tag.startswith("NNP") and following[3] and following[3].startswith("NNP"):
            protect(index, index + 2, "stanza.proper-name.v2")
    return SyntaxAnalysis(
        tuple(SyntaxBoundary(offset, tuple(sorted(relations or {"ordinary"})))
              for offset, relations in sorted(boundaries.items())),
        tuple(dict.fromkeys(protected)), tuple(dict.fromkeys(spans)),
    )


class StanzaConstituencyAnalyzer:
    """A prepared, hash-locked model bundle. Construction never loads a model."""

    def __init__(self, bundle_path: str, *, loader: Callable | None = None):
        self._root = Path(bundle_path).resolve()
        self._loader = loader
        self._pipeline = None
        installed_lock = self._root / "model_identity.json"
        if installed_lock.read_bytes() != MODEL_LOCK_PATH.read_bytes():
            raise ValueError("Stanza bundle does not match the pinned production model")
        lock = json.loads(installed_lock.read_bytes())
        if (set(lock) != {"stanza_version", "processors", "files", "transformer_path"}
                or lock["stanza_version"] != STANZA_VERSION
                or not isinstance(lock["files"], dict) or not lock["files"]):
            raise ValueError("invalid pinned Stanza model identity")
        if version("stanza") != STANZA_VERSION:
            raise ValueError("installed Stanza version differs from pinned identity")
        for relative, expected in lock["files"].items():
            path = (self._root / relative).resolve()
            if not path.is_relative_to(self._root) or not path.is_file() or _sha256(path) != expected:
                raise ValueError(f"missing or changed Stanza dependency: {relative}")
        self._lock = lock
        self._identity = {
            "engine": f"stanza-{STANZA_VERSION}",
            "model_manifest_sha256": _sha256(self._root / "model_identity.json"),
            "processors": lock["processors"],
            "mapping": "exact-char-spans.v1", "protection": "minimal-np-pp-quantity-aux-marker-inversion-scope-predicate.v6",
            "ranking": "typed-constituency-relations.v10",
        }

    @property
    def identity(self):
        return dict(self._identity)

    def analyze(self, words: tuple[TimedWordDTO, ...]) -> SyntaxAnalysis:
        if self._pipeline is None:
            if self._loader is None:
                import stanza
                from stanza.models.common.foundation_cache import FoundationCache, BertRecord
                from transformers import AutoModel, AutoTokenizer
                cache = FoundationCache(local_files_only=True)
                transformer = str(self._root / self._lock["transformer_path"])
                cache.bert["google/electra-large-discriminator"] = BertRecord(
                    AutoModel.from_pretrained(transformer, local_files_only=True),
                    AutoTokenizer.from_pretrained(transformer, local_files_only=True), {},
                )
                def loader(**kwargs):
                    return stanza.Pipeline(foundation_cache=cache, **kwargs)
            else:
                loader = self._loader
            # A local transformer directory plus these flags prevents implicit HTTP.
            previous = {key: os.environ.get(key) for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")}
            try:
                os.environ["HF_HUB_OFFLINE"] = "1"
                os.environ["TRANSFORMERS_OFFLINE"] = "1"
                self._pipeline = loader(
                    lang="en", dir=str(self._root / "stanza"),
                    processors=self._lock["processors"], package=None,
                    download_method=None, use_gpu=False, tokenize_no_ssplit=True,
                    verbose=False,
                )
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        return analyze_stanza_sentence(words, self._pipeline(reconstruct_sentence_text(words)))
