"""Read-only frozen-source experiments; never publish stage manifests or call a provider.

Old code runs only in an isolated child using an independent working-tree copy.
Capacity overrides are experiment-only, in memory. The 97 reviewed sentences are
development/regression data, not a holdout or an automatically scored gold set.
"""

from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

from .full_fresh import ROOT, snapshot


def fingerprint(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"a regular, non-symlink file is required: {path}")
    before = path.stat()
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"file changed while hashing: {path}")
    return {"sha256": digest.hexdigest(), "size_bytes": after.st_size, "mtime_ns": after.st_mtime_ns}


def write_exclusive(path, data):
    with Path(path).open("x", encoding="utf-8") as stream:
        if isinstance(data, str):
            stream.write(data)
        else:
            json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")


def code_snapshot(root):
    return {name: value for name, value in snapshot(root, all_files=True).items()
            if "__pycache__" not in Path(name).parts and not name.endswith(".pyc")}


def verify_baseline(baseline):
    baseline = Path(baseline).resolve()
    identity = json.loads((baseline / "baseline_identity.json").read_bytes())
    for relative, expected in identity["working_tree_files"].items():
        path = baseline / "working_tree" / relative
        if not path.resolve().is_relative_to(baseline) or fingerprint(path) != expected:
            raise ValueError(f"frozen working-tree evidence differs: {relative}")
    inventory = baseline / "nb09_inventory.json"
    if fingerprint(inventory) != identity["nb09_inventory"]:
        raise ValueError("frozen NB09 inventory differs")
    original_inventory = json.loads(inventory.read_bytes())
    if snapshot(identity["nb09_root"], all_files=True) != original_inventory["files"]:
        raise ValueError("original NB09 assets differ from the frozen baseline")
    for name, expected in identity["nb09_forensic_copies"].items():
        if fingerprint(baseline / "nb09_frozen" / name) != expected:
            raise ValueError(f"frozen NB09 copy differs: {name}")
    return identity


def _child(source_root, code, args, *, timeout=1800):
    source_root = Path(source_root).resolve()
    environment = dict(os.environ)
    environment.update(PYTHONPATH=str(source_root), PYTHONDONTWRITEBYTECODE="1",
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    # The repository cwd must not accidentally shadow the frozen imports.
    result = subprocess.run([sys.executable, "-c", code, *map(str, args)],
                            cwd=source_root.parent, env=environment,
                            capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(result.stdout.splitlines()[-1])


_PARSE_WORKER = r'''
import json, sys
from pathlib import Path
from archive_core.interfaces.transcription import SourceAlignmentDTO, reconstruct_sentence_text
from srt_processing.infrastructure.stanza_chunking import StanzaConstituencyAnalyzer
alignment = SourceAlignmentDTO.from_dict(json.loads(Path(sys.argv[1]).read_bytes()))
analyzer = StanzaConstituencyAnalyzer(sys.argv[2])
indices = {word.id: n for n, word in enumerate(alignment.words)}
rows = []
for sentence in alignment.sentences:
    words = alignment.words[indices[sentence.first_word_id]:indices[sentence.last_word_id] + 1]
    if analyzer._pipeline is None:
        analyzer.analyze(words)  # Initialize the exact pinned production pipeline once.
    document = analyzer._pipeline(reconstruct_sentence_text(words))
    sentences = []
    for parsed in document.sentences:
        tokens = []
        for token in parsed.tokens:
            tokens.append({'text': token.text, 'start_char': token.start_char,
                'end_char': token.end_char, 'words': [word.to_dict() for word in token.words]})
        sentences.append({'tokens': tokens, 'constituency': str(parsed.constituency)})
    rows.append({'sentence_id': sentence.id, 'word_ids': [word.id for word in words],
                 'text': reconstruct_sentence_text(words), 'sentences': sentences})
print(json.dumps({'analyzer_identity': analyzer.identity, 'rows': rows}, ensure_ascii=False))
'''


def prepare_parse_cache(baseline, model_bundle, output):
    identity = verify_baseline(baseline)
    baseline, output = Path(baseline).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("parse cache output must be absent")
    source = baseline / "nb09_frozen/source_alignment.json"
    before = snapshot(baseline, all_files=True)
    parsed = _child(baseline / "working_tree/src", _PARSE_WORKER, (source, Path(model_bundle).resolve()))
    parsed.update(schema_version="chunking.raw-stanza-cache.v1", source_alignment=fingerprint(source),
                  baseline_identity=fingerprint(baseline / "baseline_identity.json"),
                  purpose="Raw exact pinned parse evidence; no provider, ASR or stage publication",
                  dataset_role="reviewed-development-regression-not-holdout")
    if snapshot(baseline, all_files=True) != before:
        raise AssertionError("parsing changed the frozen baseline")
    if parsed["analyzer_identity"]["model_manifest_sha256"] != identity["prepared_model_manifest"]["sha256"]:
        raise ValueError("parse model differs from baseline lock")
    write_exclusive(output, parsed)
    return {"path": str(output), **fingerprint(output), "sentence_count": len(parsed["rows"])}


_EVALUATION_WORKER = r'''
import importlib, json, sys
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict, is_dataclass
from archive_core.interfaces.transcription import SourceAlignmentDTO
from archive_core.interfaces.bilingual import MediaBoundaryDTO
from archive_core.interfaces.bilingual_timing import empty_frame_count
from srt_processing.domain import chunking
policy_module = importlib.import_module('srt_processing.domain.chunking_policy')
from srt_processing.infrastructure.stanza_chunking import StanzaConstituencyAnalyzer, analyze_stanza_sentence
from stanza.models.constituency.tree_reader import read_trees
source, media_path, cache_path, model, capacity = sys.argv[1:6]
alignment = SourceAlignmentDTO.from_dict(json.loads(Path(source).read_bytes()))
media = MediaBoundaryDTO.from_dict(json.loads(Path(media_path).read_bytes()))
cache = json.loads(Path(cache_path).read_bytes())
rows = {tuple(row['word_ids']): row for row in cache['rows']}
pinned = StanzaConstituencyAnalyzer(model)
if dict(pinned.identity).get('model_manifest_sha256') != cache['analyzer_identity']['model_manifest_sha256']:
    raise ValueError('cached parse model differs')
class CachedAnalyzer:
    identity = pinned.identity
    def analyze(self, words):
        row = rows[tuple(word.id for word in words)]
        parsed = []
        for sentence in row['sentences']:
            tokens = []
            for token in sentence['tokens']:
                tokens.append(SimpleNamespace(text=token['text'], start_char=token['start_char'],
                    end_char=token['end_char'], words=[SimpleNamespace(**word) for word in token['words']]))
            trees = read_trees(sentence['constituency'], use_tqdm=False)
            if len(trees) != 1: raise ValueError('cached constituency is not one tree')
            parsed.append(SimpleNamespace(tokens=tokens, constituency=trees[0]))
        return analyze_stanza_sentence(words, SimpleNamespace(sentences=parsed))
# Isolated, in-memory experimental override; never edit the frozen files.
policy_module.ENGLISH_MAX_CHARACTERS = int(capacity)
chunking.ENGLISH_MAX_CHARACTERS = int(capacity)
options = {}
if len(sys.argv) > 6:
    options = json.loads(sys.argv[6])
    if any(key not in {'use_gap', 'use_relative_gap', 'use_reading', 'use_rhythm'} or type(value) is not bool for key, value in options.items()):
        raise ValueError('invalid isolated ablation options')
typed = hasattr(chunking, '_PartitionScorer')
historical_fields = ('high_impact_events', 'ordinary_structure_events', 'short_cue_count', 'shortfall_ms',
    'cps_exceed_cue_count', 'cps_excess_burden', 'ordinary_grade3_count', 'ordinary_grade2_count',
    'ordinary_grade1_count', 'cue_count', 'negative_pause_reward', 'adjacent_character_rhythm', 'squared_character_load')
policy_version = policy_module.chunking_policy()['version']
if typed:
    configured_fields = getattr(policy_module, 'SCORE_FIELDS', None)
    if configured_fields is not None:
        base_score_fields = tuple(configured_fields)
    elif policy_version in {'english-typed-cue-dp.v1', 'english-typed-cue-dp.v2', 'english-typed-cue-dp.v3'}:
        # Decode explicitly frozen historical experiments only; production has no legacy path.
        base_score_fields = historical_fields
    else:
        raise ValueError('unknown score-field identity in the experiment source')
    if len(base_score_fields) != 13 or set(base_score_fields) != set(historical_fields):
        raise ValueError('source score fields differ from the supported diagnostic components')
else:
    base_score_fields = historical_fields  # Never exposed as a legacy numeric score vector.
objective_id = sys.argv[7] if len(sys.argv) > 7 else 'production'
if objective_id not in {'production', 'B', 'U', 'S', 'US'}:
    raise ValueError('unsupported isolated objective')
if objective_id != 'production' and not typed:
    raise ValueError('objective experiment requires the frozen typed scorer')
if objective_id != 'production' and policy_version != 'english-typed-cue-dp.v3':
    raise ValueError('objective U/S overrides are restricted to the authorised frozen v3 scorer')
objective_permutation = (0,1,2,3,6,7,8,4,5,9,10,11,12) if objective_id in {'S', 'US'} else tuple(range(13))
if objective_id in {'U', 'US'}:
    original_grade = chunking._ordinary_grade
    def collapsed_unknown_grade(relations):
        grade = original_grade(relations)
        return 2 if grade == 3 else grade
    chunking._ordinary_grade = collapsed_unknown_grade
global_scorers, split_trace = [], []
if typed:
    original_scorer = chunking._PartitionScorer
    if objective_id in {'S', 'US'}:
        original_cost = original_scorer.cost
        def reordered_cost(self, *args, **kwargs):
            cost = original_cost(self, *args, **kwargs)
            return tuple(cost[n] for n in objective_permutation)
        original_scorer.cost = reordered_cost
    def configured_scorer(*args, **kwargs):
        kwargs.update(options)
        scorer = original_scorer(*args, **kwargs)
        if kwargs.get('sentence_ranges') is not None:
            global_scorers.append(scorer)
        return scorer
    chunking._PartitionScorer = configured_scorer
original_split = chunking._split_sentence
def observed_split(words, analysis, confirmed, **kwargs):
    result = original_split(words, analysis, confirmed, **kwargs)
    split_trace.append({'word_ids': tuple(word.id for word in words), 'analysis': analysis,
                        'parts': result, 'media_used': kwargs.get('stanza_media') is not None})
    return result
chunking._split_sentence = observed_split
from hashlib import sha256
plan = chunking.build_source_chunks(asset_id='cnbc:2000:morning-ch6-7', alignment=alignment,
    source_alignment_sha256=sha256(Path(source).read_bytes()).hexdigest(), media=media, analyzer=CachedAnalyzer())
plan.validate_against_alignment(alignment)
if plan.policy['english_max_characters'] != int(capacity):
    raise AssertionError('experimental capacity is not bound in plan policy')
metrics = []
for n, item in enumerate(plan.chunks):
    duration = item.base_end_ms - item.start_ms
    next_start = plan.chunks[n + 1].start_ms if n + 1 < len(plan.chunks) else None
    metrics.append({'id': item.id, 'characters': len(item.english_text), 'duration_ms': duration,
        'cps_numerator': len(item.english_text) * 1000, 'cps_denominator': duration,
        'cps_excess': max(0, len(item.english_text) * 1000 - 20 * duration),
        'shortfall_ms': max(0, 834 - duration),
        'empty_frames_to_next': None if next_start is None else empty_frame_count(media, item.base_end_ms, next_start),
        'issues': list(item.issues)})
score_fields = tuple(base_score_fields[n] for n in objective_permutation)
experiment_objective = {'objective_id': objective_id if typed else 'legacy-frozen', 'unknown_grade3_to2': objective_id in {'U', 'US'},
    'cost_permutation': list(objective_permutation) if typed else None, 'score_fields': list(score_fields) if typed else None,
    'cps_enabled': options.get('use_reading', True) if typed else None, 'capacity': int(capacity),
    'note': 'An isolated worker objective; plan.policy describes the frozen source profile, not a claim that production selected experimental U/S/US groups. Numeric objective scores are not cross-objective human quality scores.'}
def groups(parts):
    return [[word.id for word in part] for part in parts]
def features(analysis):
    return {'boundaries': [asdict(item) if is_dataclass(item) else list(item) for item in analysis.boundaries],
            'spans': [asdict(item) for item in getattr(analysis, 'spans', ())],
            'protected_spans': [item.to_dict() for item in analysis.protected_spans]}
def scored(scorer, parts):
    score = scorer.score(parts)
    if len(score) != len(score_fields) + 1:
        raise ValueError('diagnostic component labels differ from the active score vector')
    first, previous_first, cue_costs = 0, None, []
    for part in parts:
        last = first + len(part)
        cost = scorer.cost(first, last, previous_first)
        level = scorer.cue_level(first, last, previous_first)
        cue_costs.append({'word_ids': [word.id for word in part], 'components': dict(zip(score_fields, cost)),
                         'cue_level': level, 'pause_reward': scorer.pause_reward(first, level)})
        previous_first, first = first, last
    return {'components': dict(zip(score_fields, score[:-1])), 'score_fields': list(score_fields),
            'ordered_values': list(score[:-1]), 'stable_offsets': list(score[-1]), 'cue_costs': cue_costs}
indices = {word.id: n for n, word in enumerate(alignment.words)}
analyzer = CachedAnalyzer()
sentence_trace, before_rescue = [], []
for sentence in alignment.sentences:
    words = alignment.words[indices[sentence.first_word_id]:indices[sentence.last_word_id] + 1]
    attempts = [item for item in split_trace if item['word_ids'] == tuple(word.id for word in words)]
    selected = attempts[-1] if attempts else None
    initial = (selected['parts'] or (words,)) if selected is not None else (words,)
    before_rescue.extend(initial)
    raw = analyzer.analyze(words)
    used = selected['analysis'] if selected is not None else None
    final = [cue for cue in plan.chunks if sentence.id in cue.sentence_ids]
    row = {'sentence_id': sentence.id, 'word_ids': [word.id for word in words],
        'actual_stanza_triggered': sentence.id in plan.analyzed_sentence_ids,
        'raw_parse_features_diagnostic_only': features(raw),
        'features_used_for_split': features(used) if used is not None else None,
        'split_attempts': [{'features': features(item['analysis']), 'dp_feasible': item['parts'] is not None,
                            'returned_groups_before_global_short_rescue': groups(item['parts']) if item['parts'] else None,
                            'media_used': item['media_used']} for item in attempts],
        'decision': 'dp-or-explicit-complete-sentence-fallback' if selected is not None else 'not-triggered-preserve-complete-sentence',
        'groups_before_global_short_rescue': groups(initial),
        'final_associated_cues_after_short_rescue': [{'cue_id': cue.id, 'word_ids': list(cue.word_ids),
                                                     'sentence_ids': list(cue.sentence_ids)} for cue in final],
        'score_comparability': 'same-new-objective-only' if typed else 'legacy-numeric-not-comparable-to-new-vector'}
    if typed:
        scorer = original_scorer(words, used or raw, media, **options)
        valid = [value for value in scorer.frames.values() if value is not None]
        center, mad = scorer.relative_center, scorer.relative_mad
        reason = ('missing_pts' if media.frame_timestamps_us is None else
                  'insufficient_samples' if len(valid) < chunking.GAP_RELATIVE_MIN_SAMPLES else
                  'zero_mad' if not mad else 'eligible')
        row['relative_gap_statistics'] = {'sample_count': len(valid), 'minimum_samples': chunking.GAP_RELATIVE_MIN_SAMPLES,
            'unknown_gap_count': len(words) - 1 - len(valid),
            'median_log1p_frames': center, 'mad_log1p_frames': mad, 'availability_reason': reason,
            'relative_feature_flag': options.get('use_relative_gap', True),
            'pause_rewards_flag': options.get('use_gap', True),
            'scoring_enabled': options.get('use_gap', True) and options.get('use_relative_gap', True),
            'scoring_applicable': options.get('use_gap', True) and options.get('use_relative_gap', True) and reason == 'eligible',
            'note': 'Raw timestamp gaps are not evidence of breathing/emphasis; neutral frames never earn a reward.'}
        row['boundary_gap_evidence'] = [{'offset': n, 'left_word_id': words[n-1].id, 'right_word_id': words[n].id,
            'gap_ms': words[n].start_ms - words[n-1].end_ms, 'empty_frames': scorer.frames.get(n),
            'relations': sorted(scorer.relations[n]), 'hard_forbidden': n in scorer.forbidden}
            for n in range(1, len(words))]
        row['before_rescue_score_diagnostic'] = scored(scorer, initial)
    else:
        row['relative_gap_statistics'] = {'availability_reason': 'not_applicable_legacy_raw_gap_ranking'}
        row['boundary_gap_evidence'] = [{'offset': n, 'left_word_id': words[n-1].id, 'right_word_id': words[n].id,
            'gap_ms': words[n].start_ms - words[n-1].end_ms,
            'empty_frames': empty_frame_count(media, words[n-1].end_ms, words[n].start_ms)}
            for n in range(1, len(words))]
    sentence_trace.append(row)
final_parts = tuple(tuple(alignment.words[indices[word_id]] for word_id in cue.word_ids) for cue in plan.chunks)
trace = {'schema_version': 'chunking.algorithm-diagnostics.v2', 'sentence_count': len(sentence_trace),
    'note': 'Algorithm diagnostics, not human error counts or a semantic quality pass. Extra raw parse projections do not imply the production chunker analysed untriggered sentences.',
    'sentences': sentence_trace, 'groups_before_global_short_rescue': groups(before_rescue),
    'final_groups_after_short_rescue': groups(final_parts),
    'legacy_local_repair_note': None if typed else 'Legacy split outputs may already include its local tight-triplet repair; no new-vector score is assigned.'}
if typed:
    if len(global_scorers) != 1: raise ValueError('expected exactly one actual global rescue scorer')
    trace['actual_global_rescue_score_before'] = scored(global_scorers[0], before_rescue)
    trace['actual_global_rescue_score_final'] = scored(global_scorers[0], final_parts)
print(json.dumps({'plan': plan.to_dict(), 'metrics': metrics, 'trace': trace,
                  'experiment_objective': experiment_objective}, ensure_ascii=False))
'''


def _summary(result):
    metrics = result["metrics"]
    return {"cue_count": len(metrics), "short_cue_count": sum(item["shortfall_ms"] > 0 for item in metrics),
            "shortfall_ms": sum(item["shortfall_ms"] for item in metrics),
            "cps_excess_cue_count": sum(item["cps_excess"] > 0 for item in metrics),
            "cps_excess": sum(item["cps_excess"] for item in metrics),
            "short_frame_gap_count": sum(item["empty_frames_to_next"] is not None and item["empty_frames_to_next"] < 2
                                         for item in metrics[:-1]),
            "warning_count": sum(len(item["issues"]) for item in metrics),
            "human_quality": "not_assessed"}


def validate_labels(labels, alignment):
    if labels.get("schema_version") != "chunking.human-labels.v1":
        raise ValueError("unsupported human-label schema")
    sentences = {item["id"]: item for item in alignment["sentences"]}
    words = {item["id"]: n for n, item in enumerate(alignment["words"])}
    rows = labels.get("items", [])
    if not isinstance(rows, list):
        raise ValueError("human-label items must be a list")
    for item in rows:
        if item.get("sentence_id") not in sentences or not set(item.get("word_ids", [])) <= words.keys():
            raise ValueError("human label references unknown canonical source IDs")
        sentence = sentences[item["sentence_id"]]
        first, last = words[sentence["first_word_id"]], words[sentence["last_word_id"]]
        if any(not first <= words[word] <= last for word in item.get("word_ids", [])):
            raise ValueError("human label word IDs escape its source sentence")
        for field in ("forbidden_boundaries", "allowed_boundaries", "preferred_boundaries"):
            for pair in item.get(field, []):
                if (not isinstance(pair, list) or len(pair) != 2 or any(word not in words for word in pair)
                        or words[pair[1]] != words[pair[0]] + 1
                        or not first <= words[pair[0]] < words[pair[1]] <= last):
                    raise ValueError("label boundary must be adjacent canonical IDs within its sentence")
        for grouping in item.get("allowed_groupings", []):
            position = first
            if not isinstance(grouping, list) or not grouping:
                raise ValueError("an allowed grouping cannot be empty")
            for span in grouping:
                if (not isinstance(span, list) or len(span) != 2 or any(word not in words for word in span)
                        or words[span[0]] != position or not position <= words[span[1]] <= last):
                    raise ValueError("allowed grouping must provide ordered contiguous canonical ranges")
                position = words[span[1]] + 1
            if position != last + 1:
                raise ValueError("allowed grouping must cover the complete source sentence")
        for span in item.get("forbidden_cue_start_ranges", []):
            if (not isinstance(span, list) or len(span) != 2 or any(word not in words for word in span)
                    or not first <= words[span[0]] <= words[span[1]] <= last):
                raise ValueError("forbidden cue-start range differs from canonical sentence")
        if item.get("layer", "source_chunking") not in {"source_chunking", "final_bilingual"}:
            raise ValueError("human label must identify its evaluation layer")
        if item.get("decision") not in {None, "acceptable", "reject", "needs_listening", "disputed"}:
            raise ValueError("unrecognized human decision")
        if item.get("data_origin") not in {"reviewed_real", "synthetic", "unseen_real"}:
            raise ValueError("human label must state its data origin")
    return labels


def _markdown(alignment, results, aliases, *, context_note=None):
    lines = ["# 源语切分匿名四组全句对照", "", "固定 canonical 词ID/词时间；只展示源语分组与技术指标。",
             "这是反复审阅的开发/回归集，不是holdout。不同分组可能同样合理；指标不自动判断语义质量。",
             context_note or "旧代码仅在冻结副本的独立进程运行；容量覆盖只用于实验，不发布旧策略manifest。", ""]
    for sentence in alignment["sentences"]:
        lines.extend([f"## {sentence['id'].upper()}", "", sentence["text"], ""])
        for alias, name in aliases.items():
            lines.extend([f"### {alias}", ""])
            metrics = {item["id"]: item for item in results[name]["metrics"]}
            for cue in results[name]["plan"]["chunks"]:
                if sentence["id"] not in cue["sentence_ids"]:
                    continue
                item = metrics[cue["id"]]
                shared = f"；共用{','.join(cue['sentence_ids'])}，以下为整cue" if len(cue["sentence_ids"]) > 1 else ""
                lines.extend([f"- `{cue['word_ids'][0]}–{cue['word_ids'][-1]}` "
                              f"{cue['start_ms']}–{cue['base_end_ms']}ms；{item['characters']}字符；"
                              f"{item['duration_ms']}ms{shared}", "", f"> {cue['english_text']}", ""])
        lines.extend(["人工结论：待审（允许多解；需核听项保留未知）。", ""])
    return "\n".join(lines)


def label_observations(plan, labels, alignment):
    """Apply frozen human constraints, not the candidate's own quality function."""
    positions = {word["id"]: n for n, word in enumerate(alignment["words"])}
    cuts = {cue["word_ids"][-1] for cue in plan["chunks"][:-1]}
    starts = {cue["word_ids"][0] for cue in plan["chunks"]}
    observations = []
    for item in labels["items"]:
        if item.get("layer", "source_chunking") != "source_chunking":
            observations.append({"label_id": item.get("id"), "layer": item["layer"],
                                 "excluded_from_source_pass_fail": True, "assessment": "final-stage-review-required"})
            continue
        forbidden = [pair for pair in item.get("forbidden_boundaries", []) if pair[0] in cuts]
        tail_starts = [word for word in sorted(starts, key=positions.get) if any(
            positions[first] <= positions[word] <= positions[last] for first, last in item.get("forbidden_cue_start_ranges", []))]
        local = [[cue["word_ids"][0], cue["word_ids"][-1]] for cue in plan["chunks"]
                 if item["sentence_id"] in cue["sentence_ids"]]
        observations.append({"label_id": item.get("id"), "layer": "source_chunking",
                             "forbidden_boundary_hits": forbidden, "forbidden_tail_start_hits": tail_starts,
                             "known_constraint_violation": bool(forbidden or tail_starts),
                             "matched_acceptable_witness": local in item["allowed_groupings"] if item.get("allowed_groupings") else None,
                             "approved_boundary_present": [pair for pair in item.get("allowed_boundaries", []) if pair[0] in cuts],
                             "unlisted_alternatives_require_human_review": True})
    return observations


def sentence_changes(alignment, results, *, pairs=None):
    """List every changed/unchanged fixed source unit; no inferred quality scores."""
    positions = {word["id"]: n for n, word in enumerate(alignment["words"])}
    if pairs is None:
        pairs = (("old80", "new80"), ("old84", "new84"), ("old80", "old84"), ("new80", "new84"))
        pairs += tuple(("new84", name) for name in results if name.startswith("new84_"))
    rows = []
    for sentence in alignment["sentences"]:
        first, last = positions[sentence["first_word_id"]], positions[sentence["last_word_id"]]
        variants = {}
        for name, result in results.items():
            items = []
            for cue in result["plan"]["chunks"]:
                local = [word for word in cue["word_ids"] if first <= positions[word] <= last]
                if local:
                    items.append({"cue_id": cue["id"], "local_word_ids": local,
                                  "whole_cue_word_ids": cue["word_ids"], "whole_cue_english": cue["english_text"],
                                  "whole_cue_start_ms": cue["start_ms"], "whole_cue_end_ms": cue["base_end_ms"],
                                  "shared_sentence_ids": cue["sentence_ids"]})
            covered = [word for item in items for word in item["local_word_ids"]]
            expected = [word["id"] for word in alignment["words"][first:last + 1]]
            if covered != expected:
                raise ValueError("comparison variant does not cover the canonical sentence exactly once")
            variants[name] = items
        changed = []
        for left, right in pairs:
            # Include whole ranges so a cross-sentence merge cannot masquerade as unchanged.
            before = [item["whole_cue_word_ids"] for item in variants[left]]
            after = [item["whole_cue_word_ids"] for item in variants[right]]
            if before != after:
                changed.append(f"{left}_to_{right}")
        rows.append({"sentence_id": sentence["id"], "source_english": sentence["text"],
                     "variants": variants, "changed_pairs": changed, "human_quality": "not_assessed"})
    return {"schema_version": "chunking.sentence-deltas.v1", "fixed_source_unit_count": len(rows),
            "changed_sentences_by_pair": {f"{left}_to_{right}": [row["sentence_id"] for row in rows
                if f"{left}_to_{right}" in row["changed_pairs"]] for left, right in pairs},
            "all_sentences": rows, "shared_cue_timing_note": "Whole cue times are not projected local display times."}


def evaluate_four_way(baseline, parse_cache, model_bundle, output, *, labels_path=None, include_ablations=False):
    identity = verify_baseline(baseline)
    baseline, output, parse_cache = map(lambda value: Path(value).resolve(), (baseline, output, parse_cache))
    if output.exists() or output.is_symlink():
        raise ValueError("experiment directory must be absent")
    source, media = baseline / "nb09_frozen/source_alignment.json", baseline / "nb09_frozen/media_boundary.json"
    alignment = json.loads(source.read_bytes())
    cache = json.loads(parse_cache.read_bytes())
    if cache["source_alignment"] != fingerprint(source):
        raise ValueError("parse cache belongs to different frozen source evidence")
    if cache["baseline_identity"] != fingerprint(baseline / "baseline_identity.json"):
        raise ValueError("parse cache belongs to another baseline")
    labels = None if labels_path is None else validate_labels(json.loads(Path(labels_path).read_bytes()), alignment)
    if labels is not None and labels.get("source_alignment_sha256", fingerprint(source)["sha256"]) != fingerprint(source)["sha256"]:
        raise ValueError("human labels belong to different canonical source evidence")
    frozen_before, old_before = snapshot(baseline, all_files=True), snapshot(identity["nb09_root"], all_files=True)
    current_before = code_snapshot(ROOT / "src")
    helper_before = fingerprint(__file__)
    output.mkdir(parents=True, exist_ok=False)
    candidate_source = output / "candidate_source/src"
    for relative, expected in current_before.items():
        source_file, destination = ROOT / "src" / relative, candidate_source / relative
        if "link_target" in expected:
            raise ValueError("candidate source snapshot cannot contain symlinks")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination)
        if fingerprint(destination) != expected:
            raise AssertionError("candidate source snapshot differs")
    write_exclusive(output / "experiment_worker.py", _EVALUATION_WORKER)
    results = {}
    experiments = [("old80", baseline / "working_tree/src", 80, {}),
                   ("old84", baseline / "working_tree/src", 84, {}),
                   ("new80", candidate_source, 80, {}), ("new84", candidate_source, 84, {})]
    if include_ablations:
        experiments.extend((name, candidate_source, 84, options) for name, options in (
            ("new84_no_gap", {"use_gap": False}),
            ("new84_no_relative_gap", {"use_relative_gap": False}),
            ("new84_no_reading", {"use_reading": False}),
            ("new84_no_rhythm", {"use_rhythm": False})))
    for name, selected, capacity, options in experiments:
        arguments = (source, media, parse_cache, Path(model_bundle).resolve(), capacity)
        if options:
            arguments += (json.dumps(options),)
        result = _child(selected, _EVALUATION_WORKER, arguments)
        results[name] = result
        write_exclusive(output / f"{name}.json", result)
        if name == "old80" and result["plan"] != json.loads((baseline / "nb09_frozen/source_chunks.json").read_bytes()):
            raise AssertionError("frozen old80 replay differs from the persisted source chunks; evidence retained")
    if (snapshot(baseline, all_files=True) != frozen_before
            or snapshot(identity["nb09_root"], all_files=True) != old_before
            or code_snapshot(ROOT / "src") != current_before or fingerprint(__file__) != helper_before):
        raise AssertionError("four-way replay changed or raced with protected source/code evidence")
    # Deterministic anonymisation, separate from the review document.
    ordering = sorted(("old80", "old84", "new80", "new84"), key=lambda name: sha256((fingerprint(source)["sha256"] + name).encode()).hexdigest())
    aliases = dict(zip(("A", "B", "C", "D"), ordering))
    write_exclusive(output / "review_identity_key.json", aliases)
    write_exclusive(output / "algorithm_diagnostics_index.json", {
        "schema_version": "chunking.algorithm-diagnostics-index.v1",
        "note": "Each variant JSON stores all per-sentence syntax/gaps/MAD, actual DP outputs and final global rescue scores under trace. Algorithm scores are not cross-algorithm human quality scores.",
        "variants": {name: {"path": str(output / f"{name}.json"), "json_field": "trace",
                            "evidence": fingerprint(output / f"{name}.json")} for name in results}})
    write_exclusive(output / "all_97_sentences.md", _markdown(alignment, results, aliases))
    deltas = sentence_changes(alignment, results)
    write_exclusive(output / "sentence_changes.json", deltas)
    if labels is not None:
        write_exclusive(output / "frozen_human_labels.json", labels)
        write_exclusive(output / "human_constraint_observations.json", {
            name: label_observations(result["plan"], labels, alignment) for name, result in results.items()})
    write_exclusive(output / "human_labels.template.json", {"schema_version": "chunking.human-labels.v1", "items": [
        {"sentence_id": row["id"], "word_ids": [], "data_origin": "reviewed_real", "decision": None,
         "allowed_groupings": [], "forbidden_boundaries": [], "pairwise_preference": None,
         "reason": "Unfilled: freeze human judgements before using them for tuning."}
        for row in alignment["sentences"]]})
    boundaries = {name: {cue["word_ids"][-1] for cue in result["plan"]["chunks"][:-1]}
                  for name, result in results.items()}
    evidence = {"schema_version": "chunking.four-way-evidence.v1", "dataset_role": "reviewed-development-regression-not-holdout",
                "baseline_identity": fingerprint(baseline / "baseline_identity.json"),
                "parse_cache": {"path": str(parse_cache), **fingerprint(parse_cache)},
                "current_source_files": current_before, "sentence_count": len(alignment["sentences"]),
                "candidate_source_snapshot_root": str(candidate_source), "runner_identity": helper_before,
                "worker_identity": fingerprint(output / "experiment_worker.py"),
                "source_word_count": len(alignment["words"]), "summary": {name: _summary(result) for name, result in results.items()},
                "changed_sentences_by_pair": deltas["changed_sentences_by_pair"],
                "boundary_deltas": {f"{left}_to_{right}": {"removed": sorted(boundaries[left] - boundaries[right]),
                                                          "added": sorted(boundaries[right] - boundaries[left])}
                                    for left, right in (("old80", "new80"), ("old84", "new84"), ("new80", "new84"))},
                "old80_exact_replay": True, "source_and_code_unchanged": True,
                "provider_calls": 0, "asr_calls": 0, "human_quality": "not_assessed",
                "labels_supplied": labels is not None, "automatic_publication_quality_gate": False}
    evidence["ablation_options"] = {name: options for name, _, _, options in experiments if options}
    evidence["unperformed_ablation_scope"] = "Unified-candidate, protection, relation and cue-feature effects are not isolated by these on/off scoring controls."
    write_exclusive(output / "experiment_evidence.json", evidence)
    return {"path": str(output), "sentence_count": evidence["sentence_count"], "summary": evidence["summary"],
            "evidence_sha256": fingerprint(output / "experiment_evidence.json")["sha256"]}


_OBJECTIVE_ORDER = (0, 1, 2, 3, 6, 7, 8, 4, 5, 9, 10, 11, 12)
_OBJECTIVE_FIELDS = ("high_impact_events", "ordinary_structure_events", "short_cue_count", "shortfall_ms",
    "cps_exceed_cue_count", "cps_excess_burden", "ordinary_grade3_count", "ordinary_grade2_count",
    "ordinary_grade1_count", "cue_count", "negative_pause_reward", "adjacent_character_rhythm", "squared_character_load")


def prepare_objective_experiment(baseline, reference, parse_cache, model_bundle, labels_path, output):
    """Preregister the exact authorised two factors before any candidate worker runs."""
    verify_baseline(baseline)
    baseline, reference, parse_cache, model_bundle, labels_path, output = map(
        lambda value: Path(value).resolve(), (baseline, reference, parse_cache, model_bundle, labels_path, output))
    if output.exists() or output.is_symlink():
        raise ValueError("objective experiment directory must be absent")
    for protected in (baseline, reference, model_bundle, ROOT / "src"):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError("objective outputs must be disjoint from protected source/model roots")
    identity = json.loads((reference / "experiment_evidence.json").read_bytes())
    frozen_source = Path(identity["candidate_source_snapshot_root"])
    if code_snapshot(frozen_source) != identity["current_source_files"]:
        raise ValueError("reference candidate source differs from its frozen experiment")
    source = baseline / "nb09_frozen/source_alignment.json"
    cache = json.loads(parse_cache.read_bytes())
    if cache["source_alignment"] != fingerprint(source):
        raise ValueError("objective parse cache belongs to another source")
    if (identity["baseline_identity"] != fingerprint(baseline / "baseline_identity.json")
            or any(fingerprint(parse_cache)[key] != identity["parse_cache"][key]
                   for key in ("sha256", "size_bytes", "mtime_ns"))):
        raise ValueError("objective baseline or raw parse differs from the reference experiment")
    labels = validate_labels(json.loads(labels_path.read_bytes()), json.loads(source.read_bytes()))
    if labels.get("source_alignment_sha256") != fingerprint(source)["sha256"]:
        raise ValueError("objective human labels belong to another source")
    if labels != json.loads((reference / "frozen_human_labels.json").read_bytes()):
        raise ValueError("objective human labels differ from the frozen reference labels")
    output.mkdir(parents=True, exist_ok=False)
    selected_source = output / "candidate_source/src"
    for relative, expected in identity["current_source_files"].items():
        destination = selected_source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frozen_source / relative, destination)
        if fingerprint(destination) != expected:
            raise AssertionError("objective source snapshot differs")
    write_exclusive(output / "experiment_worker.py", _EVALUATION_WORKER)
    write_exclusive(output / "frozen_human_labels.json", labels)
    variants = {}
    for name in ("B", "U", "S", "US"):
        order = _OBJECTIVE_ORDER if name in {"S", "US"} else tuple(range(13))
        variants[name] = {"objective_id": name, "unknown_grade3_to2": name in {"U", "US"},
                          "cost_permutation": list(order), "score_fields": [_OBJECTIVE_FIELDS[n] for n in order],
                          "cps_enabled": True, "capacity": 84}
    plan = {"schema_version": "chunking.objective-experiment-plan.v1", "status": "preregistered-before-workers",
            "approval": "root explicit authorisation 2026-11-14; isolated worker only",
            "dataset_role": "reviewed-development-regression-not-holdout", "read_only_overrides": True,
            "no_manifest_publication": True, "production_changed": False, "capacity": 84,
            "baseline": str(baseline), "baseline_identity": fingerprint(baseline / "baseline_identity.json"),
            "reference_experiment": str(reference), "reference_identity": fingerprint(reference / "experiment_evidence.json"),
            "control_B_reference": {"path": str(reference / "new84.json"), "evidence": fingerprint(reference / "new84.json"),
                "complete_plan_sha256": sha256(json.dumps(json.loads((reference / "new84.json").read_bytes())["plan"],
                    ensure_ascii=False, sort_keys=True).encode()).hexdigest()},
            "selected_source_root": str(selected_source), "source_files": identity["current_source_files"],
            "parse_cache": {"path": str(parse_cache), "evidence": fingerprint(parse_cache)},
            "model_bundle": str(model_bundle), "worker": fingerprint(output / "experiment_worker.py"),
            "runner_identity": fingerprint(__file__), "human_labels": fingerprint(output / "frozen_human_labels.json"),
            "variants": variants,
            "constants": "Same v4 raw parse, protections, trigger, spans, threshold, pause, cue fees and rhythm; CPS stays on. U changes only grade-return 3 to 2. S reorders the same 13 cost components and their labels; stable cuts remain last.",
            "interpretation": "B must exactly reproduce the complete v4 new84 plan. Objective vectors have different definitions/order and are not comparable human-quality scores."}
    write_exclusive(output / "experiment_plan.json", plan)
    return {"path": str(output), "plan_sha256": fingerprint(output / "experiment_plan.json")["sha256"],
            "status": plan["status"], "variants": variants}


def execute_objective_experiment(output):
    output = Path(output).resolve()
    plan_path = output / "experiment_plan.json"
    plan = json.loads(plan_path.read_bytes())
    if plan["schema_version"] != "chunking.objective-experiment-plan.v1":
        raise ValueError("unsupported objective experiment plan")
    if any((output / name).exists() for name in ("B", "U", "S", "US", "failure.json", "objective_evidence.json")):
        raise ValueError("objective run requires unused variant directories; retain failed runs and prepare a new experiment")
    baseline, selected = Path(plan["baseline"]), Path(plan["selected_source_root"])
    identity = verify_baseline(baseline)
    for path, expected in ((output / "experiment_worker.py", plan["worker"]),
                           (output / "frozen_human_labels.json", plan["human_labels"]),
                           (Path(plan["parse_cache"]["path"]), plan["parse_cache"]["evidence"]),
                           (Path(plan["control_B_reference"]["path"]), plan["control_B_reference"]["evidence"])):
        if fingerprint(path) != expected:
            raise ValueError("preregistered objective inputs changed")
    if fingerprint(__file__) != plan["runner_identity"] or code_snapshot(selected) != plan["source_files"]:
        raise ValueError("objective runner or frozen source changed after preregistration")
    source, media = baseline / "nb09_frozen/source_alignment.json", baseline / "nb09_frozen/media_boundary.json"
    alignment = json.loads(source.read_bytes())
    labels = validate_labels(json.loads((output / "frozen_human_labels.json").read_bytes()), alignment)
    before = {"baseline": snapshot(baseline, all_files=True), "reference": snapshot(plan["reference_experiment"], all_files=True),
              "original": snapshot(identity["nb09_root"], all_files=True), "production": code_snapshot(ROOT / "src"),
              "selected": code_snapshot(selected), "plan": fingerprint(plan_path)}
    results = {}
    try:
        for name in ("B", "U", "S", "US"):
            destination = output / name
            destination.mkdir(exist_ok=False)
            result = _child(selected, (output / "experiment_worker.py").read_text(),
                (source, media, plan["parse_cache"]["path"], plan["model_bundle"], 84, "{}", name))
            if any(result["experiment_objective"][key] != expected for key, expected in plan["variants"][name].items()):
                raise AssertionError("worker objective differs from preregistered variant")
            write_exclusive(destination / "result.json", result)
            if name == "B" and result["plan"] != json.loads(Path(plan["control_B_reference"]["path"]).read_bytes())["plan"]:
                raise AssertionError("control B does not exactly reproduce complete v4 plan")
            results[name] = result
        after = {"baseline": snapshot(baseline, all_files=True), "reference": snapshot(plan["reference_experiment"], all_files=True),
                 "original": snapshot(identity["nb09_root"], all_files=True), "production": code_snapshot(ROOT / "src"),
                 "selected": code_snapshot(selected), "plan": fingerprint(plan_path)}
        if after != before:
            raise AssertionError("objective experiment changed protected source/code/preregistration")
    except BaseException as error:
        write_exclusive(output / "failure.json", {"status": "failed", "error_type": type(error).__name__,
            "error_message": str(error), "completed_variants": list(results)})
        raise
    pairs = (("B", "U"), ("B", "S"), ("B", "US"), ("U", "US"), ("S", "US"), ("U", "S"))
    deltas = sentence_changes(alignment, results, pairs=pairs)
    write_exclusive(output / "sentence_changes.json", deltas)
    aliases = dict(zip(("A", "B", "C", "D"), sorted(results, key=lambda name: sha256((fingerprint(source)["sha256"] + name).encode()).hexdigest())))
    write_exclusive(output / "review_identity_key.json", aliases)
    write_exclusive(output / "all_97_sentences.md", _markdown(alignment, results, aliases,
        context_note="固定v4源码/84容量；仅未知边界分级与评分顺序2×2隔离试验。各目标分数不可直接跨组作质量分，未改生产或发布manifest。"))
    write_exclusive(output / "human_constraint_observations.json", {
        name: label_observations(result["plan"], labels, alignment) for name, result in results.items()})
    evidence = {"schema_version": "chunking.objective-experiment-evidence.v1", "status": "succeeded",
                "experiment_plan": fingerprint(plan_path), "variants": plan["variants"],
                "control_B_matches_v4_complete_plan": True, "protected_sources_and_production_unchanged": True,
                "sentence_count": len(alignment["sentences"]), "source_word_count": len(alignment["words"]),
                "summary": {name: _summary(result) for name, result in results.items()},
                "changed_sentences_by_pair": deltas["changed_sentences_by_pair"],
                "results": {name: fingerprint(output / name / "result.json") for name in results},
                "provider_calls": 0, "asr_calls": 0, "no_manifest_publication": True,
                "human_quality": "not_assessed", "dataset_role": "reviewed-development-regression-not-holdout"}
    write_exclusive(output / "objective_evidence.json", evidence)
    return {"path": str(output), "evidence_sha256": fingerprint(output / "objective_evidence.json")["sha256"],
            "summary": evidence["summary"], "changed_sentences_by_pair": evidence["changed_sentences_by_pair"]}


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--model-bundle", type=Path)
    parser.add_argument("--parse-cache", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-cache", action="store_true")
    mode.add_argument("--prepare-objective", action="store_true")
    mode.add_argument("--run-objective", action="store_true")
    parser.add_argument("--reference-experiment", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--labels", type=Path)
    parser.add_argument("--ablations", action="store_true")
    args = parser.parse_args(argv)
    if args.run_objective:
        if args.output is None:
            parser.error("objective execution requires --output containing a preregistered plan")
        result = execute_objective_experiment(args.output)
    elif any(value is None for value in (args.baseline, args.model_bundle, args.parse_cache)):
        parser.error("preparation/four-way modes require --baseline, --model-bundle and --parse-cache")
    elif args.prepare_objective:
        if any(value is None for value in (args.reference_experiment, args.labels, args.output)):
            parser.error("objective preparation requires --reference-experiment, --labels and --output")
        result = prepare_objective_experiment(args.baseline, args.reference_experiment, args.parse_cache,
                                              args.model_bundle, args.labels, args.output)
    elif args.prepare_cache:
        result = prepare_parse_cache(args.baseline, args.model_bundle, args.parse_cache)
    else:
        if args.output is None:
            parser.error("four-way evaluation requires --output")
        result = evaluate_four_way(args.baseline, args.parse_cache, args.model_bundle, args.output,
                                   labels_path=args.labels, include_ablations=args.ablations)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
